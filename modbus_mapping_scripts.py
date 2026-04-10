"""IO mapping Modbus script generators."""

from modbus_script_utils import device_script, literal, py_bool


def get_mapping(device_name, channel_name):
    return device_script(
        device_name,
        """\
_mappings = []
_found = False
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@ and str(_p.ChannelType) != "None":
        try:
            _io_map = _p.IoMapping
        except:
            continue
        _found = True
        _var_maps = _io_map.VariableMappings
        for _vm in _var_maps:
            _mappings.append({
                "variable": str(_vm.Variable),
                "iecAddress": str(_io_map.IecAddress),
            })
        result = {
            "success": True,
            "device": @@DEVICE_NAME@@,
            "channel": @@CHANNEL_NAME@@,
            "iecAddress": str(_io_map.IecAddress),
            "mappings": _mappings
        }
        break

if not _found:
    result = {"success": False, "error": "Channel IO param not found: @@CHANNEL_TEXT@@"}
""".replace("@@CHANNEL_NAME@@", literal(channel_name))
   .replace("@@CHANNEL_TEXT@@", channel_name)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
        needs_clr=True,
        needs_native_pset=True,
    )


def set_mapping(device_name, channel_name, variable, create_variable=True):
    return device_script(
        device_name,
        """\
_mapped = False
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@ and str(_p.ChannelType) != "None":
        try:
            _io_map = _p.IoMapping
        except:
            continue
        _var_maps = _io_map.VariableMappings
        while _var_maps.Count > 0:
            _var_maps.RemoveAt(0)
        _var_maps.AddMapping(@@VARIABLE@@, @@CREATE_VARIABLE@@)
        _mapped = True
        result = {
            "success": True,
            "device": @@DEVICE_NAME@@,
            "channel": @@CHANNEL_NAME@@,
            "variable": @@VARIABLE@@,
            "iecAddress": str(_io_map.IecAddress)
        }
        break

if not _mapped:
    result = {"success": False, "error": "Channel IO param not found: @@CHANNEL_TEXT@@"}
""".replace("@@CHANNEL_NAME@@", literal(channel_name))
   .replace("@@CHANNEL_TEXT@@", channel_name)
   .replace("@@DEVICE_NAME@@", literal(device_name))
   .replace("@@VARIABLE@@", literal(variable))
   .replace("@@CREATE_VARIABLE@@", py_bool(create_variable)),
        needs_clr=True,
        needs_native_pset=True,
    )


def clear_mapping(device_name, channel_name):
    return device_script(
        device_name,
        """\
_cleared = False
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@ and str(_p.ChannelType) != "None":
        try:
            _io_map = _p.IoMapping
        except:
            continue
        _var_maps = _io_map.VariableMappings
        _count = _var_maps.Count
        while _var_maps.Count > 0:
            _var_maps.RemoveAt(0)
        _cleared = True
        result = {
            "success": True,
            "device": @@DEVICE_NAME@@,
            "channel": @@CHANNEL_NAME@@,
            "removedMappings": _count
        }
        break

if not _cleared:
    result = {"success": False, "error": "Channel IO param not found: @@CHANNEL_TEXT@@"}
""".replace("@@CHANNEL_NAME@@", literal(channel_name))
   .replace("@@CHANNEL_TEXT@@", channel_name)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
        needs_clr=True,
        needs_native_pset=True,
    )
