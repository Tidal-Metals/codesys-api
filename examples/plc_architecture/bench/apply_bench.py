"""Generate the bench sources and apply them to the bench project open in the API session, then save it.

Run from the repo root, with ~/projects/codesys_projects/arch_bench/arch_bench.project open in the session and
not logged in (a copy of the MQTT demo project: device, MQTT library, dynamic memory, AppendZ):
    python examples/plc_architecture/bench/apply_bench.py [tag_count]
Download afterwards with deploy_bench.py.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

BENCH = Path(__file__).resolve().parent
SOURCE_DIR = ROOT / "tmp" / "arch_bench" / "src"

CODE = """
execfile(@@BUILDER@@, globals())
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('/arch_bench.project'), p.path
steps = []
report = apply_bench(p, @@SOURCE_DIR@@, steps)
report['steps'] = steps
if report['success']:
    p.save()
    report['saved'] = True
result = report
""".replace("@@BUILDER@@", repr(str(BENCH / "build_bench_project.py"))).replace("@@SOURCE_DIR@@", repr(str(SOURCE_DIR)))

if __name__ == "__main__":
    tags = sys.argv[1] if len(sys.argv) > 1 else "2000"
    subprocess.run([sys.executable, str(BENCH / "make_bench_sources.py"), tags, str(SOURCE_DIR)], check=True)
    print(json.dumps(execute(CODE, 300), indent=1))
