"""A deliberate close (MqttClient ENABLE FALSE) with and without a birth message, library 1.4.0.0.

    python examples/mqtt_large_payload/will_enable_test.py [--out results/exp/sfw/will_enable.json]

Needs the demo patched by patch_demo_enable_switch.py (PLC_PRG.IsClientEnabled drives ENABLE). Against the temporary
MQTTug on the dev VM (192.168.50.142:1887), with the will on STATUS_TOPIC (as in will_test.py), for MQTT 5 and 3.1.1:
  * birth set (the liveness contract): ENABLE FALSE closes the connection without a DISCONNECT, so the broker
    publishes the will 'offline' at once; ENABLE TRUE reconnects and publishes 'online';
  * no birth (the original behaviour): ENABLE FALSE sends DISCONNECT, so the broker discards the will and the status
    topic gets nothing.
Tokens as in will_test.py. Afterwards the PLC is back on MQTT 3.1.1 at HQ with the default will and ENABLE TRUE.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import will_test as wt  # noqa: E402

NO_BIRTH = [(k, v) for k, v in wt.CONTRACT if k != "PLC_PRG.MqttLink.BirthMessage"] + [
    ("PLC_PRG.MqttLink.BirthMessage", "''")]


def wait_status(watcher, payload, seconds):
    """Seconds until payload arrives on the status topic (None if it doesn't), and everything that arrived."""
    start, seen = time.time(), []
    while time.time() - start < seconds:
        seen += watcher.take()
        if any(message == payload for message, _ in seen):
            return round(time.time() - start, 2), seen
        time.sleep(0.1)
    return None, seen


def run_case(watcher, secret, version, settings, expect_offline):
    case = {"connect": wt.connect_plc(wt.url(secret), version, settings)}
    time.sleep(2.0)
    watcher.take()
    m5.write([("PLC_PRG.IsClientEnabled", "FALSE")])
    seconds, seen = wait_status(watcher, "offline", 6.0 if expect_offline else 8.0)
    case["after_enable_false"] = {"offline_after_s": seconds, "status": seen,
                                  "plc": wt.short(m5.read(wt.STATE))}
    m5.write([("PLC_PRG.IsClientEnabled", "TRUE")])
    seconds, seen = wait_status(watcher, "online", 20.0) if expect_offline else (None, [])
    case["after_enable_true"] = {"online_after_s": seconds, "status": seen, "reconnected": wt.wait_connected()}
    case["ok"] = (case["after_enable_false"]["offline_after_s"] is not None) == expect_offline and (
        not expect_offline or seconds is not None)
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    secret = wt.token("sfw_plc_nowill.token")
    results = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": {}}
    watcher = None
    try:
        wt.clear_retained()
        watcher = wt.Watcher("observer-status")
        for version, label in (("5", "v5"), ("4", "v311")):
            results["cases"][label + "_birth"] = run_case(watcher, secret, version, wt.CONTRACT, True)
            results["cases"][label + "_no_birth"] = run_case(watcher, secret, version, NO_BIRTH, False)
        wt.clear_retained()
    finally:
        if watcher:
            watcher.close()
        m5.write([("PLC_PRG.IsClientEnabled", "TRUE")] + wt.DEFAULT_WILL)
        m5.reconnect(m5.HQ_URL, "4")
    results["ok"] = all(case["ok"] for case in results["cases"].values())
    print(json.dumps(results, indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
