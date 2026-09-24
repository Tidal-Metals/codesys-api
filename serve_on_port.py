#!/usr/bin/env python
"""Run the CODESYS API server on an explicit port."""

from __future__ import annotations

import argparse

import HTTP_SERVER
import server_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True, help="Port to bind the HTTP server to.")
    args = parser.parse_args()

    server_config.SERVER_PORT = args.port
    HTTP_SERVER.SERVER_PORT = args.port
    HTTP_SERVER.run_server()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
