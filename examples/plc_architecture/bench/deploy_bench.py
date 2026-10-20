"""Download the two-task bench to the bench PLC through the IDE session, start it, make it the boot app.

Run from the repo root with arch_bench.project open in the session (after apply_bench.py):
    python examples/plc_architecture/bench/deploy_bench.py [project name; default arch_bench]
Full download: it replaces whatever runs on the PLC. Redeploy the MQTT demo afterwards to restore it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

DOWNLOAD = """
import time
from scriptengine import OnlineChangeOption
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('/@@PROJECT@@.project'), p.path
on = session.ensure_online_application('', False)
on.login(OnlineChangeOption.Never, True)
if 'run' not in str(on.application_state).lower():
    on.start()
deadline = time.time() + 10
while 'run' not in str(on.application_state).lower() and time.time() < deadline:
    time.sleep(0.5)
on.create_boot_application()
state = str(on.application_state)
# The handle used for the download resolves most variables as 'Invalid variable reference' afterwards;
# dispose it by application path (not '') so the next request logs in fresh.
session.dispose_online_application(session.find_application('')[1]['path'], True)
result = {'success': True, 'state': state}
"""

LOGIN = """
on = session.ensure_online_application('', True)
result = {'success': True, 'state': str(on.application_state)}
"""

READBACK = """
import time
on = session.ensure_online_application('', True)
time.sleep(5)
names = ['PRG_ControlTask.ScanCount', 'PRG_CommsTask.ScanCount', 'PRG_Comms.MqttLink.BROKER_CONNECTED',
         'PRG_CommsTask.PublishCount', 'PRG_ControlTask.MaxExecUs']
result = {'success': True, 'state': str(on.application_state),
          'values': dict((name, str(on.read_value(name))) for name in names)}
"""

if __name__ == "__main__":
    project = sys.argv[1] if len(sys.argv) > 1 else "arch_bench"
    deployed = execute(DOWNLOAD.replace("@@PROJECT@@", project), 300)
    print(json.dumps(deployed, indent=1))
    if deployed.get("success"):
        execute(LOGIN, 120)
        if project == "arch_bench":
            print(json.dumps(execute(READBACK, 120), indent=1))
