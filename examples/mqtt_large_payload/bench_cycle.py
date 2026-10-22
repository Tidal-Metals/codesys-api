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
TASK_INTERVAL_CODE = """
p = scriptengine.projects.primary
tasks = []
for obj in p.get_children(True):
    try:
        is_task = obj.is_task
    except Exception:
        is_task = False
    if is_task:
        obj.interval = '@@MS@@'
        obj.interval_unit = 'ms'
        tasks.append('%s=%s %s' % (obj.get_name(), obj.interval, obj.interval_unit))
p.save()
result = {'success': bool(tasks), 'tasks': tasks}
"""


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
    parser.add_argument("--deploy-only", action="store_true", help="stop after deploying (and --plc-set): no tests")
    parser.add_argument("--task-ms", type=int, help="set the demo's task interval (ms) before deploying")
    parser.add_argument("--plc-set", action="append", default=[], metavar="NAME=VALUE",
                        help="write an online value after deploying, e.g. PLC_PRG.IsClientCalledLast=TRUE")
    parser.add_argument("--fork", type=Path, default=FORK, help="CODESYS-MQTT checkout to build (default ~/projects/CODESYS-MQTT)")
    args = parser.parse_args()
    fork = args.fork.resolve()
    out = HERE / "results" / "exp" / args.label
    out.mkdir(parents=True, exist_ok=True)
    log = out / "cycle.log"
    meta = {"label": args.label,
            "commit": subprocess.check_output(["git", "-C", str(fork), "rev-parse", "--short", "HEAD"], text=True).strip(),
            "diff": subprocess.check_output(["git", "-C", str(fork), "diff", "--", "src", "build.json"], text=True)}
    (out / "library.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if not args.skip_build:
        step("build library")
        if run([PY, "tools/build_library.py"], fork, log) != 0:
            sys.exit("build failed; see %s" % log)
    step("close session project")
    api("/plc/logout")
    api("/project/close")
    if args.apply_sources:
        step("apply demo sources to the original demo")
        api("/project/open", {"path": str(DEMO).replace("\\", "/")})
        if run([PY, HERE / "apply_session.py", "--fork-only"], REPO, log) != 0:
            sys.exit("apply_session failed; see %s" % log)
        api("/project/close")
    step("compile demo against the build")
    if run([PY, "tools/app_check.py", "--host", DEMO, "--keep-as", DEMO_TM], fork, log) != 0:
        sys.exit("application check failed; see %s" % log)
    step("open and deploy")
    api("/project/open", {"path": str(DEMO_TM).replace("\\", "/")})
    refs = subprocess.check_output([PY, "run_ide_script.py", "tmp/list_mqtt_refs.py", "--timeout", "60"], cwd=REPO, text=True)
    if "MQTT, 1.3" not in refs:
        sys.exit("the open demo does not reference the fork:\n" + refs)
    if args.task_ms:
        step("task interval %d ms" % args.task_ms)
        sys.path.insert(0, str(REPO))
        from run_ide_script import execute  # noqa: E402
        result = execute(TASK_INTERVAL_CODE.replace("@@MS@@", str(args.task_ms)), 120)
        if not result.get("success"):
            sys.exit("setting the task interval failed: %s" % result)
        meta["taskMs"] = args.task_ms
        meta["tasks"] = result.get("tasks")
        (out / "library.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if run([PY, HERE / "deploy_demo.py"], REPO, log) != 0:
        sys.exit("deploy failed; see %s" % log)
    if args.plc_set:
        step("online values " + ", ".join(args.plc_set))
        sys.path.insert(0, str(REPO))
        from run_ide_script import execute  # noqa: E402
        pairs = [tuple(item.split("=", 1)) for item in args.plc_set]
        code = ("on = session.ensure_online_application('', True)\nfor path, value in %r:\n"
                "    on.set_prepared_value(path, value)\non.write_prepared_values()\nresult = {'success': True}\n" % pairs)
        if not execute(code, 60).get("success"):
            sys.exit("writing online values failed")
        meta["plcSet"] = args.plc_set
        (out / "library.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if args.deploy_only:
        print("done: deployed %s (no tests)" % args.label, flush=True)
        return 0
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
    latency |= run([PY, HERE / "measure_latency.py", "--count", "40", "--second-call",
                    "--out", out / "latency_second_call.json"], REPO, log)
    print("done: %s (throughput exit %d, edge exit %d, latency exit %d)" % (out, code, edge, latency))
    return code or edge or latency


if __name__ == "__main__":
    raise SystemExit(main())
