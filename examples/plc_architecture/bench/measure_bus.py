"""Measure the bench's Modbus lines with control running: per-device poll rate, errors, request times, jitter.

Run from the repo root with the bench application running (deploy_bench.py) and the simulators applied
(bus_sim.py apply). Usage:
    python examples/plc_architecture/bench/measure_bus.py --name baseline [--gateway-period 1000] [--serial-period 1000]
        [--fb-serial on|off] [--seconds 60] [--out results/bus_baseline.json]
Each device's poll rate is counted twice: by the PLC (GVL_Bus.BlockReads, ModbusFB lines only) and by the
simulators from the requests they answered (logs/rtu_sim_<COM>_status.json), the neutral yardstick that also
covers native device-tree masters. Every counter carries its own read time: the ~80 sequential online reads take
seconds, and dividing by the sleep alone overstated rates by ~20%. Block periods are written online; 0 = poll as fast as the line allows.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

GVL_BUS = ROOT / "tmp" / "arch_bench" / "src" / "st" / "GVL_Bus.st"
SIM_STATUS = {"gateway": ROOT / "logs" / "rtu_sim_COM11_status.json", "serial": ROOT / "logs" / "rtu_sim_COM12_status.json"}
CONTROL = ["ScanCount", "MinIntervalUs", "MaxIntervalUs", "MaxDeviationUs", "MaxExecUs", "ExecTotalUs"]

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

if @@SETTINGS@@:
    write(@@SETTINGS@@)
time.sleep(@@SETTLE@@)
write([('PRG_ControlTask.ResetStats', 'TRUE'), ('PRG_BusTask.ResetStats', 'TRUE')])
blocks = @@BLOCKS@@

def counters():
    # Online reads are sequential and slow (~0.1 s each), so every counter pair carries its own timestamp.
    rows = dict(('b%d' % b, (value('GVL_Bus.BlockReads[%d]' % b), value('GVL_Bus.BlockErrors[%d]' % b), time.time())) for b in blocks)
    for l in @@LINES@@:
        rows['l%d' % l] = (value('PRG_Bus.Lines[%d].RequestCount' % l), value('PRG_Bus.Lines[%d].ErrorCount' % l), time.time())
    for n in range(1, @@NATIVE_COUNT@@ + 1):
        rows['n%d' % n] = (value('PRG_NativeSerial.ErrorCycles[%d]' % n), value('PRG_NativeSerial.ErrorEdges[%d]' % n), time.time())
    if @@NATIVE_COUNT@@:
        rows['nc'] = (value('PRG_NativeSerial.CycleCount'), 0, time.time())
    return rows

def sim_status():
    texts = {}
    for kind, path in @@SIM_STATUS@@:
        try:
            texts[kind] = open(path).read()
        except IOError:
            texts[kind] = None
    return texts

sims_before = sim_status()
before = counters()
started = time.time()
time.sleep(@@SECONDS@@)
elapsed = time.time() - started
after = counters()
sims_after = sim_status()

def rate(key):
    seconds = after[key][2] - before[key][2]
    return [after[key][0] - before[key][0], after[key][1] - before[key][1], round(seconds, 2)]
run = {'elapsed': elapsed}
for name in @@CONTROL@@:
    run['control.' + name] = value('PRG_ControlTask.' + name)
for index in range(6):
    run['control.Deviation[%d]' % index] = value('PRG_ControlTask.Deviation[%d]' % index)
run['busTask.MaxExecUs'] = value('PRG_BusTask.MaxExecUs')
for l in @@LINES@@:
    run['line%d.requests' % l], run['line%d.errors' % l], run['line%d.seconds' % l] = rate('l%d' % l)
    run['line%d.LastRequestUs' % l] = value('PRG_Bus.Lines[%d].LastRequestUs' % l)
    run['line%d.MaxRequestUs' % l] = value('PRG_Bus.Lines[%d].MaxRequestUs' % l)
run['blocks'] = dict((b, rate('b%d' % b)) for b in blocks)
run['simTexts'] = [sims_before, sims_after]
# Native servers: error edges in the window, and the share of bus cycles spent in error.
for number in range(1, @@NATIVE_COUNT@@ + 1):
    cycles, edges, _ = rate('n%d' % number)
    run['native.ErrorEdges[%d]' % number] = edges
    run['native.ErrorShare[%d]' % number] = round(float(cycles) / max(rate('nc')[0], 1), 3)
run['sources'] = dict((s, [str(on.read_value('GVL_Bus.SourceHealthy[%d]' % s)), value('GVL_Bus.SourceFailCount[%d]' % s)]) for s in @@SOURCES@@)
result = {'success': True, 'run': run}
"""


def block_lines():
    """Block number -> (line, unit) from the generated GVL_Bus."""
    text = GVL_BUS.read_text(encoding="utf-8")
    rows = re.findall(r"\(Line := (\d+), UnitId := (\d+), ReadFunction := E_BusFunction\.(\w+)", text)
    return dict((index + 1, (int(line), int(unit), function)) for index, (line, unit, function) in enumerate(rows))


def sim_units(text):
    status = json.loads(text)
    return dict((int(unit), (row.get("requests", 0), row.get("replies", 0))) for unit, row in (status.get("units") or {}).items())


def heartbeat(text):
    """The simulator's heartbeatAt in seconds (ISO 8601 with 7 fractional digits and a UTC offset)."""
    stamp = json.loads(text)["heartbeatAt"]
    stamp = re.sub(r"(\.\d{6})\d*", r"\1", stamp)
    return datetime.fromisoformat(stamp).timestamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--gateway-period", type=int, help="ms for every gateway-line block; 0 = as fast as possible")
    parser.add_argument("--serial-period", type=int, help="ms for every serial-line block (ModbusFB line)")
    parser.add_argument("--fb-serial", choices=["on", "off"], help="turn the ModbusFB serial line on or off")
    parser.add_argument("--fb-gateway", choices=["on", "off"], help="turn the ModbusFB gateway line on or off")
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--settle", type=float, default=8)
    parser.add_argument("--sources", default="1,15,31,35", help="sources whose health to report")
    parser.add_argument("--out")
    args = parser.parse_args()
    lines = block_lines()
    gvl = GVL_BUS.read_text(encoding="utf-8")
    line_numbers = list(range(1, int(re.search(r"LINE_COUNT : INT := (\d+);", gvl).group(1)) + 1))
    native = GVL_BUS.with_name("GVL_Native.st")
    native_count = len(re.findall(r"\tUnit\d+ :", native.read_text(encoding="utf-8"))) if native.exists() else 0
    settings = []
    for block, (line, _, _) in lines.items():
        period = args.gateway_period if line == 1 else args.serial_period
        if period is not None:
            settings.append(("GVL_Bus.Blocks[%d].PeriodMs" % block, str(period)))
    if args.fb_gateway:
        settings.append(("PRG_Bus.Lines[1].IsEnabled", "TRUE" if args.fb_gateway == "on" else "FALSE"))
    if args.fb_serial and 2 in line_numbers:
        settings.append(("PRG_Bus.Lines[2].IsEnabled", "TRUE" if args.fb_serial == "on" else "FALSE"))
    code = (CODE.replace("@@SETTINGS@@", repr(settings)).replace("@@SETTLE@@", repr(args.settle))
            .replace("@@SECONDS@@", repr(args.seconds)).replace("@@BLOCKS@@", repr(sorted(lines)))
            .replace("@@CONTROL@@", repr(CONTROL)).replace("@@SOURCES@@", repr([int(s) for s in args.sources.split(",")]))
            .replace("@@LINES@@", repr(line_numbers)).replace("@@NATIVE_COUNT@@", str(native_count))
            .replace("@@SIM_STATUS@@", repr([(kind, str(path)) for kind, path in SIM_STATUS.items()])))
    result = execute(code, int(args.seconds + args.settle) + 300)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    run = result["run"]
    seconds = run["elapsed"]
    run["control.MeanExecUs"] = round(run["control.ExecTotalUs"] / max(run["control.ScanCount"], 1))
    per_block = {}
    for block, (reads, errors, window) in run.pop("blocks").items():
        line, unit, function = lines[int(block)]
        per_block[int(block)] = {"line": line, "unit": unit, "function": function, "reads": reads, "errors": errors,
                                 "seconds": window, "periodMs": round(window * 1000 / reads) if reads else None}
    run["blocks"] = per_block
    for l in line_numbers:
        run["line%d.perSecond" % l] = round(run["line%d.requests" % l] / run["line%d.seconds" % l], 2)
    # The simulators' view over the same window: replies each unit sent per second, timed by the simulator's own
    # heartbeat (the status file is rewritten every few seconds).
    texts_before, texts_after = run.pop("simTexts")
    run["simulator"] = {}
    for kind in SIM_STATUS:
        if not texts_before.get(kind) or not texts_after.get(kind):
            continue
        first, last = sim_units(texts_before[kind]), sim_units(texts_after[kind])
        window = (heartbeat(texts_after[kind]) - heartbeat(texts_before[kind])) or seconds
        rates = dict((unit, round((last[unit][1] - first.get(unit, last[unit])[1]) / window, 2)) for unit in last)
        run["simulator"][kind] = {"seconds": round(window, 1), "repliesPerSecond": rates,
                                  "total": round(sum(rates.values()), 1)}
    run["settings"] = {"gatewayPeriod": args.gateway_period, "serialPeriod": args.serial_period, "fbSerial": args.fb_serial,
                       "fbGateway": args.fb_gateway,
                       "seconds": args.seconds, "name": args.name}
    text = json.dumps(run, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    summary = {k: v for k, v in run.items() if not isinstance(v, dict)}
    summary["simulatorTotals"] = dict((k, v["total"]) for k, v in run["simulator"].items())
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
