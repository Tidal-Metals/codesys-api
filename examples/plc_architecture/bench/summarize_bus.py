"""Summarize bench/results/bus/*.json (measure_bus.py and verify_arch.py output) as one Markdown table.

Usage: python examples/plc_architecture/bench/summarize_bus.py [results_dir]
Poll rates come from the simulators (replies each unit sent per second), so ModbusFB and native runs are
measured the same way. Unit 1 on the serial line is the real ME31, which the simulator doesn't see.
"""
import json
import statistics
import sys
from pathlib import Path

RESULTS = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "results" / "bus"
DEAD = {"gateway": 25, "serial": 5}


def rates(run, kind, exclude_dead):
    units = run.get("simulator", {}).get(kind, {}).get("repliesPerSecond", {})
    return [rate for unit, rate in units.items() if not (exclude_dead and int(unit) == DEAD[kind])]


def row(name):
    run = json.loads((RESULTS / (name + ".json")).read_text(encoding="utf-8"))
    verify_path = RESULTS / ("verify_" + name + ".json")
    verify = json.loads(verify_path.read_text(encoding="utf-8")) if verify_path.exists() else {}
    is_dead = name.endswith("_dead")
    cells = [name]
    for kind in ("gateway", "serial"):
        values = rates(run, kind, is_dead)
        cells.append("%.2f (%.2f-%.2f)" % (statistics.median(values), min(values), max(values)) if values else "-")
        cells.append("%.1f" % sum(values) if values else "-")
    errors = ["%d" % run.get("line%d.errors" % line, 0) for line in (1, 2) if "line%d.errors" % line in run]
    native = sum(v for k, v in run.items() if k.startswith("native.ErrorEdges"))
    shares = [(v, k) for k, v in run.items() if k.startswith("native.ErrorShare")]
    worst = max(shares) if shares else (0, "")
    in_error = " (worst server in error %d%% of cycles)" % round(worst[0] * 100) if worst[0] else ""
    cells.append("/".join(errors) + (" + %d native edges%s" % (native, in_error) if native else ""))
    cells.append("%.2f" % (run["control.MaxDeviationUs"] / 1000))
    cells.append("%.2f" % (run["control.MeanExecUs"] / 1000))
    cells.append("%.2f" % (run["busTask.MaxExecUs"] / 1000))
    bus = verify.get("bus", {})
    cells.append("%s/%s, %s NaN" % (bus.get("minMatch", "-"), bus.get("mismatches", "-"), bus.get("nanMax", "-")))
    return cells


def main():
    header = ["run", "gateway unit/s median (min-max)", "gateway line/s", "serial unit/s median (min-max)",
              "serial line/s", "PLC errors (line 1/2)", "control max dev ms", "control mean exec ms",
              "bus task max exec ms", "broker: min match/mismatch, max NaN"]
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for mode in ("fb", "native"):
        for run in ("baseline", "saturation", "dead"):
            name = "%s_%s" % (mode, run)
            if (RESULTS / (name + ".json")).exists():
                print("| " + " | ".join(row(name)) + " |")


if __name__ == "__main__":
    main()
