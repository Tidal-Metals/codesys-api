"""Send a known byte pattern on a PC serial port, for a PLC-side receive check (PRG_SerialProbe).

Usage: python examples/plc_architecture/bench/serial_pattern.py COM12 [--baud 9600] [--seconds 10] [--period 0.1]
Sends 55 AA 01 02 03 04 05 06 every period. Only on a port no simulator owns (GET /api/v1/bench -> adapters ->
owner; POST /api/v1/modbus/simulator/stop {"port": "COM12"} frees it).
"""
import argparse
import json
import time

import serial

PATTERN = bytes([0x55, 0xAA, 1, 2, 3, 4, 5, 6])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--period", type=float, default=0.1)
    args = parser.parse_args()
    sent = 0
    with serial.Serial(args.port, args.baud, bytesize=8, parity="N", stopbits=1, timeout=0) as port:
        end = time.time() + args.seconds
        while time.time() < end:
            port.write(PATTERN)
            sent += len(PATTERN)
            time.sleep(args.period)
        port.flush()
    print(json.dumps({"port": args.port, "baud": args.baud, "bytesSent": sent, "pattern": PATTERN.hex(" ")}))


if __name__ == "__main__":
    main()
