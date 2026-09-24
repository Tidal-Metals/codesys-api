#!/usr/bin/env python
"""Apply a JSON Modbus device-driver manifest to the simulator and PLC."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_BASE_URL = "http://localhost:8081"
DEFAULT_API_KEY = "admin"


def windows_creationflags() -> int:
    flags = 0
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def load_manifest(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("Manifest root must be a JSON object.")
    if not isinstance(data.get("devices"), list) or not data["devices"]:
        raise ValueError("Manifest must contain a non-empty devices array.")
    return data


def request_json(base_url: str, api_key: str, method: str, path: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=body,
        method=method.upper(),
        headers={
            "Authorization": "ApiKey {0}".format(api_key),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def best_effort_request_json(
    base_url: str,
    api_key: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> dict[str, Any]:
    try:
        return request_json(base_url, api_key, method, path, payload, timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc)
        return {
            "success": False,
            "httpStatus": getattr(exc, "code", None),
            "error": detail or str(exc),
        }


def start_simulator(manifest_path: str, serial: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    port = str(serial["port"])
    baudrate = int(serial.get("baudrate", 9600))
    bytesize = int(serial.get("bytesize", 8))
    parity = str(serial.get("parity", "N"))
    stopbits = int(serial.get("stopbits", 1))
    timeout = float(serial.get("timeout", 1.0))

    command = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "modbus_rtu_slave_sim.py"),
        "--port", port,
        "--manifest", manifest_path,
        "--baudrate", str(baudrate),
        "--bytesize", str(bytesize),
        "--parity", parity,
        "--stopbits", str(stopbits),
        "--timeout", str(timeout),
    ]

    if dry_run:
        return {"success": True, "dryRun": True, "command": command}

    stdout_path = os.path.join(SCRIPT_DIR, "modbus_sim_{0}_{1}_stdout.log".format(port, baudrate))
    stderr_path = os.path.join(SCRIPT_DIR, "modbus_sim_{0}_{1}_stderr.log".format(port, baudrate))
    stdout_handle = open(stdout_path, "w", encoding="utf-8")
    stderr_handle = open(stderr_path, "w", encoding="utf-8")
    process = subprocess.Popen(  # noqa: S603
        command,
        cwd=SCRIPT_DIR,
        stdout=stdout_handle,
        stderr=stderr_handle,
        creationflags=windows_creationflags(),
        close_fds=True,
    )
    time.sleep(2)
    return {
        "success": True,
        "pid": process.pid,
        "command": command,
        "stdout": stdout_path,
        "stderr": stderr_path,
    }


def plc_payload_for_device(manifest: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    plc = manifest.get("plc", {})
    return {
        "mode": "script",
        "masterPath": device.get("masterPath", plc.get("masterPath")),
        "slaveAddress": int(device.get("slaveAddress", device.get("unit", device.get("serverAddress", 1)))),
        "replace": True,
        "channels": device.get("channels", []),
    }


def plc_create_payload_for_device(manifest: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    plc = manifest.get("plc", {})
    return {
        "masterPath": device.get("masterPath", plc.get("masterPath")),
        "name": str(device["name"]),
        "slaveAddress": int(device.get("slaveAddress", device.get("unit", device.get("serverAddress", 1)))),
        "deviceType": int(device.get("deviceType", plc.get("deviceType", 91))),
        "deviceId": str(device.get("deviceId", plc.get("deviceId", "0000 0001"))),
        "deviceVersion": str(device.get("deviceVersion", plc.get("deviceVersion", "4.5.0.0"))),
    }


def normalize_mapping_variable(variable_name: str, manifest: dict[str, Any], device: dict[str, Any]) -> str:
    normalized = str(variable_name).strip()
    if "." not in normalized:
        return normalized
    if normalized.startswith("Application.") or normalized.startswith("Device."):
        return normalized

    plc = manifest.get("plc", {})
    application_name = str(device.get("applicationName", plc.get("applicationName", "Application"))).strip()
    if normalized.startswith("GVL."):
        return "{0}.{1}".format(application_name, normalized)
    return normalized


def apply_plc_devices(base_url: str, api_key: str, manifest: dict[str, Any], dry_run: bool) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for device in manifest["devices"]:
        name = str(device["name"])
        create_payload = plc_create_payload_for_device(manifest, device)
        channel_payload = plc_payload_for_device(manifest, device)
        if not create_payload.get("masterPath"):
            raise ValueError("Device {0} is missing plc.masterPath/masterPath.".format(name))

        result: dict[str, Any] = {
            "device": name,
            "deleteExisting": None,
            "createDevice": None,
            "createChannels": None,
            "deviceUpdate": None,
            "mappings": [],
        }

        if dry_run:
            result["deleteExisting"] = {"dryRun": True, "path": "/api/v1/modbus/devices/{0}".format(name)}
            result["createDevice"] = {"dryRun": True, "payload": create_payload}
            result["createChannels"] = {"dryRun": True, "payload": channel_payload}
        else:
            result["deleteExisting"] = best_effort_request_json(
                base_url,
                api_key,
                "DELETE",
                "/api/v1/modbus/devices/{0}".format(urllib.parse.quote(name)),
                None,
                timeout=120,
            )
            result["createDevice"] = request_json(
                base_url,
                api_key,
                "POST",
                "/api/v1/modbus/devices",
                create_payload,
                timeout=180,
            )
            result["createChannels"] = request_json(
                base_url,
                api_key,
                "POST",
                "/api/v1/modbus/devices/{0}/channels/bulk".format(urllib.parse.quote(name)),
                channel_payload,
                timeout=180,
            )

        update_fields: dict[str, Any] = {}
        if "responseTimeout" in device:
            update_fields["responseTimeout"] = int(device["responseTimeout"])
        if "slaveAddress" in device:
            update_fields["slaveAddress"] = int(device["slaveAddress"])

        if update_fields:
            if dry_run:
                result["deviceUpdate"] = {"dryRun": True, "payload": update_fields}
            else:
                result["deviceUpdate"] = request_json(
                    base_url,
                    api_key,
                    "PATCH",
                    "/api/v1/modbus/devices/{0}".format(urllib.parse.quote(name)),
                    update_fields,
                    timeout=120,
                )

        for mapping in device.get("mappings", []):
            channel_name = mapping["channel"]
            variable_name = normalize_mapping_variable(mapping["variable"], manifest, device)
            mapping_payload = {
                "variable": variable_name,
                "createVariable": bool(mapping.get("createVariable", False)),
            }
            if dry_run:
                result["mappings"].append({"channel": channel_name, "dryRun": True, "payload": mapping_payload})
            else:
                mapping_result = request_json(
                    base_url,
                    api_key,
                    "PUT",
                    "/api/v1/modbus/devices/{0}/channels/{1}/mapping".format(
                        urllib.parse.quote(name),
                        urllib.parse.quote(channel_name),
                    ),
                    mapping_payload,
                    timeout=120,
                )
                result["mappings"].append({"channel": channel_name, "result": mapping_result})

        results.append(result)

    return results


def save_project(base_url: str, api_key: str, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"success": True, "dryRun": True}
    return request_json(base_url, api_key, "POST", "/api/v1/project/save", {}, timeout=60)


def read_modbus_status(base_url: str, api_key: str, manifest: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {
            "success": True,
            "dryRun": True,
            "path": "/api/v1/modbus/status",
            "applicationPath": manifest.get("plc", {}).get("applicationPath", "Device/Plc Logic/Application"),
            "master": manifest.get("plc", {}).get("masterName", "Modbus_Client_COM_Port"),
        }

    payload = None
    path = "/api/v1/modbus/status?applicationPath={0}&master={1}".format(
        urllib.parse.quote(str(manifest.get("plc", {}).get("applicationPath", "Device/Plc Logic/Application")), safe=""),
        urllib.parse.quote(str(manifest.get("plc", {}).get("masterName", "Modbus_Client_COM_Port")), safe=""),
    )
    return best_effort_request_json(base_url, api_key, "GET", path, payload, timeout=120)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", help="Path to the JSON Modbus device-driver manifest.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CODESYS API base URL.")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="CODESYS API key.")
    parser.add_argument("--skip-simulator", action="store_true", help="Do not start the simulator.")
    parser.add_argument("--skip-plc", action="store_true", help="Do not apply PLC configuration.")
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without changing anything.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = load_manifest(args.manifest)
        serial = manifest.get("serial", manifest.get("simulator", {}))
        output: dict[str, Any] = {"manifest": os.path.abspath(args.manifest)}

        if not args.skip_simulator:
            if "port" not in serial:
                raise ValueError("Manifest serial/simulator section must define a port.")
            output["simulator"] = start_simulator(args.manifest, serial, args.dry_run)

        if not args.skip_plc:
            output["plc"] = {
                "devices": apply_plc_devices(args.base_url, args.api_key, manifest, args.dry_run),
                "save": save_project(args.base_url, args.api_key, args.dry_run),
                "status": read_modbus_status(args.base_url, args.api_key, manifest, args.dry_run),
            }

        print(json.dumps(output, indent=2))
        return 0
    except (ValueError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
