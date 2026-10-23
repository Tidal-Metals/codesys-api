"""Broker URL by host name on the bench PLC: does it connect, and how long does name resolution block the scan?

Run from the repo root after deploy_demo.py:
    python examples/mqtt_large_payload/dns_test.py --out examples/mqtt_large_payload/results/exp/validation/dns.json
The library resolves a name with SysSockGetHostByName inside the client call (MQTT_CONTROL -> ResolveIPAddr), which
blocks the PLC task. Cases: the HQ broker by its LAN name, then a name that does not exist. For each: connected or
not, connect attempts in the window, and PLC_PRG.MaxCycleUs (the longest scan) against the 100 ms task. Restores the
IP address at the end.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

HQ_URL = "192.168.50.240:1883"
CASES = [("HQ broker by name", "tigstack.localdomain:1883", True),
         ("name that does not exist", "no-such-broker.localdomain:1883", False)]

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE = """
on = session.ensure_online_application('', True)
def number(path):
    return int(str(on.read_value(path)).split('#')[-1])
result = {'success': True, 'connected': str(on.read_value('PLC_PRG.IsBrokerConnected')) == 'TRUE',
          'attempts': number('PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt'),
          'maxCycleUs': number('PLC_PRG.MaxCycleUs'), 'maxClientUs': number('PLC_PRG.MaxClientUs')}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state() -> dict:
    return execute(STATE, 60)


def run_case(name: str, url: str, should_connect: bool, seconds: float) -> dict:
    write([("PLC_PRG.BrokerUrl", "'%s'" % url), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
    time.sleep(1)
    write([("PLC_PRG.ResetStats", "TRUE")])
    before = state()
    started = time.time()
    connected_after = None
    while time.time() - started < seconds:
        current = state()
        if current["connected"] and connected_after is None:
            connected_after = round(time.time() - started, 1)
            if should_connect:
                break
        time.sleep(0.5)
    time.sleep(2)
    after = state()
    return {"case": name, "url": url, "connected": after["connected"], "connectedAfterSeconds": connected_after,
            "connectAttempts": after["attempts"] - before["attempts"], "maxScanMs": round(after["maxCycleUs"] / 1000, 1),
            "maxClientMs": round(after["maxClientUs"] / 1000, 1),
            "ok": after["connected"] == should_connect}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--out")
    args = parser.parse_args()
    rows = []
    try:
        for name, url, should_connect in CASES:
            rows.append(run_case(name, url, should_connect, args.seconds))
            print(json.dumps(rows[-1]), flush=True)
    finally:
        write([("PLC_PRG.BrokerUrl", "'%s'" % HQ_URL), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
        time.sleep(3)
        restored = state()["connected"]
    report = {"cases": rows, "backOnIp": restored, "success": all(r["ok"] for r in rows) and restored}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("success:", report["success"])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
