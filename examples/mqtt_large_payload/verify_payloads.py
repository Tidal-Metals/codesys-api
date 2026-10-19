"""Subscribe to the demo topics on the HQ broker and check every published value.

Large payload (raw_data_demo) lines, built on the PLC without CONCAT:
    DEMO_SEQ:<seq>  DEMO_COUNT:<n>  DEMO_V1..DEMO_Vn:<seq*1000+i>  DEMO_END:<seq>
The CONCAT copy (raw_data_demo/concat) carries the same text; its length shows the 255 cap.

Usage: python verify_payloads.py --seconds 60 [--out result.json]
Exit code 0 only if at least one large message arrived and every one was complete and exact.
"""
import argparse
import json
import sys
import threading
import time

import paho.mqtt.client as mqtt

LARGE_TOPIC = "raw_data_demo"
CONCAT_TOPIC = "raw_data_demo/concat"


def expected_text(sequence, count):
    lines = ["DEMO_SEQ:%d" % sequence, "DEMO_COUNT:%d" % count]
    lines += ["DEMO_V%d:%d" % (index, sequence * 1000 + index) for index in range(1, count + 1)]
    lines.append("DEMO_END:%d" % sequence)
    return "".join(line + "\n" for line in lines)


def header_value(text, key):
    prefix = key + ":"
    for line in text.split("\n", 2)[:2]:
        if line.startswith(prefix) and line[len(prefix):].isdigit():
            return int(line[len(prefix):])
    return None


def check_large(payload):
    text = payload.decode("ascii", errors="replace")
    sequence, count = header_value(text, "DEMO_SEQ"), header_value(text, "DEMO_COUNT")
    report = {"sequence": sequence, "count": count, "bytes": len(payload)}
    if sequence is None or count is None:
        report.update(ok=False, problem="missing DEMO_SEQ/DEMO_COUNT header")
        return report
    expected = expected_text(sequence, count)
    report["valuesChecked"] = count
    if text == expected:
        report["ok"] = True
        return report
    mismatch = next((i for i, (a, b) in enumerate(zip(text, expected)) if a != b), min(len(text), len(expected)))
    report.update(ok=False, problem="differs from expected at byte %d" % mismatch,
                  expectedBytes=len(expected), received=text[max(0, mismatch - 40):mismatch + 40])
    return report


def check_concat(payload, large_by_sequence):
    text = payload.decode("ascii", errors="replace")
    sequence = header_value(text, "DEMO_SEQ")
    full = large_by_sequence.get(sequence)
    report = {"sequence": sequence, "bytes": len(payload), "endsWithEndLine": "DEMO_END:" in text}
    if full is not None:
        report["fullBytes"] = len(full)
        report["isPrefixOfFull"] = full.startswith(text)
    return report


def run(host, port, seconds):
    lock = threading.Lock()
    large, concat, large_text = [], [], {}

    def on_connect(client, userdata, flags, reason_code, properties=None):
        if reason_code.is_failure:
            print("connect failed:", reason_code, file=sys.stderr)
            return
        client.subscribe([(LARGE_TOPIC, 1), (CONCAT_TOPIC, 1)])

    def on_message(client, userdata, message):
        with lock:
            if message.topic == LARGE_TOPIC:
                result = check_large(message.payload)
                large.append(result)
                if result["sequence"] is not None:
                    large_text[result["sequence"]] = message.payload.decode("ascii", errors="replace")
                print("large  seq=%s bytes=%d ok=%s %s" % (result["sequence"], result["bytes"], result["ok"], result.get("problem", "")))
            elif message.topic == CONCAT_TOPIC:
                concat.append(message.payload)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mqtt-demo-verifier-%d" % int(time.time()))
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(host, port, keepalive=20)
    client.loop_start()
    time.sleep(seconds)
    client.loop_stop()
    client.disconnect()

    concat_reports = [check_concat(payload, large_text) for payload in concat]
    sequences = sorted(r["sequence"] for r in large if r["sequence"] is not None)
    gaps = [b for a, b in zip(sequences, sequences[1:]) if b != a + 1]
    return {
        "broker": "%s:%d" % (host, port),
        "seconds": seconds,
        "large": {
            "messages": len(large),
            "allExact": bool(large) and all(r["ok"] for r in large),
            "valuesChecked": sum(r.get("valuesChecked", 0) for r in large if r["ok"]),
            "bytesMin": min((r["bytes"] for r in large), default=0),
            "bytesMax": max((r["bytes"] for r in large), default=0),
            "sequenceGaps": gaps,
            "failures": [r for r in large if not r["ok"]],
        },
        "concat": {
            "messages": len(concat_reports),
            "bytes": sorted(set(r["bytes"] for r in concat_reports)),
            "samples": concat_reports[:3],
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="192.168.50.240")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--out", help="write the summary JSON here")
    args = parser.parse_args()
    summary = run(args.host, args.port, args.seconds)
    text = json.dumps(summary, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text)
    return 0 if summary["large"]["allExact"] else 1


if __name__ == "__main__":
    sys.exit(main())
