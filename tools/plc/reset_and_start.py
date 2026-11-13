"""Recover the bench PLC application from a task stuck in a system call (docs/modbus-bench.md).

    python tools/plc/reset_and_start.py [cold]

Resets the application in the IDE session (warm, or cold with the argument) with force_kill, which kills a task
mid-cycle where the device allows it, then starts it, and reports the state. The scan check reads the MQTT demo's
PLC_PRG.CycleStartUs and PLC_PRG.IsBrokerConnected; with another application those reads fail after the reset.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

CODE = """
import time
from scriptengine import ResetOption
out = {'steps': []}
on = session.ensure_online_application('', True)
out['steps'].append('before: ' + str(on.application_state))
on.reset(ResetOption.@@OPTION@@, True)
out['steps'].append('after reset: ' + str(on.application_state))
on.start()
deadline = time.time() + 15
while 'run' not in str(on.application_state).lower() and time.time() < deadline:
    time.sleep(0.5)
out['steps'].append('after start: ' + str(on.application_state))
a = str(on.read_value('PLC_PRG.CycleStartUs'))
time.sleep(2)
b = str(on.read_value('PLC_PRG.CycleStartUs'))
out['scanning'] = a != b
out['broker'] = str(on.read_value('PLC_PRG.IsBrokerConnected'))
result = {'success': True, 'out': out}
"""
option = "Cold" if len(sys.argv) > 1 and sys.argv[1] == "cold" else "Warm"
print(json.dumps(execute(CODE.replace("@@OPTION@@", option), 300), indent=1))
