"""One large message or many small ones: the same data split into 1 .. 1625 messages, at QoS 0, 1 and 2.

Run from the repo root after deploy_demo.py (the demo with SplitTest; session logged in):
    python examples/mqtt_large_payload/split_test.py --out examples/mqtt_large_payload/results/exp/split/split.json
For every cell (parts x publishers x QoS x scan allowance) SplitTest sends TotalBytes (26,000 by default,
the 2,000-tag full refresh) as Parts messages through Publishers MQTTPublish instances, --rounds times.
The PLC measures each round from the first request to the last part done (ms and scans) and the most client
time in one scan; a subscriber here checks every part at the broker: each arrives once, complete, and
byte-exact (header digits, then the pattern (offset * 31 + 7) MOD 251). Scan allowances (PLC_PRG):
  call1   one client call at the start of the scan (plus the gated reply call at the end)
  budget5 calls at the start of the scan while a message is in flight, up to 5 ms (plus the reply call)
"""
import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

BROKER = "192.168.50.240"
TOPIC = "raw_data_demo/split"
S = "SplitTest"
PARTS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 1625]
PUBLISHERS = [1, 8, 32]
MAX_PARTS_ONE_PUBLISHER = 64          # one publisher sends about one message per scan: 1625 would take minutes
ALLOWANCES = {"call1": [("PLC_PRG.ClientCallsPerScan", "1"), ("PLC_PRG.ClientBudgetUs", "1000000")],
              "budget5": [("PLC_PRG.ClientCallsPerScan", "32"), ("PLC_PRG.ClientBudgetUs", "5000")]}

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE = """
on = session.ensure_online_application('', True)
def number(path):
    return int(str(on.read_value(path)).split('#')[-1])
S = 'SplitTest'
result = {'success': True, 'round': number(S + '.Round'), 'roundsDone': number(S + '.RoundsDone'),
          'sumRoundUs': number(S + '.SumRoundUs'), 'maxRoundUs': number(S + '.MaxRoundUs'),
          'sumRoundScans': number(S + '.SumRoundScans'), 'maxRoundScans': number(S + '.MaxRoundScans'),
          'maxScanClientUs': number(S + '.MaxScanClientUs'), 'partsDone': number(S + '.PartsDone'),
          'timeouts': number(S + '.TimeoutCount'),
          'active': str(on.read_value(S + '.IsRoundActive')) == 'TRUE',
          'connected': str(on.read_value('PLC_PRG.IsBrokerConnected')) == 'TRUE'}
"""


ROUNDS = """
on = session.ensure_online_application('', True)
result = {'success': True, 'roundsDone': int(str(on.read_value('SplitTest.RoundsDone')).split('#')[-1]),
          'active': str(on.read_value('SplitTest.IsRoundActive')) == 'TRUE'}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state() -> dict:
    return execute(STATE, 60)


class Checker:
    """Collects SplitTest's messages at the broker and checks them per round."""

    def __init__(self, total_bytes: int) -> None:
        self.pattern = bytes((i * 31 + 7) % 251 for i in range(total_bytes))
        self.lock = threading.Lock()
        self.bad_examples = []
        self.messages = []
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="split-test-%d" % os.getpid())
        client.on_connect = lambda c, u, f, r, p=None: c.subscribe(TOPIC, qos=2)
        client.on_message = self.on_message
        client.max_inflight_messages_set(200)
        client.connect(BROKER, 1883, keepalive=30)
        client.loop_start()
        self.client = client

    def on_message(self, client, userdata, message) -> None:
        with self.lock:
            self.messages.append((time.time(), bytes(message.payload)))

    def take(self) -> list:
        with self.lock:
            taken, self.messages = self.messages, []
        return taken

    def check(self, messages: list, rounds: range, parts: int, total: int) -> dict:
        base, rest = divmod(total, parts)
        seen = {r: {} for r in rounds}
        bad, other, arrival = 0, 0, {r: [] for r in rounds}
        for stamp, payload in messages:
            try:
                round_number, part, count = int(payload[0:6]), int(payload[6:11]), int(payload[11:16])
            except ValueError:
                bad += 1
                continue
            if round_number not in seen or count != parts:
                other += 1
                continue
            offset = part * base + min(part, rest)
            length = base + (1 if part < rest else 0)
            if len(payload) != length or payload[16:] != self.pattern[offset + 16:offset + length]:
                bad += 1
                if len(self.bad_examples) < 5:
                    expected = payload[:16] + self.pattern[offset + 16:offset + length]
                    first = next((i for i, (a, b) in enumerate(zip(payload, expected)) if a != b), None)
                    self.bad_examples.append({"round": round_number, "part": part, "length": len(payload),
                                              "expectedLength": length, "firstDifference": first,
                                              "got": payload[max(0, (first or 0) - 4):(first or 0) + 12].hex(),
                                              "expected": expected[max(0, (first or 0) - 4):(first or 0) + 12].hex()})
            seen[round_number][part] = seen[round_number].get(part, 0) + 1
            arrival[round_number].append((stamp, part))
        missing = sum(parts - len(seen[r]) for r in rounds)
        duplicates = sum(n - 1 for r in rounds for n in seen[r].values() if n > 1)
        spans = [max(a)[0] - min(a)[0] for a in arrival.values() if a]
        in_order = all([p for _, p in sorted(a)] == sorted(p for _, p in a) for a in arrival.values())
        examples, self.bad_examples = self.bad_examples, []
        return {"brokerMissing": missing, "brokerDuplicates": duplicates, "brokerBad": bad, "brokerOther": other,
                "badExamples": examples,
                "brokerInOrder": in_order,
                "brokerSpanMs": round(1000 * sum(spans) / len(spans), 1) if spans else None}


def cells(args) -> list:
    result = []
    for parts in args.parts:
        for publishers in sorted({min(p, parts) for p in args.publishers}):
            if publishers == 1 and parts > MAX_PARTS_ONE_PUBLISHER:
                continue
            for qos in args.qos:
                for allowance in args.allowances:
                    result.append((parts, publishers, qos, allowance))
    return result


def rounds_state() -> dict:
    """Only the round counter and activity: reading every result through the IDE takes seconds."""
    return execute(ROUNDS, 60)


def wait_idle(seconds: float = 60) -> dict:
    end = time.time() + seconds
    while rounds_state()["active"] and time.time() < end:
        time.sleep(0.2)
    return state()


def run_cell(checker: Checker, args, parts: int, publishers: int, qos: int, allowance: str) -> dict:
    write([(S + ".IsEnabled", "FALSE")])
    wait_idle()
    write([(S + ".TotalBytes", str(args.total)), (S + ".Parts", str(parts)), (S + ".Publishers", str(publishers)),
           (S + ".QoSLevel", str(qos)), (S + ".Period", "T#%dMS" % args.period_ms), (S + ".ResetStats", "TRUE")]
          + ALLOWANCES[allowance])
    time.sleep(0.5)
    before = state()
    checker.take()
    write([(S + ".IsEnabled", "TRUE")])
    expected_s = args.rounds * (parts / publishers * 0.25 + args.period_ms / 1000 + 1) + 10
    end = time.time() + min(expected_s, args.cell_timeout)
    while time.time() < end:
        time.sleep(0.3)
        if rounds_state()["roundsDone"] >= args.rounds:
            break
    write([(S + ".IsEnabled", "FALSE")])
    current = wait_idle()
    time.sleep(2)  # QoS 0 parts still on their way to this subscriber
    rounds = range(before["round"] + 1, current["round"] + 1)
    done = current["roundsDone"]
    row = {"parts": parts, "partBytes": args.total // parts, "publishers": publishers, "qos": qos,
           "allowance": allowance, "rounds": done,
           "roundMs": round(current["sumRoundUs"] / done / 1000, 1) if done else None,
           "maxRoundMs": round(current["maxRoundUs"] / 1000, 1) if done else None,
           "roundScans": round(current["sumRoundScans"] / done, 1) if done else None,
           "maxScanClientMs": round(current["maxScanClientUs"] / 1000, 2),
           "timeouts": current["timeouts"], "connected": current["connected"]}
    row["messagesPerSecond"] = round(parts / (row["roundMs"] / 1000), 1) if row["roundMs"] else None
    row.update(checker.check(checker.take(), rounds, parts, args.total))
    row["ok"] = (done >= 1 and row["timeouts"] == 0 and row["brokerMissing"] == 0 and row["brokerDuplicates"] == 0
                 and row["brokerBad"] == 0)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--total", type=int, default=26000)
    parser.add_argument("--parts", type=int, nargs="+", default=PARTS)
    parser.add_argument("--publishers", type=int, nargs="+", default=PUBLISHERS)
    parser.add_argument("--qos", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--allowances", nargs="+", default=list(ALLOWANCES), choices=list(ALLOWANCES))
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--period-ms", type=int, default=300, help="pause between rounds")
    parser.add_argument("--cell-timeout", type=float, default=240)
    parser.add_argument("--out")
    args = parser.parse_args()
    checker = Checker(args.total)
    report = {"total": args.total, "rows": []}
    out = Path(args.out) if args.out else None
    write([("ScaleTest.IsEnabled", "FALSE"), ("EdgeTest.IsEnabled", "FALSE"), ("PLC_PRG.PublishPeriod", "T#1H"),
           ("PLC_PRG.IsTagValueEnabled", "FALSE"), ("PLC_PRG.IsSecondClientCallEnabled", "TRUE")])
    try:
        for parts, publishers, qos, allowance in cells(args):
            row = run_cell(checker, args, parts, publishers, qos, allowance)
            report["rows"].append(row)
            print(json.dumps(row), flush=True)
            if out:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    finally:
        write([(S + ".IsEnabled", "FALSE"), ("PLC_PRG.PublishPeriod", "T#1S"), ("PLC_PRG.ClientCallsPerScan", "1"),
               ("PLC_PRG.ClientBudgetUs", "5000")])
        checker.client.loop_stop()
        checker.client.disconnect()
    report["success"] = all(r["ok"] for r in report["rows"])
    if out:
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
