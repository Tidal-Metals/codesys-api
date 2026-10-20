"""Set the cycle time of every native serial channel in the bench project (servers from native_serial.json).

Usage: python examples/plc_architecture/bench/set_native_cycle.py <cycle_ms>
Only the cycle: changing a channel's length this way (PATCH readLength) leaves its I/O image at the old size, and
the server stops polling with no error flag (2026-10-20). For another length, recreate the servers with
modbus_device_driver_runner.py.
Logs the session out first (device edits need it offline) and saves; download afterwards with deploy_bench.py.
A native channel's poll rate is fixed at download: this is the native counterpart of writing
GVL_Bus.Blocks[n].PeriodMs online.
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from run_ide_script import execute  # noqa: E402

API = "http://localhost:8081/api/v1"
MANIFEST = ROOT / "tmp" / "arch_bench" / "src" / "native_serial.json"
LOGOUT = """
on = scriptengine.online.create_online_application(scriptengine.projects.primary.active_application)
if on.is_logged_in:
    on.logout()
result = {'success': True}
"""


def call(method, path, body=None):
    request = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Authorization": "ApiKey admin", "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=180) as reply:
        return json.loads(reply.read())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cycle_ms", type=int)
    args = parser.parse_args()
    execute(LOGOUT, 60)
    for device in json.loads(MANIFEST.read_text(encoding="utf-8"))["devices"]:
        for channel in device["channels"]:
            path = "/modbus/devices/%s/channels/%s" % (urllib.parse.quote(device["name"]), urllib.parse.quote(channel["name"]))
            reply = call("PATCH", path, {"cycleTime": args.cycle_ms})
            print(device["name"], channel["name"], reply.get("success"), reply.get("error") or "")
    print(call("POST", "/project/save", {}).get("success"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
