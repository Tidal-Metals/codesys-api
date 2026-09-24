"""IO mapping CRUD Modbus script generators."""

from modbus_script_utils import device_script, literal, py_bool


def get_mapping(device_name, channel_name):
    return device_script(
        device_name,
        """\
_mappings = []
_found = False
_resolved_depth = 0
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@ and str(_p.ChannelType) != "None":
        _resolved = _p
        _resolved_type = ""
        while True:
            try:
                _resolved_type = str(_resolved.BaseType)
            except:
                _resolved_type = ""
            try:
                _has_sub = bool(_resolved.HasSubElements)
            except:
                _has_sub = False
            if (not _has_sub) or _resolved_type:
                break
            try:
                _child_count = _resolved.SubElements.Count
            except:
                _child_count = 0
            if _child_count != 1:
                result = {
                    "success": False,
                    "error": "Channel mapping target is compound and ambiguous",
                    "device": @@DEVICE_NAME@@,
                    "channel": @@CHANNEL_NAME@@,
                    "resolvedDepth": _resolved_depth,
                    "resolvedType": _resolved_type,
                    "childCount": _child_count,
                }
                _found = True
                break
            _resolved = _resolved.SubElements[0]
            _resolved_depth += 1
        if _found:
            break
        try:
            _resolved_type = str(_resolved.BaseType)
        except:
            _resolved_type = ""
        try:
            _io_map = _resolved.IoMapping
        except:
            continue
        _found = True
        _subtree = [(_p, 0)]
        while len(_subtree) > 0:
            _node, _depth = _subtree.pop(0)
            try:
                _node_io_map = _node.IoMapping
                _var_maps = _node_io_map.VariableMappings
                for _vm in _var_maps:
                    _mappings.append({
                        "variable": str(_vm.Variable),
                        "iecAddress": str(_node_io_map.IecAddress),
                        "nodeVisibleName": str(_node.VisibleName),
                        "nodeDepth": _depth,
                    })
            except:
                pass
            try:
                if bool(_node.HasSubElements):
                    for _child in _node.SubElements:
                        _subtree.append((_child, _depth + 1))
            except:
                pass
        result = {
            "success": True,
            "device": @@DEVICE_NAME@@,
            "channel": @@CHANNEL_NAME@@,
            "iecAddress": str(_io_map.IecAddress),
            "mappings": _mappings,
            "resolvedDepth": _resolved_depth,
            "resolvedType": _resolved_type,
            "resolvedVisibleName": str(_resolved.VisibleName),
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
_resolved_depth = 0
_clear_count = 0
_resolved = None
_resolved_type = ""
_io_map = None
_matching_params = []
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@:
        _matching_params.append(_p)

for _p in _matching_params:
    try:
        _subtree = []
        _subtree.append(_p)
        while len(_subtree) > 0:
            _node = _subtree.pop(0)
            try:
                _target_map = _node.IoMapping
                _var_maps = _target_map.VariableMappings
                _clear_count += _var_maps.Count
                while _var_maps.Count > 0:
                    _var_maps.RemoveAt(0)
            except:
                pass
            try:
                if bool(_node.HasSubElements):
                    for _child in _node.SubElements:
                        _subtree.append(_child)
            except:
                pass
    except:
        pass

for _p in _matching_params:
    if str(_p.ChannelType) == "None":
        continue
    _resolved = _p
    _resolved_type = ""
    _resolved_depth = 0
    while True:
        try:
            _resolved_type = str(_resolved.BaseType)
        except:
            _resolved_type = ""
        try:
            _has_sub = bool(_resolved.HasSubElements)
        except:
            _has_sub = False
        if (not _has_sub) or _resolved_type:
            break
        try:
            _child_count = _resolved.SubElements.Count
        except:
            _child_count = 0
        if _child_count != 1:
            result = {
                "success": False,
                "error": "Channel mapping target is compound and ambiguous",
                "device": @@DEVICE_NAME@@,
                "channel": @@CHANNEL_NAME@@,
                "resolvedDepth": _resolved_depth,
                "resolvedType": _resolved_type,
                "childCount": _child_count,
            }
            _mapped = True
            break
        _resolved = _resolved.SubElements[0]
        _resolved_depth += 1
    if _mapped:
        break
    try:
        _resolved_type = str(_resolved.BaseType)
    except:
        _resolved_type = ""
    try:
        _io_map = _resolved.IoMapping
    except:
        continue
    _var_maps = _io_map.VariableMappings
    _var_maps.AddMapping(@@VARIABLE@@, @@CREATE_VARIABLE@@)
    _mapped = True
    result = {
        "success": True,
        "device": @@DEVICE_NAME@@,
        "channel": @@CHANNEL_NAME@@,
        "variable": @@VARIABLE@@,
        "iecAddress": str(_io_map.IecAddress),
        "resolvedDepth": _resolved_depth,
        "resolvedType": _resolved_type,
        "resolvedVisibleName": str(_resolved.VisibleName),
        "removedMappings": _clear_count,
        "matchedParamCount": len(_matching_params),
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
_resolved_depth = 0
_count = 0
_matching_params = []
for _p in _native_pset:
    if _p.VisibleName == @@CHANNEL_NAME@@:
        _matching_params.append(_p)

for _p in _matching_params:
    _resolved = _p
    _resolved_type = ""
    _resolved_depth = 0
    try:
        while True:
            try:
                _resolved_type = str(_resolved.BaseType)
            except:
                _resolved_type = ""
            try:
                _has_sub = bool(_resolved.HasSubElements)
            except:
                _has_sub = False
            if (not _has_sub) or _resolved_type:
                break
            try:
                _child_count = _resolved.SubElements.Count
            except:
                _child_count = 0
            if _child_count != 1:
                result = {
                    "success": False,
                    "error": "Channel mapping target is compound and ambiguous",
                    "device": @@DEVICE_NAME@@,
                    "channel": @@CHANNEL_NAME@@,
                    "resolvedDepth": _resolved_depth,
                    "resolvedType": _resolved_type,
                    "childCount": _child_count,
                }
                _cleared = True
                break
            _resolved = _resolved.SubElements[0]
            _resolved_depth += 1
        if _cleared:
            break
    except:
        pass
    try:
        _subtree = []
        _subtree.append(_p)
        while len(_subtree) > 0:
            _node = _subtree.pop(0)
            try:
                _target_map = _node.IoMapping
                _var_maps = _target_map.VariableMappings
                _count += _var_maps.Count
                while _var_maps.Count > 0:
                    _var_maps.RemoveAt(0)
            except:
                pass
            try:
                if bool(_node.HasSubElements):
                    for _child in _node.SubElements:
                        _subtree.append(_child)
            except:
                pass
    except:
        pass

if len(_matching_params) > 0 and not _cleared:
    _cleared = True
    result = {
        "success": True,
        "device": @@DEVICE_NAME@@,
        "channel": @@CHANNEL_NAME@@,
        "removedMappings": _count,
        "resolvedDepth": _resolved_depth,
        "resolvedType": _resolved_type,
        "resolvedVisibleName": str(_resolved.VisibleName),
        "matchedParamCount": len(_matching_params),
    }

if not _cleared:
    result = {"success": False, "error": "Channel IO param not found: @@CHANNEL_TEXT@@"}
""".replace("@@CHANNEL_NAME@@", literal(channel_name))
   .replace("@@CHANNEL_TEXT@@", channel_name)
   .replace("@@DEVICE_NAME@@", literal(device_name)),
        needs_clr=True,
        needs_native_pset=True,
    )
