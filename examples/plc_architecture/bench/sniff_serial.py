"""Listen on a USB-RS485 adapter (read-only) and print the frames seen, split at silent gaps.

Usage: python examples/plc_architecture/bench/sniff_serial.py COM12 [--baud 9600] [--seconds 5]
Opens the port only for the listening window. Check the bench inventory first: never open a port the
simulator manager owns.
"""
import argparse
import json
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("port")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--parity", default="N")
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--gap-ms", type=float, default=5)
    args = parser.parse_args()
    frames, current, last = [], bytearray(), None
    with serial.Serial(args.port, args.baud, parity=args.parity, bytesize=8, stopbits=1, timeout=0.001) as port:
        end = time.time() + args.seconds
        while time.time() < end:
            chunk = port.read(256)
            now = time.time()
            if chunk:
                if current and last is not None and (now - last) * 1000 > args.gap_ms:
                    frames.append((round(last, 3), current.hex(" ")))
                    current = bytearray()
                current.extend(chunk)
                last = now
            elif current and last is not None and (now - last) * 1000 > args.gap_ms:
                frames.append((round(last, 3), current.hex(" ")))
                current = bytearray()
        if current:
            frames.append((round(last, 3), current.hex(" ")))
    print(json.dumps({"port": args.port, "baud": args.baud, "frames": len(frames), "sample": frames[:8]}, indent=1))


if __name__ == "__main__":
    main()
