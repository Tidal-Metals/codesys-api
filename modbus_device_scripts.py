"""Device, COM, master, and project Modbus script generators."""

from modbus_script_utils import DEVICE_PARAM_IDS, device_script, literal, render


def list_device_tree():
    return render(
        """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _devices = []
    for _c0 in proj.get_children():
        if not hasattr(_c0, 'device_parameters'):
            continue
        _plc_name = _c0.get_name() if hasattr(_c0, 'get_name') else str(_c0)
        _plc_entry = {"name": _plc_name, "type": "plc", "children": []}

        if hasattr(_c0, 'get_children'):
            for _c1 in _c0.get_children():
                if not hasattr(_c1, 'device_parameters'):
                    continue
                _c1_entry = {"name": _c1.get_name() if hasattr(_c1, 'get_name') else str(_c1), "children": []}
                try:
                    _did = _c1.get_device_identification()
                    _c1_entry["device_type"] = int(_did.type)
                    _c1_entry["device_id"] = str(_did.id)
                    _c1_entry["device_version"] = str(_did.version)
                except:
                    pass

                if hasattr(_c1, 'get_children'):
                    for _c2 in _c1.get_children():
                        if not hasattr(_c2, 'device_parameters'):
                            continue
                        _c2_entry = {"name": _c2.get_name() if hasattr(_c2, 'get_name') else str(_c2), "children": []}
                        try:
                            _did2 = _c2.get_device_identification()
                            _c2_entry["device_type"] = int(_did2.type)
                            _c2_entry["device_id"] = str(_did2.id)
                            _c2_entry["device_version"] = str(_did2.version)
                        except:
                            pass

                        if hasattr(_c2, 'get_children'):
                            for _c3 in _c2.get_children():
                                if not hasattr(_c3, 'device_parameters'):
                                    continue
                                _c3_entry = {"name": _c3.get_name() if hasattr(_c3, 'get_name') else str(_c3)}
                                try:
                                    _did3 = _c3.get_device_identification()
                                    _c3_entry["device_type"] = int(_did3.type)
                                    _c3_entry["device_id"] = str(_did3.id)
                                    _c3_entry["device_version"] = str(_did3.version)
                                except:
                                    pass

                                _params = {}
                                for _conn in _c3.connectors:
                                    for _p in _conn.host_parameters:
                                        _pid = int(_p.id)
                                        if _pid == 9100:
                                            _params["slaveAddress"] = str(_p.value)
                                        elif _pid == 9101:
                                            _params["responseTimeout"] = str(_p.value)
                                if _params:
                                    _c3_entry["params"] = _params
                                _c2_entry["children"].append(_c3_entry)
                        _c1_entry["children"].append(_c2_entry)
                _plc_entry["children"].append(_c1_entry)
        _devices.append(_plc_entry)

    result = {"success": True, "devices": _devices}
"""
    )


def get_device(device_name):
    return device_script(
        device_name,
        """\
_info = {"name": _target.get_name()}
try:
    _did = _target.get_device_identification()
    _info["device_type"] = int(_did.type)
    _info["device_id"] = str(_did.id)
    _info["device_version"] = str(_did.version)
except:
    pass

_params = {}
_channels = []
for _conn in _target.connectors:
    _info["interface"] = str(_conn.interface_name)
    for _p in _conn.host_parameters:
        _pid = int(_p.id)
        _pname = str(_p.name)
        _ct = str(_p.channel_type)
        if _pid in @@DEVICE_PARAM_IDS@@:
            _params[_pname] = str(_p.value)
        elif _pname not in ("NewChannelConfig", "SlaveAddress", "ServerAddress",
                "ResponseTimeout", "UseExtendedFunctionCodes", "Server Diag",
                "Confirm Diagnosis", "ConfigVersion"):
            _fields = []
            for _i in range(9):
                try:
                    _fields.append(str(_p[_i].value))
                except:
                    _fields.append("")
            _channels.append({
                "name": _pname,
                "id": _pid,
                "channelType": _ct,
                "config": {
                    "accessType": _fields[0],
                    "readOffset": _fields[1],
                    "readLength": _fields[2],
                    "writeOffset": _fields[3],
                    "writeLength": _fields[4],
                    "trigger": _fields[5],
                    "cycleTime": _fields[6],
                    "errorHandling": _fields[7],
                },
                "raw": str(_p.value)
            })

_info["params"] = _params
_info["channels"] = _channels
result = {"success": True, "device": _info}
""".replace("@@DEVICE_PARAM_IDS@@", DEVICE_PARAM_IDS),
    )


def create_device(master_path, device_name, slave_address=1,
                  device_type=91, device_id="0000 0001", device_version="4.5.0.0"):
    return render(
        """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _current = None
    for _c in proj.get_children():
        if hasattr(_c, 'device_parameters'):
            _current = _c
            break

    if _current is None:
        result = {"success": False, "error": "No PLC device found"}
    else:
        _path_parts = @@PATH_PARTS@@
        for _part in _path_parts:
            _found = False
            if hasattr(_current, 'get_children'):
                for _child in _current.get_children():
                    if hasattr(_child, 'get_name') and _child.get_name() == _part:
                        _current = _child
                        _found = True
                        break
            if not _found:
                result = {"success": False, "error": "Path not found: " + _part}
                _current = None
                break

        if _current is not None:
            _repo = scriptengine.device_repository
            _slave_id = _repo.create_device_identification(@@DEVICE_TYPE@@, @@DEVICE_ID@@, @@DEVICE_VERSION@@)
            _current.add(@@DEVICE_NAME@@, _slave_id)

            _found_device = None
            for _child in _current.get_children():
                if hasattr(_child, 'get_name') and _child.get_name() == @@DEVICE_NAME@@:
                    _found_device = _child
                    break

            if _found_device is None:
                result = {"success": False, "error": "Device created but not found in tree"}
            else:
                for _conn in _found_device.connectors:
                    for _p in _conn.host_parameters:
                        if int(_p.id) == 9100:
                            _p.value = str(@@SLAVE_ADDRESS@@)
                            break
                result = {"success": True, "device": @@DEVICE_NAME@@, "slaveAddress": @@SLAVE_ADDRESS@@}
""",
        PATH_PARTS=literal(master_path.split(".")),
        DEVICE_NAME=literal(device_name),
        SLAVE_ADDRESS=slave_address,
        DEVICE_TYPE=device_type,
        DEVICE_ID=literal(device_id),
        DEVICE_VERSION=literal(device_version),
    )


def delete_device(device_name):
    return device_script(
        device_name,
        """\
_target.remove()
result = {"success": True, "deleted": @@DEVICE_NAME@@}
""".replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def import_native_device(master_path, export_path, device_name, replace=False):
    return render(
        """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _current = None
    for _c in proj.get_children():
        if hasattr(_c, 'device_parameters'):
            _current = _c
            break

    if _current is None:
        result = {"success": False, "error": "No PLC device found"}
    else:
        _path_parts = @@PATH_PARTS@@
        for _part in _path_parts:
            _found = False
            if hasattr(_current, 'get_children'):
                for _child in _current.get_children():
                    if hasattr(_child, 'get_name') and _child.get_name() == _part:
                        _current = _child
                        _found = True
                        break
            if not _found:
                result = {"success": False, "error": "Path not found: " + _part}
                _current = None
                break

        if _current is not None:
            _existing = None
            for _child in _current.get_children():
                if hasattr(_child, 'get_name') and _child.get_name() == @@DEVICE_NAME@@:
                    _existing = _child
                    break
            if _existing is not None and not @@REPLACE@@:
                result = {"success": False, "error": "Device already exists: @@DEVICE_TEXT@@"}
            else:
                if _existing is not None:
                    _existing.remove()
                _import_result = _current.import_native(@@EXPORT_PATH@@, filter=None, handler=None)
                _found_device = None
                for _child in _current.get_children():
                    if hasattr(_child, 'get_name') and _child.get_name() == @@DEVICE_NAME@@:
                        _found_device = _child
                        break
                result = {
                    "success": _found_device is not None,
                    "device": @@DEVICE_NAME@@,
                    "importResult": str(_import_result)
                }
""",
        PATH_PARTS=literal(master_path.split(".")),
        EXPORT_PATH=literal(export_path),
        DEVICE_NAME=literal(device_name),
        DEVICE_TEXT=device_name,
        REPLACE="True" if replace else "False",
    )


def update_device(device_name, slave_address=None, response_timeout=None):
    setters = []
    if slave_address is not None:
        setters.append(
            """\
if _pid == 9100:
    _p.value = str(@@VALUE@@)
    _updated["slaveAddress"] = str(@@VALUE@@)
""".replace("@@VALUE@@", str(slave_address))
        )
    if response_timeout is not None:
        setters.append(
            """\
if _pid == 9101:
    _p.value = str(@@VALUE@@)
    _updated["responseTimeout"] = str(@@VALUE@@)
""".replace("@@VALUE@@", str(response_timeout))
        )

    if not setters:
        return 'result = {"success": False, "error": "No fields to update"}\n'

    return device_script(
        device_name,
        """\
_updated = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _pid = int(_p.id)
@@SETTERS@@
result = {"success": True, "device": @@DEVICE_NAME@@, "updated": _updated}
""".replace("@@SETTERS@@", "\n".join("        " + line if line else "" for block in setters for line in block.splitlines()))
   .replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def get_com_params(com_name):
    return device_script(
        com_name,
        """\
_params = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _params[str(_p.name)] = str(_p.value)
result = {"success": True, "device": @@DEVICE_NAME@@, "params": _params}
""".replace("@@DEVICE_NAME@@", literal(com_name)),
    )


def get_master_params(master_name):
    return device_script(
        master_name,
        """\
_params = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _params[str(_p.name)] = str(_p.value)
result = {"success": True, "device": @@DEVICE_NAME@@, "params": _params}
""".replace("@@DEVICE_NAME@@", literal(master_name)),
    )


def save_project():
    return render(
        """\
proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    proj.save()
    result = {"success": True, "path": str(proj.path)}
"""
    )
