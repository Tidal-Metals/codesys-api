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
            # CODESYS's own export (templates/modbus_serial_slave_canonical.export) encodes
            # slot, family and register offset in the IO Id (channel 2 at offset 1 is
            # 0x2440001) and numbers array words in the second field (38010881_1_0_0).
            self.assertEqual(sorted(_word_identifiers(io_param)), ["21237776_0_0_0", "21237776_1_0_0"])

    def test_coil_channels_match_codesys_own_channels(self):
        # templates/modbus_tcp_server_canonical_coils.export holds these channels as
        # CODESYS's Modbus editor code created them (slot 1 is a register read).
        def channel(name, fc, read_offset=0, read_length=0, write_offset=0, write_length=0):
            return {"name": name, "accessType": fc, "readOffset": str(read_offset), "readLength": read_length,
                    "writeOffset": str(write_offset), "writeLength": write_length,
                    "trigger": 5, "cycleTime": 100, "errorHandling": "true"}

        channels = [
            channel("BenchRead", 3, 0, 2),
            channel("COIL_R10", 1, 0, 10),
            channel("COIL_R1", 1, 3, 1),
            channel("DI_R10", 2, 0, 10),
            channel("COIL_W1", 5, write_offset=20, write_length=1),
            channel("COIL_W10", 15, write_offset=24, write_length=10),
            channel("COIL_RBACK", 1, 20, 14),
        ]
        oracle_root = ET.parse(Path(__file__).parent / "templates/modbus_tcp_server_canonical_coils.export").getroot()
        oracle = {_child_text(p, "Id"): p for p in _host_params(oracle_root)
                  if (_child_text(p, "ParamType") or "").endswith("OF BYTE") and int(_child_text(p, "Id")) >= 1 << 24}
        self.assertEqual(len(oracle), 6)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "slave.export"
            generate_modbus_slave_export("COIL_SLAVE", 2, channels, str(output))
            generated = {_child_text(p, "Id"): p for p in _host_params(ET.parse(output).getroot())}

        for param_id, expected in oracle.items():
            with self.subTest(param_id=hex(int(param_id))):
                self.assertIn(param_id, generated)
                self.assertEqual(_io_shape(generated[param_id]), _io_shape(expected))


def _io_shape(param):
    """Everything CODESYS sets on an IO array parameter except position ids."""
    def leaf(element):
        return (_child_text(element, "Identifier"), _default(element, "Description"),
                _default(element, "VisibleName"), _child_text(element, "OfflineAccess"))

    dala = _named(param, "DalaElement")
    elements = []
    for element in _named(_named(dala, "SubElements"), "elements"):
        bits = [leaf(bit) for bit in _named(_named(element, "SubElements"), "elements")]
        elements.append((leaf(element), _child_text(element, "BaseType"), bits))
    return (_child_text(param, "ParamType"), _child_text(param, "ChannelType"), leaf(dala),
            _child_text(dala, "Dimenstion1UpperBorder"), elements)


def _named(parent, name):
    for child in list(parent):
        if child.attrib.get("Name") == name:
            return child
    raise AssertionError("no child named " + name)


def _default(parent, name):
    for child in list(parent):
        if child.attrib.get("Name") == name:
            return _child_text(child, "Default")
    return None


if __name__ == "__main__":
    unittest.main()
