"""Drive TlsProbe (patch_demo_tls_probe.py): a NON-BLOCKING TLS connect in its own low-priority task, against every
broker situation that hurt the blocking one, before the fork's TLS is reworked.

    python examples/mqtt_large_payload/tls_probe.py --out results/exp/tls/tls_probe.json [--no-install] [--cases a,b]

Needs the bench broker from tls/start_tls_broker.ps1 (1886 plain, 8886 CA-signed for 192.168.50.108, 8887 self-signed,
8888 CA-signed for another IP) and the CA from tls/make_bench_certs.sh compiled into TlsProbe. The trusted case runs
once before DoInstallCa adds the CA to the PLC's Trusted store, so the install's effect is visible. For each case:
the outcome, every distinct SysSock2Connect result with its call count, the longest single call (does any call
block?), the CONNACK, the close time, and the longest gaps of ProbeTask (20 ms) and MainTask (50 ms, PLC_PRG).
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

P = "TlsProbe."
NO_CALLBACK = {"IsVerifierUsed": "FALSE"}
CASES = {  # key: (description, ip, port, verify mode, extra TlsProbe settings; defaults: callback, host check, IP)
    "trusted": ("CA-signed broker, CA trusted", "192.168.50.108", 8886, 2, {}),
    "trusted_nocallback": ("CA-signed broker, no callback", "192.168.50.108", 8886, 2, NO_CALLBACK),
    "untrusted": ("self-signed broker, verify peer", "192.168.50.108", 8887, 2, {}),
    "untrusted_none": ("self-signed broker, verify none", "192.168.50.108", 8887, 1, NO_CALLBACK),
    "wronghost": ("CA-signed for another IP, host check", "192.168.50.108", 8888, 2, {}),
    "wronghost_nocheck": ("CA-signed for another IP, host check off", "192.168.50.108", 8888, 2,
                          {"IsHostCheckEnabled": "FALSE"}),
    "trusted_dns": ("CA-signed broker, matched by DNS name only", "192.168.50.108", 8886, 2,
                    {"IsIpExpected": "FALSE", "ExpectedDns": "'bench-broker.local'"}),
    "trusted_dns_wrong": ("CA-signed broker, expected DNS name not in SAN", "192.168.50.108", 8886, 2,
                          {"IsIpExpected": "FALSE", "ExpectedDns": "'other-broker.local'"}),
    "servername_wrong_ip_right": ("IP SAN right, expected name wrong: must fail", "192.168.50.108", 8886, 2,
                                  {"ExpectedDns": "'other-broker.local'"}),
    "wildcard_one_label": ("SAN *.bench.local, name mqtt.bench.local", "192.168.50.108", 8889, 2,
                           {"ExpectedDns": "'mqtt.bench.local'"}),
    "wildcard_two_labels": ("SAN *.bench.local, name a.mqtt.bench.local", "192.168.50.108", 8889, 2,
                            {"ExpectedDns": "'a.mqtt.bench.local'"}),
    "wildcard_apex": ("SAN *.bench.local, name bench.local", "192.168.50.108", 8889, 2,
                      {"ExpectedDns": "'bench.local'"}),
    "wildcard_by_ip": ("SAN *.bench.local, checked by IP", "192.168.50.108", 8889, 2, {}),
    "cnonly_name": ("no SAN, CN cn-broker.local, name check", "192.168.50.108", 8890, 2,
                    {"ExpectedDns": "'cn-broker.local'"}),
    "cnonly_ip": ("no SAN, CN cn-broker.local, IP check", "192.168.50.108", 8890, 2, {}),
    "ipdns_ip": ("DNS SAN '192.168.50.108', no IP SAN, IP check", "192.168.50.108", 8891, 2, {}),
    "ipdns_name": ("DNS SAN '192.168.50.108', name check with that text", "192.168.50.108", 8891, 2,
                   {"ExpectedDns": "'192.168.50.108'"}),
    "none_with_callback": ("self-signed, verify none, callback installed", "192.168.50.108", 8887, 1, {}),
    "refused": ("host up, port closed", "192.168.50.240", 8883, 2, {}),
    "unanswered": ("free address on the PLC's subnet", "192.168.50.251", 8883, 2, {}),
    "plain_mochi": ("plain MQTT port, mochi at HQ", "192.168.50.240", 1883, 2, {}),
    "plain_mqttug": ("plain MQTT port, MQTTug", "192.168.50.108", 1886, 2, {}),
}
DEFAULT_ORDER = ["trusted", "trusted_nocallback", "untrusted", "untrusted_none", "wronghost", "wronghost_nocheck",
                 "trusted_dns", "trusted_dns_wrong", "refused", "unanswered", "plain_mqttug", "plain_mochi"]
SETTING_DEFAULTS = {"IsVerifierUsed": "TRUE", "IsHostCheckEnabled": "TRUE", "IsIpExpected": "TRUE",
                    "ExpectedDns": "''"}
VERIFIER = ["Verifier.Calls", "Verifier.LastVerifyResult", "Verifier.LastContentResult", "Verifier.LastAltNameCount",
            "Verifier.IsHostMatched", "Verifier.LastReturn", "Verifier.LastExitResult", "Verifier.LastHostCheckResult",
            "Verifier.CheckedBy"] + ["Verifier.AltTypes[%d]" % i for i in range(4)] + [
            "Verifier.AltIps[%d]" % i for i in range(4)] + ["Verifier.AltDns[0]", "Verifier.AltDns[1]"]
RESULTS = ["IsBusy", "Attempt", "Outcome", "ContextResult", "CreateResult", "IoctlResult", "ConnectCalls",
           "ConnectResultCount", "LastConnectResult", "MaxConnectCallUs", "TotalConnectCallUs", "HandshakeMs",
           "SendResult", "SentBytes", "RecvCalls", "RecvResult", "RecvBytes", "MaxIoCallUs", "ShutdownResult",
           "CloseResult", "FreeResult", "CloseUs", "MaxScanUs", "ScanCount"]
ARRAYS = ["ConnectResults[%d]" % i for i in range(8)] + ["ConnectResultCalls[%d]" % i for i in range(8)] + [
    "Received[%d]" % i for i in range(4)]
CA = ["CaParseResult", "CaOpenResult", "CaAddResult", "CaStoreCloseResult", "CaCloseResult"]


def ip_dword(ip: str) -> int:
    a, b, c, d = (int(part) for part in ip.split("."))
    return (a << 24) | (b << 16) | (c << 8) | d


def read_probe(names) -> dict:
    values = m5.read([P + n for n in names])
    return {k[len(P):]: v.strip("'") for k, v in values.items()}


def run_case(key: str, timeout_ms: int) -> dict:
    name, ip, port, verify, extra = CASES[key]
    settings = dict(SETTING_DEFAULTS, **extra)
    m5.write([(P + "TargetIp", "DWORD#%d" % ip_dword(ip)), (P + "TargetPort", "WORD#%d" % port),
              (P + "VerifyMode", "DWORD#%d" % verify), (P + "TimeoutMs", "UDINT#%d" % timeout_ms),
              (P + "MaxScanUs", "UDINT#0"), ("PLC_PRG.ResetStats", "TRUE")]
             + [(P + k, v) for k, v in settings.items()])
    before = int(read_probe(["Attempt"])["Attempt"])
    calls_before = int(read_probe(["Verifier.Calls"])["Verifier.Calls"])
    m5.write([(P + "DoConnect", "TRUE")])
    deadline = time.time() + 2 * timeout_ms / 1000 + 60
    state = {}
    while time.time() < deadline:
        time.sleep(2)
        state = read_probe(["IsBusy", "Attempt"])
        if state["IsBusy"] == "FALSE" and int(state["Attempt"]) > before:
            break
    else:
        m5.write([(P + "DoAbort", "TRUE")])
    values = read_probe(RESULTS + ARRAYS)
    verifier = read_probe(VERIFIER)
    main = m5.read(["PLC_PRG.MaxIntervalUs", "PLC_PRG.CycleStartUs"])
    count = int(values["ConnectResultCount"])
    calls = int(verifier["Verifier.Calls"]) - calls_before
    out = {"case": key, "description": name, "target": "%s:%d" % (ip, port), "verifyMode": verify,
           "settings": extra, "finished": state.get("IsBusy") == "FALSE",
           "callback": {"calls": calls, **({k.split(".", 1)[1]: v for k, v in verifier.items() if k != "Verifier.Calls"}
                                           if calls else {})},
           "connect_results": [[int(values["ConnectResults[%d]" % i]), int(values["ConnectResultCalls[%d]" % i])]
                               for i in range(count)],
           "received": [int(values["Received[%d]" % i]) for i in range(4)] if int(values["RecvBytes"]) > 0 else [],
           "main_task_max_gap_ms": round(int(main["PLC_PRG.MaxIntervalUs"]) / 1000, 1),
           "probe_task_max_scan_ms": round(int(values["MaxScanUs"]) / 1000, 1)}
    out.update({k: values[k] for k in RESULTS if k not in ("IsBusy", "MaxScanUs", "ScanCount")})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=",".join(DEFAULT_ORDER))
    parser.add_argument("--no-install", action="store_true", help="skip the before-install run and DoInstallCa")
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": []}
    try:
        if not args.no_install:
            case = run_case("trusted", args.timeout_ms)
            case["case"] = "trusted_before_install"
            print(json.dumps(case), flush=True)
            result["cases"].append(case)
            m5.write([(P + "DoInstallCa", "TRUE")])
            time.sleep(3)
            result["ca_install"] = read_probe(CA)
            print("CA install:", json.dumps(result["ca_install"]), flush=True)
        for key in args.cases.split(","):
            case = run_case(key, args.timeout_ms)
            print(json.dumps(case), flush=True)
            result["cases"].append(case)
    finally:
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
