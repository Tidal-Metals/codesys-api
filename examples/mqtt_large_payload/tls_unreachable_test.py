"""How does the fork's blocking TLS connect affect the PLC when the broker cannot be reached or does not speak TLS?

    python examples/mqtt_large_payload/tls_unreachable_test.py --out results/exp/tls/tls_unreachable.json
    python examples/mqtt_large_payload/tls_unreachable_test.py --cases 3,4,5 --out ...

For TLS, IP_CONTROL puts the socket in blocking mode for SysSock2Connect (plain TCP connects non-blocking), so the
MainTask scan that calls it waits for the connect to finish or fail. Each case points the demo (patch_demo_tls.py) at a
target for --window seconds, polling every 5 s, and reads the longest gap between scan starts (PLC_PRG.MaxIntervalUs;
the task runs every 50 ms), the last blocking time (IPC.TlsConnectTime, ms) and the connect attempts. Online reads that
time out are counted: TLS to a plain MQTT port made the PLC's online communication stop answering (2026-11-12), so
writes are retried until they land. The URL carries a dummy token: the real one is never sent to an address we do not
own. Afterwards the PLC is back on MQTT 3.1.1 at HQ without TLS.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402

# The IDE's online link sometimes takes 80+ s to re-establish (seen 2026-11-12 with the PLC on plain HQ, no TLS), so
# reads and writes get 300 s instead of mqtt5_test's 60; the measurements come from the PLC's own counters.
_execute = m5.execute
m5.execute = lambda code, timeout: _execute(code, max(timeout, 300))

IPC = m5.C + ".MQTT_CONTROL.IPC"
STATS = ["PLC_PRG.MaxIntervalUs", "PLC_PRG.MaxCycleUs", "PLC_PRG.MaxClientUs", IPC + ".TlsConnectTime",
         IPC + ".c_status", m5.C + ".counts.CountConnectAttempt", "PLC_PRG.IsBrokerConnected"]
CASES = [  # name, host:port, TLS
    ("host up, port closed (refused)", "192.168.50.240:8883", True),
    ("TLS to a plain MQTT port (HQ mochi)", "192.168.50.240:1883", True),
    ("free address on the PLC's subnet", "192.168.50.251:8883", True),
    ("routed address that drops packets", "10.255.255.1:8883", True),
    ("baseline: plain TCP to the dropping address", "10.255.255.1:1883", False),
]
RESTORE = [("PLC_PRG.IsTlsEnabled", "FALSE"), ("PLC_PRG.BrokerUrl", "'%s'" % m5.HQ_URL),
           ("PLC_PRG.MqttLink.ProtocolVersion", "4"), (m5.C + ".DoDisconnect", "TRUE")]


def write_until_landed(values, tries: int = 15) -> int:
    for attempt in range(1, tries + 1):
        try:
            m5.write(values)
            return attempt
        except RuntimeError:
            continue
    raise RuntimeError("write never landed: %r" % values)


def run_case(name: str, target: str, is_tls: bool, window: float) -> dict:
    before = m5.read(STATS)
    write_until_landed([("PLC_PRG.IsTlsEnabled", "TRUE" if is_tls else "FALSE"),
                        ("PLC_PRG.BrokerUrl", "'token:dummy@%s'" % target), (m5.C + ".DoDisconnect", "TRUE"),
                        ("PLC_PRG.ResetStats", "TRUE")])
    started, end = time.time(), time.time() + window
    reads_ok, reads_failed, after = 0, 0, None
    while time.time() < end:
        time.sleep(5)
        try:
            after = m5.read(STATS)
            reads_ok += 1
        except RuntimeError:
            reads_failed += 1
    out = {"case": name, "target": target, "tls": is_tls, "window_s": round(time.time() - started),
           "online_reads_ok": reads_ok, "online_reads_failed": reads_failed}
    if after:
        out.update(attempts=int(after[m5.C + ".counts.CountConnectAttempt"])
                   - int(before[m5.C + ".counts.CountConnectAttempt"]),
                   max_scan_gap_ms=round(int(after["PLC_PRG.MaxIntervalUs"]) / 1000, 1),
                   max_cycle_ms=round(int(after["PLC_PRG.MaxCycleUs"]) / 1000, 1),
                   max_client_ms=round(int(after["PLC_PRG.MaxClientUs"]) / 1000, 1),
                   last_blocking_connect_ms=int(after[IPC + ".TlsConnectTime"]), c_status=after[IPC + ".c_status"],
                   connected=after["PLC_PRG.IsBrokerConnected"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--window", type=float, default=60)
    parser.add_argument("--cases", default="1,2,3,4,5", help="1-based case numbers, comma separated")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    chosen = [CASES[int(n) - 1] for n in args.cases.split(",")]
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    try:
        for name, target, is_tls in chosen:
            case = run_case(name, target, is_tls, args.window)
            print(json.dumps(case), flush=True)
            result["cases"].append(case)
    finally:
        result["restore_attempts"] = write_until_landed(RESTORE)
        connected = m5.wait_for(["PLC_PRG.IsBrokerConnected"], lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE", 90)
        result["restored"] = connected is not None
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
