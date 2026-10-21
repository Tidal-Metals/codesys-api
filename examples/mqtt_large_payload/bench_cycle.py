"""One MQTT library experiment on the bench PLC: build, compile into the demo, deploy, measure.

    python examples/mqtt_large_payload/bench_cycle.py --label buf16k [--skip-build] [--full]
Steps: build ~/projects/CODESYS-MQTT (tools/build_library.py); log the session out and close its
project; compile the original demo against the build and keep that copy
(tools/app_check.py --keep-as ../codesys_projects/mqtt_large_payload_demo_tm/); open it, check its MQTT
reference, deploy it (deploy_demo.py); then measure_profile.py, the quick set of run_ab.py and
edge_test.py --quick (--full: the whole sets). Results in results/exp/<label>/, with the library commit
and diff.
Needs the PLC reservation token in BENCH_RESERVATION.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FORK = Path.home() / "projects" / "CODESYS-MQTT"
DEMO = Path.home() / "projects" / "codesys_projects" / "mqtt_large_payload_demo" / "mqtt_large_payload_demo.project"
DEMO_TM = Path.home() / "projects" / "codesys_projects" / "mqtt_large_payload_demo_tm" / "mqtt_large_payload_demo.project"
API = "http://127.0.0.1:8081/api/v1"
PY = sys.executable


def api(path: str, body: dict | None = None, timeout: int = 240) -> dict:
    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": "ApiKey admin", "X-Bench-Reservation": os.environ["BENCH_RESERVATION"]}
    response = session.post(API + path, json=body or {}, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()


def run(args: list, cwd: Path, log: Path) -> int:
    with log.open("a", encoding="utf-8") as handle:
        handle.write("\n$ %s\n" % " ".join(str(a) for a in args))
        handle.flush()
        return subprocess.call([str(a) for a in args], cwd=cwd, stdout=handle, stderr=subprocess.STDOUT)


def step(name: str) -> None:
    print("== " + name, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--label", required=True)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--apply-sources", action="store_true", help="first apply st/ to the original demo (apply_session.py)")
    parser.add_argument("--edge-only", action="store_true", help="skip the profile and throughput runs")
    args = parser.parse_args()
    out = HERE / "results" / "exp" / args.label
    out.mkdir(parents=True, exist_ok=True)
    log = out / "cycle.log"
    meta = {"label": args.label,
            "commit": subprocess.check_output(["git", "-C", str(FORK), "rev-parse", "--short", "HEAD"], text=True).strip(),
            "diff": subprocess.check_output(["git", "-C", str(FORK), "diff", "--", "src", "build.json"], text=True)}
    (out / "library.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not args.skip_build:
        step("build library")
        if run([PY, "tools/build_library.py"], FORK, log) != 0:
            sys.exit("build failed; see %s" % log)
    step("close session project")
    api("/plc/logout")
    api("/project/close")
    if args.apply_sources:
        step("apply demo sources to the original demo")
        api("/project/open", {"path": str(DEMO).replace("\\", "/")})
        if run([PY, HERE / "apply_session.py"], REPO, log) != 0:
            sys.exit("apply_session failed; see %s" % log)
        api("/project/close")
    step("compile demo against the build")
    if run([PY, "tools/app_check.py", "--host", DEMO, "--keep-as", DEMO_TM], FORK, log) != 0:
        sys.exit("application check failed; see %s" % log)
    step("open and deploy")
    api("/project/open", {"path": str(DEMO_TM).replace("\\", "/")})
    refs = subprocess.check_output([PY, "run_ide_script.py", "tmp/list_mqtt_refs.py", "--timeout", "60"], cwd=REPO, text=True)
    if "MQTT, 1.3" not in refs:
        sys.exit("the open demo does not reference the fork:\n" + refs)
    if run([PY, HERE / "deploy_demo.py"], REPO, log) != 0:
        sys.exit("deploy failed; see %s" % log)
    code = 0
    if not args.edge_only:
        step("profile")
        run([PY, HERE / "measure_profile.py", "--out", out / "profile.json"], REPO, log)
        step("throughput")
        ab = [PY, HERE / "run_ab.py", "--label", args.label, "--out-dir", out] + ([] if args.full else ["--quick"])
        code = run(ab, REPO, log)
    step("edge cases")
    edge = run([PY, HERE / "edge_test.py", "--out", out / "edge.json"] + ([] if args.full else ["--quick"]), REPO, log)
    step("command round trip")
    latency = run([PY, HERE / "measure_latency.py", "--count", "40", "--out", out / "latency_idle.json"], REPO, log)
    latency |= run([PY, HERE / "measure_latency.py", "--count", "40", "--load", "--out", out / "latency_load.json"], REPO, log)
    print("done: %s (throughput exit %d, edge exit %d, latency exit %d)" % (out, code, edge, latency))
    return code or edge or latency


if __name__ == "__main__":
    raise SystemExit(main())
