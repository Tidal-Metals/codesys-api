"""MQTT over TLS on the bench PLC: does the fork's TLS path (CmpTls through SysSocket2) work on the P2CDS-622, how long
does the blocking connect take, and does the PLC check the broker's certificate?

    python examples/mqtt_large_payload/tls_test.py --out results/exp/tls/tls_check.json

Needs the demo copy patched with patch_demo_tls.py and deployed, and the private MQTTug started with a TLS listener on
:8886 using a self-signed certificate the PLC has no reason to trust (tmp/mqtt5_bench/tls/), next to the plain :1886.
Each case sets PLC_PRG.TlsConfig.verifyMode, connects over TLS and counts the demo's messages on the plain listener.
A connection with a peer-verifying mode means the PLC accepted an untrusted certificate. Afterwards the PLC is back on
MQTT 3.1.1 at HQ without TLS, with the library's default verifyMode.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402

TLS_PORT = 8886
IPC = m5.C + ".MQTT_CONTROL.IPC"
CFG = "PLC_PRG.TlsConfig"
LINK = [IPC + n for n in (".TLS", ".TlsConnectTime", ".c_status", ".c_ready")] + [
    "PLC_PRG.IsBrokerConnected", m5.C + ".counts.CountConnectAttempt", m5.C + ".MQTT_INFO.ConnectReasonCode",
    m5.C + ".MQTT_INFO.Broker.ProtocolLevel"]
# CmpTls.CmpTlsConstants (not OpenSSL's numbering): TLS_VERIFY_NONE 1, PEER 2, FAIL_IF_NO_PEER_CERT 4 and
# CLIENT_ONCE 8 (the last two for servers only). The library default is CLIENT_ONCE alone.
CASES = [("library default (CLIENT_ONCE)", None), ("VERIFY_NONE", 1), ("VERIFY_PEER", 2),
         ("VERIFY_PEER + CLIENT_ONCE", 10)]


def tls_url() -> str:
    return "token:%s@%s:%d" % (m5.token("plc.token"), m5.BROKER_HOST, TLS_PORT)


def try_case(name: str, verify_mode, default_mode: str) -> dict:
    m5.write([(CFG + ".verifyMode", "DWORD#%s" % (default_mode if verify_mode is None else verify_mode))])
    observer = m5.Observer("observer-tls-test")
    started = time.time()
    connected = m5.reconnect(tls_url(), "5")
    seconds = round(time.time() - started, 1)
    time.sleep(10)
    with observer.lock:
        received = len(observer.messages)
    observer.client.loop_stop()
    observer.client.disconnect()
    return {"case": name, "verifyMode": verify_mode, "connected": connected is not None, "connect_wait_s": seconds,
            "messages_in_10s": received, "link": m5.short(m5.read(LINK))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    defaults = m5.read([CFG + ".verifyMode", CFG + ".tlsMethod", CFG + ".chiperList"])
    result["defaults"] = defaults
    result["plain_before"] = m5.short(m5.read(LINK))
    try:
        m5.write([("PLC_PRG.IsTlsEnabled", "TRUE")])
        result["cases"] = []
        for name, mode in CASES:
            case = try_case(name, mode, defaults[CFG + ".verifyMode"])
            print(json.dumps(case), flush=True)
            result["cases"].append(case)
    finally:
        m5.write([("PLC_PRG.IsTlsEnabled", "FALSE"), (CFG + ".verifyMode", "DWORD#" + defaults[CFG + ".verifyMode"])])
        result["restored"] = m5.reconnect(m5.HQ_URL, "4") is not None
        result["plain_after"] = m5.short(m5.read(LINK))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
