"""Check every ScaleTest message on the HQ broker: all 2,000 tags, in order, with the expected values.

Usage: python examples/mqtt_large_payload/verify_scale.py --seconds 400 [--out result.json]
Recomputes names and values from the sequence number with the same formulas as ScaleTest.
Handles both formats: "tag:value" lines (optionally "tag:value:ms", one snapshot time for the whole message)
and publish-map groups "[Gn, v1, ...]". For timestamped messages it records arrival time minus the PLC's
timestamp; that includes the PLC-to-PC clock offset, so compare the spread, not the absolute value.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

TOPIC = "raw_data_demo/scale"
TAG_COUNT, BOOL_COUNT, INT_COUNT, GROUP_SIZE = 2000, 1000, 500, 100
PREFIXES = ["TT", "PT", "FT", "LT", "XV", "HS", "ZS", "PIT", "FIT", "TIT", "LIT", "AIT"]
SUFFIXES = ["A", "B", "S", "V"]
REAL_TOLERANCE = 0.006


def name(index):
    text = "%s-%d" % (PREFIXES[(index - 1) % 12], 1000 + index)
    return text + SUFFIXES[(index // 3) % 4] if index % 3 == 0 else text


def expected(index, sequence):
    """(kind, value) for tag number index (1-based)."""
    if index <= BOOL_COUNT:
        return "bool", "1" if (index + sequence) % 3 == 0 else "0"
    if index <= BOOL_COUNT + INT_COUNT:
        k = index - BOOL_COUNT
        return "int", str((k * 37 + sequence) % 20000 - 10000)
    k = index - BOOL_COUNT - INT_COUNT
    return "real", ((k * 1237 + sequence * 17) % 200000 - 100000) / 100.0


def value_problem(index, sequence, text):
    kind, want = expected(index, sequence)
    if kind != "real":
        return None if text == want else "tag %d is %r, expected %r" % (index, text, want)
    try:
        return None if abs(float(text) - want) <= REAL_TOLERANCE else "tag %d is %s, expected %.2f" % (index, text, want)
    except ValueError:
        return "tag %d is not a number: %r" % (index, text)


def check_tag_value(lines):
    """(sequence, timestamp ms or None, problem or None)."""
    head, _, seq_text = lines[0].partition(":")
    if head != "SCALE-SEQ" or not seq_text.isdigit():
        return None, None, "bad header %r" % lines[0]
    sequence = int(seq_text)
    if len(lines) != TAG_COUNT + 1:
        return sequence, None, "%d tag lines, expected %d" % (len(lines) - 1, TAG_COUNT)
    stamps = set()
    for index in range(1, TAG_COUNT + 1):
        tag, separator, rest = lines[index].partition(":")
        value, _, stamp = rest.partition(":")
        if tag != name(index) or not separator:
            return sequence, None, "line %r where %s was expected" % (lines[index], name(index))
        if stamp and not (stamp.isdigit() and len(stamp) == 13):
            return sequence, None, "line %r: timestamp is not 13 digits" % lines[index]
        stamps.add(stamp)
        problem = value_problem(index, sequence, value)
        if problem:
            return sequence, None, problem
    if len(stamps) != 1:
        return sequence, None, "%d different timestamps in one message" % len(stamps)
    stamp = stamps.pop()
    return sequence, int(stamp) if stamp else None, None


def check_positional(lines):
    if not (lines[0].startswith("[SCALE_SEQ, ") and lines[0].endswith("]")):
        return None, None, "bad header %r" % lines[0]
    sequence = int(lines[0][len("[SCALE_SEQ, "):-1])
    groups = TAG_COUNT // GROUP_SIZE
    if len(lines) != groups + 1:
        return sequence, None, "%d group lines, expected %d" % (len(lines) - 1, groups)
    for group in range(1, groups + 1):
        line = lines[group]
        parts = [part.strip() for part in line[1:-1].split(",")] if line.startswith("[") and line.endswith("]") else []
        if not parts or parts[0] != "G%d" % group or len(parts) != GROUP_SIZE + 1:
            return sequence, None, "group line %d malformed: %r" % (group, line[:60])
        for offset, text in enumerate(parts[1:]):
            problem = value_problem((group - 1) * GROUP_SIZE + offset + 1, sequence, text)
            if problem:
                return sequence, None, problem
    return sequence, None, None


def check(payload):
    text = payload.decode("ascii", errors="replace")
    if not text.endswith("\n"):
        return None, None, None, "no trailing newline (truncated?)"
    lines = text[:-1].split("\n")
    fmt = "positional" if lines[0].startswith("[") else "tagvalue"
    sequence, stamp, problem = (check_positional if fmt == "positional" else check_tag_value)(lines)
    return fmt, sequence, stamp, problem


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.50.240")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--seconds", type=float, default=400)
    parser.add_argument("--out")
    args = parser.parse_args()
    lock = threading.Lock()
    results = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(TOPIC, qos=1)

    def on_message(client, userdata, message):
        arrived_ms = time.time() * 1000.0
        fmt, sequence, stamp, problem = check(message.payload)
        with lock:
            results.append({"format": fmt, "sequence": sequence, "bytes": len(message.payload), "problem": problem,
                            "ageMs": None if stamp is None else round(arrived_ms - stamp, 1)})

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="scale-verifier-%d" % int(time.time()))
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=20)
    client.loop_start()
    time.sleep(args.seconds)
    client.loop_stop()
    client.disconnect()
    summary = {"topic": TOPIC, "seconds": args.seconds, "byFormat": {}}
    for fmt in ("tagvalue", "positional"):
        rows = [r for r in results if r["format"] == fmt]
        failures = [r for r in rows if r["problem"]]
        sequences = sorted(r["sequence"] for r in rows if r["sequence"] is not None)
        summary["byFormat"][fmt] = {
            "messages": len(rows), "allCorrect": bool(rows) and not failures,
            "valuesChecked": TAG_COUNT * (len(rows) - len(failures)),
            "bytesMin": min((r["bytes"] for r in rows), default=0), "bytesMax": max((r["bytes"] for r in rows), default=0),
            "sequenceGaps": [b for a, b in zip(sequences, sequences[1:]) if b != a + 1],
            "failures": failures[:5],
        }
        ages = sorted(r["ageMs"] for r in rows if r["ageMs"] is not None)
        if ages:
            summary["byFormat"][fmt]["timestamped"] = len(ages)
            summary["byFormat"][fmt]["arrivalMinusStampMs"] = {
                "min": ages[0], "median": ages[len(ages) // 2], "max": ages[-1], "spread": round(ages[-1] - ages[0], 1)}
    summary["unparsed"] = [r for r in results if r["format"] is None][:5]
    text = json.dumps(summary, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if all(v["allCorrect"] for v in summary["byFormat"].values() if v["messages"]) else 1


if __name__ == "__main__":
    sys.exit(main())
