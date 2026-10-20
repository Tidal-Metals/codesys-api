"""Block-size sweep on a ModbusFB line: request rate and time per request vs registers per request.

Usage: python examples/plc_architecture/bench/sweep_block_size.py [--line 1] [--counts 1,10,30,60,125]
    [--skip-units 1] [--park-units 1] [--baud 38400] [--seconds 30] [--out x.json]
Sets Count of the line's register blocks online (all but --skip-units, which keep their size), polls the whole
line as fast as possible (PeriodMs 0) and counts its requests. --park-units stops polling those units (an hour's
period), e.g. the real ME31 while the line runs at a baud rate it doesn't speak. --baud sets a serial line's baud
rate and reconnects it first; run bus_sim.py apply --serial-baud with the same rate. Tags read wrong values
while a block is shorter than its entries: a timing test, not a value test. Restores every block's generated
Count and PeriodMs, and the line's generated baud rate, afterwards. Needs bus_sim.py's 125-register maps
(holding 0-124, input 400-524).
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
REGISTER_READS = ("READ_HOLDING_REGISTERS", "READ_INPUT_REGISTERS")
CODE = """
import time
on = session.ensure_online_application('', True)

def value(path):
    return int(str(on.read_value(path)).split('#')[-1])

def write(values):
    for path, text in values:
        on.set_prepared_value(path, text)
    on.write_prepared_values()

line = @@LINE@@
rows = []

def set_baud(baud):
    write([('GVL_Bus.Lines[%d].Baudrate' % line, str(baud))])
    write([('PRG_Bus.Reconnect[%d]' % line, 'TRUE')])          # PRG_Bus clears it; the line reconnects in 0.5 s
    time.sleep(3)

if @@BAUD@@:
    set_baud(@@BAUD@@)
write([('GVL_Bus.Blocks[%d].PeriodMs' % b, '0') for b in @@LINE_BLOCKS@@])
write([('GVL_Bus.Blocks[%d].PeriodMs' % b, '3600000') for b in @@PARKED@@])
for count in @@COUNTS@@:
    write([('GVL_Bus.Blocks[%d].Count' % b, str(count)) for b in @@SWEPT@@])
    time.sleep(5)
    first = (value('PRG_Bus.Lines[%d].RequestCount' % line), value('PRG_Bus.Lines[%d].ErrorCount' % line), time.time())
    time.sleep(@@SECONDS@@)
    last = (value('PRG_Bus.Lines[%d].RequestCount' % line), value('PRG_Bus.Lines[%d].ErrorCount' % line), time.time())
    rows.append({'count': count, 'requests': last[0] - first[0], 'errors': last[1] - first[1], 'seconds': round(last[2] - first[2], 2),
                 'lastRequestUs': value('PRG_Bus.Lines[%d].LastRequestUs' % line)})
write(@@RESTORE@@)
if @@BAUD@@:
    set_baud(@@LINE_BAUD@@)
result = {'success': True, 'rows': rows}
"""
BLOCK = re.compile(r"\(Line := (\d+), UnitId := (\d+), ReadFunction := E_BusFunction\.(\w+), Start := \d+, Count := (\d+), PeriodMs := (\d+)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--line", type=int, default=1)
    parser.add_argument("--counts", default="1,10,30,60,125")
    parser.add_argument("--skip-units", default="", help="units whose blocks keep their size, e.g. 1 (the ME31)")
    parser.add_argument("--park-units", default="", help="units not polled during the sweep")
    parser.add_argument("--baud", type=int, default=0, help="serial line baud rate for the sweep")
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out")
    args = parser.parse_args()
    skip = set(int(u) for u in args.skip_units.split(",") if u.strip())
    parked_units = set(int(u) for u in args.park_units.split(",") if u.strip())
    gvl = GVL_BUS.read_text(encoding="utf-8")
    blocks = [(index + 1, int(line), int(unit), function, int(count), int(period))
              for index, (line, unit, function, count, period) in enumerate(BLOCK.findall(gvl))]
    on_line = [b for b in blocks if b[1] == args.line]
    parked = [b[0] for b in on_line if b[2] in parked_units]
    swept = [b[0] for b in on_line if b[3] in REGISTER_READS and b[2] not in skip | parked_units]
    line_rows = re.search(r"Lines : ARRAY\[1\.\.LINE_COUNT\] OF ST_BusLine := \[(.*?)\];", gvl, re.S).group(1)
    line_baud = int((re.findall(r"\(([^()]*)\)", line_rows)[args.line - 1].split("Baudrate := ") + ["9600"])[1].split(",")[0])
    restore = ([("GVL_Bus.Blocks[%d].Count" % b[0], str(b[4])) for b in on_line]
               + [("GVL_Bus.Blocks[%d].PeriodMs" % b[0], str(b[5])) for b in on_line])
    counts = [int(c) for c in args.counts.split(",")]
    code = (CODE.replace("@@LINE@@", str(args.line)).replace("@@COUNTS@@", repr(counts)).replace("@@SWEPT@@", repr(swept))
            .replace("@@LINE_BLOCKS@@", repr([b[0] for b in on_line])).replace("@@RESTORE@@", repr(restore))
            .replace("@@PARKED@@", repr(parked)).replace("@@BAUD@@", str(args.baud)).replace("@@LINE_BAUD@@", str(line_baud))
            .replace("@@SECONDS@@", repr(args.seconds)))
    result = execute(code, int(len(counts) * (args.seconds + 15)) + 120)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    for row in result["rows"]:
        row["perSecond"] = round(row["requests"] / row["seconds"], 2)
        row["msPerRequest"] = round(1000 / row["perSecond"], 1) if row["perSecond"] else None
        print(json.dumps(row))
    if args.out:
        report = {"line": args.line, "baud": args.baud or line_baud, "blocks": len(on_line), "sweptBlocks": len(swept),
                  "skipUnits": sorted(skip), "parkedUnits": sorted(parked_units), "rows": result["rows"]}
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
