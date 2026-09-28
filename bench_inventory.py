"""Identity-based inventory of the bench's USB-RS485 adapters and TCP-to-RTU gateways.

Adapters are keyed by USB serial (FTDI's Windows ``A`` suffix stripped) and
gateways by MAC. COM numbers and IP addresses are reported as current
observations, never used as keys. Registered labels come from the tracked
seed ``templates/bench_inventory.default.json`` merged with local edits in
``bench_inventory.json``.
"""

from __future__ import annotations

import concurrent.futures
import copy
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
from typing import Any

import modbus_simulator_control
from bench_reservations import normalize_adapter_serial

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SEED_PATH = os.path.join(SCRIPT_DIR, "templates", "bench_inventory.default.json")
LOCAL_PATH = os.path.join(SCRIPT_DIR, "bench_inventory.json")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ARP_LINE = re.compile(r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\w+)", re.M)
PROBE_TIMEOUT_SECONDS = 0.5
ADAPTER_FIELDS = ("label", "wiredTo", "notes")
GATEWAY_FIELDS = ("label", "model", "expectedIp", "ports", "profileUrl", "notes")

_registry_lock = threading.Lock()


class InventoryError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def normalize_mac(mac: str) -> str:
    text = str(mac).strip().upper().replace(":", "-")
    if not re.fullmatch(r"[0-9A-F]{2}(-[0-9A-F]{2}){5}", text):
        raise InventoryError(f"Invalid MAC {mac!r}; expected e.g. B0-CB-D8-4E-88-BB")
    return text


def _read_json(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_registry() -> dict[str, dict[str, dict[str, Any]]]:
    registry = {"adapters": {}, "gateways": {}}
    for source in (_read_json(SEED_PATH), _read_json(LOCAL_PATH)):
        for serial, entry in (source.get("adapters") or {}).items():
            registry["adapters"].setdefault(normalize_adapter_serial(serial), {}).update(entry)
        for mac, entry in (source.get("gateways") or {}).items():
            registry["gateways"].setdefault(normalize_mac(mac), {}).update(entry)
    return registry


def register(kind: str, key: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Record labels for one adapter (kind='adapters') or gateway (kind='gateways') locally."""
    allowed = ADAPTER_FIELDS if kind == "adapters" else GATEWAY_FIELDS
    key = normalize_adapter_serial(key) if kind == "adapters" else normalize_mac(key)
    unknown = sorted(set(fields) - set(allowed))
    if unknown:
        raise InventoryError(f"Unknown fields {unknown}; allowed: {list(allowed)}")
    if kind == "gateways" and fields.get("expectedIp"):
        ipaddress.IPv4Address(fields["expectedIp"])
    if kind == "adapters" and fields.get("wiredTo"):
        fields = dict(fields, wiredTo=normalize_mac(fields["wiredTo"]))
    with _registry_lock:
        local = _read_json(LOCAL_PATH)
        local.setdefault(kind, {}).setdefault(key, {}).update(fields)
        tmp = LOCAL_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(local, handle, indent=2, sort_keys=True)
        os.replace(tmp, LOCAL_PATH)
    return dict(load_registry()[kind][key], id=key)


# --- adapters ---------------------------------------------------------------

def list_serial_ports() -> list[dict[str, Any]]:
    from serial.tools import list_ports
    ports = []
    for port in list_ports.comports():
        if not port.serial_number:
            continue
        ports.append({
            "port": port.device,
            "usbSerial": normalize_adapter_serial(port.serial_number),
            "reportedSerial": port.serial_number,
            "vid": "%04X" % port.vid if port.vid is not None else None,
            "pid": "%04X" % port.pid if port.pid is not None else None,
            "description": port.description,
        })
    return ports


def _simulator_owners() -> list[dict[str, Any]]:
    return modbus_simulator_control.get_simulator_status().get("simulators", [])


def describe_adapters(ports=None, owners=None, registry=None) -> list[dict[str, Any]]:
    ports = list_serial_ports() if ports is None else ports
    owners = _simulator_owners() if owners is None else owners
    registry = load_registry() if registry is None else registry
    by_serial: dict[str, dict[str, Any]] = {}
    for port in ports:
        by_serial[port["usbSerial"]] = dict(port, present=True)
    for serial in registry["adapters"]:
        by_serial.setdefault(serial, {"usbSerial": serial, "port": None, "present": False})

    adapters = []
    for serial, entry in sorted(by_serial.items()):
        entry = dict(entry, registered=serial in registry["adapters"])
        entry.update(copy.deepcopy(registry["adapters"].get(serial, {})))
        entry["owner"] = _owner_for(entry, owners)
        if entry["present"] and not entry["registered"]:
            entry["warning"] = "Unregistered adapter; PUT /api/v1/inventory/adapters/{0} to label it".format(serial)
        adapters.append(entry)
    return adapters


def _owner_for(adapter: dict[str, Any], owners: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in owners:
        managed_serial = normalize_adapter_serial(row["usbSerial"]) if row.get("usbSerial") else None
        if managed_serial == adapter["usbSerial"] or (not managed_serial and row.get("port") == adapter.get("port")):
            worker = row.get("worker") or {}
            return {
                "kind": "simulator",
                "simulatorPort": row.get("port"),
                "backend": row.get("backend", "python"),
                "running": row.get("running"),
                "portOpen": row.get("portOpen"),
                "pid": row.get("pid"),
                "units": [d.get("unit") for d in row.get("devices", [])],
                "lastRxAt": worker.get("lastRxAt"),
            }
    return None


# --- gateways ---------------------------------------------------------------

def read_arp_table() -> dict[str, str]:
    """MAC -> IPv4 from the Windows ARP cache."""
    try:
        output = subprocess.run(["arp", "-a"], capture_output=True, text=True, timeout=10,
                                creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    return parse_arp(output)


def parse_arp(output: str) -> dict[str, str]:
    table = {}
    for ip, mac, _kind in ARP_LINE.findall(output):
        mac = mac.upper()
        if mac != "FF-FF-FF-FF-FF-FF" and not ip.endswith(".255"):
            table[mac] = ip
    return table


def sweep_subnet(network: str) -> int:
    """Send one UDP datagram to every host so the OS resolves (and caches) their MACs."""
    hosts = list(ipaddress.IPv4Network(network, strict=False).hosts())

    def poke(host):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            try:
                sock.sendto(b"", (str(host), 9))
            except OSError:
                pass

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
        list(pool.map(poke, hosts))
    return len(hosts)


def tcp_reachable(ip: str, port: int) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=PROBE_TIMEOUT_SECONDS):
            return True
    except OSError:
        return False


def describe_gateways(refresh: bool = False, probe_ports: bool = False, arp=None, registry=None,
                      probe=tcp_reachable) -> dict[str, Any]:
    """refresh sweeps the expected /24s to repopulate ARP. probe_ports opens a TCP
    connection to each Modbus port, which briefly uses one of the gateway's few
    client slots, so it is opt-in."""
    registry = load_registry() if registry is None else registry
    swept = []
    if refresh:
        networks = sorted({str(ipaddress.IPv4Network(g["expectedIp"] + "/24", strict=False))
                           for g in registry["gateways"].values() if g.get("expectedIp")})
        for network in networks:
            sweep_subnet(network)
            swept.append(network)
    arp = read_arp_table() if arp is None else arp
    gateways = []
    for mac, entry in sorted(registry["gateways"].items()):
        row = dict(copy.deepcopy(entry), mac=mac, currentIp=arp.get(mac))
        row["found"] = row["currentIp"] is not None
        ports = entry.get("ports") or [502]
        if probe_ports:
            row["reachablePorts"] = [p for p in ports if row["found"] and probe(row["currentIp"], p)]
        expected = entry.get("expectedIp")
        if not row["found"]:
            row["warning"] = "Not in the ARP cache; retry with ?refresh=true or check power/cabling"
        elif expected and expected != row["currentIp"]:
            row["warning"] = ("Address changed: clients configured for {0} will fail; reserve the DHCP "
                              "lease or update them to {1}").format(expected, row["currentIp"])
        gateways.append(row)
    return {"gateways": gateways, "sweptNetworks": swept}
