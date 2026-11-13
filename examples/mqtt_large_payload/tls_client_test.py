"""The reworked TLS in MqttClient (CODESYS-MQTT docs/tls-design.md) on the bench PLC, case by case.

    python examples/mqtt_large_payload/tls_client_test.py --out results/exp/tls/tls_client.json [--cases a,b] [--keep]

Needs the demo copy patched with patch_demo_tls.py (PLC_PRG.IsTlsEnabled, PLC_PRG.TlsConfig wired to MqttLink) and
deployed, the bench broker from tls/start_tls_broker.ps1, and the bench CA in the PLC's Trusted store (tls_probe.py
installs it). Each case sets TlsConfig, IsTlsEnabled and BrokerUrl, reconnects and watches for --window seconds:
connected or not, connect attempts (the TLS back-off doubles from 1 s), the client's ERROR_C/ERROR_T (the TLS status is
ERROR_C's top byte), MQTT_INFO's TLS fields, the client's last error text, and the longest MainTask scan gap (the
demo calls the client from MainTask, so a handshake's crypto shows there). Connected cases also count the demo's
messages on the broker's plain listener. Afterwards (unless --keep) the PLC is back on HQ, MQTT 3.1.1, no TLS.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402

_execute = m5.execute  # the IDE's online link sometimes stalls 80+ s; allow 300 s per call
m5.execute = lambda code, timeout: _execute(code, max(timeout, 300))

C = m5.C
HOST = "192.168.50.108"
TLS_STATUS = {20: "CONTEXT_FAILED", 21: "SOCKET_FAILED", 22: "HANDSHAKE_FAILED", 23: "NOT_TRUSTED", 24: "WRONG_HOST",
              25: "CONFIG_INVALID", 255: "CONNECT_TIMEOUT"}
WATCH = ["PLC_PRG.IsBrokerConnected", C + ".counts.CountConnectAttempt", C + ".ERROR_C", C + ".ERROR_T",
         C + ".MQTT_INFO.IsTlsActive", C + ".MQTT_INFO.IsTlsVerified", C + ".MQTT_INFO.IsTlsHostMatched",
         C + ".MQTT_INFO.TlsChainResult", C + ".MQTT_INFO.TlsConnectResult", C + ".ErrorText", C + ".TlsFailCount",
         C + ".MQTT_INFO.Broker.ProtocolLevel", "PLC_PRG.MaxIntervalUs"]
DEFAULTS = {"verifyMode": "2", "IsHostCheckEnabled": "TRUE", "ServerName": "''"}


def url(port: int, host: str = HOST, scheme: str = "", secret: str = "") -> str:
    return "%stoken:%s@%s:%d" % (scheme, secret or m5.token("plc.token"), host, port)


VM = "192.168.50.142"   # vm_tls_peers.sh: openssl s_server per certificate, and a silent listener
CASES = {  # key: (description, url builder, IsTlsEnabled, TlsConfig changes, expected outcome)
    # expected: "connect"; "reject:<TLS status>" (not connected, that status seen); "verified_then_timeout" (the
    # handshake verified the broker, which never answers MQTT: openssl s_server)
    "trusted_ip": ("CA-signed broker by IP", lambda: url(8886), True, {}, "connect"),
    "mqtts_scheme": ("mqtts:// URL, TLS input off", lambda: url(8886, scheme="mqtts://"), False, {}, "connect"),
    "servername_ok": ("by IP, ServerName names the DNS SAN", lambda: url(8886), True,
                      {"ServerName": "'bench-broker.local'"}, "connect"),
    "wildcard_servername": ("SAN *.bench.local, ServerName mqtt.bench.local", lambda: url(8889), True,
                            {"ServerName": "'mqtt.bench.local'"}, "connect"),
    "verify_none": ("self-signed broker, verifyMode NONE", lambda: url(8887), True, {"verifyMode": "1"}, "connect"),
    "untrusted": ("self-signed broker", lambda: url(8887), True, {}, "reject:NOT_TRUSTED"),
    "wronghost": ("CA-signed for another IP", lambda: url(8888), True, {}, "reject:WRONG_HOST"),
    "servername_wrong": ("IP SAN right, ServerName wrong", lambda: url(8886), True,
                         {"ServerName": "'other-broker.local'"}, "reject:WRONG_HOST"),
    "plain_port": ("TLS to MQTTug's plain port", lambda: url(1886), True, {}, "reject:HANDSHAKE_FAILED"),
    "unanswered": ("free address on the PLC's subnet", lambda: url(8883, host="192.168.50.251", secret="dummy"),
                   True, {}, "reject:CONNECT_TIMEOUT"),
    "vm_good": ("VM s_server, valid certificate", lambda: url(18892, host=VM, secret="dummy"), True, {},
                "verified_then_timeout"),
    "vm_expired": ("VM s_server, expired certificate", lambda: url(18893, host=VM, secret="dummy"), True, {},
                   "reject:NOT_TRUSTED"),
    "vm_notyet": ("VM s_server, certificate not valid yet", lambda: url(18894, host=VM, secret="dummy"), True, {},
                  "reject:NOT_TRUSTED"),
    "vm_clientonly": ("VM s_server, certificate with clientAuth EKU only", lambda: url(18895, host=VM, secret="dummy"),
                      True, {}, "verified_then_timeout"),  # accepted: CmpTls ignores key usage, so do we
    "le_a_untrusted": ("LE-shaped RSA chain A before its root is trusted", lambda: url(8892), True, {}, "reject:NOT_TRUSTED"),
    "le_a": ("LE-shaped RSA chain A, old root trusted (via the cross-signed root)", lambda: url(8892), True, {}, "connect"),
    "le_b": ("LE-shaped RSA chain B, only the new self-signed root trusted", lambda: url(8893), True, {}, "connect"),
    "le_c": ("LE-shaped ECDSA chain C (P-256 leaf, P-384 YE1, Root YE, X2), RSA root trusted", lambda: url(8894), True, {},
             "connect"),
    "vm_silent": ("VM listener that accepts TCP and never answers", lambda: url(18896, host=VM, secret="dummy"), True,
                  {}, "reject:CONNECT_TIMEOUT"),
}
ORDER = ["trusted_ip", "mqtts_scheme", "servername_ok", "wildcard_servername", "verify_none", "untrusted",
         "wronghost", "servername_wrong", "plain_port", "unanswered"]
VM_ORDER = ["vm_good", "vm_expired", "vm_notyet", "vm_clientonly", "vm_silent"]


def summarise(values: dict) -> dict:
    out = m5.short(values)
    error_c = int(values[C + ".ERROR_C"])
    out["tls_status"] = TLS_STATUS.get(error_c >> 24, error_c >> 24) if int(values[C + ".ERROR_T"]) == 2 else None
    return out


def run_case(key: str, window: float) -> dict:
    name, make_url, is_tls, config, expect = CASES[key]
    settings = dict(DEFAULTS, **config)
    observer = m5.Observer("observer-tls-client-test") if expect == "connect" else None
    before = int(m5.read([C + ".counts.CountConnectAttempt"])[C + ".counts.CountConnectAttempt"])
    m5.write([("PLC_PRG.TlsConfig." + k, v) for k, v in settings.items()]
             + [("PLC_PRG.IsTlsEnabled", "TRUE" if is_tls else "FALSE"), ("PLC_PRG.BrokerUrl", "'%s'" % make_url()),
                ("PLC_PRG.MqttLink.ProtocolVersion", "5"), (C + ".DoDisconnect", "TRUE"), ("PLC_PRG.ResetStats", "TRUE")])
    started, samples, first_connected, last_error, statuses, verified = time.time(), [], None, None, set(), False
    while time.time() - started < window:
        time.sleep(3)
        values = m5.read(WATCH)
        sample = summarise(values)
        samples.append([round(time.time() - started, 1), sample])
        if values["PLC_PRG.IsBrokerConnected"] == "TRUE" and first_connected is None:
            first_connected = round(time.time() - started, 1)
        if sample["tls_status"] is not None or int(values[C + ".ERROR_T"]) != 0:
            last_error = sample
            statuses.add(sample["tls_status"])
        verified = verified or values[C + ".MQTT_INFO.IsTlsVerified"] == "TRUE"
    final = samples[-1][1] if samples else {}
    received = 0
    if observer:
        with observer.lock:
            received = len(observer.messages)
        observer.client.loop_stop()
        observer.client.disconnect()
    attempts = int(final.get("client.counts.CountConnectAttempt", before)) - before
    connected = final.get("IsBrokerConnected") == "TRUE"
    if expect == "connect":
        passed = connected
    elif expect == "verified_then_timeout":
        passed = verified and not connected
    else:
        passed = not connected and expect.split(":", 1)[1] in statuses
    return {"case": key, "description": name, "settings": config, "tls_input": is_tls, "expected": expect,
            "connected": connected, "passed": passed, "verified_seen": verified,
            "statuses_seen": sorted(str(s) for s in statuses), "first_connected_s": first_connected,
            "attempts": attempts, "messages": received, "final": final, "last_error": last_error, "samples": samples}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=",".join(ORDER), help="case keys, or 'vm' for the dev-VM peer cases")
    parser.add_argument("--window", type=float, default=30)
    parser.add_argument("--keep", action="store_true", help="leave the PLC on the last case")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    try:
        for key in (VM_ORDER if args.cases == "vm" else args.cases.split(",")):
            case = run_case(key, args.window)
            brief = {k: case[k] for k in ("case", "passed", "expected", "connected", "verified_seen", "statuses_seen",
                                          "first_connected_s", "attempts", "messages")}
            brief.update({k: case["final"].get(k) for k in ("client.MQTT_INFO.IsTlsVerified",
                                                            "client.MQTT_INFO.IsTlsHostMatched", "MaxIntervalUs")})
            brief["error"] = case["last_error"] and {k: case["last_error"].get(k) for k in (
                "tls_status", "client.MQTT_INFO.TlsChainResult", "client.MQTT_INFO.TlsConnectResult",
                "client.ErrorText", "client.TlsFailCount")}
            print(json.dumps(brief), flush=True)
            result["cases"].append(case)
    finally:
        if not args.keep:
            m5.write([("PLC_PRG.IsTlsEnabled", "FALSE")] + [("PLC_PRG.TlsConfig." + k, v) for k, v in DEFAULTS.items()])
            result["restored"] = m5.reconnect(m5.HQ_URL, "4") is not None
            print("restored to HQ 3.1.1:", result["restored"], flush=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
