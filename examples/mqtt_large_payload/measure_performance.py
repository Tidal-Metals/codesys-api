"""Sweep the demo's payload size on the running PLC and record what each size costs.

Run from the repo root after deploy_demo.py (the session must be logged in):
    python examples/mqtt_large_payload/measure_performance.py --sizes 50 500 1100 --seconds 35
Run verify_payloads.py alongside to confirm every message stays exact during the sweep.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

STATS = [
    "LastLargeLength", "LastConcatLength", "LargeSentCount", "TimeoutCount", "SkippedBusyCount",
    "LastLargeBuildUs", "MaxLargeBuildUs", "LastConcatBuildUs", "MaxConcatBuildUs",
    "MaxClientUs", "CycleUs", "MaxCycleUs", "MinIntervalUs", "MaxIntervalUs",
    "LastPublishCycles", "MaxPublishCycles", "LastPublishUs", "MaxPublishUs",
]

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state
names = @@STATS@@
runs = []
for size in @@SIZES@@:
    session.report_progress({'step': 'ValueCount=%d' % size})
    on.set_prepared_value('PLC_PRG.ValueCount', str(size))
    on.set_prepared_value('PLC_PRG.ResetStats', 'TRUE')
    on.write_prepared_values()
    sent_before = str(on.read_value('PLC_PRG.LargeSentCount'))
    time.sleep(@@SECONDS@@)
    values = {}
    for name in names:
        text = str(on.read_value('PLC_PRG.' + name))
        values[name] = int(text.split('#')[-1]) if text.split('#')[-1].isdigit() else text
    values['ValueCount'] = size
    values['sentDuringRun'] = values['LargeSentCount'] - int(sent_before.split('#')[-1])
    runs.append(values)
result = {'success': True, 'runs': runs}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[50, 500, 1100])
    parser.add_argument("--seconds", type=float, default=35)
    parser.add_argument("--out")
    args = parser.parse_args()
    code = (CODE.replace("@@STATS@@", repr(STATS)).replace("@@SIZES@@", repr(args.sizes))
            .replace("@@SECONDS@@", repr(args.seconds)))
    result = execute(code, int(len(args.sizes) * (args.seconds + 20)) + 30)
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
