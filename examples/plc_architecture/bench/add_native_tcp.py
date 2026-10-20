"""Add native Modbus TCP servers (Ethernet -> Modbus_TCP_Client -> one server per unit) to the project in the session.

Usage: python examples/plc_architecture/bench/add_native_tcp.py [--units 11,12,13,14,15] [--ip 192,168,50,67]
    [--cycle-ms 1000] [--list] [--remove]
The Ethernet node is bound to ETH1 ('et1', the port with the PLC's own address 192.168.50.123) with
SaveCommunicationSettings false, so a download can't change the PLC's IP settings. Each server is imported from the
proven template examples/modbus_tcp_native/GatewayUnit1_20260924.export (FC03, offset 0, 2 registers) and given its
unit id, IP, a 500 ms reply timeout and the cycle time; the template's I/O mapping is removed and the server is
updated every bus cycle, so it polls without IEC code (a rate test, measured at the simulator). The API's channel
endpoints only build serial servers, hence the template. The client's AutoReconnect is turned on: off (the default),
one failure stops it. Each server opens its own TCP connection: the NA111-E accepts six in total.
--list prints the Ethernet node's parameters; --remove deletes the Ethernet subtree. Logs the session out first.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

TEMPLATE = ROOT / "examples" / "modbus_tcp_native" / "GatewayUnit1_20260924.export"
ETHERNET = {"10": "'et1'", "12": '"et1"', "0": "[192, 168, 50, 123]", "1": "[255, 255, 255, 0]", "13": "false"}
CODE = """
import clr
clr.AddReference('DeviceObject')
on = scriptengine.online.create_online_application(scriptengine.projects.primary.active_application)
if on.is_logged_in:
    on.logout()
proj = scriptengine.projects.primary
repo = scriptengine.device_repository
plc = [c for c in proj.get_children() if getattr(c, 'is_device', False)][0]
steps = []

def child(parent, name):
    for c in parent.get_children():
        if c.get_name() == name:
            return c
    return None

def params(device):
    return [(int(p.id), str(p.visible_name), str(p.value)) for connector in device.connectors for p in connector.host_parameters]

def set_params(device, values):
    for connector in device.connectors:
        for p in connector.host_parameters:
            if str(p.id) in values:
                before = str(p.value)
                p.value = values[str(p.id)]
                steps.append('%s [%s] %s: %s -> %s' % (device.get_name(), p.id, p.visible_name, before, str(p.value)))

def clear_mappings(node):
    parent = node.connectors[0].host_parameters.parent
    iface = [i for i in parent.GetType().GetInterfaces() if 'IParameterSetContainer' in i.Name][0]
    cleared = 0
    stack = list(iface.GetProperty('ParameterSet').GetValue(parent, None))
    while stack:
        sub = stack.pop()
        try:
            maps = sub.IoMapping.VariableMappings
            while maps.Count:
                maps.RemoveAt(0)
                cleared += 1
        except Exception:
            pass
        try:
            if sub.HasSubElements:
                stack.extend(list(sub.SubElements))
        except Exception:
            pass
    return cleared

eth = child(plc, 'Ethernet')
if @@REMOVE@@:
    if eth is not None:
        eth.remove()
        steps.append('removed Ethernet')
    proj.save()
    result = {'success': True, 'steps': steps}
else:
    if eth is None:
        plc.add('Ethernet', repo.create_device_identification(110, '0000 0002', '4.2.0.0'))
        eth = child(plc, 'Ethernet')
        steps.append('added Ethernet')
    if @@LIST@@:
        result = {'success': True, 'ethernet': params(eth), 'steps': steps}
    else:
        set_params(eth, @@ETHERNET@@)
        client = child(eth, 'Modbus_TCP_Client')
        if client is None:
            eth.add('Modbus_TCP_Client', repo.create_device_identification(88, '0000 0003', '4.5.0.0'))
            client = child(eth, 'Modbus_TCP_Client')
            steps.append('added Modbus_TCP_Client')
        set_params(client, {'9002': 'TRUE'})               # AutoReconnect
        for unit in @@UNITS@@:
            name = 'GW_U%d' % unit
            old = child(client, name)
            if old is not None:
                old.remove()
            before = set(c.get_name() for c in client.get_children())
            client.import_native(@@TEMPLATE@@)
            added = [c for c in client.get_children() if c.get_name() not in before]
            assert len(added) == 1, [c.get_name() for c in added]
            node = added[0]
            node.rename(name)
            set_params(node, {'9100': str(unit), '9101': '500', '9102': '[@@IP@@]', '9103': '502'})
            for connector in node.connectors:
                for p in connector.host_parameters:
                    if int(p.id) == 17825792:                # the channel: a struct, set field by field
                        p[6].value = str(@@CYCLE@@)
                        steps.append('%s channel %s' % (name, str(p.value)))
            cleared = clear_mappings(node)
            node.driver_info.always_update_variables = scriptengine.AlwaysUpdateVariablesMode.AlwaysInBusCycle
            steps.append('%s imported, %d template mapping(s) removed' % (name, cleared))
        proj.save()
        result = {'success': True, 'steps': steps}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--remove", action="store_true")
    parser.add_argument("--units", default="11,12,13,14,15")
    parser.add_argument("--ip", default="192,168,50,67")
    parser.add_argument("--cycle-ms", type=int, default=1000)
    args = parser.parse_args()
    code = (CODE.replace("@@REMOVE@@", repr(args.remove)).replace("@@LIST@@", repr(args.list))
            .replace("@@UNITS@@", repr([int(u) for u in args.units.split(",")])).replace("@@IP@@", args.ip)
            .replace("@@ETHERNET@@", repr(ETHERNET)).replace("@@TEMPLATE@@", repr(str(TEMPLATE)))
            .replace("@@CYCLE@@", str(args.cycle_ms)))
    print(json.dumps(execute(code, 300), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
