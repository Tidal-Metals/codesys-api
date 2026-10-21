"""Compare MQTT library A/B runs (results/ab/<label>/) with each other and with results/throughput/.

    python examples/mqtt_large_payload/compare_ab.py 1.2.0.7 1.3.0.0 [--baseline] [--json out.json]
Per run: send-to-done time of the 26 KB message (LastPublishUs), scans it took, worst client time in a
scan, mean scan time, publishes in the window and timeouts; then idle client cost per call and the
broker-side verification.
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
AB = "ab"  # results/<AB>/<label>; --exp switches to the bench_cycle.py results
RUNS = (["calls%d_qos0" % n for n in (1, 2, 4, 8, 16, 32)]
        + ["adaptive_budget%d_qos0" % b for b in (5000, 10000, 20000)] + ["calls1_qos1"])
FIELDS = [("LastPublishUs", "publish ms", 1000.0), ("LastPublishCycles", "scans", 1), ("MaxClientUs", "max client ms", 1000.0), ("MaxScanClientUs", "max scan client ms", 1000.0),
          ("cycleSampleMeanUs", "mean scan ms", 1000.0), ("sentDuringWindow", "sent", 1), ("TimeoutCount", "timeouts", 1)]


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def baseline(run):
    name = {"calls1_qos1": None}.get(run, run)
    if run == "calls1_qos1":
        return load(RESULTS / "scale" / "tagvalue_per2000_qos1.json")
    return load(RESULTS / "throughput" / (name + ".json"))


def fmt(value, scale):
    if value is None:
        return "-"
    return ("%.1f" % (value / scale)) if scale != 1 else str(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("labels", nargs="+")
    parser.add_argument("--baseline", action="store_true", help="add the 2026-10-19/20 runs in results/throughput/")
    parser.add_argument("--json")
    parser.add_argument("--exp", action="store_true", help="labels are results/exp/<label> (bench_cycle.py) instead of results/ab/")
    args = parser.parse_args()
    if args.exp:
        global AB
        AB = "exp"
    columns = (["2026-10 baseline"] if args.baseline else []) + args.labels
    table = {}
    for run in RUNS:
        sources = ([baseline(run)] if args.baseline else []) + [load(RESULTS / AB / l / (run + ".json")) for l in args.labels]
        table[run] = dict(zip(columns, sources))
        print("\n%s" % run)
        print("  %-16s" % "" + "".join("%18s" % c for c in columns))
        for key, label, scale in FIELDS:
            print("  %-16s" % label + "".join("%18s" % fmt((s or {}).get(key), scale) for s in sources))
    print("\nidle client, us per call (1, 4, 16, 32 calls)")
    idles = ([load(RESULTS / "throughput" / "idle_client.json")] if args.baseline else []) + \
        [load(RESULTS / AB / l / "idle_client.json") for l in args.labels]
    for column, idle in zip(columns, idles):
        runs = (idle or {}).get("runs", [])
        print("  %-18s %s" % (column, ", ".join("%.0f" % r["meanPerCallUs"] for r in runs) or "-"))
    print("\nbroker verification during calls16_qos0")
    verifies = ([load(RESULTS / "throughput" / "verify_calls16.json")] if args.baseline else []) + \
        [load(RESULTS / AB / l / "verify_calls16_qos0.json") for l in args.labels]
    for column, verify in zip(columns, verifies):
        tv = ((verify or {}).get("byFormat") or {}).get("tagvalue") or {}
        print("  %-18s messages=%s allCorrect=%s" % (column, tv.get("messages", "-"), tv.get("allCorrect", "-")))
    if args.json:
        Path(args.json).write_text(json.dumps({"columns": columns, "runs": table}, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
