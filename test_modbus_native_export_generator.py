import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from modbus_native_export_generator import generate_modbus_slave_export


def _child_text(parent, name):
    for child in list(parent):
        if child.tag == "Single" and child.attrib.get("Name") == name:
            return child.text
    return None


def _host_params(root):
    for single in root.iter("Single"):
        if single.attrib.get("Name") == "HostParameterSet":
            for child in list(single):
                if child.tag == "List2" and child.attrib.get("Name") == "Params":
                    return list(child)
    raise AssertionError("HostParameterSet Params not found")


def _generated_params(root):
    params = []
    for param in _host_params(root):
        param_type = _child_text(param, "ParamType") or ""
        if param_type == "localTypes:CHANNEL_PACKED" or param_type.startswith("std:ARRAY"):
            params.append(param)
    return params


def _field_visible_identifier(config_param, field_identifier):
    for single in config_param.iter("Single"):
        if single.attrib.get("Name") == "Identifier" and single.text == field_identifier:
            parent = _parent(config_param, single)
            for item in parent.iter("Single"):
                if item.attrib.get("Name") == "VisibleName":
                    for visible_child in item.iter("Single"):
                        if visible_child.attrib.get("Name") == "Identifier":
                            return visible_child.text
    return None


def _first_bit_identifier(io_param):
    for single in io_param.iter("Single"):
        if single.attrib.get("Name") == "Default" and single.text == "FALSE":
            parent = _parent(io_param, single)
            return _child_text(parent, "Identifier")
    return None


def _word_identifiers(io_param):
    identifiers = []
    for single in io_param.iter("Single"):
        if single.attrib.get("Name") != "Identifier" or not single.text:
            continue
        text = str(single.text)
        if text.count("_") == 3:
            identifiers.append(text)
    return identifiers


def _parent(root, target):
    for parent in root.iter():
        if target in list(parent):
            return parent
    raise AssertionError("parent not found")


class NativeExportGeneratorTests(unittest.TestCase):
    def test_generated_real_template_preserves_nested_identifiers(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "slave.export"
            generate_modbus_slave_export(
                "TEST_SLAVE",
                13,
                [
                    {
                        "name": "TEST_CHANNEL",
                        "accessType": 3,
                        "readOffset": "16#0000",
                        "readLength": 1,
                        "writeOffset": "0",
                        "writeLength": 0,
                        "trigger": 5,
                        "cycleTime": 100,
                        "errorHandling": "true",
                    }
                ],
                str(output),
            )

            root = ET.parse(output).getroot()
            config_param, io_param = _generated_params(root)

            self.assertEqual(_child_text(config_param, "Id"), "17825792")
            self.assertEqual(_field_visible_identifier(config_param, "FunctionCode"), "CHANNEL.FunctionCode")
            self.assertEqual(_child_text(io_param, "Id"), "21233664")
            self.assertEqual(_first_bit_identifier(io_param), "21233664_0_0_0_0")
            self.assertEqual(_child_text(io_param, "ParamType"), "std:ARRAY[0..0] OF WORD")

    def test_generated_real_template_expands_two_word_io_arrays(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "slave.export"
            generate_modbus_slave_export(
                "FIT_1520",
                59,
                [
                    {
                        "name": "FIT-1520",
                        "accessType": 3,
                        "readOffset": "16#1010",
                        "readLength": 2,
                        "writeOffset": "0",
                        "writeLength": 0,
                        "trigger": 5,
                        "cycleTime": 100,
                        "errorHandling": "true",
                    }
                ],
                str(output),
            )

            root = ET.parse(output).getroot()
            _config_param, io_param = _generated_params(root)

            self.assertEqual(_child_text(io_param, "ParamType"), "std:ARRAY[0..1] OF WORD")
            self.assertEqual(sorted(_word_identifiers(io_param)), ["21233664_0_0_0", "21233664_0_0_1"])


if __name__ == "__main__":
    unittest.main()
