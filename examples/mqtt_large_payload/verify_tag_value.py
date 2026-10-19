"""Check the tag:value messages on the HQ broker: every expected line, in order, with a parseable value.

Usage: python examples/mqtt_large_payload/verify_tag_value.py --seconds 60 [--out result.json]
Expected tag names come from st/bcnf_style/BcnfTagValueNames.json (written by make_bcnf_copy.py).
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

TOPIC = "raw_data_demo/tagvalue"
NAMES = json.loads((Path(__file__).resolve().parent / "st" / "bcnf_style" / "BcnfTagValueNames.json").read_text())


def check(payload):
    text = payload.decode("ascii", errors="replace")
    if not text.endswith("\n"):
        return "no trailing newline (truncated?)"
    lines = text[:-1].split("\n")
    if len(lines) != len(NAMES):
        return "%d lines, expected %d" % (len(lines), len(NAMES))
    for expected, line in zip(NAMES, lines):
        tag, separator, value = line.partition(":")
        if tag != expected or not separator:
            return "line %r where %s was expected" % (line, expected)
        if value not in ("TRUE", "FALSE"):
            try:
                float(value)
            except ValueError:
                return "%s has an unparseable value %r" % (tag, value)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.50.240")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--out")
    args = parser.parse_args()
    lock = threading.Lock()
    results = []

    def on_connect(client, userdata, flags, reason_code, properties=None):
        client.subscribe(TOPIC, qos=1)

    def on_message(client, userdata, message):
        with lock:
            results.append({"bytes": len(message.payload), "problem": check(message.payload)})

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="tag-value-verifier-%d" % int(time.time()))
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=20)
    client.loop_start()
    time.sleep(args.seconds)
    client.loop_stop()
    client.disconnect()
    failures = [r for r in results if r["problem"]]
    summary = {
        "topic": TOPIC, "seconds": args.seconds, "messages": len(results), "linesPerMessage": len(NAMES),
        "linesChecked": len(NAMES) * (len(results) - len(failures)), "allCorrect": bool(results) and not failures,
        "bytes": sorted(set(r["bytes"] for r in results)), "failures": failures[:5],
    }
    text = json.dumps(summary, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if summary["allCorrect"] else 1


if __name__ == "__main__":
    sys.exit(main())
