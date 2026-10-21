"""MQTT library edge cases on the bench PLC: every payload size around the buffer boundaries, both directions.

Run from the repo root after deploy_demo.py (session logged in; the demo includes EdgeTest):
    python examples/mqtt_large_payload/edge_test.py --out results/edge/<label>.json [--quick]
Send: EdgeTest publishes each size on raw_data_demo/edge (QoS 0, and QoS 1 for the 16 KB boundary); a
subscriber here checks that every message arrives, in order, with exactly the expected bytes. The sizes
step one byte at a time across the 16 KB and 32 KB send-chunk boundaries, where a split payload could lose
its last byte or a topic could run past the buffer. Receive: this script publishes each size on
raw_data_demo/edge_in (QoS 1) and EdgeTest reports size and Adler-32; the sizes step across the receive
buffer's in-place limit (16 KB) and the large-message path. Also checks the client stayed connected.
"""
import argparse
import json
import os
import sys
import threading
import time
import zlib
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

BROKER = "192.168.50.240"
TOPIC_OUT = "raw_data_demo/edge"
TOPIC_IN = "raw_data_demo/edge_in"


def send_cases(quick: bool) -> list:
    sizes = [1, 2, 100, 1000, 4094, 4095, 4096, 4097, 8000, 12000, 16000]
    boundary16 = range(16330, 16421) if not quick else range(16350, 16371)
    boundary32 = range(32690, 32791) if not quick else range(32730, 32760)
    cases = [(n, False) for n in list(sizes) + list(boundary16) + list(boundary32) + [39990, 40000]]
    cases += [(n, True) for n in (boundary16 if not quick else range(16350, 16371))]
    return cases


def receive_sizes(quick: bool) -> list:
    sizes = [1, 100, 2000, 8000, 8300, 8400, 12000, 30000, 39000]
    boundary = range(16300, 16421) if not quick else range(16340, 16391)
    return list(sizes) + list(boundary) + list(range(32700, 32801, 5) if not quick else [])


def pattern(seq: int, size: int) -> bytes:
    return bytes((i * 31 + seq) % 251 for i in range(size))


SEND_CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state

def text(path):
    return str(on.read_value(path)).split('#')[-1]

def write(values):
    for path, value in values:
        on.set_prepared_value(path, value)
    on.write_prepared_values()

write([('EdgeTest.IsEnabled', 'TRUE')])
time.sleep(2)
seq = int(text('EdgeTest.SendSequence'))
start_timeouts = int(text('EdgeTest.TimeoutCount'))
sent = []
for size, qos1 in @@CASES@@:
    seq += 1
    # Size and QoS first, the sequence (which starts the send) in a second write: one write of all three can
    # reach the PLC across a scan boundary, and EdgeTest would start with the previous size.
    write([('EdgeTest.SendSize', str(size)), ('EdgeTest.IsQos1', 'TRUE' if qos1 else 'FALSE')])
    write([('EdgeTest.SendSequence', str(seq))])
    started = time.time()
    done = False
    while time.time() - started < 10:
        if int(text('EdgeTest.DoneSequence')) == seq:
            done = True
            break
        time.sleep(0.02)
    sent.append({'seq': seq, 'size': size, 'qos1': qos1, 'done': done, 'seconds': round(time.time() - started, 3)})
    if not done:
        break
result = {'success': True, 'sent': sent, 'timeouts': int(text('EdgeTest.TimeoutCount')) - start_timeouts,
          'connected': text('PLC_PRG.IsBrokerConnected')}
"""

READ_RECEIVER = """
import time
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path)).split('#')[-1]
deadline = time.time() + 10
count = int(text('EdgeTest.Receiver.ReceivedCount'))
while count <= @@BEFORE@@ and time.time() < deadline:
    time.sleep(0.05)
    count = int(text('EdgeTest.Receiver.ReceivedCount'))
result = {'success': True, 'count': count, 'size': int(text('EdgeTest.Receiver.LastSize')),
          'adler32': int(text('EdgeTest.Receiver.LastAdler32')), 'connected': text('PLC_PRG.IsBrokerConnected')}
"""


def run_send(quick: bool) -> dict:
    cases = send_cases(quick)
    received, lock = [], threading.Lock()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(TOPIC_OUT, qos=1)

    def on_message(client, userdata, message):
        with lock:
            received.append(bytes(message.payload))

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-checker-%d" % os.getpid())
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(BROKER, 1883, keepalive=30)
    client.loop_start()
    time.sleep(1)
    plc = execute(SEND_CODE.replace("@@CASES@@", repr(cases)), 900)
    time.sleep(3)
    client.loop_stop()
    client.disconnect()
    if not plc.get("success"):
        return {"error": plc}
    sent = plc["sent"]
    problems = []
    if len(received) != len(sent):
        problems.append("sent %d, broker delivered %d" % (len(sent), len(received)))
    for item, payload in zip(sent, received):
        if not item["done"]:
            problems.append("seq %d size %d not done" % (item["seq"], item["size"]))
        elif payload != pattern(item["seq"], item["size"]):
            first = next((i for i, (a, b) in enumerate(zip(payload, pattern(item["seq"], item["size"]))) if a != b), None)
            problems.append("seq %d size %d qos1=%s: got %d bytes, first difference at %s"
                            % (item["seq"], item["size"], item["qos1"], len(payload), first))
    return {"cases": len(cases), "sent": len(sent), "delivered": len(received), "timeouts": plc["timeouts"],
            "connectedAfter": plc["connected"], "problems": problems,
            "slowest": sorted(sent, key=lambda s: -s["seconds"])[:3]}


def run_receive(quick: bool) -> dict:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="edge-sender-%d" % os.getpid())
    client.connect(BROKER, 1883, keepalive=30)
    client.loop_start()
    problems, before, checked = [], None, 0
    first = execute(READ_RECEIVER.replace("@@BEFORE@@", "-1"), 60)
    before = first["count"]
    for size in receive_sizes(quick):
        payload = os.urandom(size)
        client.publish(TOPIC_IN, payload, qos=1).wait_for_publish(10)
        reading = execute(READ_RECEIVER.replace("@@BEFORE@@", str(before)), 60)
        checked += 1
        if reading["count"] != before + 1:
            problems.append("size %d: PLC count %d -> %d" % (size, before, reading["count"]))
        elif reading["size"] != size or reading["adler32"] != zlib.adler32(payload):
            problems.append("size %d: PLC saw %d bytes, adler32 %s (expected %s)"
                            % (size, reading["size"], reading["adler32"], zlib.adler32(payload)))
        before = reading["count"]
        if reading["connected"] != "TRUE":
            problems.append("size %d: client disconnected" % size)
            break
    client.loop_stop()
    client.disconnect()
    return {"checked": checked, "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--only", choices=["send", "receive"])
    args = parser.parse_args()
    report = {}
    if args.only != "receive":
        report["send"] = run_send(args.quick)
    if args.only != "send":
        report["receive"] = run_receive(args.quick)
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    bad = any(report.get(k, {}).get("problems") or report.get(k, {}).get("error") for k in report)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
