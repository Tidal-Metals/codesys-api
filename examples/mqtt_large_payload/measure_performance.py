"""Sweep the demo's payload size on the running PLC and record what each size costs.

Run from the repo root after deploy_demo.py (the session must be logged in):
    python examples/mqtt_large_payload/measure_performance.py --sizes 50 500 1100 --format real --qos 0
Defaults match BCNF in production: two-decimal REALs, QoS 0, one publish a second, no CONCAT copy.
Run verify_payloads.py alongside to confirm every message stays correct during the sweep.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

STATS = [
    "LastLargeLength", "LargeSentCount", "TimeoutCount", "SkippedBusyCount", "OverflowCount",
    "LastLargeBuildUs", "MaxLargeBuildUs", "MaxConcatBuildUs",
    "MaxClientUs", "CycleUs", "MaxCycleUs", "MinIntervalUs", "MaxIntervalUs",
    "LastPublishCycles", "MaxPublishCycles", "LastPublishUs", "MaxPublishUs",
]

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state

def number(name):
    text = str(on.read_value('PLC_PRG.' + name)).split('#')[-1]
    return int(text) if text.isdigit() else text

for name, value in @@SETTINGS@@:
    on.set_prepared_value('PLC_PRG.' + name, value)
on.write_prepared_values()
time.sleep(@@SETTLE@@)  # let a publish from the previous settings finish
on.set_prepared_value('PLC_PRG.ResetStats', 'TRUE')
on.write_prepared_values()
sent_before = number('LargeSentCount')
time.sleep(@@SECONDS@@)
values = dict((name, number(name)) for name in @@STATS@@)
values['sentDuringRun'] = values['LargeSentCount'] - sent_before
result = {'success': True, 'run': values}
"""


def measure(size, args):
    settings = [
        ("ValueCount", str(size)),
        ("IsRealFormat", "TRUE" if args.format == "real" else "FALSE"),
        ("IsQos1", "TRUE" if args.qos == 1 else "FALSE"),
        ("IsConcatControlEnabled", "TRUE" if args.concat else "FALSE"),
        ("PublishPeriod", "T#%dMS" % args.period_ms),
    ]
    code = (CODE.replace("@@SETTINGS@@", repr(settings)).replace("@@STATS@@", repr(STATS))
            .replace("@@SECONDS@@", repr(args.seconds)).replace("@@SETTLE@@", repr(args.settle)))
    result = execute(code, int(args.seconds + args.settle) + 60)
    if not result.get("success"):
        raise RuntimeError("measurement failed at ValueCount=%d: %s" % (size, result.get("error") or result))
    run = result["run"]
    run.update(ValueCount=size, format=args.format.upper(), qos=args.qos, periodMs=args.period_ms,
               concatControl=args.concat, seconds=args.seconds)
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[50, 500, 1100])
    parser.add_argument("--format", choices=["real", "int"], default="real")
    parser.add_argument("--qos", type=int, choices=[0, 1], default=0)
    parser.add_argument("--period-ms", type=int, default=1000)
    parser.add_argument("--concat", action="store_true", help="also build the CONCAT control copy (not production work)")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--settle", type=float, default=4)
    parser.add_argument("--out")
    args = parser.parse_args()
    runs = []
    for size in args.sizes:
        runs.append(measure(size, args))
        print(json.dumps(runs[-1]), flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps({"runs": runs}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
