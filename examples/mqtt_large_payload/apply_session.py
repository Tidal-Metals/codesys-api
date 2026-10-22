"""Apply the demo sources to the project open in the API session, rebuild and save it.

Run from the repo root: python examples/mqtt_large_payload/apply_session.py [--fork-only]
--fork-only saves the sources even when they do not compile against the original demo's upstream MQTT 1.2.0.7
reference (they use the fork's MQTTPublish.Rejected); bench_cycle passes it and compiles the fork copy after.
An A/B run on 1.2.0.7 needs the Rejected lines in st/edge/EdgeTest.st and st/split/SplitTest.st removed.
Download afterwards with deploy_demo.py.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

SOURCE_DIR = Path(__file__).resolve().parent

CODE = """
DEMO_IN_SESSION = True
execfile(@@BUILDER@@, globals())
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('/mqtt_large_payload_demo.project'), p.path
steps = []
report = apply_demo(p, @@SOURCE_DIR@@, steps)
report['steps'] = steps
if @@FORK_ONLY@@ and not report['success']:
    # the original demo references upstream MQTT 1.2.0.7; sources using the fork's additions (MQTTPublish.Rejected)
    # cannot compile there. Save anyway: bench_cycle's app_check compiles the copy that references the fork.
    report['errorsAgainstOriginalReferences'] = len(report['errors'])
    report['success'] = True
if report['success']:
    p.save()
    report['saved'] = True
result = report
""".replace("@@BUILDER@@", repr(str(SOURCE_DIR / "build_demo_project.py"))).replace("@@SOURCE_DIR@@", repr(str(SOURCE_DIR))).replace(
    "@@FORK_ONLY@@", repr("--fork-only" in sys.argv))

if __name__ == "__main__":
    report = execute(CODE, 240)
    messages = report.pop("messages", None) or []
    report["memory"] = [m["text"] for m in messages if "emory" in m["text"] or "address" in m["text"]]
    print(json.dumps(report, indent=1))
    raise SystemExit(0 if report.get("success") else 1)
