"""Measure the two-task bench in one configuration: control task timing while the comms task publishes.

Run from the repo root after deploy_bench.py:
    python examples/plc_architecture/bench/measure_bench.py --comms on --tags-per-call 250 --calls 16 --budget-us 5000 --out x.json
Writes the settings online, waits, resets the counters, measures for --seconds and reads them back.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

CONTROL = ["ScanCount", "MinIntervalUs", "MaxIntervalUs", "MaxDeviationUs", "MaxExecUs", "ExecTotalUs", "MaxSimUs",
           "GoodCount", "NotGoodCount"]
COMMS = ["ScanCount", "MaxExecUs", "ExecTotalUs", "MaxIntervalUs", "PublishCount", "LastPublishUs", "MaxPublishUs",
         "LastPayloadLength", "MaxClientCalls"]

CODE = """
import time
on = session.ensure_online_application('', True)

def value(path):
    text = str(on.read_value(path)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for path, text in values:
        on.set_prepared_value(path, text)
    on.write_prepared_values()

write(@@SETTINGS@@)
time.sleep(@@SETTLE@@)
write([('PRG_ControlTask.ResetStats', 'TRUE'), ('PRG_CommsTask.ResetStats', 'TRUE')])
time.sleep(@@SECONDS@@)
write([('PRG_ControlTask.IsQualityCountRequested', 'TRUE')])
time.sleep(0.5)
run = {}
for name in @@CONTROL@@:
    run['control.' + name] = value('PRG_ControlTask.' + name)
for index in range(6):
    run['control.Deviation[%d]' % index] = value('PRG_ControlTask.Deviation[%d]' % index)
for name in @@COMMS@@:
    run['comms.' + name] = value('PRG_CommsTask.' + name)
result = {'success': True, 'run': run}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comms", choices=["on", "off"], default="on")
    parser.add_argument("--full-every", type=int, default=1, help="FULL_REFRESH_EVERY; 1 = every message has all tags")
    parser.add_argument("--tags-per-call", type=int, default=250)
    parser.add_argument("--calls", type=int, default=16, help="ClientCallsMax")
    parser.add_argument("--budget-us", type=int, default=5000)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--settle", type=float, default=5)
    parser.add_argument("--out")
    args = parser.parse_args()
    settings = [("PRG_CommsTask.IsEnabled", "TRUE" if args.comms == "on" else "FALSE"),
                ("PRG_Comms.FULL_REFRESH_EVERY", str(args.full_every)), ("PRG_Comms.TAGS_PER_CALL", str(args.tags_per_call)),
                ("PRG_Comms.ClientCallsMax", str(args.calls)), ("PRG_Comms.ClientBudgetUs", str(args.budget_us))]
    code = (CODE.replace("@@SETTINGS@@", repr(settings)).replace("@@SETTLE@@", repr(args.settle))
            .replace("@@SECONDS@@", repr(args.seconds)).replace("@@CONTROL@@", repr(CONTROL)).replace("@@COMMS@@", repr(COMMS)))
    result = execute(code, int(args.seconds + args.settle) + 120)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    run = result["run"]
    run["control.MeanExecUs"] = round(run["control.ExecTotalUs"] / max(run["control.ScanCount"], 1))
    run["comms.MeanExecUs"] = round(run["comms.ExecTotalUs"] / max(run["comms.ScanCount"], 1))
    run["settings"] = dict(settings)
    run["seconds"] = args.seconds
    print(json.dumps(run))
    if args.out:
        Path(args.out).write_text(json.dumps(run, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
