"""Log out, save and close the session's project, and open another one as primary.

Usage: python examples/plc_architecture/bench/open_project.py <path to .project>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

CODE = """
p = scriptengine.projects.primary
closed = None
if p is not None:
    closed = p.path
    try:
        session.dispose_online_application(session.find_application('')[1]['path'], True)
    except Exception:
        pass
    p.save()
    p.close()
p = scriptengine.projects.open(@@PATH@@, primary=True)
result = {'success': True, 'closed': closed, 'opened': p.path}
"""

if __name__ == "__main__":
    path = str(Path(sys.argv[1]).resolve()).replace("\\", "/")
    print(json.dumps(execute(CODE.replace("@@PATH@@", repr(path)), 180), indent=1))
