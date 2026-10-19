"""Apply the demo sources to the project open in the API session, rebuild and save it.

Run from the repo root: python examples/mqtt_large_payload/apply_session.py
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
if report['success']:
    p.save()
    report['saved'] = True
result = report
""".replace("@@BUILDER@@", repr(str(SOURCE_DIR / "build_demo_project.py"))).replace("@@SOURCE_DIR@@", repr(str(SOURCE_DIR)))

if __name__ == "__main__":
    report = execute(CODE, 240)
    messages = report.pop("messages", None) or []
    report["memory"] = [m["text"] for m in messages if "emory" in m["text"] or "address" in m["text"]]
    print(json.dumps(report, indent=1))
