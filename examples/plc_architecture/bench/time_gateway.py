"""Round-trip time of Modbus TCP requests through a gateway, from the PC, without the PLC's task cycle.

Usage: python examples/plc_architecture/bench/time_gateway.py [--host 192.168.50.67] [--unit 12] [--count 100]
    [--registers 10[,60,...]]
Sequential FC03 reads of 10 registers (or each --registers size in turn) on one connection; prints min/median/p95/max in ms. Takes one of the
gateway's client slots (6 on the NA111-E) for its duration.
"""
import argparse
import socket
import statistics
import struct
import time


def read_holding(sock, transaction, unit, start, count):
    sock.sendall(struct.pack(">HHHBBHH", transaction, 0, 6, unit, 3, start, count))
    header = b""
    while len(header) < 7:
        header += sock.recv(7 - len(header))
    _, _, length, _ = struct.unpack(">HHHB", header)
    body = b""
    while len(body) < length - 1:
        body += sock.recv(length - 1 - len(body))
    if body[0] & 0x80:
        raise RuntimeError("exception %d" % body[1])
    return body


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.50.67")
    parser.add_argument("--unit", type=int, default=12)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--registers", default="10")
    args = parser.parse_args()
    with socket.create_connection((args.host, 502), timeout=2) as sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for registers in [int(r) for r in args.registers.split(",")]:
            times = []
            for transaction in range(1, args.count + 1):
                started = time.perf_counter()
                read_holding(sock, transaction, args.unit, 0, registers)
                times.append((time.perf_counter() - started) * 1000)
            times.sort()
            print("unit %d, %d registers, %d requests: min %.1f, median %.1f, p95 %.1f, max %.1f ms" % (
                args.unit, registers, len(times), times[0], statistics.median(times), times[int(len(times) * 0.95) - 1], times[-1]))


if __name__ == "__main__":
    main()
