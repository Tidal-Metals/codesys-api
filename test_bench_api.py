"""Phase 1 bench API: reservations, jobs, inventory, routing and the live HTTP surface.

Runs without CODESYS: a fake executor stands in for the IDE session.
"""

import json
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from unittest import mock

import api_bench_handlers
import bench_inventory
import bench_services
from auth import ApiKeyManager
from bench_jobs import CANCELLED, FAILED, JobError, JobManager, SUCCEEDED
from bench_reservations import ReservationError, ReservationManager, normalize_adapter_serial
from bench_services import BenchServices
from HTTP_SERVER import create_handler, create_http_server

ARP_SAMPLE = """
Interface: 192.168.50.108 --- 0x7
  Internet Address      Physical Address      Type
  192.168.50.1          aa-bb-cc-dd-ee-01     dynamic
  192.168.50.153        b0-cb-d8-4e-88-bb     dynamic
  192.168.50.255        ff-ff-ff-ff-ff-ff     static
"""
REGISTRY = {
    "adapters": {"BG01GGR2": {"label": "NE2 bus", "wiredTo": "B0-CB-D8-4E-88-BB"}},
    "gateways": {"B0-CB-D8-4E-88-BB": {"model": "NE2-D11P", "expectedIp": "192.168.50.151", "ports": [502, 1502]},
                 "0C-3D-5E-88-FD-2A": {"model": "NA111-E", "expectedIp": "192.168.50.67"}},
}


def wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class ReservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1000.0]
        self.manager = ReservationManager(os.path.join(self.tmp.name, "r.json"), clock=lambda: self.now[0])

    def tearDown(self):
        self.tmp.cleanup()

    def test_holder_passes_others_blocked_unreserved_open(self):
        mine = self.manager.create("agent-a", "soak", ["plc", "adapter:BG01GGR2A"], 60)
        self.assertEqual(mine["scope"], ["adapter:BG01GGR2", "plc"])
        self.manager.check(["plc"], mine["token"])
        self.manager.check(["adapter:BG00XX03"], None)
        with self.assertRaises(ReservationError) as blocked:
            self.manager.check(["plc"], "br_wrong")
        self.assertEqual(blocked.exception.status, 423)
        self.assertEqual(blocked.exception.conflicts[0]["holder"], "agent-a")
        self.assertNotIn("tokenHash", blocked.exception.conflicts[0])

    def test_overlap_rejected_and_bench_claims_everything(self):
        self.manager.create("agent-a", "", ["adapter:BG01GGR2"], 60)
        with self.assertRaises(ReservationError) as conflict:
            self.manager.create("agent-b", "", ["bench"], 60)
        self.assertEqual(conflict.exception.status, 409)

    def test_expiry_renew_release_and_token_checks(self):
        mine = self.manager.create("agent-a", "", ["plc"], 60)
        with self.assertRaises(ReservationError) as wrong:
            self.manager.renew(mine["id"], "br_wrong", 60)
        self.assertEqual(wrong.exception.status, 403)
        self.now[0] += 50
        self.manager.renew(mine["id"], mine["token"], 60)
        self.now[0] += 50
        self.assertEqual(len(self.manager.list()), 1)
        self.manager.release(mine["id"], mine["token"])
        self.assertEqual(self.manager.list(), [])
        again = self.manager.create("agent-b", "", ["plc"], 10)
        self.now[0] += 11
        self.manager.check(["plc"], None)  # expired
        self.assertEqual(self.manager.holder_for_token(again["token"]), "")

    def test_invalid_input(self):
        for scopes in ([], ["everything"], ["adapter:"], "plc"):
            with self.assertRaises(ReservationError):
                self.manager.create("a", "", scopes, 60)
        with self.assertRaises(ReservationError):
            self.manager.create("a", "", ["plc"], 5)

    def test_ftdi_suffix_normalized(self):
        self.assertEqual(normalize_adapter_serial("BG01GGR2A"), "BG01GGR2")
        self.assertEqual(normalize_adapter_serial("bg01ggr2"), "BG01GGR2")


class JobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.status = {}
        self.jobs = JobManager(self.tmp.name, lambda: self.status)

    def tearDown(self):
        self.tmp.cleanup()

    def test_fifo_results_and_failures(self):
        order, gate = [], threading.Event()

        def slow(job):
            gate.wait(5)
            order.append("first")
            return {"success": True, "value": 1}

        first = self.jobs.submit("script", "first", slow, 10)
        second = self.jobs.submit("script", "second", lambda job: order.append("second") or {"success": False, "error": "boom"}, 10)
        crashing = self.jobs.submit("script", "crash", lambda job: 1 / 0, 10)
        self.assertEqual(self.jobs.cancel(second["id"])["state"], CANCELLED)
        with self.assertRaises(JobError) as running:
            wait_for(lambda: self.jobs.get(first["id"])["state"] == "running")
            self.jobs.cancel(first["id"])
        self.assertEqual(running.exception.status, 409)
        gate.set()
        self.assertTrue(wait_for(lambda: self.jobs.get(crashing["id"])["state"] == FAILED))
        self.assertEqual(self.jobs.get(first["id"])["state"], SUCCEEDED)
        self.assertEqual(self.jobs.get(first["id"])["result"]["value"], 1)
        self.assertIn("ZeroDivisionError", self.jobs.get(crashing["id"])["error"])
        self.assertEqual(order, ["first"])

    def test_progress_exposed_while_running(self):
        gate = threading.Event()
        job = self.jobs.submit("plc-watch", "w", lambda j: gate.wait(5) and {"success": True}, 10)
        self.assertTrue(wait_for(lambda: self.jobs.get(job["id"])["state"] == "running"))
        self.status.update(request={"id": job["requestId"]}, progress={"samples": 7}, timestamp=1)
        self.assertEqual(self.jobs.get(job["id"])["progress"], {"samples": 7})
        gate.set()
        self.assertTrue(wait_for(lambda: self.jobs.get(job["id"])["state"] == SUCCEEDED))

    def test_unfinished_job_from_previous_process_reported_failed(self):
        gate = threading.Event()
        job = self.jobs.submit("script", "orphan", lambda j: gate.wait(5) and {"success": True}, 10)
        self.assertTrue(wait_for(lambda: self.jobs.get(job["id"])["state"] == "running"))
        restarted = JobManager(self.tmp.name)
        self.assertEqual(restarted.get(job["id"])["state"], FAILED)
        gate.set()
        self.assertTrue(wait_for(lambda: self.jobs.get(job["id"])["state"] == SUCCEEDED))
        with self.assertRaises(JobError):
            restarted.get("../../etc")


class InventoryTests(unittest.TestCase):
    def test_parse_arp_skips_broadcast(self):
        table = bench_inventory.parse_arp(ARP_SAMPLE)
        self.assertEqual(table["B0-CB-D8-4E-88-BB"], "192.168.50.153")
        self.assertNotIn("FF-FF-FF-FF-FF-FF", table)

    def test_gateway_address_change_and_absence_flagged(self):
        found = bench_inventory.describe_gateways(arp=bench_inventory.parse_arp(ARP_SAMPLE), registry=REGISTRY,
                                                  probe_ports=True, probe=lambda ip, port: port == 502)
        rows = {g["model"]: g for g in found["gateways"]}
        self.assertIn("192.168.50.151", rows["NE2-D11P"]["warning"])
        self.assertEqual(rows["NE2-D11P"]["reachablePorts"], [502])
        self.assertFalse(rows["NA111-E"]["found"])

    def test_adapters_by_serial_with_owner_and_unregistered_warning(self):
        ports = [{"port": "COM18", "usbSerial": "BG01GGR2"}, {"port": "COM12", "usbSerial": "BG041BD0"}]
        owners = [{"port": "COM18", "usbSerial": "BG01GGR2", "backend": "go", "running": True, "portOpen": True,
                   "devices": [{"unit": 1}], "worker": {"lastRxAt": "t"}}]
        registry = {"adapters": dict(REGISTRY["adapters"], BG00XX03={"label": "absent"}), "gateways": {}}
        rows = {a["usbSerial"]: a for a in bench_inventory.describe_adapters(ports, owners, registry)}
        self.assertEqual(rows["BG01GGR2"]["owner"]["simulatorPort"], "COM18")
        self.assertIn("Unregistered", rows["BG041BD0"]["warning"])
        self.assertFalse(rows["BG00XX03"]["present"])

    def test_register_validates_and_persists_locally(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bench_inventory, "LOCAL_PATH", os.path.join(tmp, "inv.json")), \
                mock.patch.object(bench_inventory, "SEED_PATH", os.path.join(tmp, "none.json")):
            saved = bench_inventory.register("adapters", "BG041BD0A", {"label": "spare", "wiredTo": "b0:cb:d8:4e:88:bb"})
            self.assertEqual(saved["wiredTo"], "B0-CB-D8-4E-88-BB")
            with self.assertRaises(bench_inventory.InventoryError):
                bench_inventory.register("adapters", "X", {"colour": "red"})
            with self.assertRaises(bench_inventory.InventoryError):
                bench_inventory.register("gateways", "not-a-mac", {})


class RoutingTests(unittest.TestCase):
    def test_routes(self):
        cases = {("GET", "api/v1/bench"): "bench_snapshot",
                 ("PUT", "api/v1/bench/reservations/abc123"): "reservations_renew",
                 ("GET", "api/v1/jobs/0123abcd"): "jobs_get",
                 ("PUT", "api/v1/inventory/gateways/B0-CB-D8-4E-88-BB"): "gateways_register",
                 ("POST", "api/v1/plc/app/stop"): "plc_app_control"}
        for (method, path), name in cases.items():
            self.assertEqual(api_bench_handlers.match_bench_route(method, path)[0], name)
        self.assertIsNone(api_bench_handlers.match_bench_route("POST", "api/v1/plc/app/reboot")[0])

    def test_simulator_scopes_resolve_port_to_serial(self):
        with mock.patch.object(bench_inventory, "list_serial_ports",
                               return_value=[{"port": "COM18", "usbSerial": "BG01GGR2"}]):
            scopes = api_bench_handlers.simulator_scopes([{"pcPort": "com18"}, {"usbSerial": "BG00XX03A"}, {"pcPort": "COM99"}])
        self.assertEqual(scopes, ["adapter:BG01GGR2", "adapter:BG00XX03"])


class FakeExecutor:
    """Records scripts; answers online scripts as 'not logged in' and others with success."""

    def __init__(self):
        self.calls = []

    def execute_script(self, script, timeout=60, request_id=None):
        source = _decoded(script)
        self.calls.append({"timeout": timeout, "request_id": request_id, "script": script, "source": source})
        if "def matches(" in source:  # write script: values written, readback failed
            return {"success": False, "code": "readback_mismatch", "written": {"X": "TRUE"},
                    "previous": {"X": "FALSE"}}
        if "open_online" in source:
            return {"success": False, "code": "not_logged_in", "error": "Not logged in"}
        return {"success": True, "ran": True}


def _decoded(wrapped):
    import base64
    import re
    match = re.search(r"b64decode\('([^']+)'\)", wrapped)
    return base64.b64decode(match.group(1)).decode("utf-8") if match else wrapped


class LiveServerTests(unittest.TestCase):
    """Real threaded HTTP server, real handler stack, fake IDE."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        keys = os.path.join(cls.tmp.name, "keys.json")
        with open(keys, "w") as handle:
            json.dump({"k1": {"name": "test"}}, handle)
        cls.status_path = os.path.join(cls.tmp.name, "session_status.json")
        cls.status_patch = mock.patch.object(bench_services, "STATUS_FILE", cls.status_path)
        cls.status_patch.start()
        cls.executor = FakeExecutor()
        bench = BenchServices(JobManager(os.path.join(cls.tmp.name, "jobs"), bench_services.read_session_status),
                              ReservationManager(os.path.join(cls.tmp.name, "res.json")))
        process_manager = mock.Mock()
        process_manager.is_running.return_value = False
        handler = create_handler(process_manager, cls.executor, mock.Mock(), ApiKeyManager(keys), bench)
        cls.server = create_http_server(("127.0.0.1", 0), handler)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.status_patch.stop()
        cls.tmp.cleanup()

    def call(self, method, path, body=None, token=None):
        request = urllib.request.Request(self.base + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None)
        request.add_header("Authorization", "ApiKey k1")
        if token:
            request.add_header("X-Bench-Reservation", token)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def test_reservation_blocks_other_callers(self):
        status, created = self.call("POST", "/api/v1/bench/reservations", {"holder": "a", "scope": ["plc"], "ttlSeconds": 60})
        self.assertEqual(status, 201)
        token = created["reservation"]["token"]
        status, body = self.call("POST", "/api/v1/plc/login", {})
        self.assertEqual(status, 423)
        self.assertEqual(body["conflicts"][0]["holder"], "a")
        status, _ = self.call("POST", "/api/v1/plc/online/write", {"values": {"X": 1}}, token="br_other")
        self.assertEqual(status, 423)
        status, _ = self.call("DELETE", "/api/v1/bench/reservations/" + created["reservation"]["id"], token=token)
        self.assertEqual(status, 200)

    def test_script_job_runs_wrapped_with_timeout(self):
        status, body = self.call("POST", "/api/v1/jobs", {"script": "def f():\n    return 1\nresult = {'success': True}\n",
                                                          "timeoutSeconds": 900, "label": "t"})
        self.assertEqual(status, 202)
        job_id = body["job"]["id"]
        self.assertTrue(wait_for(lambda: self.call("GET", "/api/v1/jobs/" + job_id)[1]["job"]["state"] == SUCCEEDED))
        call = [c for c in self.executor.calls if c["request_id"] == body["job"]["requestId"]][0]
        self.assertEqual(call["timeout"], 900)
        self.assertIn("_scope", call["script"])

    def test_online_errors_map_to_http_status(self):
        status, body = self.call("POST", "/api/v1/plc/online/read", {"names": ["PLC_PRG.x"]})
        self.assertEqual((status, body["code"]), (409, "not_logged_in"))
        status, _ = self.call("POST", "/api/v1/plc/online/read", {"names": []})
        self.assertEqual(status, 400)

    def test_watch_is_a_job(self):
        status, body = self.call("POST", "/api/v1/plc/online/watch", {"names": ["a"], "durationSeconds": 5})
        self.assertEqual(status, 202)
        self.assertEqual(body["job"]["kind"], "plc-watch")
        self.assertEqual(body["job"]["timeoutSeconds"], 65)

    def restore_jobs(self):
        return [j for j in self.call("GET", "/api/v1/jobs")[1]["jobs"] if j["kind"] == "plc-restore"]

    def test_restore_scheduled_after_readback_mismatch_and_runs_when_unreserved(self):
        before = len(self.restore_jobs())
        status, body = self.call("POST", "/api/v1/plc/online/write", {"values": {"X": "TRUE"}, "restoreAfterSeconds": 1})
        self.assertEqual((status, body["code"]), (409, "readback_mismatch"))
        self.assertEqual(body["restoreScheduled"]["values"], {"X": "FALSE"})
        self.assertTrue(wait_for(lambda: len(self.restore_jobs()) > before))
        job = self.restore_jobs()[0]
        self.assertTrue(wait_for(lambda: self.call("GET", "/api/v1/jobs/" + job["id"])[1]["job"]["state"] != "queued"))
        detail = self.call("GET", "/api/v1/jobs/" + job["id"])[1]["job"]
        self.assertNotEqual((detail.get("result") or {}).get("code"), "reserved")

    def test_restore_skipped_if_someone_else_reserves_the_plc_meanwhile(self):
        existing = {j["id"] for j in self.restore_jobs()}
        status, body = self.call("POST", "/api/v1/plc/online/write", {"values": {"X": "TRUE"}, "restoreAfterSeconds": 1})
        self.assertIn("restoreScheduled", body)
        _, other = self.call("POST", "/api/v1/bench/reservations", {"holder": "b", "scope": ["plc"], "ttlSeconds": 60})
        try:
            new_jobs = lambda: [j for j in self.restore_jobs() if j["id"] not in existing and j["state"] == "failed"]
            self.assertTrue(wait_for(lambda: new_jobs(), timeout=8))
            detail = self.call("GET", "/api/v1/jobs/" + new_jobs()[0]["id"])[1]["job"]
            self.assertEqual(detail["result"]["code"], "reserved")
        finally:
            self.call("DELETE", "/api/v1/bench/reservations/" + other["reservation"]["id"],
                      token=other["reservation"]["token"])

    def test_restore_keeps_the_application_alias(self):
        before = {j["id"] for j in self.restore_jobs()}
        self.call("POST", "/api/v1/plc/online/write", {"values": {"X": "TRUE"}, "application": "Second",
                                                        "restoreAfterSeconds": 1})
        self.assertTrue(wait_for(lambda: [j for j in self.restore_jobs() if j["id"] not in before]))
        job = [j for j in self.restore_jobs() if j["id"] not in before][0]
        self.assertTrue(wait_for(lambda: self.call("GET", "/api/v1/jobs/" + job["id"])[1]["job"]["state"] != "queued"))
        request_id = self.call("GET", "/api/v1/jobs/" + job["id"])[1]["job"]["requestId"]
        self.assertTrue(wait_for(lambda: any(c["request_id"] == request_id for c in self.executor.calls)))
        source = [c["source"] for c in self.executor.calls if c["request_id"] == request_id][0]
        self.assertIn('\\"applicationPath\\": \\"Second\\"', source)

    def test_watch_login_needs_the_reservation(self):
        _, held = self.call("POST", "/api/v1/bench/reservations", {"holder": "c", "scope": ["plc"], "ttlSeconds": 60})
        try:
            status, _ = self.call("POST", "/api/v1/plc/online/watch", {"names": ["a"], "login": True})
            self.assertEqual(status, 423)
            status, _ = self.call("GET", "/api/v1/plc/online/diagnostics?login=true")
            self.assertEqual(status, 423)
            status, _ = self.call("POST", "/api/v1/plc/online/read", {"names": ["a"], "login": "false"})
            self.assertEqual(status, 409, "login 'false' must not log in or need the reservation")
            status, _ = self.call("POST", "/api/v1/plc/online/watch", {"names": ["a"], "login": True},
                                  token=held["reservation"]["token"])
            self.assertEqual(status, 202)
        finally:
            self.call("DELETE", "/api/v1/bench/reservations/" + held["reservation"]["id"], token=held["reservation"]["token"])

    def test_busy_session_status_answers_from_heartbeat(self):
        with open(self.status_path, "w") as handle:
            json.dump({"state": "busy", "timestamp": time.time(), "project": "C:/p.project",
                       "request": {"id": "r1"}, "progress": {"samples": 3}}, handle)
        before = len(self.executor.calls)
        status, body = self.call("GET", "/api/v1/session/status")
        self.assertEqual(status, 200)
        self.assertTrue(body["status"]["session"]["busy"])
        self.assertEqual(body["status"]["session"]["progress"], {"samples": 3})
        self.assertEqual(len(self.executor.calls), before, "busy status must not queue a script")
        os.remove(self.status_path)


if __name__ == "__main__":
    unittest.main()
