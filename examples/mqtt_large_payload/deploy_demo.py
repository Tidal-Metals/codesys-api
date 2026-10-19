"""Download the MQTT demo to the bench PLC through the IDE session, start it and make it the boot app.

Run from the repo root with the demo project open in the session:
    python examples/mqtt_large_payload/deploy_demo.py
Full download (OnlineChangeOption.Never, delete foreign apps): it replaces whatever runs on the PLC.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

DIAGNOSTICS = [
    "PLC_PRG.IsBrokerConnected", "PLC_PRG.Sequence", "PLC_PRG.LargeSentCount", "PLC_PRG.ConcatSentCount",
    "PLC_PRG.LastLargeLength", "PLC_PRG.LastConcatLength", "PLC_PRG.TimeoutCount",
    "PLC_PRG.OverflowCount", "PLC_PRG.SkippedBusyCount",
]

CODE = """
import time
from scriptengine import OnlineChangeOption
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('/mqtt_large_payload_demo.project'), p.path
out = {'steps': []}
session.report_progress({'step': 'login with full download'})
on = session.ensure_online_application('', False)
on.login(OnlineChangeOption.Never, True)
out['steps'].append('logged in, state=' + str(on.application_state))
if 'run' not in str(on.application_state).lower():
    on.start()
deadline = time.time() + 10
while 'run' not in str(on.application_state).lower() and time.time() < deadline:
    time.sleep(0.5)
out['steps'].append('state=' + str(on.application_state))
session.report_progress({'step': 'boot application'})
on.create_boot_application()
out['steps'].append('boot application created')
names = @@NAMES@@
deadline = time.time() + 45
values = {}
while time.time() < deadline:
    values = dict((name, str(on.read_value(name))) for name in names)
    if values['PLC_PRG.LargeSentCount'] not in ('0', 'UDINT#0') and values['PLC_PRG.ConcatSentCount'] not in ('0', 'UDINT#0'):
        break
    time.sleep(1)
out['diagnostics'] = values
out['state'] = str(on.application_state)
out['success'] = True
result = out
""".replace("@@NAMES@@", repr(DIAGNOSTICS))

if __name__ == "__main__":
    print(json.dumps(execute(CODE, 240), indent=1))
