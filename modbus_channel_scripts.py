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


def import_io_csv(device_name, file_path):
    return device_script(
        device_name,
        """\
_target.import_io_mappings_from_csv(@@FILE_PATH@@)
result = {"success": True, "device": @@DEVICE_NAME@@, "file": @@FILE_PATH@@}
""".replace("@@FILE_PATH@@", literal(file_path))
   .replace("@@DEVICE_NAME@@", literal(device_name)),
    )


def _create_channels_script(device_name, channels, bulk):
    body = """\
_channels_def = @@CHANNELS@@
_target_string_table = _native_pset.StringTable
_donor_config_param = None
_donor_io_param = None
_donor_device = None
_donor_config_id = None
_donor_io_id = None
_config_base = 17825792
_io_base = 21233664
_config_stride = 16777216
_io_stride = 16777217
_donor_stack = []
for _root in proj.get_children():
    _donor_stack.append(_root)

while _donor_stack and (_donor_config_param is None or _donor_io_param is None):
    _node = _donor_stack.pop()
    if _node is not _target and hasattr(_node, 'connectors'):
        try:
            for _dconn in _node.connectors:
                for _dp in _dconn.host_parameters:
                    _dpid = int(_dp.id)
                    if _dpid in @@DEVICE_PARAM_IDS@@:
                        continue
                    _dct = str(_dp.channel_type)
                    _ddesc = str(_dp.description)
                    if _donor_config_param is None and _dct == "None" and _ddesc == "ChannelConfig":
                        try:
                            _dconn_parent = _dconn.host_parameters.parent
                            _dconn_parent_type = _dconn_parent.GetType()
                            _dpsc_iface = None
                            for _iface in _dconn_parent_type.GetInterfaces():
                                if 'IParameterSetContainer' in _iface.Name:
                                    _dpsc_iface = _iface
                                    break
                            if _dpsc_iface is not None:
                                _dprop = _dpsc_iface.GetProperty('ParameterSet')
                                _dpset = _dprop.GetValue(_dconn_parent, None)
                                for _native_donor in _dpset:
                                    if int(_native_donor.Id) == _dpid:
                                        _donor_config_param = _native_donor
                                        _donor_device = _node.get_name() if hasattr(_node, 'get_name') else str(_node)
                                        _donor_config_id = _dpid
                                        break
                        except:
                            pass
                    elif _donor_io_param is None and _dct == "Input" and _ddesc == "Read Holding Registers":
                        try:
                            _dconn_parent = _dconn.host_parameters.parent
                            _dconn_parent_type = _dconn_parent.GetType()
                            _dpsc_iface = None
                            for _iface in _dconn_parent_type.GetInterfaces():
                                if 'IParameterSetContainer' in _iface.Name:
                                    _dpsc_iface = _iface
                                    break
                            if _dpsc_iface is not None:
                                _dprop = _dpsc_iface.GetProperty('ParameterSet')
                                _dpset = _dprop.GetValue(_dconn_parent, None)
                                for _native_donor in _dpset:
                                    if int(_native_donor.Id) == _dpid:
                                        _donor_io_param = _native_donor
                                        if _donor_device is None:
                                            _donor_device = _node.get_name() if hasattr(_node, 'get_name') else str(_node)
                                        _donor_io_id = _dpid
                                        break
                        except:
                            pass
                    if _donor_config_param is not None and _donor_io_param is not None:
                        break
                if _donor_config_param is not None and _donor_io_param is not None:
                    break
        except:
            pass
    if hasattr(_node, 'get_children'):
        try:
            for _child in _node.get_children():
                _donor_stack.append(_child)
        except:
            pass

if _donor_config_param is None or _donor_io_param is None:
    result = {
        "success": False,
        "error": "No working donor Modbus channel found",
        "donorDevice": _donor_device,
        "hasDonorConfig": _donor_config_param is not None,
        "hasDonorIo": _donor_io_param is not None
    }
else:
    _created = []
    _max_config_slot = -1
    _max_position_id = 4999
    try:
        for _existing_param in _native_pset:
            try:
                _existing_id = int(_existing_param.Id)
            except:
                continue
            if _existing_id in @@DEVICE_PARAM_IDS@@:
                continue
            try:
                if _existing_id >= _config_base and ((_existing_id - _config_base) % _config_stride) == 0:
                    _slot = (_existing_id - _config_base) / _config_stride
                    if _slot > _max_config_slot:
                        _max_config_slot = _slot
            except:
                pass
            try:
                _existing_dala = _existing_param.GetSerializableValue('DalaElement')
                _stack = [_existing_dala]
                while _stack:
                    _elt = _stack.pop()
                    try:
                        _pos = _elt.GetSerializableValue('PositionId')
                        if _pos is not None:
                            _pos_int = int(_pos)
                            if _pos_int > _max_position_id:
                                _max_position_id = _pos_int
                    except:
                        pass
                    try:
                        _epos = _elt.GetSerializableValue('EditorPositionId')
                        if _epos is not None:
                            _epos_int = int(_epos)
                            if _epos_int > _max_position_id:
                                _max_position_id = _epos_int
                    except:
                        pass
                    try:
                        if _elt.SubElements is not None:
                            for _child_elt in _elt.SubElements:
                                _stack.append(_child_elt)
                    except:
                        pass
            except:
                pass
    except:
        pass
    _next_slot_idx = _max_config_slot + 1
    _position_base = ((_max_position_id // 500) + 1) * 500 + 500
    for _idx, _ch in enumerate(_channels_def):
        _slot_idx = _next_slot_idx + _idx
        _config_id = _config_base + (_slot_idx * _config_stride)
        _io_id = _io_base + (_slot_idx * _io_stride)
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
        _read_offset_text = str(_ch["readOffset"])
        if _read_offset_text.startswith("16#"):
            _leaf_offset = "0x" + _read_offset_text[3:].upper()
        elif _read_offset_text.lower().startswith("0x"):
            _leaf_offset = "0x" + _read_offset_text[2:].upper()
        else:
            _leaf_offset = _read_offset_text

        _cfg_dala = _donor_config_param.GetSerializableValue('DalaElement').Clone()
        _cfg_dala.SetSerializableValue('VisibleName', _target_string_table.CreateStringRef('', '', _ch["name"]))
        _cfg_dala.SetSerializableValue('Identifier', str(_config_id))
        _cfg_dala.SetSerializableValue('PositionId', System.Int64(_position_base))
        _cfg_dala.SetSerializableValue('EditorPositionId', System.Int64(_position_base + 1))
        _cfg_subs = _cfg_dala.SubElements
        _sub_pos = _position_base + 2
        for _sub in _cfg_subs:
            try:
                _sub.SetSerializableValue('PositionId', System.Int64(_sub_pos))
                _sub.SetSerializableValue('EditorPositionId', System.Int64(_sub_pos + 1))
                _sub_pos = _sub_pos + 2
            except:
                pass

        _io_dala = _donor_io_param.GetSerializableValue('DalaElement').Clone()
        _io_dala.SetSerializableValue('VisibleName', _target_string_table.CreateStringRef('', '', _ch["name"]))
        _io_dala.SetSerializableValue('Identifier', str(_io_id))
        _io_dala.SetSerializableValue('PositionId', System.Int64(_position_base + 100))
        _io_dala.SetSerializableValue('EditorPositionId', System.Int64(_position_base + 101))
        _io_subs = _io_dala.SubElements
        if _io_subs is not None and len(_io_subs) > 0:
            _word = _io_subs[0]
            _word.SetSerializableValue('VisibleName', _target_string_table.CreateStringRef('', '', _ch["name"]))
            _word.SetSerializableValue('Description', _target_string_table.CreateStringRef('', '', _leaf_offset))
            _word.SetSerializableValue('Identifier', str(_io_id) + '_0_0_0')
            _word.SetSerializableValue('PositionId', System.Int64(_position_base + 102))
            _word.SetSerializableValue('EditorPositionId', System.Int64(_position_base + 103))
            _bit_pos = _position_base + 104
            _bit_idx = 0
            for _bit in _word.SubElements:
                try:
                    _bit.SetSerializableValue('Identifier', str(_io_id) + '_0_0_0_' + str(_bit_idx))
                    _bit.SetSerializableValue('PositionId', System.Int64(_bit_pos))
                    _bit.SetSerializableValue('EditorPositionId', System.Int64(_bit_pos + 1))
                    _bit_pos = _bit_pos + 2
                except:
                    pass
                _bit_idx = _bit_idx + 1

        _cp = _native_pset.AddParameter(
            System.Int64(_config_id),
            _ch["name"],
            AccessRight.ReadWrite,
            AccessRight.ReadWrite,
            ChannelType.None,
            "localTypes:CHANNEL_PACKED"
        )
        _io_type_str = "std:ARRAY[0..%d] OF WORD" % _array_size
        _iop = _native_pset.AddParameter(
            System.Int64(_io_id),
            _ch["name"],
            AccessRight.ReadWrite,
            AccessRight.ReadWrite,
            _io_ct,
            _io_type_str
        )
        _cp.SetSerializableValue('DalaElement', _cfg_dala)
        _cp.SetSerializableValue('ParamType', _donor_config_param.GetSerializableValue('ParamType'))
        _iop.SetSerializableValue('DalaElement', _io_dala)
        _iop.SetSerializableValue('ParamType', _donor_io_param.GetSerializableValue('ParamType'))
        try:
            _cp.SetDescription(_donor_config_param.DescriptionStringRef)
        except:
            pass
        try:
            _iop.SetDescription(_donor_io_param.DescriptionStringRef)
        except:
            pass

        if _ch.get("comment") and _cp is not None:
            try:
                _cp.UserComment = _ch["comment"]
            except:
                pass

        _created.append({"name": _ch["name"], "configId": int(_config_id), "ioId": int(_io_id)})
        _position_base = _position_base + 500

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
        "configuredCount": _set_count,
        "hasDonorConfigDescription": _donor_config_param is not None,
        "hasDonorIoDescription": _donor_io_param is not None,
        "donorDevice": _donor_device,
        "donorConfigId": _donor_config_id,
        "donorIoId": _donor_io_id,
        "freshIdentityFields": {
            "configIdsGenerated": True,
            "ioIdsGenerated": True,
            "channelNamesGenerated": True,
            "deviceIdentityCloned": False,
            "ioConfigGuidsCloned": False,
            "mappingsCloned": False,
            "onlyDescriptionRefsCopied": False,
            "dalaElementCloned": True
        }
    }
"""
    result_key = '"created"' if bulk else '"channel"'
    result_value = "_created" if bulk else "_created[0][\"name\"] if _created else None"
    body = (body.replace("@@CHANNELS@@", literal(channels))
                .replace("@@DEVICE_PARAM_IDS@@", DEVICE_PARAM_IDS)
                .replace("@@DEVICE_NAME@@", literal(device_name))
                .replace("@@RESULT_KEY@@", result_key)
                .replace("@@RESULT_VALUE@@", result_value))
    return device_script(device_name, body, needs_clr=True, needs_native_pset=True)


def _indent_raw(block, spaces):
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in block.strip("\n").splitlines())
