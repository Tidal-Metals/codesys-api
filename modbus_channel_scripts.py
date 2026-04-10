"""Channel CRUD and IO export Modbus script generators."""

from modbus_script_utils import (
    DEVICE_PARAM_IDS,
    device_script,
    literal,
    normalize_channel,
)


def list_channels(device_name):
    return device_script(
        device_name,
        """\
_channels = []
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _pname = str(_p.name)
        _pid = int(_p.id)
        _ct = str(_p.channel_type)
        _desc = str(_p.description)
        if _pid not in @@DEVICE_PARAM_IDS@@:
            if _desc == "ChannelConfig" or (_ct != "None" and _desc == ""):
                _fields = []
                for _i in range(9):
                    try:
                        _fields.append(str(_p[_i].value))
                    except:
                        break

                if len(_fields) >= 8:
                    _channels.append({
                        "name": _pname,
                        "id": _pid,
                        "config": {
                            "accessType": int(_fields[0]) if _fields[0].isdigit() else _fields[0],
                            "readOffset": _fields[1],
                            "readLength": int(_fields[2]) if _fields[2].isdigit() else _fields[2],
                            "writeOffset": _fields[3],
                            "writeLength": int(_fields[4]) if _fields[4].isdigit() else _fields[4],
                            "trigger": int(_fields[5]) if _fields[5].isdigit() else _fields[5],
                            "cycleTime": int(_fields[6]) if _fields[6].isdigit() else _fields[6],
                            "errorHandling": _fields[7],
                        },
                        "raw": str(_p.value)
                    })

result = {"success": True, "device": @@DEVICE_NAME@@, "channels": _channels}
""".replace("@@DEVICE_PARAM_IDS@@", DEVICE_PARAM_IDS)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def create_channel(device_name, channel_name, access_type=3, read_offset="16#0000",
                   read_length=1, write_offset="0", write_length="0",
                   trigger=5, cycle_time=100, error_handling="true", comment=""):
    channel = normalize_channel({
        "name": channel_name,
        "accessType": access_type,
        "readOffset": read_offset,
        "readLength": read_length,
        "writeOffset": write_offset,
        "writeLength": write_length,
        "trigger": trigger,
        "cycleTime": cycle_time,
        "errorHandling": error_handling,
        "comment": comment,
    })
    return _create_channels_script(device_name, [channel], bulk=False)


def create_channels_bulk(device_name, channels):
    return _create_channels_script(
        device_name,
        [normalize_channel(channel) for channel in channels],
        bulk=True,
    )


def update_channels_bulk(device_name, channels):
    return device_script(
        device_name,
        """\
_channels_def = @@CHANNELS@@
_by_name = {}
for _ch in _channels_def:
    _by_name[_ch["name"]] = _ch

_updated = []
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        _pname = str(_p.name)
        if _pname in _by_name and int(_p.id) not in @@DEVICE_PARAM_IDS@@ and str(_p.value).startswith("{"):
            _ch = _by_name[_pname]
            _p[0].value = str(_ch["accessType"])
            _p[1].value = str(_ch["readOffset"])
            _p[2].value = str(_ch["readLength"])
            _p[3].value = str(_ch["writeOffset"])
            _p[4].value = str(_ch["writeLength"])
            _p[5].value = str(_ch["trigger"])
            _p[6].value = str(_ch["cycleTime"])
            _p[7].value = str(_ch["errorHandling"])
            _updated.append(_pname)

_updated_set = {}
for _name in _updated:
    _updated_set[_name] = True

_missing = []
for _ch in _channels_def:
    if _ch["name"] not in _updated_set:
        _missing.append(_ch["name"])

result = {
    "success": len(_missing) == 0,
    "device": @@DEVICE_NAME@@,
    "updated": _updated,
    "missing": _missing,
    "updatedCount": len(_updated),
    "missingCount": len(_missing)
}
""".replace("@@CHANNELS@@", literal([normalize_channel(channel) for channel in channels]))
   .replace("@@DEVICE_PARAM_IDS@@", DEVICE_PARAM_IDS)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def delete_channel(device_name, channel_name):
    return device_script(
        device_name,
        """\
_to_remove = []
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@:
        _to_remove.append(_p.Id)

if not _to_remove:
    result = {"success": False, "error": "Channel not found: @@CHANNEL_TEXT@@"}
else:
    for _rid in reversed(_to_remove):
        _native_pset.RemoveParameter(System.Int64(_rid))
    result = {
        "success": True,
        "device": @@DEVICE_NAME@@,
        "deleted": @@CHANNEL_NAME@@,
        "removedParams": len(_to_remove)
    }
""".replace("@@CHANNEL_NAME@@", literal(channel_name))
   .replace("@@CHANNEL_TEXT@@", channel_name)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
        needs_clr=True,
        needs_native_pset=True,
    )


def update_channel(device_name, channel_name, **kwargs):
    field_map = {
        "accessType": 0,
        "readOffset": 1,
        "readLength": 2,
        "writeOffset": 3,
        "writeLength": 4,
        "trigger": 5,
        "cycleTime": 6,
        "errorHandling": 7,
    }
    set_lines = []
    for key in ("accessType", "readOffset", "readLength", "writeOffset",
                "writeLength", "trigger", "cycleTime", "errorHandling"):
        if key in kwargs:
            set_lines.append("_p[{0}].value = {1}".format(field_map[key], literal(str(kwargs[key]))))

    comment_block = "pass"
    needs_native = False
    if "comment" in kwargs:
        needs_native = True
        comment_block = """\
for _np in _native_pset:
    if _np.VisibleName == @@CHANNEL_NAME@@ and int(_np.Id) == _config_id:
        try:
            _np.UserComment = @@COMMENT@@
        except:
            pass
        break
""".replace("@@CHANNEL_NAME@@", literal(channel_name)).replace("@@COMMENT@@", literal(kwargs["comment"]))

    if not set_lines and "comment" not in kwargs:
        return 'result = {"success": False, "error": "No fields to update"}\n'

    body = """\
_config_id = None
_updated = False
for _conn in _target.connectors:
    for _p in _conn.host_parameters:
        if str(_p.name) == @@CHANNEL_NAME@@ and int(_p.id) not in @@DEVICE_PARAM_IDS@@ and str(_p.value).startswith("{"):
            try:
@@SETTERS@@
                _config_id = int(_p.id)
                _updated = True
            except Exception as _e:
                result = {"success": False, "error": str(_e)}
            break
    if _updated:
        break

if _updated:
@@COMMENT_BLOCK@@
    result = {"success": True, "device": @@DEVICE_NAME@@, "channel": @@CHANNEL_NAME@@, "updated": True}
elif _config_id is None:
    result = {"success": False, "error": "Channel not found: @@CHANNEL_TEXT@@"}
"""
    if set_lines:
        setters = "\n".join("                " + line for line in set_lines)
    else:
        setters = "                pass"
    body = (body.replace("@@CHANNEL_NAME@@", literal(channel_name))
                .replace("@@CHANNEL_TEXT@@", channel_name)
                .replace("@@DEVICE_NAME@@", literal(device_name))
                .replace("@@DEVICE_PARAM_IDS@@", DEVICE_PARAM_IDS)
                .replace("@@SETTERS@@", setters)
                .replace("@@COMMENT_BLOCK@@", _indent_raw(comment_block, 4)))
    return device_script(device_name, body, needs_clr=needs_native, needs_native_pset=needs_native)


def export_io_csv(device_name, file_path):
    return device_script(
        device_name,
        """\
_target.export_io_mappings_as_csv(@@FILE_PATH@@)
result = {"success": True, "device": @@DEVICE_NAME@@, "file": @@FILE_PATH@@}
""".replace("@@FILE_PATH@@", literal(file_path))
   .replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def _create_channels_script(device_name, channels, bulk):
    body = """\
_channels_def = @@CHANNELS@@
_max_id = 0
for _p in _native_pset:
    if _p.Id > _max_id and _p.Id < 1879052288:
        _max_id = _p.Id

_created = []
for _idx, _ch in enumerate(_channels_def):
    _config_id = _max_id + ((_idx + 1) * 16777216)
    _io_id = _config_id + 3407872
    _fc = int(_ch["accessType"])
    _is_write = _fc in (5, 6, 15, 16)
    _is_readwrite = _fc == 23

    if _is_write:
        _io_ct = ChannelType.Output
        _length = int(_ch["writeLength"])
    else:
        _io_ct = ChannelType.Input
        _length = int(_ch["readLength"])
    if _is_readwrite:
        _io_ct = ChannelType.Input
        _length = int(_ch["readLength"])
    _array_size = _length - 1 if _length > 0 else 0

    _cp = _native_pset.AddParameter(
        System.Int64(_config_id),
        _ch["name"],
        AccessRight.ReadWrite,
        AccessRight.ReadWrite,
        ChannelType.Input,
        "localTypes:CHANNEL_PACKED"
    )
    _io_type_str = "std:ARRAY[0..%d] OF WORD" % _array_size
    _native_pset.AddParameter(
        System.Int64(_io_id),
        _ch["name"],
        AccessRight.ReadWrite,
        AccessRight.ReadWrite,
        _io_ct,
        _io_type_str
    )

    if _ch.get("comment") and _cp is not None:
        try:
            _cp.UserComment = _ch["comment"]
        except:
            pass

    _created.append({"name": _ch["name"], "configId": int(_config_id), "ioId": int(_io_id)})

_set_count = 0
for _p in _conn.host_parameters:
    _pname = str(_p.name)
    _pid = int(_p.id)
    for _cr in _created:
        if _pid == _cr["configId"] and _pname == _cr["name"]:
            _ch = None
            for _cd in _channels_def:
                if _cd["name"] == _pname:
                    _ch = _cd
                    break
            if _ch:
                _p[0].value = str(_ch["accessType"])
                _p[1].value = str(_ch["readOffset"])
                _p[2].value = str(_ch["readLength"])
                _p[3].value = str(_ch["writeOffset"])
                _p[4].value = str(_ch["writeLength"])
                _p[5].value = str(_ch["trigger"])
                _p[6].value = str(_ch["cycleTime"])
                _p[7].value = str(_ch["errorHandling"])
                _set_count += 1
            break

result = {
    "success": True,
    "device": @@DEVICE_NAME@@,
    @@RESULT_KEY@@: @@RESULT_VALUE@@,
    "configuredCount": _set_count
}
"""
    result_key = '"created"' if bulk else '"channel"'
    result_value = "_created" if bulk else "_created[0][\"name\"] if _created else None"
    body = (body.replace("@@CHANNELS@@", literal(channels))
                .replace("@@DEVICE_NAME@@", literal(device_name))
                .replace("@@RESULT_KEY@@", result_key)
                .replace("@@RESULT_VALUE@@", result_value))
    return device_script(device_name, body, needs_clr=True, needs_native_pset=True)


def _indent_raw(block, spaces):
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in block.strip("\n").splitlines())
