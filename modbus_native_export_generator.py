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

    tree = ET.parse(empty_template_path)
    root = tree.getroot()
    _replace_text(root, SAMPLE_DEVICE_NAME, device_name)
    _replace_text(root, "773049b7-af3e-48c4-9667-4b1582f0d8e6", str(uuid.uuid4()))
    _set_slave_address(root, slave_address)

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
    _set_child_text(param, "Single", "Id", str(config_id))
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
    _set_child_text(param, "Single", "Id", str(io_id))
    _set_child_text(param, "Single", "Dimenstion1UpperBorder", str(upper))
    _set_child_text(param, "Single", "ParamType", "std:ARRAY[0..{0}] OF WORD".format(upper))

    channel_type = "Output" if int(channel["accessType"]) in (5, 6, 15, 16) else "Input"
    _set_child_text(param, "Single", "ChannelType", channel_type)
    position = _renumber_positions(param, position)
    return param, position


def _io_length(channel):
    access_type = int(channel["accessType"])
    if access_type in (5, 6, 15, 16):
        return int(channel["writeLength"])
    return int(channel["readLength"])


def _set_slave_address(root, slave_address):
    for param in root.iter("Single"):
        if _child_text(param, "Single", "Id") != "9100":
            continue
        _set_child_text(param, "Single", "Value", str(slave_address))
        return
    raise ValueError("slave address parameter 9100 not found")


def _set_struct_field_value(param, identifier, value):
    for single in param.iter("Single"):
        if single.attrib.get("Name") != "Identifier" or single.text != identifier:
            continue
        parent = _parent_of(param, single)
        if parent is not None:
            _set_child_text(parent, "Single", "Value", str(value))
        return
    raise ValueError("channel field not found: {0}".format(identifier))


def _set_unique_id_generator(root, value):
    _set_child_text(root, "Single", "UniqueIdGenerator", str(value))


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


def _set_child_text(parent, tag, name, value):
    for child in parent.iter(tag):
        if child.attrib.get("Name") == name:
            child.text = str(value)
            return True
    return False


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
