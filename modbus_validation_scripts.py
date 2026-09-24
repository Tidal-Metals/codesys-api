"""Validation and normalization Modbus script generators."""

from modbus_script_utils import DEVICE_PARAM_IDS, literal, render


def validate_mappings(device_name=None):
    return render(
        """\
import clr
import System

proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _wanted_device = @@DEVICE_NAME@@
    _devices_checked = []
    _mapping_entries = []
    _warnings = []
    _errors = []
    _unmapped_channels = []
    _duplicate_inputs = []
    _duplicate_input_iec_addresses = []
    _device_channel_ids = {}
    _id_pattern_issues = []
    _config_base = 17825792
    _io_base = 21233664
    _config_stride = 16777216

    _stack = []
    for _root in proj.get_children():
        _stack.append(_root)

    while _stack:
        _node = _stack.pop()
        if hasattr(_node, 'get_children'):
            try:
                for _child in _node.get_children():
                    _stack.append(_child)
            except:
                pass

        if not hasattr(_node, 'connectors') or not hasattr(_node, 'get_name'):
            continue

        _node_name = _node.get_name()
        if _wanted_device and _node_name != _wanted_device:
            continue

        _is_modbus_device = False
        _conn = None
        try:
            for _candidate_conn in _node.connectors:
                _has_slave_address = False
                for _candidate_param in _candidate_conn.host_parameters:
                    try:
                        _candidate_pid = int(_candidate_param.id)
                    except:
                        _candidate_pid = -1
                    _candidate_name = str(_candidate_param.name)
                    if _candidate_pid == 9100 or _candidate_name in ("SlaveAddress", "ServerAddress"):
                        _has_slave_address = True
                        break
                if _has_slave_address:
                    _conn = _candidate_conn
                    _is_modbus_device = True
                    break
        except:
            pass

        if not _is_modbus_device or _conn is None:
            continue

        _devices_checked.append(_node_name)
        if _node_name not in _device_channel_ids:
            _device_channel_ids[_node_name] = {"configIds": [], "ioIds": []}

        _parent = _conn.host_parameters.parent
        _parent_type = _parent.GetType()
        _psc_iface = None
        for _iface in _parent_type.GetInterfaces():
            if 'IParameterSetContainer' in _iface.Name:
                _psc_iface = _iface
                break
        if _psc_iface is None:
            _warnings.append({
                "device": _node_name,
                "warning": "IParameterSetContainer not found"
            })
            continue

        _prop = _psc_iface.GetProperty('ParameterSet')
        _native_pset = _prop.GetValue(_parent, None)
        if _native_pset is None:
            _warnings.append({
                "device": _node_name,
                "warning": "Native ParameterSet not found"
            })
            continue

        _seen_entries = {}
        for _p in _native_pset:
            try:
                _pid = int(_p.Id)
            except:
                continue
            if _pid in @@DEVICE_PARAM_IDS@@:
                continue

            try:
                _channel_type = str(_p.ChannelType)
            except:
                _channel_type = ""
            if _channel_type == "None":
                _device_channel_ids[_node_name]["configIds"].append(_pid)
            else:
                _device_channel_ids[_node_name]["ioIds"].append(_pid)

            _channel_name = str(_p.VisibleName)
            _subtree = [(_p, 0)]
            _subtree_mapping_count = 0
            while len(_subtree) > 0:
                _current, _depth = _subtree.pop(0)
                try:
                    _current_type = str(_current.BaseType)
                except:
                    _current_type = ""

                try:
                    _current_io_map = _current.IoMapping
                    _var_maps = _current_io_map.VariableMappings
                    _subtree_mapping_count += _var_maps.Count
                    for _vm in _var_maps:
                        _variable_name = str(_vm.Variable)
                        _iec_address = str(_current_io_map.IecAddress)
                        _entry_key = _node_name + "|" + _channel_name + "|" + _channel_type + "|" + _variable_name + "|" + _iec_address + "|" + str(_current.VisibleName) + "|" + str(_depth)
                        if _entry_key not in _seen_entries:
                            _seen_entries[_entry_key] = True
                            _mapping_entries.append({
                                "device": _node_name,
                                "channel": _channel_name,
                                "channelType": _channel_type,
                                "variable": _variable_name,
                                "iecAddress": _iec_address,
                                "resolvedVisibleName": str(_current.VisibleName),
                                "resolvedDepth": _depth,
                                "resolvedType": _current_type
                            })
                except:
                    pass

                try:
                    if bool(_current.HasSubElements):
                        for _child in _current.SubElements:
                            _subtree.append((_child, _depth + 1))
                except:
                    pass

            if _subtree_mapping_count == 0 and _channel_type == "Input":
                _unmapped_channels.append({
                    "device": _node_name,
                    "channel": _channel_name,
                    "iecAddress": "",
                    "resolvedVisibleName": _channel_name,
                    "resolvedDepth": 0,
                    "resolvedType": ""
                })

    _by_variable = {}
    _by_iec_address = {}
    for _entry in _mapping_entries:
        _var_name = _entry["variable"]
        if not _var_name:
            continue
        _iec_address = _entry["iecAddress"]
        _is_input_mapping = False
        if _entry["channelType"] == "Input":
            _is_input_mapping = True
        elif _iec_address and _iec_address.startswith("%I"):
            _is_input_mapping = True
        if not _is_input_mapping:
            continue
        if _var_name not in _by_variable:
            _by_variable[_var_name] = []
        _by_variable[_var_name].append(_entry)
        if _iec_address:
            if _iec_address not in _by_iec_address:
                _by_iec_address[_iec_address] = []
            _by_iec_address[_iec_address].append(_entry)

    for _var_name in _by_variable:
        _entries = _by_variable[_var_name]
        if len(_entries) > 1:
            _duplicate_inputs.append({
                "variable": _var_name,
                "count": len(_entries),
                "occurrences": _entries
            })

    for _dup in _duplicate_inputs:
        _errors.append({
            "type": "duplicateInputVariableMapping",
            "variable": _dup["variable"],
            "count": _dup["count"],
            "occurrences": _dup["occurrences"]
        })

    for _iec_address in _by_iec_address:
        _entries = _by_iec_address[_iec_address]
        if len(_entries) > 1:
            _duplicate_input_iec_addresses.append({
                "iecAddress": _iec_address,
                "count": len(_entries),
                "occurrences": _entries
            })

    for _dup_addr in _duplicate_input_iec_addresses:
        _errors.append({
            "type": "duplicateInputIecAddress",
            "iecAddress": _dup_addr["iecAddress"],
            "count": _dup_addr["count"],
            "occurrences": _dup_addr["occurrences"]
        })

    for _device_name in _device_channel_ids:
        _info = _device_channel_ids[_device_name]
        _config_ids = sorted(_info["configIds"])
        _io_ids = sorted(_info["ioIds"])
        _expected_config_ids = []
        _io_id_mismatches = []

        _idx = 0
        while _idx < len(_config_ids):
            _expected_config_ids.append(_config_base + (_idx * _config_stride))
            _idx += 1

        _idx = 0
        while _idx < len(_io_ids) and _idx < len(_config_ids):
            _expected_io_base = _config_ids[_idx] + (_io_base - _config_base)
            if _io_ids[_idx] != _expected_io_base and _io_ids[_idx] != (_expected_io_base + 1):
                _io_id_mismatches.append({
                    "index": _idx,
                    "actual": _io_ids[_idx],
                    "expectedBase": _expected_io_base,
                    "expectedVariants": [_expected_io_base, _expected_io_base + 1]
                })
            _idx += 1

        if _config_ids != _expected_config_ids or len(_io_id_mismatches) > 0:
            _id_pattern_issues.append({
                "device": _device_name,
                "configIds": _config_ids,
                "expectedConfigIds": _expected_config_ids,
                "ioIds": _io_ids,
                "ioIdMismatches": _io_id_mismatches
            })

    for _issue in _id_pattern_issues:
        _warnings.append({
            "type": "nonCanonicalChannelIds",
            "device": _issue["device"],
            "configIds": _issue["configIds"],
            "expectedConfigIds": _issue["expectedConfigIds"],
            "ioIds": _issue["ioIds"],
            "ioIdMismatches": _issue["ioIdMismatches"]
        })

    for _unmapped in _unmapped_channels:
        _warnings.append({
            "type": "unmappedInputChannel",
            "device": _unmapped["device"],
            "channel": _unmapped["channel"],
            "iecAddress": _unmapped["iecAddress"],
            "resolvedVisibleName": _unmapped["resolvedVisibleName"],
            "resolvedDepth": _unmapped["resolvedDepth"],
            "resolvedType": _unmapped["resolvedType"]
        })

    result = {
        "success": len(_errors) == 0,
        "deviceFilter": _wanted_device,
        "devicesChecked": _devices_checked,
        "mappingCount": len(_mapping_entries),
        "mappings": _mapping_entries,
        "channelIdPatterns": _device_channel_ids,
        "idPatternIssues": _id_pattern_issues,
        "duplicateInputVariables": _duplicate_inputs,
        "duplicateInputIecAddresses": _duplicate_input_iec_addresses,
        "unmappedInputChannels": _unmapped_channels,
        "errors": _errors,
        "warnings": _warnings
    }
""",
        DEVICE_NAME=literal(device_name or ""),
        DEVICE_PARAM_IDS=DEVICE_PARAM_IDS,
    )


def find_variable_mappings(variable_name):
    return render(
        """\
import clr
import System

proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _input_variable = @@VARIABLE_NAME@@
    _trimmed = _input_variable.strip()
    _canonical = _trimmed
    if "." not in _canonical:
        _canonical = "Application.GVL." + _canonical
    elif _canonical.startswith("GVL."):
        _canonical = "Application." + _canonical

    _aliases = {}
    _aliases[_canonical] = True
    _tail = _canonical
    _idx = _canonical.rfind(".")
    if _idx >= 0:
        _tail = _canonical[_idx + 1:]
    _aliases[_tail] = True
    _aliases["GVL." + _tail] = True
    _aliases["Application.GVL." + _tail] = True

    _devices_checked = []
    _matches = []
    _seen_matches = {}
    _stack = []
    for _root in proj.get_children():
        _stack.append(_root)

    while _stack:
        _node = _stack.pop()
        if hasattr(_node, 'get_children'):
            try:
                for _child in _node.get_children():
                    _stack.append(_child)
            except:
                pass

        if not hasattr(_node, 'connectors') or not hasattr(_node, 'get_name'):
            continue

        _node_name = _node.get_name()
        _is_modbus_device = False
        _conn = None
        try:
            for _candidate_conn in _node.connectors:
                _has_slave_address = False
                for _candidate_param in _candidate_conn.host_parameters:
                    try:
                        _candidate_pid = int(_candidate_param.id)
                    except:
                        _candidate_pid = -1
                    _candidate_name = str(_candidate_param.name)
                    if _candidate_pid == 9100 or _candidate_name in ("SlaveAddress", "ServerAddress"):
                        _has_slave_address = True
                        break
                if _has_slave_address:
                    _conn = _candidate_conn
                    _is_modbus_device = True
                    break
        except:
            pass

        if not _is_modbus_device or _conn is None:
            continue

        _devices_checked.append(_node_name)

        _parent = _conn.host_parameters.parent
        _parent_type = _parent.GetType()
        _psc_iface = None
        for _iface in _parent_type.GetInterfaces():
            if 'IParameterSetContainer' in _iface.Name:
                _psc_iface = _iface
                break
        if _psc_iface is None:
            continue

        _prop = _psc_iface.GetProperty('ParameterSet')
        _native_pset = _prop.GetValue(_parent, None)
        if _native_pset is None:
            continue

        for _p in _native_pset:
            try:
                _channel_name = str(_p.VisibleName)
                _channel_type = str(_p.ChannelType)
            except:
                _channel_name = ""
                _channel_type = ""
            _subtree = [(_p, 0)]
            while len(_subtree) > 0:
                _current, _depth = _subtree.pop(0)
                try:
                    _current_io_map = _current.IoMapping
                    _var_maps = _current_io_map.VariableMappings
                    for _vm in _var_maps:
                        _variable = str(_vm.Variable)
                        _is_match = False
                        if _variable in _aliases:
                            _is_match = True
                        elif _variable.endswith("." + _tail):
                            _is_match = True
                        if _is_match:
                            _match_type = "exact" if _variable == _canonical else "alias"
                            _match_key = _node_name + "|" + _channel_name + "|" + str(_current.VisibleName) + "|" + _variable + "|" + str(_current_io_map.IecAddress)
                            if _match_key not in _seen_matches:
                                _seen_matches[_match_key] = True
                                _matches.append({
                                    "device": _node_name,
                                    "channel": _channel_name,
                                    "channelType": _channel_type,
                                    "variable": _variable,
                                    "canonicalVariable": _canonical,
                                    "matchType": _match_type,
                                    "iecAddress": str(_current_io_map.IecAddress),
                                    "nodeVisibleName": str(_current.VisibleName),
                                    "nodeDepth": _depth
                                })
                except:
                    pass

                try:
                    if bool(_current.HasSubElements):
                        for _child in _current.SubElements:
                            _subtree.append((_child, _depth + 1))
                except:
                    pass

    result = {
        "success": True,
        "input": _input_variable,
        "canonicalVariable": _canonical,
        "devicesChecked": _devices_checked,
        "matchCount": len(_matches),
        "matches": _matches
    }
""",
        VARIABLE_NAME=literal(variable_name),
    )


def normalize_iec_addresses(device_name=None, start_word=0):
    return render(
        """\
import clr
import System

proj = scriptengine.projects.primary
if proj is None:
    result = {"success": False, "error": "No project open"}
else:
    _wanted_device = @@DEVICE_NAME@@
    _next_word = @@START_WORD@@
    _normalized = []
    _devices_checked = []
    _warnings = []
    _device_stack = []

    for _root in proj.get_children():
        _device_stack.append(_root)

    while _device_stack:
        _node = _device_stack.pop(0)

        if hasattr(_node, 'connectors') and hasattr(_node, 'get_name'):
            _node_name = _node.get_name()
            _conn = None
            _is_modbus_device = False
            try:
                for _candidate_conn in _node.connectors:
                    _has_slave_address = False
                    for _candidate_param in _candidate_conn.host_parameters:
                        try:
                            _candidate_pid = int(_candidate_param.id)
                        except:
                            _candidate_pid = -1
                        _candidate_name = str(_candidate_param.name)
                        if _candidate_pid == 9100 or _candidate_name in ("SlaveAddress", "ServerAddress"):
                            _has_slave_address = True
                            break
                    if _has_slave_address:
                        _conn = _candidate_conn
                        _is_modbus_device = True
                        break
            except:
                pass

            if _is_modbus_device and _conn is not None:
                if (not _wanted_device) or _node_name == _wanted_device:
                    _devices_checked.append(_node_name)
                    _parent = _conn.host_parameters.parent
                    _parent_type = _parent.GetType()
                    _psc_iface = None
                    for _iface in _parent_type.GetInterfaces():
                        if 'IParameterSetContainer' in _iface.Name:
                            _psc_iface = _iface
                            break

                    if _psc_iface is None:
                        _warnings.append({
                            "device": _node_name,
                            "warning": "IParameterSetContainer not found"
                        })
                    else:
                        _prop = _psc_iface.GetProperty('ParameterSet')
                        _native_pset = _prop.GetValue(_parent, None)
                        if _native_pset is None:
                            _warnings.append({
                                "device": _node_name,
                                "warning": "Native ParameterSet not found"
                            })
                        else:
                            _input_params = []
                            for _p in _native_pset:
                                try:
                                    _pid = int(_p.Id)
                                except:
                                    continue
                                if _pid in @@DEVICE_PARAM_IDS@@:
                                    continue
                                try:
                                    _channel_type = str(_p.ChannelType)
                                except:
                                    _channel_type = ""
                                if _channel_type != "Input":
                                    continue
                                _input_params.append(_p)

                            _input_params = sorted(_input_params, key=lambda _item: int(_item.Id))

                            for _p in _input_params:
                                _resolved = _p
                                _resolved_depth = 0
                                _resolved_type = ""
                                _ambiguous = False
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
                                        _warnings.append({
                                            "device": _node_name,
                                            "channel": str(_p.VisibleName),
                                            "warning": "Channel mapping target is compound and ambiguous",
                                            "resolvedDepth": _resolved_depth,
                                            "resolvedType": _resolved_type,
                                            "childCount": _child_count
                                        })
                                        _ambiguous = True
                                        break
                                    _resolved = _resolved.SubElements[0]
                                    _resolved_depth += 1

                                if _ambiguous:
                                    continue

                                try:
                                    _io_map = _resolved.IoMapping
                                except:
                                    _warnings.append({
                                        "device": _node_name,
                                        "channel": str(_p.VisibleName),
                                        "warning": "IoMapping not available"
                                    })
                                    continue

                                _old_address = ""
                                try:
                                    _old_address = str(_io_map.IecAddress)
                                except:
                                    pass

                                _new_address = "%%IW" + str(_next_word)
                                _io_map.manual_iec_address = _new_address

                                _normalized.append({
                                    "device": _node_name,
                                    "channel": str(_p.VisibleName),
                                    "resolvedVisibleName": str(_resolved.VisibleName),
                                    "resolvedDepth": _resolved_depth,
                                    "resolvedType": _resolved_type,
                                    "oldIecAddress": _old_address,
                                    "newIecAddress": _new_address
                                })
                                _next_word += 1

        if hasattr(_node, 'get_children'):
            try:
                for _child in _node.get_children():
                    _device_stack.append(_child)
            except:
                pass

    result = {
        "success": True,
        "deviceFilter": _wanted_device,
        "devicesChecked": _devices_checked,
        "startWord": @@START_WORD@@,
        "normalizedCount": len(_normalized),
        "normalized": _normalized,
        "warnings": _warnings
    }
""",
        DEVICE_NAME=literal(device_name or ""),
        START_WORD=int(start_word),
        DEVICE_PARAM_IDS=DEVICE_PARAM_IDS,
    )
