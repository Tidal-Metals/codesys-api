"""MQTT QoS behaviour of the bench PLC's library, every level and combination, with loss and duplicate counts.

Run from the repo root after deploy_demo.py (session logged in; the demo includes EdgeTest with
SubscribeQoS, IsQos2 and the receiver's sequence counters):
    python examples/mqtt_large_payload/qos_test.py --out results/.../qos.json
Incoming: for each subscription QoS (0, 1, 2) and publish QoS (0, 1, 2), this script publishes sequenced
messages ('00000001...') to raw_data_demo/edge_in, paced and then as a burst; EdgeTest's receiver counts
in-order messages, duplicates and gaps (losses), and the script watches for client disconnects. The
delivered QoS is the lower of the two. Outgoing: EdgeTest publishes small messages at QoS 0, 1 and 2 and
this script, subscribed at QoS 2, checks every one arrives once, in order.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

BROKER = "192.168.50.240"
R = "EdgeTest.Receiver"
C = "PLC_PRG.MqttLink.clientFB"

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path)).split('#')[-1]
result = {'success': True, 'received': int(text('%(R)s.ReceivedCount')), 'inOrder': int(text('%(R)s.InOrderCount')),
          'duplicates': int(text('%(R)s.DuplicateCount')), 'gaps': int(text('%(R)s.GapCount')),
          'lastSequence': int(text('%(R)s.LastSequence')), 'connected': text('PLC_PRG.IsBrokerConnected') == 'TRUE',
          'connectAttempts': int(text('%(C)s.counts.CountConnectAttempt')),
          'subscribeDone': text('EdgeTest.Subscriber.SubscribeDone'), 'doneSequence': int(text('EdgeTest.DoneSequence')),
          'sendSequence': int(text('EdgeTest.SendSequence')), 'timeouts': int(text('EdgeTest.TimeoutCount'))}
""" % {"R": R, "C": C}


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def read() -> dict:
    return execute(READ, 60)


def wait_connected(seconds: float = 30) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if read()["connected"]:
            return True
        time.sleep(0.5)
    return False


def resubscribe(qos: int) -> None:
    write([("EdgeTest.IsEnabled", "FALSE")])
    time.sleep(2)
    write([("EdgeTest.SubscribeQoS", str(qos)), ("EdgeTest.IsEnabled", "TRUE")])
    time.sleep(3)


def incoming(client, sub_qos: int, pub_qos: int, count: int, pace: float) -> dict:
    write([(R + ".ResetSequence", "TRUE")])
    before = read()
    for seq in range(1, count + 1):
        client.publish("raw_data_demo/edge_in", b"%08d" % seq, qos=pub_qos)
        if pace:
            time.sleep(pace)
    time.sleep(4)
    after = read()
    reconnected = after["connectAttempts"] - before["connectAttempts"]
    if not after["connected"] or reconnected:
        wait_connected()
    return {"subscribeQoS": sub_qos, "publishQoS": pub_qos, "deliveredQoS": min(sub_qos, pub_qos), "sent": count,
            "paceSeconds": pace, "inOrder": after["inOrder"], "duplicates": after["duplicates"], "gaps": after["gaps"],
            "lastSequence": after["lastSequence"], "reconnects": reconnected, "connected": after["connected"]}


def outgoing(qos: int, count: int, received: list) -> dict:
    write([("EdgeTest.IsQos1", "TRUE" if qos == 1 else "FALSE"), ("EdgeTest.IsQos2", "TRUE" if qos == 2 else "FALSE"),
           ("EdgeTest.SendSize", "16")])
    del received[:]
    state = read()
    seq, timeouts_before, done_seqs = state["sendSequence"], state["timeouts"], []
    for _ in range(count):
        seq += 1
        write([("EdgeTest.SendSequence", str(seq))])
        end = time.time() + 10
        while time.time() < end and read()["doneSequence"] != seq:
            time.sleep(0.05)
        done_seqs.append(seq)
    time.sleep(3)
    expected = [bytes((i * 31 + s) % 251 for i in range(16)) for s in done_seqs]
    got = list(received)
    return {"qos": qos, "sent": count, "delivered": len(got), "inOrderExact": got == expected,
            "duplicates": len(got) - len(set(got)), "missing": len([e for e in expected if e not in got]),
            "timeouts": read()["timeouts"] - timeouts_before}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=60)
    parser.add_argument("--burst", type=int, default=40, help="messages sent back to back")
    parser.add_argument("--out")
    args = parser.parse_args()
    received = []
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qos-test-%d" % os.getpid())
    client.on_connect = lambda c, u, f, r, p=None: c.subscribe("raw_data_demo/edge", qos=2)
    client.on_message = lambda c, u, m: received.append(bytes(m.payload))
    client.max_inflight_messages_set(100)
    client.connect(BROKER, 1883, keepalive=30)
    client.loop_start()
    report = {"incoming": [], "outgoing": []}
    try:
        write([("EdgeTest.IsEchoEnabled", "FALSE"), ("ScaleTest.IsEnabled", "FALSE")])
        for sub_qos in (0, 1, 2):
            resubscribe(sub_qos)
            for pub_qos in (0, 1, 2):
                report["incoming"].append(incoming(client, sub_qos, pub_qos, args.count, 0.05))
                report["incoming"].append(incoming(client, sub_qos, pub_qos, args.burst, 0))
        resubscribe(1)
        for qos in (0, 1, 2):
            report["outgoing"].append(outgoing(qos, 30, received))
    finally:
        write([("EdgeTest.IsQos1", "FALSE"), ("EdgeTest.IsQos2", "FALSE"), ("EdgeTest.SubscribeQoS", "1")])
        client.loop_stop()
        client.disconnect()
    for row in report["incoming"]:
        row["ok"] = row["inOrder"] == row["sent"] and row["duplicates"] == 0 and row["gaps"] == 0 and row["reconnects"] == 0
    for row in report["outgoing"]:
        row["ok"] = row["inOrderExact"] and row["timeouts"] == 0
    report["success"] = all(r["ok"] for r in report["incoming"] + report["outgoing"])
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
