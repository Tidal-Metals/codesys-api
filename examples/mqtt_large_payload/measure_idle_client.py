"""Measure what MQTT client calls cost when nothing is being sent.

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_idle_client.py --out results/throughput/idle_client.json
All publishing is paused (PLC_PRG.PublishPeriod = 1 h, ScaleTest off) and the client is called a fixed
number of times per scan (IsClientLoopGated = FALSE); PLC_PRG.ClientUs is sampled for each count.
Previous settings are restored afterwards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

CODE = """
import time
on = session.ensure_online_application('', True)

def number(path):
    text = str(on.read_value(path)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for path, value in values:
        on.set_prepared_value(path, value)
    on.write_prepared_values()

previous_period = str(on.read_value('PLC_PRG.PublishPeriod'))
write([('PLC_PRG.PublishPeriod', 'T#1H'), ('ScaleTest.IsEnabled', 'FALSE'), ('PLC_PRG.IsTagValueEnabled', 'FALSE'),
       ('PLC_PRG.IsClientLoopGated', 'FALSE'), ('PLC_PRG.ClientBudgetUs', '1000000')])
time.sleep(3)
runs = []
for calls in @@COUNTS@@:
    write([('PLC_PRG.ClientCallsPerScan', str(calls))])
    time.sleep(1)
    write([('PLC_PRG.ResetStats', 'TRUE')])
    samples = []
    end = time.time() + @@SECONDS@@
    while time.time() < end:
        samples.append(number('PLC_PRG.ClientUs'))
        time.sleep(0.25)
    runs.append({'calls': calls, 'samplesUs': samples, 'MaxClientUs': number('PLC_PRG.MaxClientUs')})
write([('PLC_PRG.ClientCallsPerScan', '1'), ('PLC_PRG.IsClientLoopGated', 'TRUE'), ('PLC_PRG.ClientBudgetUs', '5000'),
       ('PLC_PRG.PublishPeriod', previous_period)])
result = {'success': True, 'runs': runs}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts", default="1,4,16,32")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--out")
    args = parser.parse_args()
    counts = [int(c) for c in args.counts.split(",")]
    code = CODE.replace("@@COUNTS@@", repr(counts)).replace("@@SECONDS@@", repr(args.seconds))
    result = execute(code, int(len(counts) * (args.seconds + 2)) + 120)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    runs = []
    for run in result["runs"]:
        samples = run.pop("samplesUs")
        run["meanUs"] = round(sum(samples) / len(samples))
        run["meanPerCallUs"] = round(run["meanUs"] / float(run["calls"]), 1)
        runs.append(run)
    text = json.dumps({"runs": runs}, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
