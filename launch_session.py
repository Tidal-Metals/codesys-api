#!/usr/bin/env python
"""Robust launcher for the CODESYS API bridge and persistent session."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORTS = [8081, 8082, 8090, 8091]
DEFAULT_API_KEY = "admin"


class LaunchError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, flush=True)


def request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": "ApiKey {0}".format(DEFAULT_API_KEY),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def try_request_json(base_url: str, method: str, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any] | None:
    try:
        return request_json(base_url, method, path, payload, timeout)
    except (HTTPError, URLError, OSError, TimeoutError, json.JSONDecodeError, ValueError):
        return None


def port_owner_pid(port: int) -> int | None:
    try:
        output = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except Exception:
        return None

    pattern = re.compile(r"^\s*TCP\s+\S+:{0}\s+\S+\s+LISTENING\s+(\d+)\s*$".format(port), re.IGNORECASE)
    for line in output.splitlines():
        match = pattern.match(line)
        if match:
            return int(match.group(1))
    return None


def process_info(pid: int) -> dict[str, Any]:
    command = (
        "Get-CimInstance Win32_Process -Filter \"ProcessId = {0}\" | "
        "Select-Object ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    ).format(pid)
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception:
        return {}

    if not output:
        return {}

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def find_launch_session_pids() -> list[int]:
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*launch_session.py*' } | "
        "Select-Object -ExpandProperty ProcessId | ConvertTo-Json -Compress"
    )
    try:
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", command],
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).strip()
    except Exception:
        return []

    if not output:
        return []

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        return [int(pid) for pid in parsed]
    return []


def stop_stale_launchers() -> None:
    current_pid = os.getpid()
    stale = [pid for pid in find_launch_session_pids() if pid != current_pid]
    if not stale:
        return

    for pid in stale:
        log("Stopping stale launch_session.py process PID {0}.".format(pid))
        stop_pid(pid)


def is_our_server_process(info: dict[str, Any]) -> bool:
    command_line = str(info.get("CommandLine") or "").lower()
    return "codesys-api" in command_line and (
        "serve_on_port.py" in command_line
        or "http_server.py" in command_line
        or "http_server.run_server" in command_line
    )


def stop_pid(pid: int) -> None:
    subprocess.run(
        ["taskkill", "/PID", str(pid), "/F", "/T"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def wait_for_port_free(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_is_free(port):
            return True
        time.sleep(0.5)
    return port_is_free(port)


def choose_port(preferred_ports: list[int], base_url_template: str) -> tuple[int, bool]:
    for port in preferred_ports:
        base_url = base_url_template.format(port=port)
        health = try_request_json(base_url, "GET", "/api/v1/system/info", None, timeout=2.0)
        if health and health.get("success"):
            log("Reusing healthy CODESYS API server on port {0}.".format(port))
            return port, True

        pid = port_owner_pid(port)
        if pid is None:
            return port, False

        info = process_info(pid)
        if is_our_server_process(info):
            log("Stopping stale CODESYS API server on port {0} (PID {1}).".format(port, pid))
            stop_pid(pid)
            if not wait_for_port_free(port, timeout=15.0):
                raise LaunchError("Port {0} stayed busy after stopping PID {1}.".format(port, pid))
            return port, False

    raise LaunchError("No usable CODESYS API port found in {0}.".format(", ".join(str(port) for port in preferred_ports)))


def start_server_process(port: int) -> None:
    stdout_path = SCRIPT_DIR / "server_{0}_stdout.log".format(port)
    stderr_path = SCRIPT_DIR / "server_{0}_stderr.log".format(port)
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )

    stdout_handle = open(stdout_path, "ab")
    stderr_handle = open(stderr_path, "ab")
    try:
        subprocess.Popen(
            [sys.executable, str(SCRIPT_DIR / "serve_on_port.py"), "--port", str(port)],
            cwd=str(SCRIPT_DIR),
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
            close_fds=True,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()


def wait_for_http(port: int, timeout: float) -> str:
    base_url = "http://localhost:{0}".format(port)
    deadline = time.time() + timeout
    while time.time() < deadline:
        health = try_request_json(base_url, "GET", "/api/v1/system/info", None, timeout=3.0)
        if health and health.get("success"):
            return base_url
        time.sleep(1.0)
    raise LaunchError("HTTP server on port {0} did not become healthy within {1:.0f} seconds.".format(port, timeout))


def wait_for_session_ready(base_url: str, timeout: float) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = try_request_json(base_url, "GET", "/api/v1/session/status", None, timeout=10.0)
        if status and status.get("success"):
            last_status = status
            payload = status.get("status", {})
            process_running = bool(payload.get("process", {}).get("running"))
            session_payload = payload.get("session", {})
            session_active = bool(session_payload.get("session_active") or session_payload.get("active"))
            if process_running and session_active:
                return status
        time.sleep(2.0)

    raise LaunchError(
        "CODESYS session did not become ready within {0:.0f} seconds. Last status: {1}".format(timeout, last_status)
    )


def start_codesys_session(base_url: str, timeout: float) -> dict[str, Any]:
    log("Starting CODESYS persistent session.")
    start_result = try_request_json(base_url, "POST", "/api/v1/session/start", {}, timeout=timeout)
    if start_result and start_result.get("success"):
        return start_result

    if start_result is not None:
        log("Session start returned a non-success response; polling status anyway.")
    else:
        log("Session start did not return a clean response; polling status anyway.")

    return wait_for_session_ready(base_url, timeout=timeout)


def get_active_project(base_url: str) -> dict[str, Any] | None:
    script = (
        "import scriptengine\n"
        "proj = scriptengine.projects.primary\n"
        "if proj is None and hasattr(session, 'active_project'):\n"
        "    proj = session.active_project\n"
        "if proj is None:\n"
        "    result = {'success': True, 'project': None}\n"
        "else:\n"
        "    _path = ''\n"
        "    if hasattr(proj, 'path'):\n"
        "        try:\n"
        "            _path = str(proj.path)\n"
        "        except:\n"
        "            _path = ''\n"
        "    if not _path and hasattr(proj, 'filename'):\n"
        "        try:\n"
        "            _path = str(proj.filename)\n"
        "        except:\n"
        "            _path = ''\n"
        "    _name = str(proj)\n"
        "    if hasattr(proj, 'get_name'):\n"
        "        try:\n"
        "            _name = str(proj.get_name())\n"
        "        except:\n"
        "            _name = str(proj)\n"
        "    result = {'success': True, 'project': {'path': _path, 'name': _name}}\n"
    )
    result = try_request_json(base_url, "POST", "/api/v1/script/execute", {"script": script}, timeout=30.0)
    if result and result.get("success"):
        return result.get("project")
    return None


def normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def open_project(base_url: str, project_path: str, timeout: float) -> dict[str, Any]:
    active = get_active_project(base_url)
    if active and active.get("path") and normalize_path(str(active["path"])) == normalize_path(project_path):
        log("Requested project is already active; skipping reopen.")
        return {"success": True, "project": active, "already_open": True}

    log("Opening project: {0}".format(project_path))
    result = try_request_json(base_url, "POST", "/api/v1/project/open", {"path": project_path}, timeout=timeout)
    if result and result.get("success"):
        return result

    active = get_active_project(base_url)
    if active and active.get("path") and normalize_path(str(active["path"])) == normalize_path(project_path):
        log("Project open response was noisy, but the requested project is active.")
        return {"success": True, "project": active}

    raise LaunchError("Project open failed for {0}. Response: {1}".format(project_path, result))


def parse_ports(value: str) -> list[int]:
    ports: list[int] = []
    for raw in value.split(","):
        raw = raw.strip()
        if not raw:
            continue
        ports.append(int(raw))
    if not ports:
        raise argparse.ArgumentTypeError("Expected at least one port.")
    return ports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ports", type=parse_ports, default=DEFAULT_PORTS, help="Comma-separated candidate ports.")
    parser.add_argument("--project", help="Optional CODESYS project path to open after the session starts.")
    parser.add_argument("--skip-session-start", action="store_true", help="Only ensure the HTTP bridge is running.")
    parser.add_argument("--session-timeout", type=float, default=180.0, help="Seconds to wait for the CODESYS session.")
    parser.add_argument("--project-timeout", type=float, default=180.0, help="Seconds to wait for project open.")
    args = parser.parse_args()

    project_path = None
    if args.project:
        project_path = str(Path(args.project).expanduser().resolve())
        if not Path(project_path).exists():
            raise LaunchError("Project file not found: {0}".format(project_path))

    stop_stale_launchers()

    port, reused = choose_port(args.ports, "http://localhost:{port}")
    if not reused:
        log("Starting CODESYS API server on port {0}.".format(port))
        start_server_process(port)

    base_url = wait_for_http(port, timeout=30.0)
    log("HTTP bridge ready at {0}.".format(base_url))

    if not args.skip_session_start:
        start_codesys_session(base_url, timeout=args.session_timeout)
        ready = wait_for_session_ready(base_url, timeout=args.session_timeout)
        log("CODESYS session ready: {0}".format(json.dumps(ready.get("status", {}), indent=2)))

    if project_path:
        result = open_project(base_url, project_path, timeout=args.project_timeout)
        log("Project ready: {0}".format(json.dumps(result, indent=2)))

    log("Launch complete. Base URL: {0}".format(base_url))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LaunchError as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        raise SystemExit(1)
