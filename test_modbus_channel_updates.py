"""Channel updates must refuse shape changes (function code, offset, length) and allow the rest."""

import types
import unittest

import modbus_channel_scripts
from modbus_handler_channels import ModbusChannelMixin


class FakeField:
    def __init__(self, value):
        self.value = value


class FakeChannelParam:
    def __init__(self, pid, name, fields):
        self.id = pid
        self.name = name
        self.fields = [FakeField(v) for v in fields]

    def __getitem__(self, index):
        return self.fields[index]

    @property
    def value(self):
        return "{" + ", ".join(str(f.value) for f in self.fields) + "}"


class FakeDevice:
    def __init__(self, name, params):
        self.name = name
        self.connectors = [types.SimpleNamespace(host_parameters=params)]

    def get_name(self):
        return self.name

    def get_children(self):
        return []


def run_bulk_update(device, channels):
    script = modbus_channel_scripts.update_channels_bulk(device.get_name(), channels)
    project = types.SimpleNamespace(get_children=lambda: [device])
    script_globals = {"scriptengine": types.SimpleNamespace(projects=types.SimpleNamespace(primary=project))}
    script_locals = {}
    # Separate globals and locals, as older persistent sessions run unwrapped handler scripts.
    exec(script, script_globals, script_locals)
    return script_locals["result"]


def ph_channel():
    # FC, read offset, read length, write offset, write length, trigger, cycle, error handling
    return FakeChannelParam(0x01100000, "pH Read", ["3", "16#2001", "1", "0", "0", "5", "500", "false"])


def request(**overrides):
    channel = {"name": "pH Read", "accessType": 3, "readOffset": "16#2001", "readLength": 1,
               "writeOffset": "0", "writeLength": "0", "trigger": 5, "cycleTime": 2000, "errorHandling": "false"}
    channel.update(overrides)
    return [channel]


class BulkUpdateTests(unittest.TestCase):
    def test_cycle_time_change_is_applied(self):
        param = ph_channel()
        result = run_bulk_update(FakeDevice("ATI_6106_44", [param]), request())
        self.assertTrue(result["success"], result)
        self.assertEqual(param[6].value, "2000")
        self.assertEqual(param[1].value, "16#2001")

    def test_offset_change_is_refused_and_nothing_changes(self):
        param = ph_channel()
        result = run_bulk_update(FakeDevice("ATI_6105_43", [param]), request(readOffset="16#0001"))
        self.assertFalse(result["success"])
        self.assertEqual([c["field"] for c in result["shapeChanges"]], ["readOffset"])
        self.assertEqual(param[1].value, "16#2001")
        self.assertEqual(param[6].value, "500")

    def test_function_code_change_is_refused(self):
        result = run_bulk_update(FakeDevice("ATI_6106_44", [ph_channel()]), request(accessType=4))
        self.assertFalse(result["success"])
        self.assertEqual([c["field"] for c in result["shapeChanges"]], ["accessType"])


class SingleUpdateTests(unittest.TestCase):
    class Handler(ModbusChannelMixin):
        def _exec(self, script, timeout=None):
            raise AssertionError("a refused update must not reach the IDE")

    def test_shape_fields_are_refused(self):
        for key, value in (("readOffset", "16#2001"), ("writeOffset", "16#0010"), ("accessType", 4),
                           ("readLength", 3)):
            result = self.Handler().update_channel({key: value}, {"device": "D", "channel": "pH Read"})
            self.assertFalse(result["success"], key)
            self.assertIn("needs the channel rebuilt", result["error"])


if __name__ == "__main__":
    unittest.main()
