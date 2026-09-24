"""Process/state helpers for managed Modbus RTU simulator instances.

Two backends serve a bus: the PyModbus script (``backend: "python"``, the
default) and the Go worker ``build/rtu-sim.exe`` (``backend: "go"``). Both
read the same per-port configuration file; only the Go worker uses the bus
settings in it and publishes a status file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Any

from modbus_rtu_slave_sim import normalize_device

try:
    import psutil
except ImportError:  # identity checks degrade to PID-only without psutil
    psutil = None


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIMULATOR_STATE_PATH = os.path.join(SCRIPT_DIR, "modbus_simulator_state.json")
GO_EXECUTABLE = os.path.join(SCRIPT_DIR, "build", "rtu-sim.exe")
PYTHON_SCRIPT = os.path.join(SCRIPT_DIR, "modbus_rtu_slave_sim.py")
WORKER_CONFIG_VERSION = 1
BACKENDS = ("python", "go")
# The installed PyModbus multidrop transport fails above this rate.
PYTHON_MULTIDROP_MAX_BAUD = 38400
# tasklist/taskkill must not flash a console when called from a windowless server.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
GO_OPEN_WAIT_SECONDS = 3.0
HEARTBEAT_STALE_SECONDS = 5.0


def read_state() -> dict[str, Any]:
    if not os.path.exists(SIMULATOR_STATE_PATH):
        return {"simulators": {}}
    try:
        with open(SIMULATOR_STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("simulators"), dict):
            return data
    except Exception:
        pass
    return {"simulators": {}}


def write_state(state: dict[str, Any]) -> None:
    with open(SIMULATOR_STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)


def pid_running(pid: int | None) -> bool:
    if not pid:
        return False

    try:
        pid_value = int(pid)
    except Exception:
        return False

    if psutil is not None:
        return psutil.pid_exists(pid_value)

    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", "PID eq {0}".format(pid_value)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=NO_WINDOW,
            )
            output = result.stdout or ""
            return str(pid_value) in output and "No tasks are running" not in output
        except Exception:
            return False

    try:
        os.kill(pid_value, 0)
        return True
    except Exception:
        return False


def worker_alive(entry: dict[str, Any]) -> bool:
    """True only if the recorded PID is still the worker we launched.

    Windows reuses PIDs, so a bare PID check could match an unrelated process.
    Entries record the process create time and config path; both must match.
    """
    pid = entry.get("pid")
    if not pid_running(pid):
        return False
    if psutil is None:
        return True
    try:
        process = psutil.Process(int(pid))
        created = entry.get("createTime")
        if created is not None and abs(process.create_time() - float(created)) > 1.0:
            return False
        marker = entry.get("manifestPath")
        if marker and marker not in " ".join(process.cmdline()):
            return False
        return True
    except (psutil.Error, ValueError):
        return False


def stop_pid(pid: int | None) -> None:
    if not pid:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=NO_WINDOW,
        )
    except Exception:
        pass


def stop_worker(entry: dict[str, Any]) -> bool:
    """Stop the recorded worker if it is still ours; return whether it was."""
    if not worker_alive(entry):
        return False
    stop_pid(entry.get("pid"))
    return True


def windows_creationflags() -> int:
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def read_worker_status(entry: dict[str, Any]) -> dict[str, Any] | None:
    path = entry.get("statusPath")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def heartbeat_age_seconds(worker: dict[str, Any]) -> float | None:
    heartbeat = worker.get("heartbeatAt")
    if not heartbeat:
        return None
    try:
        stamp = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
    except ValueError:
        return None
    return round(time.time() - stamp.timestamp(), 3)


def describe_entry(port: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Status row: process-alive, port-open and traffic are reported separately."""
    row = dict(entry)
    row["port"] = port
    row["running"] = worker_alive(entry)
    if entry.get("backend") == "go":
        worker = read_worker_status(entry)
        row["worker"] = worker
        row["portOpen"] = bool(worker and worker.get("portOpen"))
        row["heartbeatAgeSeconds"] = heartbeat_age_seconds(worker) if worker else None
        row["heartbeatStale"] = row["heartbeatAgeSeconds"] is None or row["heartbeatAgeSeconds"] > HEARTBEAT_STALE_SECONDS
    return row


def get_simulator_status() -> dict[str, Any]:
    state = read_state()
    simulators = [describe_entry(port, entry) for port, entry in sorted(state.get("simulators", {}).items())]
    return {"success": True, "simulators": simulators}


def normalize_manifest_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_devices: list[dict[str, Any]] = []
    for entry in devices:
        normalized = normalize_device(entry)
        normalized_devices.append(
            {
                "unit": normalized["unit"],
                "name": normalized["name"],
                "coilsMap": normalized["coilsMap"],
                "discreteInputsMap": normalized["discreteInputsMap"],
                "holdingMap": normalized["holdingMap"],
                "inputRegistersMap": normalized["inputRegistersMap"],
                "silent": bool(entry.get("silent", False)),
            }
        )
    return normalized_devices


def validate_bus(bus: Any) -> dict[str, Any]:
    """Return a normalized bus spec or raise ValueError describing the problem."""
    if not isinstance(bus, dict):
        raise ValueError("Each bus entry must be an object")

    port = str(bus.get("pcPort", bus.get("port", ""))).strip()
    if not port:
        raise ValueError("Each bus entry must define pcPort or port")

    backend = str(bus.get("backend", "python")).strip().lower()
    if backend not in BACKENDS:
        raise ValueError(f"Bus {port}: backend must be one of {', '.join(BACKENDS)}")

    devices = bus.get("devices")
    if not isinstance(devices, list) or not devices:
        raise ValueError(f"Bus {port} must contain a non-empty devices list")

    multidrop = bus.get("multidrop", False)
    if not isinstance(multidrop, bool):
        raise ValueError("multidrop must be a boolean")

    try:
        spec = {
            "port": port,
            "backend": backend,
            "usbSerial": str(bus.get("usbSerial", "")).strip(),
            "baudrate": int(bus.get("baudrate", 9600)),
            "multidrop": multidrop,
            "bytesize": int(bus.get("bytesize", 8)),
            "parity": str(bus.get("parity", "N")).upper(),
            "stopbits": int(bus.get("stopbits", 1)),
            "timeout": float(bus.get("timeout", 1.0)),
            "idleGapMs": int(bus.get("idleGapMs", 50)),
            "traceFrames": bool(bus.get("traceFrames", False)),
            "devices": normalize_manifest_devices(devices),
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Bus {port}: {exc}") from exc

    if backend == "python" and multidrop and spec["baudrate"] > PYTHON_MULTIDROP_MAX_BAUD:
        raise ValueError(f"Bus {port}: python multidrop requires baudrate <= {PYTHON_MULTIDROP_MAX_BAUD}; use backend go")
    if backend == "python" and spec["usbSerial"]:
        raise ValueError(f"Bus {port}: usbSerial is only supported by backend go")
    if any(device["silent"] for device in spec["devices"]) and backend != "go":
        raise ValueError(f"Bus {port}: silent devices are only supported by backend go")
    units = [device["unit"] for device in spec["devices"]]
    if len(units) != len(set(units)):
        raise ValueError(f"Bus {port}: duplicate unit IDs {sorted(u for u in set(units) if units.count(u) > 1)}")
    return spec


def validate_request(buses: list[Any], existing: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate every bus before any worker changes; raise ValueError on the first problem."""
    specs = [validate_bus(bus) for bus in buses]
    ports = [spec["port"] for spec in specs]
    if len(ports) != len(set(ports)):
        raise ValueError("Each port may appear only once per request")
    if not os.path.exists(GO_EXECUTABLE) and any(spec["backend"] == "go" for spec in specs):
        raise ValueError(f"Go backend requested but {GO_EXECUTABLE} is missing; run tools/modbus-rtu-sim/build.ps1")

    # One owner per physical adapter, including workers this request leaves alone.
    owners: dict[str, str] = {}
    for port, entry in existing.items():
        if entry.get("usbSerial") and port not in ports and worker_alive(entry):
            owners[entry["usbSerial"].upper()] = port
    for spec in specs:
        serial_number = spec["usbSerial"].upper()
        if serial_number and owners.setdefault(serial_number, spec["port"]) != spec["port"]:
            raise ValueError(f"USB adapter {spec['usbSerial']} is already owned by {owners[serial_number]}")
    return specs


def worker_paths(port: str) -> dict[str, str]:
    return {
        "manifestPath": os.path.join(SCRIPT_DIR, "templates", f"modbus_simulator_{port}.json"),
        "statusPath": os.path.join(SCRIPT_DIR, "logs", f"rtu_sim_{port}_status.json"),
        "stdout": os.path.join(SCRIPT_DIR, f"modbus_sim_{port}_managed_stdout.log"),
        "stderr": os.path.join(SCRIPT_DIR, f"modbus_sim_{port}_managed_stderr.log"),
    }


def write_worker_config(spec: dict[str, Any], paths: dict[str, str]) -> None:
    """Write the shared per-port file; the Python backend reads only devices."""
    config = {
        "version": WORKER_CONFIG_VERSION,
        "port": spec["port"],
        "usbSerial": spec["usbSerial"],
        "baudrate": spec["baudrate"],
        "bytesize": spec["bytesize"],
        "parity": spec["parity"],
        "stopbits": spec["stopbits"],
        "idleGapMs": spec["idleGapMs"],
        "statusFile": paths["statusPath"],
        "statusIntervalMs": 1000,
        "traceFrames": spec["traceFrames"],
        "devices": spec["devices"],
    }
    os.makedirs(os.path.dirname(paths["manifestPath"]), exist_ok=True)
    with open(paths["manifestPath"], "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)


def worker_command(spec: dict[str, Any], paths: dict[str, str]) -> list[str]:
    if spec["backend"] == "go":
        return [GO_EXECUTABLE, "--config", paths["manifestPath"]]
    command = [
        sys.executable,
        PYTHON_SCRIPT,
        "--port", spec["port"],
        "--manifest", paths["manifestPath"],
        "--baudrate", str(spec["baudrate"]),
        "--bytesize", str(spec["bytesize"]),
        "--parity", spec["parity"],
        "--stopbits", str(spec["stopbits"]),
        "--timeout", str(spec["timeout"]),
    ]
    if spec["multidrop"]:
        command.append("--multidrop")
    return command


def launch_worker(spec: dict[str, Any], prior: dict[str, Any]) -> dict[str, Any]:
    paths = worker_paths(spec["port"])
    if stop_worker(prior):
        time.sleep(0.5)
    write_worker_config(spec, paths)
    os.makedirs(os.path.dirname(paths["statusPath"]), exist_ok=True)
    if os.path.exists(paths["statusPath"]):
        os.remove(paths["statusPath"])

    with open(paths["stdout"], "w", encoding="utf-8") as stdout_handle, \
            open(paths["stderr"], "w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            worker_command(spec, paths),
            cwd=SCRIPT_DIR,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=windows_creationflags(),
            close_fds=True,
        )
    entry = {key: value for key, value in spec.items() if key != "port"}
    entry.update(paths)
    entry["pid"] = process.pid
    entry["deviceCount"] = len(spec["devices"])
    if psutil is not None:
        try:
            entry["createTime"] = psutil.Process(process.pid).create_time()
        except psutil.Error:
            pass
    wait_for_start(spec, entry)
    return entry


def wait_for_start(spec: dict[str, Any], entry: dict[str, Any]) -> None:
    """Give the worker a moment; the Go worker is waited on until its port opens."""
    if spec["backend"] != "go":
        time.sleep(1.0)
        return
    deadline = time.time() + GO_OPEN_WAIT_SECONDS
    while time.time() < deadline:
        worker = read_worker_status(entry)
        if worker and worker.get("portOpen"):
            return
        if not pid_running(entry["pid"]):
            return
        time.sleep(0.1)


def apply_simulator(buses: list[dict[str, Any]]) -> dict[str, Any]:
    state = read_state()
    simulators = dict(state.get("simulators", {}))
    try:
        specs = validate_request(buses, simulators)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    results = []
    for spec in specs:
        entry = launch_worker(spec, simulators.get(spec["port"], {}))
        simulators[spec["port"]] = entry
        row = describe_entry(spec["port"], entry)
        results.append(row)
        # Persist after each start so a later failure cannot orphan this worker.
        write_state({"simulators": simulators})

    def started(row: dict[str, Any]) -> bool:
        return row["running"] and (row.get("backend") != "go" or row.get("portOpen"))

    return {"success": all(started(row) for row in results), "simulators": results}
