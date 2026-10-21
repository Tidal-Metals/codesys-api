"""Run the MQTT library A/B measurement set against whatever demo build is deployed, for one label.

Run from the repo root after deploy_demo.py, with the demo project open in the session:
    python examples/mqtt_large_payload/run_ab.py --label 1.2.0.7
Writes results/ab/<label>/*.json with the runs of the MQTT publish throughput report
(report/make_throughput_doc.py): the 2,000-tag tag:value scale test at a fixed 1, 2, 4, 8, 16 and 32
client calls per scan (no client budget, as those runs were made before the budget existed), the
adaptive loop (up to 32 calls within 5, 10 and 20 ms), QoS 1 at one call per scan for 45 s,
broker-side verification during the 16-call run, and the idle client cost. The same set for every
library version, so runs compare with each other and with results/throughput/.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable
SCALE = [str(HERE / "measure_scale.py"), "--format", "tagvalue", "--tags-per-scan", "2000"]
NO_BUDGET_US = "1000000"  # a fixed number of calls per scan, whatever they take
RUNS = [("calls%d_qos0" % n, ["--qos", "0", "--client-calls", str(n), "--budget-us", NO_BUDGET_US,
                              "--seconds", "30"], n == 16)
        for n in (1, 2, 4, 8, 16, 32)]
RUNS += [("adaptive_budget%d_qos0" % b, ["--qos", "0", "--client-calls", "32", "--budget-us", str(b),
                                         "--seconds", "30"], False)
         for b in (5000, 10000, 20000)]
RUNS += [("calls1_qos1", ["--qos", "1", "--client-calls", "1", "--budget-us", NO_BUDGET_US, "--seconds", "45"], False)]


QUICK = {"calls1_qos0", "calls4_qos0", "calls16_qos0", "adaptive_budget5000_qos0", "adaptive_budget10000_qos0"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--out-dir", type=Path, help="default results/ab/<label>")
    parser.add_argument("--quick", action="store_true", help="1, 4, 16 calls and 5/10 ms budgets only")
    args = parser.parse_args()
    out = args.out_dir or HERE / "results" / "ab" / args.label
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, extra, verify in RUNS:
        if args.quick and name not in QUICK:
            continue
        print("== %s" % name, flush=True)
        verifier = None
        if verify:
            verifier = subprocess.Popen([PY, str(HERE / "verify_scale.py"), "--seconds", "40",
                                         "--out", str(out / ("verify_" + name + ".json"))])
            time.sleep(2)
        code = subprocess.call([PY] + SCALE + extra + ["--out", str(out / (name + ".json"))])
        if verifier is not None:
            if verifier.wait(timeout=120) != 0:
                failures.append("verify_" + name)
        if code != 0:
            failures.append(name)
    print("== idle_client", flush=True)
    if subprocess.call([PY, str(HERE / "measure_idle_client.py"), "--out", str(out / "idle_client.json")]) != 0:
        failures.append("idle_client")
    print("failures:", failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
