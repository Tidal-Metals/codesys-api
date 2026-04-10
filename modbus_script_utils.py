"""Shared helpers for generating CODESYS IronPython Modbus scripts."""

import textwrap


DEVICE_PARAM_IDS = "(8000, 9100, 9101, 9102, 9200, 9201, 1879052288)"


def render(template, **values):
    """Render a script template without treating Python dict braces as format tokens."""
    script = textwrap.dedent(template).strip()
    for key, value in values.items():
        script = script.replace("@@" + key + "@@", str(value))
    return script + "\n"


def literal(value):
    return repr(value)


def py_bool(value):
    return "True" if value else "False"


def indent(block, spaces=4):
    prefix = " " * spaces
    lines = textwrap.dedent(block).strip("\n").splitlines()
    return "\n".join(prefix + line if line else "" for line in lines)


def normalize_channel(channel):
    """Normalize REST channel payloads for IronPython literal generation."""
    def get(camel_key, snake_key=None, default=None):
        if camel_key in channel:
            return channel[camel_key]
        if snake_key and snake_key in channel:
            return channel[snake_key]
        return default

    return {
        "name": get("name", default="Channel"),
        "accessType": get("accessType", "access_type", 3),
        "readOffset": get("readOffset", "read_offset", "16#0000"),
        "readLength": get("readLength", "read_length", 1),
        "writeOffset": get("writeOffset", "write_offset", "0"),
        "writeLength": get("writeLength", "write_length", "0"),
        "trigger": get("trigger", default=5),
        "cycleTime": get("cycleTime", "cycle_time", 100),
        "errorHandling": get("errorHandling", "error_handling", "true"),
        "comment": get("comment", default=""),
    }


def device_script(device_name, body, needs_clr=False, needs_native_pset=False):
    """Wrap operation-specific code in a complete flat IronPython script."""
    imports = ""
    if needs_clr:
        imports = """\
import clr
import System
clr.AddReference('DeviceObject')
from _3S.CoDeSys.DeviceObject import AccessRight, ChannelType

"""

    if needs_native_pset:
        operation = """\
_conn = _target.connectors[0]
_parent = _conn.host_parameters.parent
_parent_type = _parent.GetType()
_psc_iface = None
for _iface in _parent_type.GetInterfaces():
    if 'IParameterSetContainer' in _iface.Name:
        _psc_iface = _iface
        break

if _psc_iface is None:
    result = {"success": False, "error": "IParameterSetContainer not found"}
else:
    _prop = _psc_iface.GetProperty('ParameterSet')
    _native_pset = _prop.GetValue(_parent, None)
    if _native_pset is None:
        result = {"success": False, "error": "Native ParameterSet not found"}
    else:
@@BODY@@
"""
        operation = operation.replace("@@BODY@@", indent(body, 8))
    else:
        operation = indent(body, 8)

    template = imports + """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _target = None
    _stack = []
    for _root in proj.get_children():
        _stack.append(_root)

    while _stack and _target is None:
        _node = _stack.pop()
        if hasattr(_node, 'get_name') and _node.get_name() == @@DEVICE@@:
            _target = _node
            break
        if hasattr(_node, 'get_children'):
            for _child in _node.get_children():
                _stack.append(_child)

    if _target is None:
        result = {"success": False, "error": "Device not found: @@DEVICE_NAME@@"}
    else:
@@OPERATION@@
"""
    return render(
        template,
        DEVICE=literal(device_name),
        DEVICE_NAME=device_name,
        OPERATION=indent(operation, 8) if needs_native_pset else operation,
    )


def list_devices_script(body):
    return render(
        """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
@@BODY@@
""",
        BODY=indent(body, 4),
    )
