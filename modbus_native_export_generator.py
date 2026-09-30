"""Generate CODESYS native .export files for Modbus serial slave devices."""

import copy
import os
import time
import uuid
import xml.etree.ElementTree as ET

from modbus_script_utils import normalize_channel


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(SCRIPT_DIR, "templates")
DEFAULT_EMPTY_TEMPLATE = os.path.join(TEMPLATE_DIR, "modbus_serial_slave_empty.export")
DEFAULT_CHANNEL_SAMPLE = os.path.join(TEMPLATE_DIR, "modbus_serial_slave_channel_sample.export")
DEFAULT_REAL_TEMPLATE = os.path.join(TEMPLATE_DIR, "modbus_serial_slave_real.export")
DEFAULT_CANONICAL_TEMPLATE = os.path.join(TEMPLATE_DIR, "modbus_serial_slave_canonical_mixed.export")
# Coil and discrete-input channels created by CODESYS's own Modbus editor code
# (ChannelData.CreateSlaveChannel, bench 2026-09-30): packed BYTE arrays, one
# BIT per coil, unused tail bits disabled.
DEFAULT_COIL_TEMPLATE = os.path.join(TEMPLATE_DIR, "modbus_tcp_server_canonical_coils.export")

BIT_FUNCTION_CODES = (1, 2, 5, 15)
FUNCTION_CODE_TEXT = {
    1: "Read Coils",
    2: "Read Discrete Inputs",
    5: "Write Single Coil",
    15: "Write Multiple Coils",
}

SAMPLE_DEVICE_NAME = "TEST_SLAVE"
SAMPLE_CHANNEL_NAME = "XML_GEN_SAMPLE"
SAMPLE_CONFIG_ID = "16786417"
SAMPLE_IO_ID = "20194289"


def generate_modbus_slave_export(device_name, slave_address, channels, output_path,
                                 empty_template_path=DEFAULT_EMPTY_TEMPLATE,
                                 channel_sample_path=DEFAULT_CHANNEL_SAMPLE):
    """Generate a native CODESYS .export file for one Modbus serial slave."""
    if not device_name:
        raise ValueError("device_name is required")
    if not output_path:
        raise ValueError("output_path is required")
    if not os.path.exists(empty_template_path):
        raise ValueError("empty template not found: {0}".format(empty_template_path))
    if not os.path.exists(channel_sample_path):
        raise ValueError("channel sample not found: {0}".format(channel_sample_path))

    normalized = [normalize_channel(channel) for channel in channels]

    if os.path.exists(DEFAULT_CANONICAL_TEMPLATE):
        return _generate_from_real_template(
            device_name,
            slave_address,
            normalized,
            output_path,
            DEFAULT_CANONICAL_TEMPLATE,
        )

    tree = ET.parse(empty_template_path)
    root = tree.getroot()
    _replace_text(root, SAMPLE_DEVICE_NAME, device_name)
    _replace_text(root, "773049b7-af3e-48c4-9667-4b1582f0d8e6", str(uuid.uuid4()))
    _set_slave_address(root, slave_address)
    _normalize_device_runtime_flags(root)

    params = _host_params_list(root)
    config_version = _find_param_by_id(params, "1879052288")
    if config_version is None:
        raise ValueError("ConfigVersion parameter not found in empty template")
    insert_index = list(params).index(config_version)

    config_sample, io_sample = _load_channel_samples(channel_sample_path)
    position = _max_position_id(root) + 2
    for index, channel in enumerate(normalized):
        config_id = 16786417 + (index * 16777216)
        io_id = config_id + 3407872
        config_param, position = _build_channel_config_param(config_sample, channel, config_id, position)
        io_param, position = _build_io_param(io_sample, channel, io_id, position)
        params.insert(insert_index, config_param)
        insert_index += 1
        params.insert(insert_index, io_param)
        insert_index += 1

    _set_unique_id_generator(root, position)
    _indent(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=False)
    return {
        "success": True,
        "path": output_path,
        "device": device_name,
        "slaveAddress": slave_address,
        "channelCount": len(normalized),
    }


def _generate_from_real_template(device_name, slave_address, channels, output_path, template_path):
    """Generate from a native export captured from a real CODESYS Modbus slave.

    The older checked-in templates were hand-trimmed and can diverge from what
    CODESYS actually exports. This path starts from a known-good native export,
    removes its existing channel parameters, and clones the real channel
    parameter shapes for the requested manifest channels.
    """
    normalized = [normalize_channel(channel) for channel in channels]
    tree = ET.parse(template_path)
    root = tree.getroot()

    template_name = _exported_device_name(root) or "Pump2"
    _replace_text(root, template_name, device_name)
    _set_first_named_text(root, "Guid", str(uuid.uuid4()))
    _set_slave_address_real(root, slave_address)
    _normalize_device_runtime_flags(root)

    params = _host_params_list(root)
    samples = _load_real_channel_samples(params)
    if any(_is_bit_channel(channel) for channel in normalized):
        samples.update(_load_bit_channel_samples(DEFAULT_COIL_TEMPLATE))

    insert_index = _remove_real_channel_params(params)
    position = _max_position_id(root) + 2

    for index, channel in enumerate(normalized):
        channel_params = _build_real_channel_params(samples, channel, index)
        for param in channel_params:
            position = _renumber_positions(param, position)
            params.insert(insert_index, param)
            insert_index += 1

    _set_unique_id_generator(root, position)
    _indent(root)
    tree.write(output_path, encoding="utf-8", xml_declaration=False)
    return {
        "success": True,
        "path": output_path,
        "device": device_name,
        "slaveAddress": slave_address,
        "channelCount": len(normalized),
        "template": template_path,
    }


def _exported_device_name(root):
    for single in root.iter("Single"):
        if single.attrib.get("Name") == "Name":
            text = single.text.strip() if single.text else ""
            if text:
                return text
    return None


def _set_first_named_text(root, name, value):
    for single in root.iter("Single"):
        if single.attrib.get("Name") == name:
            single.text = str(value)
            return True
    return False


def _set_slave_address_real(root, slave_address):
    for param in _host_params_list(root):
        if _param_id(param) == "9100":
            _set_descendant_child_text(param, "Single", "Value", str(slave_address))
            return
    raise ValueError("slave address parameter 9100 not found")


def _load_real_channel_samples(params):
    groups = _extract_real_channel_groups(params)
    input_group = None
    output_group = None
    trigger_group = None
    for group in groups:
        if group["config"] is None or group["io"] is None:
            continue
        channel_type = group.get("channelType")
        if channel_type == "Input" and input_group is None:
            input_group = group
        elif channel_type == "Output" and output_group is None:
            output_group = group
        if group.get("bit") is not None and trigger_group is None:
            trigger_group = group

    if input_group is None:
        raise ValueError("real input channel sample not found")

    return {
        "input": input_group,
        "output": output_group,
        "trigger": trigger_group,
    }


def _load_bit_channel_samples(path):
    """Coil/discrete IO samples (BYTE arrays) from a CODESYS-created export."""
    if not os.path.exists(path):
        raise ValueError("coil channel template not found: {0}".format(path))
    params = _host_params_list(ET.parse(path).getroot())
    samples = {"bitInput": None, "bitOutput": None}
    for group in _extract_real_channel_groups(params, "BYTE"):
        key = "bitOutput" if group.get("channelType") == "Output" else "bitInput"
        if group["io"] is not None and samples[key] is None:
            samples[key] = group
    if samples["bitInput"] is None or samples["bitOutput"] is None:
        raise ValueError("coil template needs an input and an output coil channel: {0}".format(path))
    return samples


def _is_bit_channel(channel):
    return int(channel["accessType"]) in BIT_FUNCTION_CODES


def _extract_real_channel_groups(params, element_type="WORD"):
    groups = []
    current = None
    for param in list(params):
        param_id = _param_id(param)
        try:
            numeric_id = int(param_id)
        except (TypeError, ValueError):
            continue
        if numeric_id >= 1879052288:
            break
        if numeric_id in (8000, 9100, 9101, 9102, 9200, 9201):
            continue
        param_type = _child_text(param, "Single", "ParamType")
        if param_type == "localTypes:CHANNEL_PACKED":
            current = {
                "config": copy.deepcopy(param),
                "configId": numeric_id,
                "name": _visible_name(param),
                "bit": None,
                "bitId": None,
                "io": None,
                "ioId": None,
                "channelType": None,
            }
            groups.append(current)
            continue
        if current is None:
            continue
        if param_type == "std:BIT" and current["bit"] is None:
            current["bit"] = copy.deepcopy(param)
            current["bitId"] = numeric_id
            continue
        if param_type and param_type.startswith("std:ARRAY") and param_type.endswith("OF " + element_type) and current["io"] is None:
            current["io"] = copy.deepcopy(param)
            current["ioId"] = numeric_id
            current["channelType"] = _child_text(param, "Single", "ChannelType")
    return groups


def _remove_real_channel_params(params):
    children = list(params)
    insert_index = len(children)
    for index, param in enumerate(children):
        if _param_id(param) == "1879052288":
            insert_index = index
            break

    removed_before_insert = 0
    for index, param in enumerate(children):
        param_id = _param_id(param)
        try:
            numeric_id = int(param_id)
        except (TypeError, ValueError):
            continue
        if 16000000 <= numeric_id < 1879052288:
            params.remove(param)
            if index < insert_index:
                removed_before_insert += 1
    return max(insert_index - removed_before_insert, 0)


def _build_real_channel_config_param(sample, channel, config_id, sample_id):
    param = copy.deepcopy(sample)
    _replace_text(param, str(sample_id), str(config_id))
    _set_top_level_child_text(param, "Id", str(config_id))
    _set_top_level_child_text(param, "Identifier", str(config_id))
    _set_param_visible_name(param, channel["name"])
    _set_struct_field_value(param, "FunctionCode", channel["accessType"])
    _set_struct_field_value(param, "ReadOffset", channel["readOffset"])
    _set_struct_field_value(param, "ReadLength", channel["readLength"])
    _set_struct_field_value(param, "WriteOffset", channel["writeOffset"])
    _set_struct_field_value(param, "WriteLength", channel["writeLength"])
    _set_struct_field_value(param, "Trigger", channel["trigger"])
    _set_struct_field_value(param, "CycleTime", channel["cycleTime"])
    _set_struct_field_value(param, "ErrorHandling", str(channel["errorHandling"]).lower())
    return param


def _build_real_io_param(sample, channel, io_id, sample_id, channel_type):
    param = copy.deepcopy(sample)
    length = _io_length(channel)
    upper = max(length - 1, 0)
    _replace_text(param, str(sample_id), str(io_id))
    _set_top_level_child_text(param, "Id", str(io_id))
    _set_top_level_child_text(param, "Identifier", str(io_id))
    _set_descendant_child_text(param, "Single", "Dimenstion1LowerBorder", "0")
    _set_descendant_child_text(param, "Single", "Dimenstion1UpperBorder", str(upper))
    _set_top_level_child_text(param, "ParamType", "std:ARRAY[0..{0}] OF WORD".format(upper))
    _set_top_level_child_text(param, "ChannelType", channel_type)
    _set_param_visible_name(param, channel["name"])
    _rebuild_io_word_elements(param, channel, io_id)
    _clear_io_variable_mappings(param)
    return param


def _build_real_bit_io_param(sample, channel, io_id, sample_id, channel_type):
    """Coil/discrete IO parameter: ARRAY[0..ceil(n/8)-1] OF BYTE, one BIT per coil."""
    param = copy.deepcopy(sample)
    upper = (_io_length(channel) + 7) // 8 - 1
    sample_text = _dala_description(param)
    _replace_text(param, str(sample_id), str(io_id))
    _set_top_level_child_text(param, "Id", str(io_id))
    _set_descendant_child_text(param, "Single", "Dimenstion1LowerBorder", "0")
    _set_descendant_child_text(param, "Single", "Dimenstion1UpperBorder", str(upper))
    _set_top_level_child_text(param, "ParamType", "std:ARRAY[0..{0}] OF BYTE".format(upper))
    _set_top_level_child_text(param, "ChannelType", channel_type)
    _set_param_visible_name(param, channel["name"])
    if sample_text:
        _replace_text(param, sample_text, FUNCTION_CODE_TEXT[int(channel["accessType"])])
    _rebuild_io_byte_elements(param, channel, io_id)
    _clear_io_variable_mappings(param)
    return param


def _build_real_trigger_param(sample, channel, trigger_id, sample_id):
    param = copy.deepcopy(sample)
    _replace_text(param, str(sample_id), str(trigger_id))
    _set_top_level_child_text(param, "Id", str(trigger_id))
    _set_top_level_child_text(param, "Identifier", str(trigger_id))
    _set_param_visible_name(param, channel["name"])
    return param


def _build_real_channel_params(samples, channel, index):
    is_output = int(channel["accessType"]) in (5, 6, 15, 16)
    if is_output:
        group = samples["output"]
        if group is None:
            raise ValueError("canonical template does not include an output channel sample")
    else:
        group = samples["input"]
        if group is None:
            raise ValueError("input channel sample not found")
    params = []
    slot_index = index + 1
    config_id = _config_id_for_slot(slot_index)

    config_param = _build_real_channel_config_param(
        group["config"],
        channel,
        config_id,
        group["configId"],
    )
    params.append(config_param)

    if _requires_trigger_aux(channel):
        trigger_group = samples.get("trigger") or group
        if trigger_group.get("bit") is None:
            raise ValueError("trigger-enabled channel requires a trigger sample")
        trigger_id = _trigger_aux_id_for_slot(slot_index)
        trigger_param = _build_real_trigger_param(
            trigger_group["bit"],
            channel,
            trigger_id,
            trigger_group["bitId"],
        )
        params.append(trigger_param)

    io_id = _io_id_for_channel(slot_index, channel)
    channel_type = "Output" if is_output else "Input"
    if _is_bit_channel(channel):
        bit_group = samples["bitOutput" if is_output else "bitInput"]
        io_param = _build_real_bit_io_param(bit_group["io"], channel, io_id, bit_group["ioId"], channel_type)
    else:
        io_param = _build_real_io_param(group["io"], channel, io_id, group["ioId"], channel_type)
    params.append(io_param)
    return params


def _param_id(param):
    return _child_text(param, "Single", "Id")


def _io_group_length(io_param):
    upper = _child_text(io_param, "Single", "Dimenstion1UpperBorder")
    if upper is not None:
        try:
            return int(upper) + 1
        except (TypeError, ValueError):
            pass
    param_type = _child_text(io_param, "Single", "ParamType") or ""
    if ".." in param_type:
        try:
            upper_text = param_type.split("..", 1)[1].split("]", 1)[0]
            return int(upper_text) + 1
        except (IndexError, ValueError):
            pass
    return 1


def _visible_name(param):
    for child in list(param):
        if child.tag == "Single" and child.attrib.get("Name") == "DalaElement":
            for dala_child in list(child):
                if dala_child.tag != "Single" or dala_child.attrib.get("Name") != "VisibleName":
                    continue
                for visible_child in list(dala_child):
                    if visible_child.tag == "Single" and visible_child.attrib.get("Name") == "Default" and visible_child.text:
                        return visible_child.text
    for single in param.iter("Single"):
        if single.attrib.get("Name") != "VisibleName":
            continue
        for child in single.iter("Single"):
            if child.attrib.get("Name") == "Default" and child.text:
                return child.text
    return ""


def _load_channel_samples(path):
    sample_root = ET.parse(path).getroot()
    params = _host_params_list(sample_root)
    config = None
    io = None
    for param in list(params):
        param_type = _child_text(param, "Single", "ParamType")
        if param_type == "localTypes:CHANNEL_PACKED":
            config = copy.deepcopy(param)
        elif param_type and param_type.startswith("std:ARRAY") and param_type.endswith("OF WORD"):
            io = copy.deepcopy(param)
    if config is None:
        raise ValueError("CHANNEL_PACKED sample parameter not found: {0}".format(path))
    if io is None:
        raise ValueError("IO array sample parameter not found: {0}".format(path))
    return config, io


def _host_params_list(root):
    for single in root.iter("Single"):
        if single.attrib.get("Name") == "HostParameterSet":
            for child in list(single):
                if child.tag == "List2" and child.attrib.get("Name") == "Params":
                    return child
    raise ValueError("HostParameterSet Params list not found")


def _find_param_by_id(params, param_id):
    for param in list(params):
        if _child_text(param, "Single", "Id") == str(param_id):
            return param
    return None


def _build_channel_config_param(sample, channel, config_id, position):
    param = copy.deepcopy(sample)
    _replace_text(param, SAMPLE_CHANNEL_NAME, channel["name"])
    _replace_text(param, SAMPLE_CONFIG_ID, str(config_id))
    _set_top_level_child_text(param, "Id", str(config_id))
    _set_struct_field_value(param, "FunctionCode", channel["accessType"])
    _set_struct_field_value(param, "ReadOffset", channel["readOffset"])
    _set_struct_field_value(param, "ReadLength", channel["readLength"])
    _set_struct_field_value(param, "WriteOffset", channel["writeOffset"])
    _set_struct_field_value(param, "WriteLength", channel["writeLength"])
    _set_struct_field_value(param, "Trigger", channel["trigger"])
    _set_struct_field_value(param, "CycleTime", channel["cycleTime"])
    _set_struct_field_value(param, "ErrorHandling", str(channel["errorHandling"]).lower())
    position = _renumber_positions(param, position)
    return param, position


def _build_io_param(sample, channel, io_id, position):
    param = copy.deepcopy(sample)
    length = _io_length(channel)
    upper = max(length - 1, 0)
    _replace_text(param, SAMPLE_CHANNEL_NAME, channel["name"])
    _replace_text(param, SAMPLE_IO_ID, str(io_id))
    _set_top_level_child_text(param, "Id", str(io_id))
    _set_top_level_child_text(param, "Dimenstion1UpperBorder", str(upper))
    _set_top_level_child_text(param, "ParamType", "std:ARRAY[0..{0}] OF WORD".format(upper))

    channel_type = "Output" if int(channel["accessType"]) in (5, 6, 15, 16) else "Input"
    _set_top_level_child_text(param, "ChannelType", channel_type)
    _set_first_io_word_metadata(param, channel)
    position = _renumber_positions(param, position)
    return param, position


def _io_length(channel):
    access_type = int(channel["accessType"])
    if access_type in (5, 6, 15, 16):
        return int(channel["writeLength"])
    return int(channel["readLength"])


def _config_id_for_slot(slot_index):
    return (int(slot_index) << 24) | 0x00100000


def _trigger_aux_id_for_slot(slot_index):
    return (int(slot_index) << 24) | 0x00200001


def _io_id_for_channel(slot_index, channel):
    offset = _channel_offset(channel)
    family = _family_byte_for_channel(channel)
    return (int(slot_index) << 24) | (family << 16) | offset


def _channel_offset(channel):
    access_type = int(channel["accessType"])
    source = channel["writeOffset"] if access_type in (5, 6, 15, 16) else channel["readOffset"]
    text = str(source).strip()
    if not text or text == "0":
        return 0
    if text.lower().startswith("16#"):
        return int(text[3:], 16)
    return int(text)


def _family_byte_for_channel(channel):
    access_type = int(channel["accessType"])
    if access_type == 1:
        return 0x42
    if access_type == 2:
        return 0x41
    if access_type == 3:
        return 0x44
    if access_type == 4:
        return 0x43
    if access_type in (5, 15):
        return 0x82
    if access_type in (6, 16):
        return 0x84
    raise ValueError("Unsupported access type for IO family: {0}".format(access_type))


def _requires_trigger_aux(channel):
    try:
        trigger = int(channel.get("trigger", 5))
    except (TypeError, ValueError, AttributeError):
        return False
    return trigger != 5


def _set_slave_address(root, slave_address):
    for param in root.iter("Single"):
        if _child_text(param, "Single", "Id") != "9100":
            continue
        _set_descendant_child_text(param, "Single", "Value", str(slave_address))
        return
    raise ValueError("slave address parameter 9100 not found")


def _normalize_device_runtime_flags(root):
    """Force imported devices into an enabled, included state.

    Some captured native exports can persist the current IDE/runtime state,
    including a disabled device. That produces gray imported devices and
    breaks the automated import path even though the channel data itself is
    structurally valid.
    """
    _set_descendant_child_text(root, "Single", "Disable", "False")
    _set_descendant_child_text(root, "Single", "Exclude", "False")


def _set_struct_field_value(param, identifier, value):
    for single in param.iter("Single"):
        if single.attrib.get("Name") != "Identifier" or single.text != identifier:
            continue
        parent = _parent_of(param, single)
        if parent is not None:
            _set_top_level_child_text(parent, "Value", str(value))
        return
    raise ValueError("channel field not found: {0}".format(identifier))


def _set_unique_id_generator(root, value):
    _set_descendant_child_text(root, "Single", "UniqueIdGenerator", str(value))


def _max_position_id(root):
    max_id = 0
    for single in root.iter("Single"):
        if single.attrib.get("Name") in ("PositionId", "EditorPositionId"):
            try:
                max_id = max(max_id, int(single.text))
            except (TypeError, ValueError):
                pass
    return max_id


def _renumber_positions(root, start):
    current = start
    for single in root.iter("Single"):
        if single.attrib.get("Name") in ("PositionId", "EditorPositionId"):
            single.text = str(current)
            current += 1
    return current


def _replace_text(root, old, new):
    for elem in root.iter():
        if elem.text and old in elem.text:
            elem.text = elem.text.replace(old, new)
        if elem.tail and old in elem.tail:
            elem.tail = elem.tail.replace(old, new)


def _child_text(parent, tag, name):
    for child in list(parent):
        if child.tag == tag and child.attrib.get("Name") == name:
            return child.text
    return None


def _set_descendant_child_text(parent, tag, name, value):
    for child in parent.iter(tag):
        if child.attrib.get("Name") == name:
            child.text = str(value)
            return True
    return False


def _set_top_level_child_text(parent, name, value):
    for child in list(parent):
        if child.tag == "Single" and child.attrib.get("Name") == name:
            child.text = str(value)
            return True
    return False


def _set_param_visible_name(param, value):
    dala = _find_direct_child(param, "Single", "DalaElement")
    if dala is not None:
        visible = _find_direct_child(dala, "Single", "VisibleName")
        if visible is not None:
            default = _find_direct_child(visible, "Single", "Default")
            if default is not None:
                default.text = str(value)
                return True
    visible = _find_direct_child(param, "Single", "VisibleName")
    if visible is None:
        return False
    default = _find_direct_child(visible, "Single", "Default")
    if default is None:
        return False
    default.text = str(value)
    return True


def _set_param_description(param, value):
    description = _find_direct_child(param, "Single", "Description")
    if description is None:
        return False
    default = _find_direct_child(description, "Single", "Default")
    if default is None:
        return False
    default.text = str(value)
    return True


def _set_first_io_word_metadata(param, channel):
    """Rewrite stale leaf metadata inside copied IO array params."""
    word_element = _first_io_word_element(param)
    if word_element is None:
        return False
    _set_param_visible_name(word_element, channel["name"])
    _set_param_description(word_element, _channel_leaf_description(channel))
    return True


def _rebuild_io_word_elements(param, channel, io_id):
    """Rebuild nested WORD array children so multiword channels materialize correctly.

    The native export sample only carries one WORD child. For length > 1 channels,
    CODESYS expects one WORD child per array element, each with its own identifier
    family and register-offset description. Merely changing ParamType / upper bound
    is not enough.
    """
    length = _io_length(channel)
    dala = _find_direct_child(param, "Single", "DalaElement")
    if dala is None:
        return False
    sub_elements = _find_direct_child(dala, "Single", "SubElements")
    if sub_elements is None:
        return False
    elements = _find_direct_child(sub_elements, "List2", "elements")
    if elements is None:
        return False

    template_word = None
    template_bits = []
    for child in list(elements):
        if child.tag != "Single":
            continue
        if _child_text(child, "Single", "BaseType") == "WORD":
            template_word = copy.deepcopy(child)
            break
    if template_word is None:
        return False

    word_sub_elements = _find_direct_child(template_word, "Single", "SubElements")
    if word_sub_elements is not None:
        word_bit_elements = _find_direct_child(word_sub_elements, "List2", "elements")
        if word_bit_elements is not None:
            template_bits = [copy.deepcopy(child) for child in list(word_bit_elements) if child.tag == "Single"]

    for child in list(elements):
        if child.tag == "Single" and _child_text(child, "Single", "BaseType") == "WORD":
            elements.remove(child)

    for word_index in range(length):
        word_element = copy.deepcopy(template_word)
        _set_param_visible_name(word_element, channel["name"])
        _set_param_description(word_element, _channel_leaf_description(channel, word_index))
        _set_top_level_child_text(word_element, "Identifier", "{0}_{1}_0_0".format(io_id, word_index))
        _clear_io_variable_mappings(word_element)

        word_sub_elements = _find_direct_child(word_element, "Single", "SubElements")
        if word_sub_elements is not None:
            word_bit_elements = _find_direct_child(word_sub_elements, "List2", "elements")
            if word_bit_elements is not None:
                for child in list(word_bit_elements):
                    word_bit_elements.remove(child)
                for bit_index, template_bit in enumerate(template_bits):
                    bit_element = copy.deepcopy(template_bit)
                    bit_identifier = "{0}_{1}_0_0_{2}".format(io_id, word_index, bit_index)
                    for identifier_node in bit_element.iter("Single"):
                        if identifier_node.attrib.get("Name") == "Identifier":
                            identifier_node.text = bit_identifier
                    word_bit_elements.append(bit_element)

        elements.append(word_element)
    return True


def _rebuild_io_byte_elements(param, channel, io_id):
    """Rebuild BYTE children, eight BIT children each, as CODESYS's editor does.

    Coil n of the channel is bit n % 8 of byte n // 8 (Modbus LSB-first order).
    Used bits describe their coil address (0x0008); bits past the channel
    length are disabled with OfflineAccess None and describe the function.
    """
    length = _io_length(channel)
    function_text = FUNCTION_CODE_TEXT[int(channel["accessType"])]
    elements = _io_array_elements(param)
    sample_bytes = [child for child in list(elements)
                    if child.tag == "Single" and _child_text(child, "Single", "BaseType") == "BYTE"]
    if not sample_bytes:
        raise ValueError("coil IO sample has no BYTE element")
    sample_bits = [bit for byte in sample_bytes for bit in _byte_bits(byte)]
    enabled_bits = [bit for bit in sample_bits if _find_direct_child(bit, "Single", "OfflineAccess") is None]
    offline_marks = [_find_direct_child(bit, "Single", "OfflineAccess") for bit in sample_bits
                     if _find_direct_child(bit, "Single", "OfflineAccess") is not None]
    if not enabled_bits or not offline_marks:
        raise ValueError("coil IO sample needs an enabled and a disabled bit")
    template_byte = copy.deepcopy(sample_bytes[0])
    for child in sample_bytes:
        elements.remove(child)

    first_address = _channel_offset(channel)
    for byte_index in range((length + 7) // 8):
        byte_element = copy.deepcopy(template_byte)
        _set_param_visible_name(byte_element, channel["name"])
        _set_param_description(byte_element, function_text)
        _set_top_level_child_text(byte_element, "Identifier", "{0}_{1}_0_0".format(io_id, byte_index))
        _clear_io_variable_mappings(byte_element)
        bit_list = _find_direct_child(_find_direct_child(byte_element, "Single", "SubElements"), "List2", "elements")
        for child in list(bit_list):
            bit_list.remove(child)
        for bit_index in range(8):
            coil = byte_index * 8 + bit_index
            bit = copy.deepcopy(enabled_bits[0])
            for node in bit.iter("Single"):
                if node.attrib.get("Name") == "Identifier":
                    node.text = "{0}_{1}_0_0_{2}".format(io_id, byte_index, bit_index)
                elif node.attrib.get("Name") == "VisibleName":
                    _set_top_level_child_text(node, "Default", "Bit{0}".format(bit_index))
            if coil < length:
                _set_param_description(bit, "0x{0:04X}".format(first_address + coil))
            else:
                _set_param_description(bit, function_text)
                bit.insert(0, copy.deepcopy(offline_marks[0]))
            bit_list.append(bit)
        elements.append(byte_element)
    return True


def _io_array_elements(param):
    dala = _find_direct_child(param, "Single", "DalaElement")
    sub_elements = _find_direct_child(dala, "Single", "SubElements") if dala is not None else None
    elements = _find_direct_child(sub_elements, "List2", "elements") if sub_elements is not None else None
    if elements is None:
        raise ValueError("IO array parameter has no element list")
    return elements


def _byte_bits(byte_element):
    sub_elements = _find_direct_child(byte_element, "Single", "SubElements")
    bit_list = _find_direct_child(sub_elements, "List2", "elements") if sub_elements is not None else None
    return [child for child in list(bit_list)] if bit_list is not None else []


def _dala_description(param):
    dala = _find_direct_child(param, "Single", "DalaElement")
    description = _find_direct_child(dala, "Single", "Description") if dala is not None else None
    default = _find_direct_child(description, "Single", "Default") if description is not None else None
    return default.text if default is not None else None


def _clear_io_variable_mappings(param):
    for single in param.iter("Single"):
        if single.attrib.get("Name") != "Mappings":
            continue
        for child in list(single):
            if child.tag == "List2" and child.attrib.get("Name") == "Mappings":
                for entry in list(child):
                    child.remove(entry)
    return True


def _first_io_word_element(param):
    dala = _find_direct_child(param, "Single", "DalaElement")
    if dala is None:
        return None
    sub_elements = _find_direct_child(dala, "Single", "SubElements")
    if sub_elements is None:
        return None
    elements = _find_direct_child(sub_elements, "List2", "elements")
    if elements is None:
        return None
    for child in list(elements):
        if child.tag != "Single":
            continue
        if _child_text(child, "Single", "BaseType") == "WORD":
            return child
    return None


def _channel_leaf_description(channel, word_index=0):
    access_type = int(channel["accessType"])
    source = channel["writeOffset"] if access_type in (5, 6, 15, 16) else channel["readOffset"]
    text = str(source).strip()
    if text.lower().startswith("16#"):
        try:
            value = int(text[3:], 16) + int(word_index)
            return "0x{0:04X}".format(value)
        except ValueError:
            return "0x" + text[3:].upper()
    try:
        return str(int(text) + int(word_index))
    except ValueError:
        return text


def _find_direct_child(parent, tag, name):
    for child in list(parent):
        if child.tag == tag and child.attrib.get("Name") == name:
            return child
    return None


def _parent_of(root, target):
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                return parent
    return None


def _indent(elem, level=0):
    spacer = "\n" + level * "  "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = spacer + "  "
        for child in elem:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = spacer
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = spacer


if __name__ == "__main__":
    output = os.path.join(SCRIPT_DIR, "generated_modbus_slave_{0}.export".format(int(time.time())))
    print(generate_modbus_slave_export(
        "GENERATED_TEST_SLAVE",
        7,
        [
            {"name": "GEN_READ_01", "access_type": 3, "read_offset": "16#0001", "read_length": 2, "cycle_time": 250},
            {"name": "GEN_WRITE_01", "access_type": 16, "read_length": 0, "write_offset": "16#0020", "write_length": 3},
        ],
        output,
    ))
