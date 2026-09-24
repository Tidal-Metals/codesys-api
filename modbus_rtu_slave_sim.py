#!/usr/bin/env python
"""Simple Modbus RTU slave simulator for bench testing against a PLC.

Supports a single legacy device from CLI flags or multiple simulated slave
devices from a JSON manifest.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
from collections.abc import Iterable

from pymodbus.framer import FramerType
from pymodbus.server import StartSerialServer
from pymodbus.simulator import DataType, SimData, SimDevice


LOG = logging.getLogger("modbus_rtu_slave_sim")


def parse_values(raw: str) -> list[int]:
    values: list[int] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token, 0))
    if not values:
        raise argparse.ArgumentTypeError("Expected at least one integer value.")
    return values


def load_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise argparse.ArgumentTypeError("Manifest root must be a JSON object.")
    return data


def device_from_args(args: argparse.Namespace) -> dict:
    return {
        "unit": args.unit,
        "holdingMap": dense_sequence_to_map(args.holding),
        "inputRegistersMap": dense_sequence_to_map(args.input_registers),
        "coilsMap": dense_sequence_to_map(args.coils),
        "discreteInputsMap": dense_sequence_to_map(args.discrete_inputs),
        "name": "device_{0}".format(args.unit),
    }


def dense_sequence_to_map(values: Iterable[int]) -> dict[int, int]:
    return {index: int(value) for index, value in enumerate(values)}


def normalize_value_map(raw_map: object) -> dict[int, int]:
    if raw_map is None:
        return {}
    if isinstance(raw_map, dict):
        normalized: dict[int, int] = {}
        for key, value in raw_map.items():
            normalized[int(key)] = int(value)
        return normalized
    if isinstance(raw_map, list):
        return {index: int(value) for index, value in enumerate(raw_map)}
    raise argparse.ArgumentTypeError("Simulator value map must be an object or array.")


def resolve_value_map(raw: dict, map_keys: tuple[str, ...], legacy_keys: tuple[str, ...], default_values: list[int]) -> dict[int, int]:
    for key in map_keys:
        if key in raw:
            return normalize_value_map(raw.get(key))
    for key in legacy_keys:
        if key in raw:
            return normalize_value_map(raw.get(key))
    return dense_sequence_to_map(default_values)


def normalize_device(raw: dict, fallback_unit: int | None = None) -> dict:
    if not isinstance(raw, dict):
        raise argparse.ArgumentTypeError("Each simulator device must be a JSON object.")

    unit = raw.get("unit", raw.get("deviceId", raw.get("serverAddress", raw.get("slaveAddress", fallback_unit))))
    if unit is None:
        raise argparse.ArgumentTypeError("Each simulator device needs a unit/deviceId/serverAddress.")

    return {
        "unit": int(unit),
        "name": str(raw.get("name", "device_{0}".format(unit))),
        "coilsMap": resolve_value_map(raw, ("coilsMap",), ("coils",), [0] * 16),
        "discreteInputsMap": resolve_value_map(raw, ("discreteInputsMap",), ("discreteInputs", "discrete_inputs"), [0] * 16),
        "holdingMap": resolve_value_map(raw, ("holdingMap",), ("holding",), [1234, 5678, 0, 0, 0, 0, 0, 0]),
        "inputRegistersMap": resolve_value_map(raw, ("inputRegistersMap",), ("inputRegisters", "input_registers"), [1234, 5678, 0, 0, 0, 0, 0, 0]),
    }


def contiguous_segments(value_map: dict[int, int]) -> list[tuple[int, list[int]]]:
    if not value_map:
        return []
    segments: list[tuple[int, list[int]]] = []
    current_start: int | None = None
    current_values: list[int] = []
    previous_index: int | None = None
    for index in sorted(value_map):
        value = int(value_map[index])
        if current_start is None:
            current_start = index
            current_values = [value]
        elif previous_index is not None and index == previous_index + 1:
            current_values.append(value)
        else:
            segments.append((current_start, current_values))
            current_start = index
            current_values = [value]
        previous_index = index
    if current_start is not None:
        segments.append((current_start, current_values))
    return segments


def simdata_from_map(value_map: dict[int, int], datatype: DataType, *, default_count: int = 0) -> list[SimData]:
    segments = contiguous_segments(value_map)
    if not segments and default_count > 0:
        return [SimData(0, values=[0] * default_count, datatype=datatype)]
    return [SimData(address=start, values=values, datatype=datatype) for start, values in segments]


def preview_map(value_map: dict[int, int], *, limit: int = 12) -> list[tuple[int, int]]:
    items = sorted(value_map.items())
    return items[:limit]


def values_for_range(value_map: dict[int, int], address: int, count: int, *, default: int = 0) -> list[int]:
    return [int(value_map.get(offset, default)) for offset in range(address, address + count)]


def build_devices(args: argparse.Namespace) -> list[dict]:
    if not args.manifest:
        return [normalize_device(device_from_args(args))]

    manifest = load_manifest(args.manifest)
    raw_devices = manifest.get("devices")
    if raw_devices is None:
        simulator = manifest.get("simulator")
        if isinstance(simulator, dict):
            raw_devices = simulator.get("devices")
    if raw_devices is None:
        raw_devices = [manifest]
    if not isinstance(raw_devices, list) or not raw_devices:
        raise argparse.ArgumentTypeError("Manifest must contain a non-empty devices list.")
    return [normalize_device(entry) for entry in raw_devices]


def create_sim_device(config: dict) -> SimDevice:
    unit = int(config["unit"])
    coils_map = dict(config["coilsMap"])
    discrete_inputs_map = dict(config["discreteInputsMap"])
    holding_map = dict(config["holdingMap"])
    input_registers_map = dict(config["inputRegistersMap"])

    async def on_access(function_code, start_address, address, count, current_registers, set_values):
        op = "WRITE" if set_values is not None else "READ"
        fc = int(function_code)
        read_values = None
        if fc in (1, 5, 15):
            read_values = values_for_range(coils_map, int(address), int(count), default=0)
        elif fc == 2:
            read_values = values_for_range(discrete_inputs_map, int(address), int(count), default=0)
        elif fc in (3, 6, 16):
            read_values = values_for_range(holding_map, int(address), int(count), default=0)
        elif fc == 4:
            read_values = values_for_range(input_registers_map, int(address), int(count), default=0)
        LOG.info(
            "device=%s %s fc=%s address=%s count=%s start=%s values=%s set=%s",
            unit,
            op,
            function_code,
            address,
            count,
            start_address,
            read_values,
            set_values,
        )

    return SimDevice(
        id=unit,
        simdata=(
            simdata_from_map(coils_map, DataType.BITS),
            simdata_from_map(discrete_inputs_map, DataType.BITS),
            simdata_from_map(holding_map, DataType.REGISTERS),
            simdata_from_map(input_registers_map, DataType.REGISTERS),
        ),
        action=on_access,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="Windows serial port, for example COM36.")
    parser.add_argument("--manifest", help="JSON manifest with one or more simulated devices.")
    parser.add_argument("--unit", type=int, default=7, help="Modbus slave address.")
    parser.add_argument("--baudrate", type=int, default=115200, help="Serial baud rate.")
    parser.add_argument("--bytesize", type=int, default=8, help="Serial data bits.")
    parser.add_argument("--parity", default="N", help="Serial parity: N, E, or O.")
    parser.add_argument("--stopbits", type=int, default=1, help="Serial stop bits.")
    parser.add_argument("--timeout", type=float, default=1.0, help="Serial timeout in seconds.")
    parser.add_argument("--multidrop", action="store_true",
                        help="Share RS485 with other responders; requires baudrate <= 38400.")
    parser.add_argument(
        "--holding",
        type=parse_values,
        default=[1234, 5678, 0, 0, 0, 0, 0, 0],
        help="Comma-separated holding register values starting at offset 0.",
    )
    parser.add_argument(
        "--input-registers",
        type=parse_values,
        default=[1234, 5678, 0, 0, 0, 0, 0, 0],
        help="Comma-separated input register values starting at offset 0.",
    )
    parser.add_argument(
        "--coils",
        type=parse_values,
        default=[0] * 16,
        help="Comma-separated coil values starting at offset 0.",
    )
    parser.add_argument(
        "--discrete-inputs",
        type=parse_values,
        default=[0] * 16,
        help="Comma-separated discrete input values starting at offset 0.",
    )
    args = parser.parse_args()
    if args.multidrop and args.baudrate > 38400:
        parser.error("--multidrop requires baudrate <= 38400 in the installed PyModbus transport")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    def trace_packet(is_send: bool, packet: bytes) -> bytes:
        direction = "TX" if is_send else "RX"
        LOG.info("%s packet %s", direction, packet.hex(" "))
        return packet

    def trace_pdu(is_send: bool, pdu) -> object:
        direction = "TX" if is_send else "RX"
        LOG.info("%s pdu %s", direction, pdu)
        return pdu

    try:
        devices = build_devices(args)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
        return 2

    context = [create_sim_device(device) for device in devices]

    def _handle_signal(signum, _frame):
        LOG.info("Stopping on signal %s", signum)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    LOG.info(
        "Starting Modbus RTU slave on %s with %d device(s) %s%s%s %s baud",
        args.port,
        len(devices),
        args.bytesize,
        args.parity.upper(),
        args.stopbits,
        args.baudrate,
    )
    if args.manifest:
        LOG.info("Loaded simulator manifest: %s", os.path.abspath(args.manifest))
    for device in devices:
        LOG.info(
            "Device name=%s unit=%s holdingMap=%s inputMap=%s",
            device["name"],
            device["unit"],
            preview_map(device["holdingMap"]),
            preview_map(device["inputRegistersMap"]),
        )

    try:
        StartSerialServer(
            context=context,
            framer=FramerType.RTU,
            port=args.port,
            baudrate=args.baudrate,
            bytesize=args.bytesize,
            parity=args.parity.upper(),
            stopbits=args.stopbits,
            timeout=args.timeout,
            # Filter foreign requests and other responders' replies before decoding.
            allow_multiple_devices=args.multidrop,
            ignore_missing_devices=args.multidrop,
            trace_packet=trace_packet,
            trace_pdu=trace_pdu,
        )
    except KeyboardInterrupt:
        LOG.info("Simulator stopped.")
        return 0
    except Exception as exc:
        LOG.exception("Simulator failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
