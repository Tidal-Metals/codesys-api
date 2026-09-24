#!/usr/bin/env python
"""Run a known-value Modbus TCP server on an explicitly selected bench interface."""

import argparse
import logging

from pymodbus.server import StartTcpServer

from modbus_rtu_slave_sim import create_sim_device, normalize_device, parse_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="PC interface address to bind.")
    parser.add_argument("--port", type=int, default=502)
    parser.add_argument("--unit", type=int, default=1)
    parser.add_argument("--holding", type=parse_values, default=[1234, 5678, 9012, 3456])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("pymodbus").setLevel(logging.DEBUG)
    config = normalize_device({"unit": args.unit, "name": "tcp_bench", "holding": args.holding})

    def trace_packet(sending, packet):
        logging.info("%s %s", "TX" if sending else "RX", packet.hex(" "))
        return packet

    logging.info("Listening on %s:%s unit=%s holding offset 0=%s", args.host, args.port, args.unit, args.holding)
    StartTcpServer(context=[create_sim_device(config)], address=(args.host, args.port), trace_packet=trace_packet)


if __name__ == "__main__":
    main()
