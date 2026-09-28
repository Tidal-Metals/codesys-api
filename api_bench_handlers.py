"""Bench endpoints for remote agents: snapshot, reservations, jobs, inventory, online PLC.

Routes are a table like the Modbus router's. Changes to shared equipment
check reservations via the ``X-Bench-Reservation`` header; reads never do.
"""

from __future__ import annotations

import re
import threading
import time

import bench_inventory
import modbus_simulator_control
import script_plc_online_generators as online
from script_plc_online_generators import application_path, as_bool
from bench_inventory import InventoryError
from bench_jobs import MAX_JOB_TIMEOUT_SECONDS, JobError
from bench_reservations import ReservationError, normalize_adapter_serial
from bench_services import read_session_status
from script_executor import clamp_timeout, wrap_shared_namespace

RESERVATION_HEADER = "X-Bench-Reservation"
SYNC_ONLINE_TIMEOUT_SECONDS = 60
HEARTBEAT_STALE_SECONDS = 10
ONLINE_ERROR_STATUS = {"not_logged_in": 409, "no_project": 409, "prepared_values_pending": 409,
                       "state_not_reached": 409, "readback_mismatch": 409,
                       "bad_expression": 400, "unsupported_session": 501}

ROUTES = [
    ("GET", r"api/v1/bench$", "bench_snapshot"),
    ("GET", r"api/v1/bench/reservations$", "reservations_list"),
    ("POST", r"api/v1/bench/reservations$", "reservations_create"),
    ("PUT", r"api/v1/bench/reservations/(?P<rid>[0-9a-f]+)$", "reservations_renew"),
    ("DELETE", r"api/v1/bench/reservations/(?P<rid>[0-9a-f]+)$", "reservations_release"),
    ("GET", r"api/v1/jobs$", "jobs_list"),
    ("POST", r"api/v1/jobs$", "jobs_create"),
    ("GET", r"api/v1/jobs/(?P<jid>[0-9a-f]+)$", "jobs_get"),
    ("DELETE", r"api/v1/jobs/(?P<jid>[0-9a-f]+)$", "jobs_cancel"),
    ("GET", r"api/v1/inventory/adapters$", "adapters_list"),
    ("PUT", r"api/v1/inventory/adapters/(?P<serial>[^/]+)$", "adapters_register"),
    ("GET", r"api/v1/inventory/gateways$", "gateways_list"),
    ("PUT", r"api/v1/inventory/gateways/(?P<mac>[^/]+)$", "gateways_register"),
    ("POST", r"api/v1/plc/online/read$", "plc_online_read"),
    ("POST", r"api/v1/plc/online/write$", "plc_online_write"),
    ("POST", r"api/v1/plc/online/watch$", "plc_online_watch"),
    ("GET", r"api/v1/plc/online/diagnostics$", "plc_online_diagnostics"),
    ("POST", r"api/v1/plc/app/(?P<command>start|stop)$", "plc_app_control"),
]
_COMPILED = [(method, re.compile(pattern), name) for method, pattern, name in ROUTES]


def match_bench_route(method, path):
    for route_method, pattern, name in _COMPILED:
        if route_method == method:
            match = pattern.match(path)
            if match:
                return name, match.groupdict()
    return None, None


def simulator_scopes(buses):
    """Reservation scopes an apply touches: each bus's adapter by USB serial."""
    port_serials = {p["port"].upper(): p["usbSerial"] for p in bench_inventory.list_serial_ports()}
    scopes = []
    for bus in buses if isinstance(buses, list) else []:
        if not isinstance(bus, dict):
            continue
        serial = bus.get("usbSerial") or port_serials.get(str(bus.get("pcPort", bus.get("port", ""))).upper())
        if serial:
            scopes.append("adapter:" + normalize_adapter_serial(serial))
    return scopes


class BenchHandlersMixin:
    """Mixed into CodesysApiHandler; needs self.bench, self.script_executor, self.headers."""

    def try_bench_route(self, method, path, params):
        name, groups = match_bench_route(method, path)
        if name is None:
            return False
        try:
            body, status = getattr(self, "bench_" + name)(params, groups)
        except (ReservationError, JobError, InventoryError) as exc:
            body = {"success": False, "error": str(exc)}
            if getattr(exc, "conflicts", None):
                body["conflicts"] = exc.conflicts
            status = exc.status
        except ValueError as exc:
            body, status = {"success": False, "error": str(exc)}, 400
        self.send_json_response(body, status)
        return True

    # --- reservations -------------------------------------------------------

    def reservation_token(self):
        return self.headers.get(RESERVATION_HEADER)

    def require_scopes(self, scopes):
        """Raise ReservationError(423) if someone else holds any of these scopes."""
        if scopes:
            self.bench.reservations.check(scopes, self.reservation_token())

    def bench_reservations_list(self, params, groups):
        return {"success": True, "reservations": self.bench.reservations.list()}, 200

    def bench_reservations_create(self, params, groups):
        reservation = self.bench.reservations.create(
            params.get("holder"), params.get("purpose", ""), params.get("scope"), params.get("ttlSeconds"))
        return {"success": True, "reservation": reservation,
                "usage": f"Send header {RESERVATION_HEADER}: <token> on changes; renew with PUT before expiresAt"}, 201

    def bench_reservations_renew(self, params, groups):
        reservation = self.bench.reservations.renew(groups["rid"], self.reservation_token(), params.get("ttlSeconds"))
        return {"success": True, "reservation": reservation}, 200

    def bench_reservations_release(self, params, groups):
        reservation = self.bench.reservations.release(groups["rid"], self.reservation_token())
        return {"success": True, "released": reservation}, 200

    # --- jobs ---------------------------------------------------------------

    def submit_script_job(self, kind, label, script, timeout_seconds, holder=None, require_at_run=None,
                          token=None):
        """Queue a script. require_at_run lists scopes re-checked against token when the job
        starts, so a queued or delayed PLC change can't act on equipment someone else has
        reserved in the meantime."""
        executor = self.script_executor
        reservations = self.bench.reservations
        wrapped = wrap_shared_namespace(script)
        token = self.reservation_token() if token is None else token
        if holder is None:
            holder = reservations.holder_for_token(token)

        def run(job):
            if require_at_run:
                try:
                    reservations.check(require_at_run, token)
                except ReservationError as exc:
                    return {"success": False, "code": "reserved", "error": "Skipped: " + str(exc),
                            "conflicts": exc.conflicts}
            return executor.execute_script(wrapped, timeout=job["timeoutSeconds"], request_id=job["requestId"])

        return self.bench.jobs.submit(kind, label, run, timeout_seconds, holder=holder)

    def bench_jobs_create(self, params, groups):
        kind = params.get("kind", "script")
        if kind != "script":
            raise ValueError("kind must be 'script' (PLC watch jobs: POST /api/v1/plc/online/watch)")
        script = params.get("script")
        if not isinstance(script, str) or not script.strip():
            raise ValueError("script is required")
        timeout = clamp_timeout(params.get("timeoutSeconds"), 600, MAX_JOB_TIMEOUT_SECONDS)
        job = self.submit_script_job("script", str(params.get("label", ""))[:200], script, timeout)
        return {"success": True, "job": job, "poll": "/api/v1/jobs/" + job["id"]}, 202

    def bench_jobs_list(self, params, groups):
        try:
            limit = max(1, min(int(params.get("limit", 50)), 200))
        except (TypeError, ValueError):
            raise ValueError("limit must be an integer")
        return {"success": True, "jobs": self.bench.jobs.list(limit), "counts": self.bench.jobs.counts()}, 200

    def bench_jobs_get(self, params, groups):
        return {"success": True, "job": self.bench.jobs.get(groups["jid"])}, 200

    def bench_jobs_cancel(self, params, groups):
        return {"success": True, "job": self.bench.jobs.cancel(groups["jid"])}, 200

    # --- inventory ----------------------------------------------------------

    def bench_adapters_list(self, params, groups):
        return {"success": True, "adapters": bench_inventory.describe_adapters()}, 200

    def bench_adapters_register(self, params, groups):
        return {"success": True, "adapter": bench_inventory.register("adapters", groups["serial"], params)}, 200

    def bench_gateways_list(self, params, groups):
        found = bench_inventory.describe_gateways(refresh=as_bool(params.get("refresh", False)),
                                                  probe_ports=as_bool(params.get("probe", False)))
        return dict(found, success=True), 200

    def bench_gateways_register(self, params, groups):
        return {"success": True, "gateway": bench_inventory.register("gateways", groups["mac"], params)}, 200

    # --- snapshot -----------------------------------------------------------

    def bench_bench_snapshot(self, params, groups):
        session = read_session_status()
        simulators = modbus_simulator_control.get_simulator_status().get("simulators", [])
        adapters = bench_inventory.describe_adapters(owners=simulators)
        gateways = bench_inventory.describe_gateways(refresh=as_bool(params.get("refresh", False)))["gateways"]
        warnings = [f"{a['usbSerial']} ({a.get('port')}): {a['warning']}" for a in adapters if a.get("warning")]
        warnings += [f"{g.get('model')} {g['mac']}: {g['warning']}" for g in gateways if g.get("warning")]
        for row in simulators:
            if row.get("backend") == "go" and row.get("running") and row.get("heartbeatStale"):
                warnings.append(f"Simulator {row['port']} is running but its heartbeat is stale")
        age = session.get("fileAgeSeconds")
        if age is None or age > HEARTBEAT_STALE_SECONDS:
            warnings.append(f"IDE session heartbeat is {age} s old; the session may be stopped or blocked")
        snapshot = {
            "success": True,
            "time": time.time(),
            "session": {k: session.get(k) for k in ("state", "timestamp", "fileAgeSeconds", "project", "request", "progress")},
            "reservations": self.bench.reservations.list(),
            "jobs": {"counts": self.bench.jobs.counts(), "recent": self.bench.jobs.list(5)},
            "simulators": [_simulator_summary(row) for row in simulators],
            "adapters": adapters,
            "gateways": gateways,
            "warnings": warnings,
        }
        return snapshot, 200

    # --- online PLC ---------------------------------------------------------

    def run_online_script(self, script, timeout):
        result = self.script_executor.execute_script(wrap_shared_namespace(script), timeout=timeout)
        if result.get("timeout"):
            return result, 504
        if not result.get("success"):
            return result, ONLINE_ERROR_STATUS.get(result.get("code"), 500 if "code" not in result else 400)
        return result, 200

    def bench_plc_online_read(self, params, groups):
        if as_bool(params.get("login", False)):
            self.require_scopes(["plc"])
        timeout = clamp_timeout(params.get("timeout"), 20, SYNC_ONLINE_TIMEOUT_SECONDS)
        return self.run_online_script(online.generate_plc_online_read_script(params), timeout)

    def bench_plc_online_write(self, params, groups):
        self.require_scopes(["plc"])
        restore_after = params.get("restoreAfterSeconds")
        timeout = clamp_timeout(params.get("timeout"), 20, SYNC_ONLINE_TIMEOUT_SECONDS)
        result, status = self.run_online_script(online.generate_plc_online_write_script(params), timeout)
        if result.get("written") and restore_after is not None:
            delay = clamp_timeout(restore_after, 60, MAX_JOB_TIMEOUT_SECONDS)
            restore = dict((k, v) for k, v in result.get("previous", {}).items() if v is not None)
            result["restoreScheduled"] = self.schedule_restore(params, restore, delay)
        return result, status

    def schedule_restore(self, params, previous, delay):
        """Queue a job that writes the previous values back after delay seconds."""
        restore_params = {"values": previous, "applicationPath": application_path(params), "force": True}
        script = online.generate_plc_online_write_script(restore_params)
        submit = self.submit_script_job
        token = self.reservation_token() or ""

        def enqueue():
            submit("plc-restore", "Restore " + ", ".join(sorted(previous)), script, 60,
                   require_at_run=["plc"], token=token)

        timer = threading.Timer(delay, enqueue)
        timer.daemon = True
        timer.start()
        return {"afterSeconds": delay, "values": previous, "restoresAt": time.time() + delay}

    def bench_plc_online_watch(self, params, groups):
        login = as_bool(params.get("login", False))
        if login:
            self.require_scopes(["plc"])
        duration = clamp_timeout(params.get("durationSeconds"), 10, MAX_JOB_TIMEOUT_SECONDS - 60)
        params = dict(params, durationSeconds=duration)
        script = online.generate_plc_online_watch_script(params)
        label = "Watch {0} for {1:g} s".format(", ".join(params["names"][:5]), duration)
        job = self.submit_script_job("plc-watch", label, script, duration + 60,
                                     require_at_run=["plc"] if login else None)
        return {"success": True, "job": job, "poll": "/api/v1/jobs/" + job["id"]}, 202

    def bench_plc_online_diagnostics(self, params, groups):
        if as_bool(params.get("login", False)):
            self.require_scopes(["plc"])
        if isinstance(params.get("names"), str):
            params = dict(params, names=[n for n in params["names"].split(",") if n])
        timeout = clamp_timeout(params.get("timeout"), 30, SYNC_ONLINE_TIMEOUT_SECONDS)
        return self.run_online_script(online.generate_plc_online_diagnostics_script(params), timeout)

    def bench_plc_app_control(self, params, groups):
        self.require_scopes(["plc"])
        script = online.generate_plc_app_control_script(params, groups["command"])
        return self.run_online_script(script, clamp_timeout(params.get("timeout"), 30, SYNC_ONLINE_TIMEOUT_SECONDS))



def _simulator_summary(row):
    worker = row.get("worker") or {}
    return {
        "port": row.get("port"),
        "backend": row.get("backend", "python"),
        "usbSerial": row.get("usbSerial"),
        "baudrate": row.get("baudrate"),
        "units": [d.get("unit") for d in row.get("devices", [])],
        "running": row.get("running"),
        "portOpen": row.get("portOpen"),
        "heartbeatAgeSeconds": row.get("heartbeatAgeSeconds"),
        "lastRxAt": worker.get("lastRxAt"),
        "requests": (worker.get("framer") or {}).get("requests"),
    }

