"""Check the two-task bench's messages on the HQ broker: every message complete, every line "name:value".

Usage: python examples/plc_architecture/bench/verify_arch.py --seconds 70 [--tags 2000] [--out result.json]
A full message has one line per tag, each tag once; values are numbers or NaN.
"""
import argparse
import json
import math
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

TOPIC = "raw_data_demo/arch"


def check(payload, tag_count, expected):
    """(tag count, problem, bus summary). expected: tag name -> value, or "temperature" for a thermocouple."""
    text = payload.decode("ascii", errors="replace")
    if not text.endswith("\n"):
        return 0, "no trailing newline", None
    values = {}
    for line in text[:-1].split("\n"):
        name, separator, value = line.partition(":")
        if not separator or not name:
            return len(values), "bad line %r" % line[:40], None
        try:
            values[name] = float(value)
        except ValueError:
            return len(values), "value is not a number: %r" % line[:40], None
        if list(values).count(name) > 1:
            return len(values), "%s twice" % name, None
    if len(values) != tag_count:
        return len(values), "%d tags, expected %d" % (len(values), tag_count), None
    bus = {"match": 0, "mismatch": [], "temperatures": [], "nan": 0}
    for name, want in expected.items():
        if name.startswith("_") or name not in values:
            continue
        got = values[name]
        if want == "nan":
            if math.isnan(got):
                bus["match"] += 1
            else:
                bus["mismatch"].append((name, got, want))
        elif math.isnan(got):
            bus["nan"] += 1
        elif want == "temperature":
            bus["temperatures"].append(got)
        elif abs(got - want) <= 0.051:
            bus["match"] += 1
        else:
            bus["mismatch"].append((name, got, want))
    if "_setpoint" in expected:
        bus["setpoint"] = values.get(expected["_setpoint"])
        bus["setpointFeedback"] = values.get(expected["_setpoint_feedback"])
    return len(values), None, bus


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.50.240")
    parser.add_argument("--seconds", type=float, default=70)
    parser.add_argument("--tags", type=int, default=2000)
    parser.add_argument("--expected", help="expected_bus_values.json from make_bench_sources.py")
    parser.add_argument("--out")
    args = parser.parse_args()
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8")) if args.expected else {}
    rows, lock = [], threading.Lock()

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(TOPIC, qos=1)

    def on_message(client, userdata, message):
        arrived = time.time()
        tags, problem, bus = check(message.payload, args.tags, expected)
        with lock:
            rows.append({"t": arrived, "bytes": len(message.payload), "tags": tags, "problem": problem, "bus": bus})

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="arch-verifier-%d" % int(time.time()))
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, 1883, keepalive=20)
    client.loop_start()
    time.sleep(args.seconds)
    client.loop_stop()
    client.disconnect()
    gaps = [b["t"] - a["t"] for a, b in zip(rows, rows[1:])]
    summary = {"topic": TOPIC, "seconds": args.seconds, "messages": len(rows),
               "complete": sum(1 for r in rows if not r["problem"]), "problems": [r["problem"] for r in rows if r["problem"]][:5],
               "bytesMin": min((r["bytes"] for r in rows), default=0), "bytesMax": max((r["bytes"] for r in rows), default=0),
               "gapMinS": round(min(gaps), 3) if gaps else None, "gapMaxS": round(max(gaps), 3) if gaps else None,
               "gapMeanS": round(sum(gaps) / len(gaps), 3) if gaps else None}
    buses = [r["bus"] for r in rows if r["bus"]]
    if buses:
        temperatures = [t for b in buses for t in b["temperatures"]]
        summary["bus"] = {
            "messages": len(buses), "minMatch": min(b["match"] for b in buses), "maxMatch": max(b["match"] for b in buses),
            "mismatches": sum(len(b["mismatch"]) for b in buses), "mismatchSample": [m for b in buses for m in b["mismatch"]][:5],
            "nanMin": min(b["nan"] for b in buses), "nanMax": max(b["nan"] for b in buses),
            "temperatureRange": [min(temperatures), max(temperatures)] if temperatures else None,
            "lastSetpoint": buses[-1].get("setpoint"), "lastSetpointFeedback": buses[-1].get("setpointFeedback")}
    text = json.dumps(summary, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if rows and summary["complete"] == len(rows) and not math.isnan(len(rows)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
