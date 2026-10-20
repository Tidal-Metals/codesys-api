"""Simulated RS485 buses for the bench.

Gateway bus: behind the NA111-E (COM11, 115200), units 11-40, ten holding registers each.

Usage: python examples/plc_architecture/bench/bus_sim.py apply|show [--token <reservation>]
Register r of unit u holds u * 100 + r (unit 11: 1100, 1101, ...), except register 9, a setpoint the PLC
writes (starts at 0). Unit 11 also has coils 0-9 = COILS.
Serial bus: on the PLC's terminal block (COM2), wired to the USB adapter COM12, 9600 8N1: units 1-10 shaped like
the Ebyte ME31 thermocouple module, input registers 400-405 = temperature x 10 (unit 10 channel 6 = -999, open).
bench/make_bench_sources.py maps the same units and registers to tags.
"""
import argparse
import json
import sys
import urllib.request

API = "http://localhost:8081/api/v1"
UNITS = list(range(11, 41))
REGISTERS = 10
SETPOINT_REGISTER = 9
COILS = [1, 0, 1, 1, 0, 0, 0, 1, 0, 1]      # unit 11 coils 0-9
SERIAL_UNITS = list(range(1, 11))
SERIAL_BAUD = 9600
TEMPERATURE_REGISTER = 400
CHANNELS = 6
OPEN_SENSOR = (10, 5)                       # (unit, channel) that reads -999


def temperature_raw(unit, channel):
    return -999 if (unit, channel) == OPEN_SENSOR else 200 + unit * 10 + channel


def holding(unit):
    return dict((str(r), 0 if r == SETPOINT_REGISTER else unit * 100 + r) for r in range(REGISTERS))


def device(unit):
    entry = {"unit": unit, "holdingMap": holding(unit)}
    if unit == UNITS[0]:
        entry["coilsMap"] = dict((str(bit), state) for bit, state in enumerate(COILS))
    return entry


def serial_device(unit):
    registers = dict((str(TEMPERATURE_REGISTER + c), temperature_raw(unit, c) & 0xFFFF) for c in range(CHANNELS))
    return {"unit": unit, "inputRegistersMap": registers}


def request(method, path, body=None, token=None):
    headers = {"Authorization": "ApiKey admin", "Content-Type": "application/json"}
    if token:
        headers["X-Bench-Reservation"] = token
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(API + path, data=data, headers=headers, method=method), timeout=120) as reply:
        return json.loads(reply.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["apply", "show"])
    parser.add_argument("--token")
    args = parser.parse_args()
    if args.action == "apply":
        gateway = {"backend": "go", "pcPort": "COM11", "usbSerial": "BG00XX03", "baudrate": 115200, "multidrop": True,
                   "devices": [device(unit) for unit in UNITS]}
        serial_bus = {"backend": "go", "pcPort": "COM12", "usbSerial": "BG041BD0", "baudrate": SERIAL_BAUD, "multidrop": True,
                      "devices": [serial_device(unit) for unit in SERIAL_UNITS]}
        reply = request("POST", "/modbus/simulator/apply", {"buses": [gateway, serial_bus]}, args.token)
        print(json.dumps({"success": reply.get("success"), "error": reply.get("error"),
                          "buses": [(s.get("pcPort"), s.get("baudrate"), len(s.get("devices", []))) for s in reply.get("simulators", [])]}))
    else:
        print(json.dumps(request("GET", "/modbus/simulator/status"), indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
