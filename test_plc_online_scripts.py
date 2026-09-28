"""Run the generated online-PLC scripts against a simulated CODESYS online application."""

import sys
import time
import types
import unittest
from unittest import mock

import script_plc_online_generators as gen
from script_executor import wrap_shared_namespace


class FakeOnlineApp:
    def __init__(self, values, logged_in=True, state="run", reach_state=True):
        self.values = dict(values)
        self.prepared = {}
        self.is_logged_in = logged_in
        self.application_state = state
        self.operation_state = "normal"
        self.reach_state = reach_state
        self.commands = []

    def read_value(self, name):
        if name not in self.values:
            raise Exception("Unknown expression " + name)
        return self.values[name]

    def get_prepared_expressions(self):
        return list(self.prepared)

    def set_prepared_value(self, name, value):
        if value in (None, ""):
            self.prepared.pop(name, None)
        else:
            self.prepared[name] = value

    def write_prepared_values(self):
        self.values.update(self.prepared)
        self.prepared = {}

    def start(self):
        self.commands.append("start")
        if self.reach_state:
            self.application_state = "run"

    def stop(self):
        self.commands.append("stop")
        if self.reach_state:
            self.application_state = "stop"


class FakeApplication:
    def get_name(self):
        return "Application"

    def create_boot_application(self):
        pass

    def build(self):
        pass

    def get_children(self):
        return []


class FakeDevice:
    def __init__(self, name, kind, children=()):
        self.name, self.kind, self.children = name, kind, list(children)

    def get_name(self):
        return self.name

    def get_device_identification(self):
        return types.SimpleNamespace(type=self.kind)

    def get_children(self):
        return self.children


class FakeProject:
    def __init__(self, children=None):
        self.children = children

    def get_children(self):
        return self.children if self.children is not None else [FakeApplication()]


class FakeSession:
    def __init__(self, online_app):
        self.online_app = online_app
        self.progress = []

    def ensure_online_application(self, path, login):
        if login:
            self.online_app.is_logged_in = True
        return self.online_app

    def report_progress(self, data):
        self.progress.append(data)


def run_script(script, online_app, project=None):
    scriptengine = types.ModuleType("scriptengine")
    scriptengine.projects = types.SimpleNamespace(primary=project or FakeProject())
    scriptengine.OnlineChangeOption = types.SimpleNamespace(Keep="Keep")
    session = FakeSession(online_app)
    namespace = {"session": session, "json": __import__("json"), "time": time}
    with mock.patch.dict(sys.modules, {"scriptengine": scriptengine}):
        exec(wrap_shared_namespace(script), namespace, namespace)
    return namespace["result"], session


class OnlineScriptTests(unittest.TestCase):
    def test_read_reports_values_and_bad_expressions(self):
        app = FakeOnlineApp({"PLC_PRG.x": "WORD#5"})
        result, _ = run_script(gen.generate_plc_online_read_script({"names": ["PLC_PRG.x", "nope"]}), app)
        self.assertEqual(result["values"], {"PLC_PRG.x": "WORD#5"})
        self.assertIn("nope", result["errors"])
        self.assertFalse(result["success"])

    def test_not_logged_in_without_login_flag(self):
        app = FakeOnlineApp({"a": "1"}, logged_in=False)
        result, _ = run_script(gen.generate_plc_online_read_script({"names": ["a"]}), app)
        self.assertEqual(result["code"], "not_logged_in")
        result, _ = run_script(gen.generate_plc_online_read_script({"names": ["a"], "login": True}), app)
        self.assertTrue(result["success"])

    def test_write_returns_previous_and_confirms(self):
        app = FakeOnlineApp({"Modbus_TCP_Client.xStop": "FALSE"})
        result, _ = run_script(gen.generate_plc_online_write_script({"values": {"Modbus_TCP_Client.xStop": True}}), app)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["previous"], {"Modbus_TCP_Client.xStop": "FALSE"})
        self.assertEqual(app.values["Modbus_TCP_Client.xStop"], "True")

    def test_pending_prepared_values_refused_then_discarded_not_committed(self):
        app = FakeOnlineApp({"Target": "0", "Other": "0"})
        app.prepared["Other"] = "99"
        result, _ = run_script(gen.generate_plc_online_write_script({"values": {"Target": 1}}), app)
        self.assertEqual(result["code"], "prepared_values_pending")
        result, _ = run_script(gen.generate_plc_online_write_script({"values": {"Target": 1}, "force": True}), app)
        self.assertTrue(result["success"])
        self.assertEqual(result["discardedPrepared"], ["Other"])
        self.assertEqual(app.values["Other"], "0", "force must not commit someone else's prepared value")

    def test_write_readback_mismatch_still_reports_previous(self):
        app = FakeOnlineApp({"Latch": "FALSE"})
        app.write_prepared_values = lambda: app.prepared.clear()  # PLC ignores the write
        with mock.patch("time.sleep"):
            result, _ = run_script(gen.generate_plc_online_write_script({"values": {"Latch": "TRUE"}}), app)
        self.assertEqual(result["code"], "readback_mismatch")
        self.assertEqual(result["previous"], {"Latch": "FALSE"})
        self.assertTrue(result["written"])

    def test_watch_summarizes_and_never_sleeps_past_duration(self):
        app = FakeOnlineApp({"PLC_PRG.TenErrorCycles[5]": "UDINT#10"})
        started = time.time()
        result, session = run_script(gen.generate_plc_online_watch_script(
            {"names": ["PLC_PRG.TenErrorCycles[5]"], "intervalMs": 120000, "durationSeconds": 0.3}), app)
        self.assertLess(time.time() - started, 5, "a long interval must not outlast durationSeconds")
        summary = result["summary"]["PLC_PRG.TenErrorCycles[5]"]
        self.assertEqual((summary["first"], summary["delta"]), ("UDINT#10", 0))
        self.assertTrue(session.progress)

    def test_string_false_does_not_log_in(self):
        app = FakeOnlineApp({"a": "1"}, logged_in=False)
        result, _ = run_script(gen.generate_plc_online_read_script({"names": ["a"], "login": "false"}), app)
        self.assertEqual(result["code"], "not_logged_in")
        self.assertFalse(app.is_logged_in)

    def test_native_timeout_on_start_reports_state_not_reached(self):
        app = FakeOnlineApp({}, state="stop", reach_state=False)

        def timing_out():
            raise Exception("TimeoutException: state not reached")

        app.start = timing_out
        with mock.patch("time.sleep"):
            result, _ = run_script(gen.generate_plc_app_control_script({}, "start"), app)
        self.assertEqual(result["code"], "state_not_reached")
        self.assertIn("TimeoutException", result["error"])

    def test_diagnostics_flags_stopped_app_and_missing_connections(self):
        master = FakeDevice("Modbus_TCP_Client", 88, [FakeDevice("Unit1", 89), FakeDevice("Unit2", 89)])
        project = FakeProject([FakeApplication(), master])
        app = FakeOnlineApp({"Modbus_TCP_Client.uiConnectedSlaves": "UINT#0", "Unit1.xError": "FALSE",
                             "Unit2.xError": "FALSE"}, state="stop")
        result, _ = run_script(gen.generate_plc_online_diagnostics_script({}), app, project)
        self.assertFalse(result["healthy"])
        self.assertEqual(result["unhealthyDevices"], [])
        self.assertTrue(any("stop" in w for w in result["warnings"]))
        self.assertTrue(any("0 of 2 slaves" in w for w in result["warnings"]))
        app.application_state, app.values["Modbus_TCP_Client.uiConnectedSlaves"] = "run", "UINT#2"
        result, _ = run_script(gen.generate_plc_online_diagnostics_script({}), app, project)
        self.assertTrue(result["healthy"], result["warnings"])

    def test_start_fails_when_state_never_changes(self):
        app = FakeOnlineApp({}, state="stop", reach_state=False)
        with mock.patch("time.sleep"):
            result, _ = run_script(gen.generate_plc_app_control_script({}, "start"), app)
        self.assertEqual(result["code"], "state_not_reached")
        app = FakeOnlineApp({}, state="stop")
        result, _ = run_script(gen.generate_plc_app_control_script({}, "start"), app)
        self.assertTrue(result["success"])
        self.assertEqual(app.commands, ["start"])


if __name__ == "__main__":
    unittest.main()
