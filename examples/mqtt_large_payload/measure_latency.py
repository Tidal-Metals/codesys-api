"""Command-to-acknowledgement round trip through the bench PLC's MQTT client (EdgeTest echo).

Run from the repo root after deploy_demo.py (session logged in; the demo includes EdgeTest):
    python examples/mqtt_large_payload/measure_latency.py --count 50 [--load] --out results/.../latency.json
Publishes one small QoS 1 message at a time on raw_data_demo/edge_in and waits for EdgeTest's QoS 1 echo
on raw_data_demo/edge_echo: the path of a command and its acknowledgement. --load runs the 2,000-tag full
refresh (ScaleTest, one message a second) at the same time, so commands arrive while a large publish is
being sent. Reports min, median, p90 and max milliseconds, and lost echoes.
"""
import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

BROKER = "192.168.50.240"
# Written only with --second-call, so older demo builds without the variable still work.
SECOND_ON = "[('PLC_PRG.IsSecondClientCallEnabled', 'TRUE')]"
SECOND_OFF = "[('PLC_PRG.IsSecondClientCallEnabled', 'FALSE')]"

SETUP = """
on = session.ensure_online_application('', True)
def write(values):
    for path, value in values:
        on.set_prepared_value(path, value)
    on.write_prepared_values()
write([('EdgeTest.IsEnabled', 'TRUE'), ('EdgeTest.IsEchoEnabled', @@ECHO@@),
       ('ScaleTest.IsTagValueFormat', 'TRUE'), ('ScaleTest.TagsPerScan', '2000'), ('ScaleTest.IsQos1', 'FALSE'),
       ('ScaleTest.IsEnabled', @@LOAD@@), ('PLC_PRG.ClientCallsPerScan', '@@CALLS@@'), ('PLC_PRG.ClientBudgetUs', '@@BUDGET@@')]
      + @@SECOND@@)
result = {'success': True, 'calls': str(on.read_value('PLC_PRG.ClientCallsPerScan'))}
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--load", action="store_true")
    parser.add_argument("--client-calls", type=int, default=1)
    parser.add_argument("--budget-us", type=int, default=1000000)
    parser.add_argument("--second-call", action="store_true", help="PLC_PRG calls the client again after the publishers")
    parser.add_argument("--client-last", choices=["on", "off"], help="set PLC_PRG.IsClientCalledLast for the run")
    parser.add_argument("--out")
    args = parser.parse_args()
    client_last = "" if not args.client_last else " + [('PLC_PRG.IsClientCalledLast', '%s')]" % ("TRUE" if args.client_last == "on" else "FALSE")
    echoes, arrived = [], threading.Event()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe("raw_data_demo/edge_echo", qos=1)

    def on_message(client, userdata, message):
        echoes.append(time.perf_counter())
        arrived.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="latency-%d" % os.getpid())
    client.on_connect, client.on_message = on_connect, on_message
    client.connect(BROKER, 1883, keepalive=30)
    client.loop_start()
    setup = SETUP.replace("@@ECHO@@", "'TRUE'").replace("@@LOAD@@", "'TRUE'" if args.load else "'FALSE'") \
        .replace("@@CALLS@@", str(args.client_calls)).replace("@@BUDGET@@", str(args.budget_us)) \
        .replace("@@SECOND@@", (SECOND_ON if args.second_call else "[]") + client_last)
    execute(setup, 60)
    time.sleep(3)
    rtts, lost = [], 0
    for i in range(args.count):
        arrived.clear()
        started = time.perf_counter()
        client.publish("raw_data_demo/edge_in", b"cmd%d" % i, qos=1)
        if arrived.wait(5):
            rtts.append((time.perf_counter() - started) * 1000.0)
        else:
            lost += 1
        # a random gap: a fixed one locks the commands to the PLC scan phase and biases the result
        time.sleep(random.uniform(0.15, 0.45))
    stop = SETUP.replace("@@ECHO@@", "'FALSE'").replace("@@LOAD@@", "'FALSE'").replace("@@CALLS@@", "1") \
        .replace("@@BUDGET@@", "5000").replace("@@SECOND@@", SECOND_OFF if args.second_call else "[]")
    execute(stop, 60)
    client.loop_stop()
    client.disconnect()
    rtts.sort()
    report = {"count": args.count, "lost": lost, "load": args.load, "clientCalls": args.client_calls, "secondCall": args.second_call, "clientLast": args.client_last,
              "budgetUs": args.budget_us}
    if rtts:
        report.update({"minMs": round(rtts[0], 1), "medianMs": round(statistics.median(rtts), 1),
                       "p90Ms": round(rtts[int(0.9 * (len(rtts) - 1))], 1), "maxMs": round(rtts[-1], 1)})
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if not lost else 1


if __name__ == "__main__":
    raise SystemExit(main())
