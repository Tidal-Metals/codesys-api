"""Block-size sweep on the ModbusFB gateway line: request rate and time per request vs registers per request.

Usage: python examples/plc_architecture/bench/sweep_block_size.py [--counts 1,10,30,60,125] [--seconds 30] [--out x.json]
Sets Count of every line-1 FC03 block online, polls as fast as possible (PeriodMs 0) and counts requests.
The tags read wrong values while Count < 10 (their offsets aren't in the reply): a timing test, not a value test.
Restores Count 10 and PeriodMs 1000 afterwards. Needs bus_sim.py's 125-register holding map.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

GVL_BUS = ROOT / "tmp" / "arch_bench" / "src" / "st" / "GVL_Bus.st"
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
for count in @@COUNTS@@:
    write([('GVL_Bus.Blocks[%d].Count' % b, str(count)) for b in @@BLOCKS@@] + [('GVL_Bus.Blocks[%d].PeriodMs' % b, '0') for b in @@BLOCKS@@])
    time.sleep(5)
    first = (value('PRG_Bus.Lines[1].RequestCount'), value('PRG_Bus.Lines[1].ErrorCount'), time.time())
    time.sleep(@@SECONDS@@)
    last = (value('PRG_Bus.Lines[1].RequestCount'), value('PRG_Bus.Lines[1].ErrorCount'), time.time())
    rows.append({'count': count, 'requests': last[0] - first[0], 'errors': last[1] - first[1], 'seconds': round(last[2] - first[2], 2),
                 'lastRequestUs': value('PRG_Bus.Lines[1].LastRequestUs')})
write([('GVL_Bus.Blocks[%d].Count' % b, '10') for b in @@BLOCKS@@] + [('GVL_Bus.Blocks[%d].PeriodMs' % b, '1000') for b in @@BLOCKS@@])
result = {'success': True, 'rows': rows}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts", default="1,10,30,60,125")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = re.findall(r"\(Line := (\d+), UnitId := \d+, ReadFunction := E_BusFunction\.(\w+)", GVL_BUS.read_text(encoding="utf-8"))
    blocks = [index + 1 for index, (line, function) in enumerate(rows) if line == "1" and function == "READ_HOLDING_REGISTERS"]
    counts = [int(c) for c in args.counts.split(",")]
    code = (CODE.replace("@@COUNTS@@", repr(counts)).replace("@@BLOCKS@@", repr(blocks)).replace("@@SECONDS@@", repr(args.seconds)))
    result = execute(code, int(len(counts) * (args.seconds + 15)) + 120)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    for row in result["rows"]:
        row["perSecond"] = round(row["requests"] / row["seconds"], 2)
        row["msPerRequest"] = round(1000 / row["perSecond"], 1) if row["perSecond"] else None
        print(json.dumps(row))
    if args.out:
        Path(args.out).write_text(json.dumps({"blocks": len(blocks), "rows": result["rows"]}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
