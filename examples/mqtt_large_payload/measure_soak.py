"""Soak test: the production-like MQTT load on the bench PLC for many minutes, everything checked.

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_soak.py --minutes 20 --out results/.../soak.json
Runs the 2,000-tag tag:value full refresh (26 KB, QoS 0) once a second with one client call per scan, and a
command every 200 ms answered by EdgeTest's QoS 1 echo. verify_scale.py checks every value of every full
refresh at the broker; this script times every command round trip. At the end it reads the PLC's counters:
messages sent, timeouts, reconnects, the worst scan time, and the client's dynamic memory.
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from run_ide_script import execute  # noqa: E402

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
C = 'PLC_PRG.MqttLink.clientFB'
names = {'scaleSent': 'ScaleTest.SentCount', 'scaleTimeouts': 'ScaleTest.TimeoutCount', 'scaleOverflows': 'ScaleTest.OverflowCount',
         'maxPublishUs': 'ScaleTest.MaxPublishUs', 'echoes': 'EdgeTest.EchoCount', 'commandsReceived': 'EdgeTest.Receiver.ReceivedCount',
         'connectAttempts': C + '.counts.CountConnectAttempt', 'maxCycleUs': 'PLC_PRG.MaxCycleUs', 'maxClientUs': 'PLC_PRG.MaxClientUs',
         'dynMemUsage': 'PLC_PRG.MqttLink.dynMemUsage', 'connected': 'PLC_PRG.IsBrokerConnected'}
values = {}
for key, path in names.items():
    try:
        values[key] = text(path)
    except Exception as error:
        values[key] = 'error: %s' % error
result = {'success': True, 'values': values}
"""


def write(values) -> None:
    execute(WRITE.replace("@@VALUES@@", repr(values)), 60)


def read() -> dict:
    return execute(READ, 60)["values"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--minutes", type=float, default=20)
    parser.add_argument("--out")
    args = parser.parse_args()
    seconds = args.minutes * 60
    out = Path(args.out) if args.out else None
    verify_out = out.with_name(out.stem + "_verify.json") if out else None
    rtts, pending, lock = [], {}, threading.Lock()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="soak-%d" % os.getpid())

    def on_message(c, u, message):
        now = time.perf_counter()
        with lock:
            if pending:
                started = pending.pop(min(pending))   # the echo answers the newest command; match the oldest open one
                rtts.append((now - started) * 1000.0)
                pending.clear()

    client.on_connect = lambda c, u, f, r, p=None: c.subscribe("raw_data_demo/edge_echo", qos=1)
    client.on_message = on_message
    client.connect("192.168.50.240", 1883, keepalive=30)
    client.loop_start()
    write([("PLC_PRG.MaxCycleUs", "0"), ("PLC_PRG.ResetStats", "TRUE"), ("ScaleTest.ResetStats", "TRUE"),
           ("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.IsEchoEnabled", "TRUE"), ("ScaleTest.IsTagValueFormat", "TRUE"),
           ("ScaleTest.TagsPerScan", "2000"), ("ScaleTest.IsQos1", "FALSE"), ("PLC_PRG.ClientCallsPerScan", "1"),
           ("ScaleTest.IsEnabled", "TRUE")])
    time.sleep(3)
    before = read()
    verifier = subprocess.Popen([sys.executable, str(HERE / "verify_scale.py"), "--seconds", str(seconds)]
                                + (["--out", str(verify_out)] if verify_out else []))
    end, n, sent = time.time() + seconds, 0, 0
    while time.time() < end:
        with lock:
            pending[n] = time.perf_counter()
        client.publish("raw_data_demo/edge_in", b"cmd%d" % n, qos=1)
        n, sent = n + 1, sent + 1
        time.sleep(0.2)
    verifier.wait(timeout=600)
    time.sleep(2)
    after = read()
    write([("ScaleTest.IsEnabled", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE")])
    client.loop_stop()
    client.disconnect()
    verify = json.loads(verify_out.read_text(encoding="utf-8")) if verify_out and verify_out.exists() else {}
    tagvalue = (verify.get("byFormat") or {}).get("tagvalue") or {}
    number = lambda key, src: int(src[key]) if str(src[key]).isdigit() else src[key]
    rtts.sort()
    report = {
        "minutes": args.minutes,
        "fullRefreshes": number("scaleSent", after) - number("scaleSent", before),
        "fullRefreshTimeouts": number("scaleTimeouts", after) - number("scaleTimeouts", before),
        "brokerMessages": tagvalue.get("messages"), "brokerAllCorrect": tagvalue.get("allCorrect"),
        "commandsSent": sent, "echoesTimed": len(rtts),
        "reconnects": number("connectAttempts", after) - number("connectAttempts", before),
        "maxCycleUs": after["maxCycleUs"], "maxClientUs": after["maxClientUs"], "maxPublishUs": after["maxPublishUs"],
        "dynMemUsageBefore": before["dynMemUsage"], "dynMemUsageAfter": after["dynMemUsage"],
        "connectedAtEnd": after["connected"],
    }
    if rtts:
        report.update({"rttMedianMs": round(statistics.median(rtts), 1),
                       "rttP99Ms": round(rtts[int(0.99 * (len(rtts) - 1))], 1), "rttMaxMs": round(rtts[-1], 1)})
    report["success"] = (report["fullRefreshTimeouts"] == 0 and report["reconnects"] == 0 and bool(report["brokerAllCorrect"])
                         and report["connectedAtEnd"] == "TRUE" and report["dynMemUsageBefore"] == report["dynMemUsageAfter"])
    text = json.dumps(report, indent=1)
    print(text)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
