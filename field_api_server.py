"""Serve the API using a manually started IDE script without managing IDE processes."""

import argparse
import json
import time
from http.server import HTTPServer
from pathlib import Path

from HTTP_SERVER import create_handler
from auth import ApiKeyManager
from script_executor import ScriptExecutor
from script_generator import ScriptGenerator
from server_addresses import print_connection_addresses
from server_config import (
    API_KEY_FILE, REQUEST_DIR, RESULT_DIR, STATUS_FILE, initialize_directories,
)


class ExistingSession:
    """Supply session status without launching, terminating, or deduplicating IDEs."""

    def ensure_singleton(self):
        return []

    def get_status(self):
        try:
            return json.loads(Path(STATUS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"state": "unknown", "timestamp": time.time()}

    def is_running(self):
        try:
            return (
                self.get_status().get("state") not in ("terminated", "unknown", "error")
                and time.time() - Path(STATUS_FILE).stat().st_mtime < 30
            )
        except OSError:
            return False

    def start(self):
        return False

    def stop(self):
        return False


def create_server(host, port):
    initialize_directories()
    handler = create_handler(
        ExistingSession(),
        ScriptExecutor(REQUEST_DIR, RESULT_DIR),
        ScriptGenerator(),
        ApiKeyManager(API_KEY_FILE),
    )
    return HTTPServer((host, port), handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0", help="Listen address (default: all IPv4 interfaces).")
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args()
    server = create_server(args.host, args.port)
    print_connection_addresses(server.server_address)
    print("Start PERSISTENT_SESSION.py in the existing CODESYS IDE.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
