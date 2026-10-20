"""Add a native Modbus serial master (Modbus_COM + Modbus_Client_COM_Port) to the project open in the session.

Usage: python examples/plc_architecture/bench/add_native_serial.py [--com 2] [--baud 9600]
Same device types and versions as BCNF's serial masters. Also sets the PLC's terminal-block port (parameter 8001)
to RS485, the parity (default NONE) and the master's auto-restart. Servers and channels go under it with
modbus_device_driver_runner.py (masterPath "Modbus_COM.Modbus_Client_COM_Port"), which checks the channels
exist. A server whose channel nobody reads also needs alwaysUpdateVariables (PATCH /api/v1/modbus/devices/<name>).
The project must not be logged in.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

CODE = """
proj = scriptengine.projects.primary
repo = scriptengine.device_repository
plc = [c for c in proj.get_children() if getattr(c, 'is_device', False)][0]
steps = []

def child(parent, name):
    for c in parent.get_children():
        if c.get_name() == name:
            return c
    return None

def set_params(device, values):
    for connector in device.connectors:
        for parameter in connector.host_parameters:
            key = str(parameter.id)
            if key in values:
                before = str(parameter.value)
                parameter.value = values[key]
                steps.append('%s [%s] %s: %s -> %s' % (device.get_name(), key, parameter.visible_name, before, str(parameter.value)))

set_params(plc, {'8001': '16#0003'})
com = child(plc, 'Modbus_COM')
if com is None:
    plc.add('Modbus_COM', repo.create_device_identification(92, '0000 0001', '4.4.0.0'))
    com = child(plc, 'Modbus_COM')
    steps.append('added Modbus_COM')
# Parity is a string parameter: it takes the quoted literal "'NONE'"; plain NONE fails to compile.
set_params(com, {'9200': '@@BAUD@@', '9206': '@@COM@@', '9202': "'@@PARITY@@'"})
for connector in com.connectors:
    for parameter in connector.host_parameters:
        if str(parameter.id) in ('9202', '9203', '9204'):
            steps.append('Modbus_COM [%s] %s = %s' % (parameter.id, parameter.visible_name, str(parameter.value)))
if child(com, 'Modbus_Client_COM_Port') is None:
    com.add('Modbus_Client_COM_Port', repo.create_device_identification(90, '0000 0002', '4.5.0.0'))
    steps.append('added Modbus_Client_COM_Port')
# With auto-restart off (the default) one reply timeout stops the master for good.
set_params(child(com, 'Modbus_Client_COM_Port'), {'9005': 'TRUE'})
proj.save()
result = {'success': True, 'steps': steps}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--com", default="2")
    parser.add_argument("--baud", default="9600")
    parser.add_argument("--parity", default="NONE", choices=["NONE", "EVEN", "ODD"])
    args = parser.parse_args()
    print(json.dumps(execute(CODE.replace("@@COM@@", args.com).replace("@@BAUD@@", args.baud).replace("@@PARITY@@", args.parity), 120), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
