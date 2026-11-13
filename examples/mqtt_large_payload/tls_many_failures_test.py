"""Many failed TLS handshakes in a row, then a good one: does anything leak (CODESYS-MQTT docs/tls-design.md)?

    python examples/mqtt_large_payload/tls_many_failures_test.py --attempts 200 --out results/exp/tls/tls_many_failures.json

Needs what tls_client_test.py needs. Alternates the URL between two brokers whose certificates are rejected (self-signed
8887, CA-signed for another IP 8888). A new URL cuts the client's TLS back-off, so attempts follow each other at the
pace of the online writes. Each attempt creates and frees a TLS context and a socket. A leak would show as a context or
socket creation failure (TLS status CONTEXT_FAILED / SOCKET_FAILED) or as a final trusted connect that fails. Also
records the client's dynamic memory use (MQTT_IN_OUT.dynMemUsage) before and after.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import tls_client_test as tc  # noqa: E402  (its import also gives every IDE call 300 s)

C = m5.C
WATCH = [C + ".counts.CountConnectAttempt", C + ".ERROR_C", C + ".ERROR_T", "PLC_PRG.IsBrokerConnected",
         "PLC_PRG.MqttLink.dynMemUsage"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attempts", type=int, default=200)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    urls = [tc.url(8887), tc.url(8888)]
    try:
        m5.write([("PLC_PRG.TlsConfig." + k, v) for k, v in tc.DEFAULTS.items()]
                 + [("PLC_PRG.IsTlsEnabled", "TRUE"), ("PLC_PRG.MqttLink.ProtocolVersion", "5")])
        first = m5.read(WATCH)
        result["before"] = m5.short(first)
        start_attempts = int(first[C + ".counts.CountConnectAttempt"])
        statuses, index, started = {}, 0, time.time()
        m5.write([("PLC_PRG.BrokerUrl", "'%s'" % urls[0]), (C + ".DoDisconnect", "TRUE")])
        last_attempts = start_attempts
        while last_attempts - start_attempts < args.attempts and time.time() - started < args.attempts * 15:
            values = m5.read(WATCH)
            attempts = int(values[C + ".counts.CountConnectAttempt"])
            if int(values[C + ".ERROR_T"]) == 2:
                status = tc.TLS_STATUS.get(int(values[C + ".ERROR_C"]) >> 24, int(values[C + ".ERROR_C"]) >> 24)
                statuses[str(status)] = statuses.get(str(status), 0) + 1
            if attempts != last_attempts:
                last_attempts = attempts
                index += 1
                m5.write([("PLC_PRG.BrokerUrl", "'%s'" % urls[index % 2])])
                if index % 25 == 0:
                    print("attempts", attempts - start_attempts, "after %.0f s" % (time.time() - started),
                          json.dumps(statuses), flush=True)
        result["failed_attempts"] = last_attempts - start_attempts
        result["seconds"] = round(time.time() - started)
        result["statuses_seen"] = statuses
        result["after_failures"] = m5.short(m5.read(WATCH))
        m5.write([("PLC_PRG.BrokerUrl", "'%s'" % tc.url(8886)), (C + ".DoDisconnect", "TRUE")])
        ok = m5.wait_for(["PLC_PRG.IsBrokerConnected", C + ".MQTT_INFO.IsTlsVerified"],
                         lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE" and v[C + ".MQTT_INFO.IsTlsVerified"] == "TRUE",
                         120)
        result["trusted_connect_after"] = ok is not None
        result["final"] = m5.short(m5.read(WATCH))
        print(json.dumps({k: v for k, v in result.items() if k not in ("before",)}), flush=True)
    finally:
        m5.write([("PLC_PRG.IsTlsEnabled", "FALSE")] + [("PLC_PRG.TlsConfig." + k, v) for k, v in tc.DEFAULTS.items()])
        result["restored"] = m5.reconnect(m5.HQ_URL, "4") is not None
        print("restored to HQ 3.1.1:", result["restored"], flush=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
