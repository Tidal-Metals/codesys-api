"""Bus-task CPU per ModbusFB line: mean PRG_BusTask time per cycle with the lines switched on and off online.

Usage: python examples/plc_architecture/bench/measure_line_cost.py [--seconds 20] [--out x.json]
Runs both lines, then line 1 only, then neither, and restores both. ExecUs is wall time per cycle, including any
time the control task preempted it (the same in every state). The lines run at their current periods.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

CODE = """
import time
on = session.ensure_online_application('', True)

def value(path):
    return int(str(on.read_value(path)).split('#')[-1])

def write(values):
    for path, text in values:
        on.set_prepared_value(path, text)
    on.write_prepared_values()

rows = []
for line1, line2 in ((True, True), (True, False), (False, False)):
    write([('PRG_Bus.Lines[1].IsEnabled', str(line1).upper()), ('PRG_Bus.Lines[2].IsEnabled', str(line2).upper())])
    time.sleep(5)
    write([('PRG_BusTask.ResetStats', 'TRUE')])
    time.sleep(@@SECONDS@@)
    scans, total = value('PRG_BusTask.ScanCount'), value('PRG_BusTask.ExecTotalUs')
    rows.append({'line1': line1, 'line2': line2, 'scans': scans, 'meanExecUs': int(total / max(scans, 1)),
                 'maxExecUs': value('PRG_BusTask.MaxExecUs')})
write([('PRG_Bus.Lines[1].IsEnabled', 'TRUE'), ('PRG_Bus.Lines[2].IsEnabled', 'TRUE')])
result = {'success': True, 'rows': rows}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = execute(CODE.replace("@@SECONDS@@", repr(args.seconds)), int(3 * (args.seconds + 10)) + 60)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    for row in result["rows"]:
        print(json.dumps(row))
    if args.out:
        Path(args.out).write_text(json.dumps({"rows": result["rows"]}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
