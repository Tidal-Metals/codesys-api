"""Simulated RS485 buses for the bench.

Gateway bus: behind the NA111-E (COM11, 115200), units 11-40, holding registers 0-124 (block-size tests read
up to 125; the PLC tags use 0-9).

Usage: python examples/plc_architecture/bench/bus_sim.py apply|show [--token <reservation>]
Register r of unit u holds u * 100 + r (unit 11: 1100, 1101, ...), except register 9, a setpoint the PLC
writes (starts at 0); registers 10-124 hold r. Unit 11 also has coils 0-9 = COILS.
Serial bus: on the PLC's RJ12 jack (COM1), wired to the USB adapter COM12 and a real Ebyte ME31 (unit 1), 9600 8N1:
simulated units 2-10 shaped like the ME31, input registers 400-405 = temperature x 10 (unit 10 channel 6 = -999);
406-524 hold their offset from 400 (block-size tests).
--silent 25,5 makes those units ignore requests (dead-device tests).
bench/make_bench_sources.py maps the same units and registers to tags.
"""
import argparse
import json
import sys
import urllib.request

API = "http://localhost:8081/api/v1"
UNITS = list(range(11, 41))
REGISTERS = 10                              # registers mapped to tags
MAP_REGISTERS = 125                         # registers the simulator answers (a whole FC03 block)
SETPOINT_REGISTER = 9
COILS = [1, 0, 1, 1, 0, 0, 0, 1, 0, 1]      # unit 11 coils 0-9
ME31_UNIT = 1                               # the real Ebyte ME31 on the serial line; not simulated
SERIAL_UNITS = list(range(2, 11))
SERIAL_BAUD = 9600
TEMPERATURE_REGISTER = 400
CHANNELS = 6
SERIAL_MAP_REGISTERS = 125                  # input registers the simulator answers from 400 (a whole FC04 block)
OPEN_SENSOR = (10, 5)                       # (unit, channel) that reads -999


def temperature_raw(unit, channel):
    return -999 if (unit, channel) == OPEN_SENSOR else 200 + unit * 10 + channel


def holding(unit):
    return dict((str(r), 0 if r == SETPOINT_REGISTER else unit * 100 + r if r < REGISTERS else r) for r in range(MAP_REGISTERS))


SILENT = set()


def device(unit):
    entry = {"unit": unit, "holdingMap": holding(unit), "silent": unit in SILENT}
    if unit == UNITS[0]:
        entry["coilsMap"] = dict((str(bit), state) for bit, state in enumerate(COILS))
    return entry


def serial_device(unit):
    registers = dict((str(TEMPERATURE_REGISTER + c), temperature_raw(unit, c) & 0xFFFF if c < CHANNELS else c)
                     for c in range(SERIAL_MAP_REGISTERS))
    return {"unit": unit, "inputRegistersMap": registers, "silent": unit in SILENT}


def request(method, path, body=None, token=None):
    headers = {"Authorization": "ApiKey admin", "Content-Type": "application/json"}
    if token:
        headers["X-Bench-Reservation"] = token
    data = json.dumps(body).encode() if body is not None else None
    with urllib.request.urlopen(urllib.request.Request(API + path, data=data, headers=headers, method=method), timeout=120) as reply:
        return json.loads(reply.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["apply", "show", "stop"])
    parser.add_argument("--token")
    parser.add_argument("--silent", default="", help="units that ignore requests, e.g. 25,5")
    parser.add_argument("--serial-baud", type=int, default=SERIAL_BAUD,
                        help="serial bus baud rate (baud-rate tests; the real ME31 only answers at 9600)")
    args = parser.parse_args()
    SILENT.update(int(u) for u in args.silent.split(",") if u.strip())
    if args.action == "apply":
        gateway = {"backend": "go", "pcPort": "COM11", "usbSerial": "BG00XX03", "baudrate": 115200, "multidrop": True,
                   "devices": [device(unit) for unit in UNITS]}
        serial_bus = {"backend": "go", "pcPort": "COM12", "usbSerial": "BG041BD0", "baudrate": args.serial_baud, "multidrop": True,
                      "devices": [serial_device(unit) for unit in SERIAL_UNITS]}
        reply = request("POST", "/modbus/simulator/apply", {"buses": [gateway, serial_bus]}, args.token)
        print(json.dumps({"success": reply.get("success"), "error": reply.get("error"),
                          "buses": [(s.get("pcPort"), s.get("baudrate"), len(s.get("devices", []))) for s in reply.get("simulators", [])]}))
    elif args.action == "stop":       # frees COM11 and COM12, e.g. for sniff_serial.py or set_ftdi_latency.ps1
        for port in ("COM11", "COM12"):
            reply = request("POST", "/modbus/simulator/stop", {"port": port}, args.token)
            print(json.dumps({"port": port, "success": reply.get("success"), "error": reply.get("error")}))
    else:
        print(json.dumps(request("GET", "/modbus/simulator/status"), indent=1)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
