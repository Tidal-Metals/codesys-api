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

try:
    _info["alwaysUpdateVariables"] = str(_target.driver_info.always_update_variables)
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
        _desc = str(_p.description)
        if _pid in @@DEVICE_PARAM_IDS@@:
            _params[_pname] = str(_p.value)
        elif _desc == "ChannelConfig" or (_ct != "None" and _desc == ""):
            _fields = []
            for _i in range(9):
                try:
                    _fields.append(str(_p[_i].value))
                except:
                    break
            if len(_fields) < 8:
                continue
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
    path_parts = [part for part in str(master_path or "").split(".") if part]
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
        PATH_PARTS=literal(path_parts),
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


def update_device(device_name, slave_address=None, response_timeout=None, always_update_variables=None):
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
    if always_update_variables is not None:
        if str(always_update_variables).strip() in ("3", "AlwaysInBusCycle"):
            _mode_expr = "scriptengine.AlwaysUpdateVariablesMode.AlwaysInBusCycle"
            _mode_name = "AlwaysInBusCycle"
        elif str(always_update_variables).strip() in ("2", "OnlyIfUnused"):
            _mode_expr = "scriptengine.AlwaysUpdateVariablesMode.OnlyIfUnused"
            _mode_name = "OnlyIfUnused"
        elif str(always_update_variables).strip() in ("1", "Disabled"):
            _mode_expr = "scriptengine.AlwaysUpdateVariablesMode.Disabled"
            _mode_name = "Disabled"
        else:
            return 'result = {"success": False, "error": "Invalid alwaysUpdateVariables value"}\n'
        setters.append(
            """\
try:
    _target.driver_info.always_update_variables = @@MODE_EXPR@@
    _updated["alwaysUpdateVariables"] = @@MODE_NAME@@
except Exception as _ex:
    _updated["alwaysUpdateVariablesError"] = str(_ex)
""".replace("@@MODE_EXPR@@", _mode_expr).replace("@@MODE_NAME@@", literal(_mode_name))
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
_meta = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _params[str(_p.name)] = str(_p.value)
        _entry = {"value": str(_p.value)}
        try:
            if bool(_p.is_enumeration):
                _allowed = []
                for _v in _p.allowed_values:
                    _allowed.append({
                        "id": int(_v.id),
                        "name": str(_v.name),
                        "description": str(_v.description),
                        "index": int(_v.index),
                    })
                _entry["isEnumeration"] = True
                _entry["currentIndex"] = int(_p.enum_value_index)
                _entry["allowedValues"] = _allowed
        except:
            pass
        _meta[str(_p.name)] = _entry
result = {"success": True, "device": @@DEVICE_NAME@@, "params": _params, "meta": _meta}
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


def update_master_params(master_name, optimization_on=None, auto_restart_communication=None):
    setters = []
    if optimization_on is not None:
        normalized = str(optimization_on).strip().upper()
        value = "TRUE" if normalized in ("TRUE", "1", "YES", "ON") else "FALSE"
        setters.append(
            """\
if _pname == "OptimizationOn":
    _p.value = @@VALUE@@
    _updated["OptimizationOn"] = str(_p.value)
""".replace("@@VALUE@@", value)
        )
    if auto_restart_communication is not None:
        normalized = str(auto_restart_communication).strip().upper()
        value = "TRUE" if normalized in ("TRUE", "1", "YES", "ON") else "FALSE"
        setters.append(
            """\
if _pname == "Auto-restart communication":
    _p.value = @@VALUE@@
    _updated["AutoRestartCommunication"] = str(_p.value)
""".replace("@@VALUE@@", value)
        )

    if not setters:
        return 'result = {"success": False, "error": "No master fields to update"}\n'

    return device_script(
        master_name,
        """\
_updated = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _pname = str(_p.name)
@@SETTERS@@
result = {"success": True, "device": @@DEVICE_NAME@@, "updated": _updated}
""".replace("@@SETTERS@@", "\n".join("        " + line if line else "" for block in setters for line in block.splitlines()))
   .replace("@@DEVICE_NAME@@", literal(master_name)),
    )


def update_com_params(com_name, com_port=None, baudrate=None, data_bits=None, parity=None, stop_bits=None):
    setters = []
    if com_port is not None:
        setters.append(
            """\
if _pname == "ComPort":
    _p.value = str(@@VALUE@@)
    _updated["ComPort"] = str(_p.value)
""".replace("@@VALUE@@", literal(str(com_port)))
        )
    if baudrate is not None:
        setters.append(
            """\
if _pname == "Baudrate":
    _p.value = str(@@VALUE@@)
    _updated["Baudrate"] = str(_p.value)
""".replace("@@VALUE@@", literal(str(baudrate)))
        )
    if data_bits is not None:
        setters.append(
            """\
if _pname == "DataBits":
    _p.value = str(@@VALUE@@)
    _updated["DataBits"] = str(_p.value)
""".replace("@@VALUE@@", literal(str(data_bits)))
        )
    if parity is not None:
        setters.append(
            """\
if _pname == "Parity":
    _p.value = str(@@VALUE@@)
    _updated["Parity"] = str(_p.value)
""".replace("@@VALUE@@", literal(str(parity)))
        )
    if stop_bits is not None:
        setters.append(
            """\
if _pname == "StopBits":
    _p.value = str(@@VALUE@@)
    _updated["StopBits"] = str(_p.value)
""".replace("@@VALUE@@", literal(str(stop_bits)))
        )

    if not setters:
        return 'result = {"success": False, "error": "No COM fields to update"}\n'

    return device_script(
        com_name,
        """\
_updated = {}
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _pname = str(_p.name)
@@SETTERS@@
result = {"success": True, "device": @@DEVICE_NAME@@, "updated": _updated}
""".replace("@@SETTERS@@", "\n".join("        " + line if line else "" for block in setters for line in block.splitlines()))
   .replace("@@DEVICE_NAME@@", literal(com_name)),
    )


def get_device_status(device_name, application_path="Device/Plc Logic/Application"):
    return render(
        """\
import scriptengine
import System

_last_error_names = {
    0x00: "RESPONSE_SUCCESS",
    0x01: "ILLEGAL_FUNCTION",
    0x02: "ILLEGAL_DATA_ADDRESS",
    0x03: "ILLEGAL_DATA_VALUE",
    0x04: "SERVER_DEVICE_FAILURE",
    0x05: "ACKNOWLEDGE",
    0x06: "SERVER_DEVICE_BUSY",
    0x08: "MEMORY_PARITY_ERROR",
    0x0A: "GATEWAY_PATH_UNAVAILABLE",
    0x0B: "GATEWAY_TARGET_FAILED_TO_RESPOND",
    0xA1: "RESPONSE_TIMEOUT",
    0xA2: "RESPONSE_CRC_FAIL",
    0xA3: "RESPONSE_WRONG_SERVER",
    0xA4: "RESPONSE_WRONG_FUNCTIONCODE",
    0xA5: "TCP_COMMUNICATION_ERROR",
    0xA6: "RESPONSE_INVALID_DATA",
    0xA7: "RESPONSE_INVALID_PROTOCOL",
    0xA8: "RESPONSE_INVALID_HEADER",
    0xFF: "UNDEFINED",
}

def _find_device(_project, _wanted_name):
    _stack = []
    for _child in _project.get_children():
        _stack.append(_child)
    while _stack:
        _obj = _stack.pop(0)
        try:
            _name = _obj.get_name() if hasattr(_obj, 'get_name') else str(_obj)
        except:
            _name = str(_obj)
        if _name == _wanted_name and hasattr(_obj, 'connectors'):
            try:
                _conn_count = len(_obj.connectors)
            except:
                _conn_count = 0
            if _conn_count > 0:
                return _obj
        if hasattr(_obj, 'get_children'):
            try:
                for _child in _obj.get_children():
                    _stack.append(_child)
            except:
                pass
    return None

def _find_master(_project, _wanted_name):
    _stack = []
    for _child in _project.get_children():
        _stack.append(_child)
    while _stack:
        _obj = _stack.pop(0)
        try:
            _name = _obj.get_name() if hasattr(_obj, 'get_name') else str(_obj)
        except:
            _name = str(_obj)
        if _name == _wanted_name:
            return _obj
        if hasattr(_obj, 'get_children'):
            try:
                for _child in _obj.get_children():
                    _stack.append(_child)
            except:
                pass
    return None

def _find_master_and_instance(_project, _device_name):
    _stack = []
    for _child in _project.get_children():
        _stack.append(_child)
    while _stack:
        _obj = _stack.pop(0)
        try:
            _did = _obj.get_device_identification()
            _dtype = int(_did.type)
        except:
            _dtype = None
        if _dtype == 90 and hasattr(_obj, 'get_children'):
            _idx = 0
            try:
                for _child in _obj.get_children():
                    try:
                        _child_name = _child.get_name() if hasattr(_child, 'get_name') else str(_child)
                    except:
                        _child_name = str(_child)
                    if not hasattr(_child, 'connectors'):
                        continue
                    try:
                        _child_did = _child.get_device_identification()
                        _child_dtype = int(_child_did.type)
                    except:
                        _child_dtype = None
                    if _child_dtype != 91:
                        continue
                    if _child_name == _device_name:
                        return (_obj, _idx)
                    _idx += 1
            except:
                pass
        if hasattr(_obj, 'get_children'):
            try:
                for _child in _obj.get_children():
                    _stack.append(_child)
            except:
                pass
    return (None, None)

def _device_instance_index(_master_obj, _device_name):
    _idx = 0
    if _master_obj is None or not hasattr(_master_obj, 'get_children'):
        return None
    try:
        for _child in _master_obj.get_children():
            try:
                _name = _child.get_name() if hasattr(_child, 'get_name') else str(_child)
            except:
                _name = str(_child)
            if not hasattr(_child, 'connectors'):
                continue
            try:
                _did = _child.get_device_identification()
                _dtype = int(_did.type)
            except:
                _dtype = None
            if _dtype != 91:
                continue
            if _name == _device_name:
                return _idx
            _idx += 1
    except:
        pass
    return None

def _read_words(_raw, _device_obj, _bit_offset, _instance):
    import System
    _flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public
    _asm = _raw.GetType().Assembly
    _writer_t = _asm.GetType('_3S.CoDeSys.OnlineManager.MonitoringServiceWriterOld')
    _pai_t = _asm.GetType('_3S.CoDeSys.OnlineManager.ParameterAddressInfo')
    _cmd_t = _asm.GetType('_3S.CoDeSys.OnlineManager.EMonitoringServiceCmd')
    _add_method = None
    _get_service_writer = None
    _create_service = None
    _begin_expr = None
    _end_expr = None
    for _m in _writer_t.GetMethods(_flags):
        if _m.Name == 'AddReadExpression':
            _add_method = _m
        elif _m.Name == 'GetServiceWriter':
            _get_service_writer = _m
        elif _m.Name == 'CreateService':
            _create_service = _m
        elif _m.Name == 'BeginExpressions':
            _begin_expr = _m
        elif _m.Name == 'EndExpressions':
            _end_expr = _m

    _param_typeclass = _add_method.GetParameters()[1].ParameterType
    _writer = System.Activator.CreateInstance(_writer_t, _raw, False)
    _conn = _device_obj.connectors[0]
    _pai = System.Activator.CreateInstance(
        _pai_t,
        int(_conn.module_type),
        int(_instance),
        System.Int64(9200),
        int(_bit_offset),
        'UDINT'
    )
    _tc = System.Enum.Parse(_param_typeclass, 'UDInt')
    _cmd = System.Enum.Parse(_cmd_t, 'ERead')
    _create_service.Invoke(_writer, System.Array[System.Object]([_cmd]))
    _begin_expr.Invoke(_writer, None)
    _args = System.Array[System.Object]([_pai, _tc, System.UInt16(1), ''])
    _add_method.Invoke(_writer, _args)
    _end_expr.Invoke(_writer, None)
    _service_writer = _get_service_writer.Invoke(_writer, None)
    _reader = _raw.ExecuteService(_service_writer)
    _header = _reader.Header
    _content_length = int(_header.GetType().GetProperty('ContentLength', _flags).GetValue(_header, None))
    _read_u32 = _reader.GetType().GetMethod('ReadUInt32', _flags)
    _vals = []
    _i = 0
    while _i < int(_content_length / 4):
        _vals.append(int(_read_u32.Invoke(_reader, None)))
        _i += 1
    return _vals

def _decode_entry(_words):
    _encoded = 0
    if len(_words) > 1:
        _encoded = int(_words[1])
    return {
        "rawWords": _words,
        "encodedWord": _encoded,
        "valueHigh16": int((_encoded >> 16) & 0xFFFF),
        "valueLow16": int(_encoded & 0xFFFF),
    }

_project = scriptengine.projects.primary
if _project is None and hasattr(session, 'active_project'):
    _project = session.active_project

if _project is None:
    result = {"success": False, "error": "No project open"}
else:
    _device_obj = _find_device(_project, @@DEVICE_NAME@@)
    if _device_obj is None:
        result = {"success": False, "error": "Device not found: " + @@DEVICE_NAME@@}
    elif not hasattr(session, 'get_cached_online_application'):
        result = {"success": False, "error": "Session does not support cached online application access"}
    else:
        _online_app = session.get_cached_online_application(@@APPLICATION_PATH@@)
        if _online_app is None:
            result = {"success": False, "error": "PLC is not logged in. Call /api/v1/plc/login first."}
        else:
            try:
                _flags = System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Public
                (_master_obj, _instance) = _find_master_and_instance(_project, @@DEVICE_NAME@@)
                if _instance is None:
                    raise Exception("Unable to resolve Modbus device instance for " + @@DEVICE_NAME@@)
                _root_od = _online_app.get_online_device()
                _raw = _root_od.GetType().GetField('OnlineDevice', _flags).GetValue(_root_od)

                _com_words = _read_words(_raw, _device_obj, 32, _instance)
                _req_words = _read_words(_raw, _device_obj, 64, _instance)
                _err_words = _read_words(_raw, _device_obj, 96, _instance)
                _last_words = _read_words(_raw, _device_obj, 128, _instance)

                _com = _decode_entry(_com_words)
                _req = _decode_entry(_req_words)
                _err = _decode_entry(_err_words)
                _last = _decode_entry(_last_words)

                _last_code = int(_last["valueHigh16"])
                _last["code"] = _last_code
                _last["name"] = _last_error_names.get(_last_code, "UNKNOWN")
                _last["enumType"] = "LastErrorT"
                _last["enumMap"] = _last_error_names
                _stalled = bool(_last_code != 0)
                _healthy = not _stalled

                result = {
                    "success": True,
                    "device": @@DEVICE_NAME@@,
                    "applicationPath": @@APPLICATION_PATH@@,
                    "instance": _instance,
                    "derived": {
                        "healthy": _healthy,
                        "stalled": _stalled,
                        "ackRequired": _stalled,
                        "status": "healthy" if _healthy else "stalled",
                    },
                    "serverDiag": {
                        "comState": _com,
                        "requestCounter": _req,
                        "errorCounter": _err,
                        "lastError": _last,
                    }
                }
            except Exception as _status_error:
                result = {"success": False, "error": str(_status_error)}
""",
        DEVICE_NAME=literal(device_name),
        APPLICATION_PATH=literal(application_path),
    )


def get_status_map(master_name="Modbus_Client_COM_Port"):
    return render(
        """\
import scriptengine

def _find_master(_project, _wanted_name):
    _stack = []
    for _child in _project.get_children():
        _stack.append(_child)
    while _stack:
        _obj = _stack.pop(0)
        try:
            _name = _obj.get_name() if hasattr(_obj, 'get_name') else str(_obj)
        except:
            _name = str(_obj)
        if _name == _wanted_name:
            return _obj
        if hasattr(_obj, 'get_children'):
            try:
                for _child in _obj.get_children():
                    _stack.append(_child)
            except:
                pass
    return None

_project = scriptengine.projects.primary
if _project is None and hasattr(session, 'active_project'):
    _project = session.active_project

if _project is None:
    result = {"success": False, "error": "No project open"}
else:
    _master = _find_master(_project, @@MASTER_NAME@@)
    if _master is None:
        result = {"success": False, "error": "Master not found: " + @@MASTER_NAME@@}
    elif not hasattr(_master, 'get_children'):
        result = {"success": False, "error": "Master has no children: " + @@MASTER_NAME@@}
    else:
        _devices = []
        _idx = 0
        for _child in _master.get_children():
            if not hasattr(_child, 'connectors'):
                continue
            try:
                _did = _child.get_device_identification()
                _dtype = int(_did.type)
            except:
                _dtype = None
            if _dtype != 91:
                continue
            _entry = {
                "instance": _idx,
                "name": _child.get_name() if hasattr(_child, 'get_name') else str(_child),
                "deviceType": _dtype,
            }
            try:
                _entry["guid"] = str(_child.guid)
            except:
                pass
            try:
                _entry["deviceId"] = str(_did.id)
                _entry["deviceVersion"] = str(_did.version)
            except:
                pass
            try:
                _params = {}
                for _conn in _child.connectors:
                    for _p in _conn.host_parameters:
                        _pid = int(_p.id)
                        if _pid == 9100:
                            _params["slaveAddress"] = str(_p.value)
                        elif _pid == 9101:
                            _params["responseTimeout"] = str(_p.value)
                if _params:
                    _entry["params"] = _params
            except:
                pass
            _devices.append(_entry)
            _idx += 1
        result = {"success": True, "master": @@MASTER_NAME@@, "devices": _devices}
""",
        MASTER_NAME=literal(master_name),
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


def acknowledge_device(device_name, subtree=False):
    command_guid = "da0d023d-78ee-440a-8afd-e5461b6dbb57" if subtree else "c9272719-e5f3-46ba-aeff-c953c48ad586"
    return render(
        """\
import scriptengine
import System

proj = scriptengine.projects.primary
if proj is None and hasattr(session, 'active_project'):
    proj = session.active_project

if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _plc = None
    for _child in proj.get_children():
        if hasattr(_child, 'device_parameters'):
            _plc = _child
            break

    if _plc is None:
        result = {"success": False, "error": "No PLC device found"}
    else:
        _target = None
        _stack = [_plc]
        while len(_stack) > 0:
            _node = _stack.pop()
            if hasattr(_node, 'get_name') and _node.get_name() == @@DEVICE_NAME@@:
                _target = _node
                break
            if hasattr(_node, 'get_children'):
                try:
                    for _sub in _node.get_children():
                        _stack.append(_sub)
                except:
                    pass

        if _target is None:
            result = {"success": False, "error": "Device not found: " + @@DEVICE_NAME@@}
        else:
            _sys_instances = None
            for _asm in System.AppDomain.CurrentDomain.GetAssemblies():
                try:
                    if str(_asm.GetName().Name) == "SystemInstances":
                        _sys_instances = _asm.GetType("_3S.CoDeSys.Core.SystemInstances")
                        break
                except:
                    pass

            if _sys_instances is None:
                result = {"success": False, "error": "SystemInstances type not found"}
            else:
                _engine_prop = _sys_instances.GetProperty("Engine")
                _engine = _engine_prop.GetValue(None, None)
                _command_guid = System.Guid(@@COMMAND_GUID@@)
                _command_manager = _engine.CommandManager
                _target_guid = str(_target.guid)
                _enabled = bool(_command_manager.GetCommandEnabled(_command_guid))
                _visible = bool(_command_manager.IsCommandVisible(_command_guid, True))
                _args = System.Array[System.String](["0", _target_guid])
                _command_manager.ExecuteCommand(_command_guid, _args)

                result = {
                    "success": True,
                    "device": @@DEVICE_NAME@@,
                    "subtree": @@SUBTREE@@,
                    "commandGuid": @@COMMAND_GUID@@,
                    "enabled": _enabled,
                    "visible": _visible,
                    "targetProjectHandle": 0,
                    "targetGuid": _target_guid,
                    "batchArgs": [str(_args[0]), str(_args[1])],
                }
""",
        DEVICE_NAME=literal(device_name),
        COMMAND_GUID=literal(command_guid),
        SUBTREE="True" if subtree else "False",
    )
