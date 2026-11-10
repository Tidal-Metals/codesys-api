"""QoS 0 vs QoS 1 under a mixed-rate load: can the PLC keep up at QoS 1?

Run from the repo root after deploying the demo with MixedTest (bench_cycle.py --apply-sources; session logged in):
    python examples/mqtt_large_payload/mixed_rate_test.py --out examples/mqtt_large_payload/results/exp/qos_mixed/mixed_100ms.json
ScaleTest's 2,000 tags with full values (no report by exception) as two streams: the 1,000 BOOL and 500 DINT (75 %)
once a second on raw_data_demo/mixed/slow, the 500 REAL (25 %, analog) ten times a second on raw_data_demo/mixed/fast.
Each layout (consolidated: one message per stream; grouped: 100 or 25 tags per message) runs at QoS 0 and QoS 1 for
--seconds with the recommended client setup (up to 32 calls and 4 ms a scan, the second call at the end of the scan).
The PLC counts the periods it had to skip because the previous round was still in flight; a subscriber here checks
every value of every message and measures the age of each message at the broker (PLC UTC stamp vs this PC's clock
corrected by SNTP against the same server the PLC syncs to).
"""
import argparse
import json
import os
import socket
import statistics
import struct
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
from run_ide_script import execute  # noqa: E402
from verify_scale import name, value_problem  # noqa: E402

BROKER = "192.168.50.240"
NTP_SERVER = "192.168.50.240"
TOPIC = "raw_data_demo/mixed/+"
M = "MixedTest"
STREAMS = {"S": {"fb": "Slow", "first": 1, "last": 1500, "periodMs": 1000},
           "F": {"fb": "Fast", "first": 1501, "last": 2000, "periodMs": 100}}
# tags per message (slow, fast) and publishers (slow, fast)
LAYOUTS = {"consolidated": {"tags": (1500, 500), "publishers": (1, 1)},
           "grouped100": {"tags": (100, 100), "publishers": (8, 5)},
           "small25": {"tags": (25, 25), "publishers": (16, 20)}}
CLIENT_SETUP = [("PLC_PRG.ClientCallsPerScan", "32"), ("PLC_PRG.ClientBudgetUs", "4000"),
                ("PLC_PRG.IsSecondClientCallEnabled", "TRUE"), ("PLC_PRG.SecondCallBudgetUs", "2000"),
                ("PLC_PRG.IsClientCalledLast", "FALSE")]
QUIET = [("ScaleTest.IsEnabled", "FALSE"), ("EdgeTest.IsEnabled", "FALSE"), ("SplitTest.IsEnabled", "FALSE"),
         ("BcnfComms.IsEnabled", "FALSE"), ("PLC_PRG.PublishPeriod", "T#1H"), ("PLC_PRG.IsTagValueEnabled", "FALSE")]
RESTORE = [(M + ".IsEnabled", "FALSE"), ("PLC_PRG.PublishPeriod", "T#1S"), ("PLC_PRG.ClientCallsPerScan", "1"),
           ("PLC_PRG.ClientBudgetUs", "5000")]
STREAM_FIELDS = ["Round", "RoundsStarted", "RoundsDone", "Skipped", "SkippedOffline", "PartsDone", "TimeoutCount",
                 "OverflowCount", "LastBytes", "LastParts", "MaxBuildUs", "SumBuildUs", "MaxSendUs", "SumSendUs",
                 "MaxSendScans", "SumSendScans", "MaxLateUs", "IsRoundActive"]
TEST_FIELDS = ["ScanCount", "SumCycleUs", "MaxCycleUs", "SumScanClientUs", "MaxScanClientUs", "MaxIntervalUs",
               "MinIntervalUs", "SumClientCalls"]
CONNECTS = "PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt"

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
values = {}
for path in @@NAMES@@:
    text = str(on.read_value(path)).split('#')[-1]
    values[path] = int(text) if text.isdigit() else text
result = {'success': True, 'values': values}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def read(names) -> dict:
    result = execute(READ.replace("@@NAMES@@", repr(names)), 60)
    if not result.get("success"):
        raise RuntimeError(result)
    return result["values"]


def plc_state() -> dict:
    names = ["%s.%s.%s" % (M, s["fb"], f) for s in STREAMS.values() for f in STREAM_FIELDS]
    names += ["%s.%s" % (M, f) for f in TEST_FIELDS] + ["PLC_PRG.IsBrokerConnected", CONNECTS]
    values = read(names)
    state = {key: {f: values["%s.%s.%s" % (M, s["fb"], f)] for f in STREAM_FIELDS} for key, s in STREAMS.items()}
    state["test"] = {f: values["%s.%s" % (M, f)] for f in TEST_FIELDS}
    state["connected"] = values["PLC_PRG.IsBrokerConnected"] == "TRUE"
    state["connectAttempts"] = values[CONNECTS]
    return state


def wait_idle(seconds: float = 30) -> None:
    names = ["%s.%s.IsRoundActive" % (M, s["fb"]) for s in STREAMS.values()]
    end = time.time() + seconds
    while time.time() < end:
        if all(v == "FALSE" for v in read(names).values()):
            return
        time.sleep(0.3)
    raise RuntimeError("MixedTest still has rounds in flight after %d s" % seconds)


def sntp_offset_ms(server: str = NTP_SERVER) -> float:
    """Server clock minus this PC's clock, ms (one SNTP exchange, corrected for the round trip)."""
    packet = b"\x1b" + 47 * b"\0"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2)
        t1 = time.time()
        sock.sendto(packet, (server, 123))
        data, _ = sock.recvfrom(48)
        t4 = time.time()
    def stamp(offset):
        seconds, fraction = struct.unpack("!II", data[offset:offset + 8])
        return seconds - 2208988800 + fraction / 2 ** 32
    t2, t3 = stamp(32), stamp(40)
    return 1000 * ((t2 - t1) + (t3 - t4)) / 2


def percentiles(values: list) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    def at(q):
        return round(ordered[min(len(ordered) - 1, int(q * len(ordered)))], 1)
    return {"min": round(ordered[0], 1), "p50": at(0.5), "p90": at(0.9), "p99": at(0.99), "max": round(ordered[-1], 1),
            "mean": round(statistics.fmean(ordered), 1)}


class Checker:
    """Collects MixedTest's messages at the broker; checks them after each cell."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.messages = []
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="mixed-test-%d" % os.getpid())
        client.on_connect = lambda c, u, f, r, p=None: c.subscribe(TOPIC, qos=1)
        client.on_message = self.on_message
        client.max_inflight_messages_set(200)
        client.connect(BROKER, 1883, keepalive=30)
        client.loop_start()
        self.client = client

    def on_message(self, client, userdata, message) -> None:
        arrived = time.time()
        with self.lock:
            self.messages.append((arrived, bytes(message.payload)))

    def take(self) -> list:
        with self.lock:
            taken, self.messages = self.messages, []
        return taken

    @staticmethod
    def check_lines(lines: list, first: int, round_number: int) -> str | None:
        for offset, line in enumerate(lines):
            index = first + offset
            tag, separator, value = line.partition(":")
            if tag != name(index) or not separator:
                return "line %r where %s was expected" % (line[:40], name(index))
            problem = value_problem(index, round_number, value)
            if problem:
                return problem
        return None

    def check(self, messages: list, rounds: dict, tags: dict, offset_ms: float) -> dict:
        """rounds: stream -> range of round numbers the PLC started; tags: stream -> tags per message."""
        result = {}
        seen = {s: {r: {} for r in rounds[s]} for s in STREAMS}
        ages = {s: [] for s in STREAMS}
        last_arrival = {s: {} for s in STREAMS}
        stamps = {s: {} for s in STREAMS}
        bad, other, examples = {s: 0 for s in STREAMS}, 0, []
        for arrived, payload in messages:
            text = payload.decode("ascii", errors="replace")
            lines = text[:-1].split("\n") if text.endswith("\n") else None
            head = lines[0].split(":") if lines else []
            if len(head) != 6 or head[0] != "MIX" or head[1] not in STREAMS:
                other += 1
                continue
            stream = head[1]
            try:
                round_number, part, parts, stamp = int(head[2]), int(head[3]), int(head[4]), int(head[5])
            except ValueError:
                bad[stream] += 1
                continue
            if round_number not in seen[stream]:
                other += 1
                continue
            spec = STREAMS[stream]
            per = tags[stream]
            first = spec["first"] + part * per
            last = min(spec["last"], first + per - 1)
            expected_parts = (spec["last"] - spec["first"] + per) // per
            problem = None
            if parts != expected_parts or part >= parts:
                problem = "part %d of %d, expected %d parts" % (part, parts, expected_parts)
            elif len(lines) - 1 != last - first + 1:
                problem = "%d tag lines, expected %d" % (len(lines) - 1, last - first + 1)
            else:
                problem = self.check_lines(lines[1:], first, round_number)
            if problem:
                bad[stream] += 1
                if len(examples) < 5:
                    examples.append({"stream": stream, "round": round_number, "part": part, "problem": problem})
            seen[stream][round_number][part] = seen[stream][round_number].get(part, 0) + 1
            arrived_ms = arrived * 1000 + offset_ms
            ages[stream].append(arrived_ms - stamp)
            last_arrival[stream][round_number] = max(last_arrival[stream].get(round_number, 0), arrived_ms)
            stamps[stream][round_number] = stamp
        for stream, spec in STREAMS.items():
            per = tags[stream]
            expected_parts = (spec["last"] - spec["first"] + per) // per
            got = seen[stream]
            complete = sorted(r for r, parts in got.items() if len(parts) == expected_parts)
            # completion time of each round at the broker, and the gap between consecutive complete rounds
            done_at = [last_arrival[stream][r] for r in complete]
            gaps = [b - a for a, b in zip(done_at, done_at[1:])]
            round_age = [last_arrival[stream][r] - stamps[stream][r] for r in complete]
            result[stream] = {
                "roundsExpected": len(got), "roundsComplete": len(complete),
                "partsMissing": sum(expected_parts - len(parts) for parts in got.values()),
                "partsDuplicated": sum(n - 1 for parts in got.values() for n in parts.values() if n > 1),
                "partsBad": bad[stream],
                "valuesChecked": sum(len(parts) for parts in got.values()) * per,
                "messageAgeMs": percentiles(ages[stream]),
                "roundAgeMs": percentiles(round_age),
                "roundGapMs": percentiles(gaps),
                "gapsOver1_5Periods": sum(1 for g in gaps if g > 1.5 * spec["periodMs"]),
            }
        result["otherMessages"] = other
        result["badExamples"] = examples
        return result


def summarize_plc(before: dict, after: dict, seconds: float) -> dict:
    out = {}
    for stream, spec in STREAMS.items():
        a = after[stream]
        done = a["RoundsDone"]
        due = a["RoundsStarted"] + a["Skipped"] + a["SkippedOffline"]
        out[stream] = {
            "periodsDue": due, "roundsStarted": a["RoundsStarted"], "roundsDone": done,
            "skipped": a["Skipped"], "skippedOffline": a["SkippedOffline"],
            "keptUpPercent": round(100.0 * a["RoundsStarted"] / due, 2) if due else None,
            "timeouts": a["TimeoutCount"], "overflows": a["OverflowCount"],
            "bytesPerRound": a["LastBytes"], "messagesPerRound": a["LastParts"],
            "buildMs": round(a["SumBuildUs"] / a["RoundsStarted"] / 1000, 2) if a["RoundsStarted"] else None,
            "maxBuildMs": round(a["MaxBuildUs"] / 1000, 2),
            "sendMs": round(a["SumSendUs"] / done / 1000, 1) if done else None,
            "maxSendMs": round(a["MaxSendUs"] / 1000, 1),
            "sendScans": round(a["SumSendScans"] / done, 2) if done else None,
            "maxSendScans": a["MaxSendScans"], "maxLateMs": round(a["MaxLateUs"] / 1000, 1),
        }
    t = after["test"]
    scans = t["ScanCount"] or 1
    out["scan"] = {"scans": t["ScanCount"], "cycleMs": round(t["SumCycleUs"] / scans / 1000, 2),
                   "maxCycleMs": round(t["MaxCycleUs"] / 1000, 2),
                   "clientMs": round(t["SumScanClientUs"] / scans / 1000, 2),
                   "maxClientMs": round(t["MaxScanClientUs"] / 1000, 2),
                   "clientCallsPerScan": round(t["SumClientCalls"] / scans, 2),
                   "intervalMs": [round(t["MinIntervalUs"] / 1000, 1), round(t["MaxIntervalUs"] / 1000, 1)],
                   "taskLoadPercent": round(100.0 * t["SumCycleUs"] / 1e6 / seconds, 2)}
    out["reconnects"] = after["connectAttempts"] - before["connectAttempts"]
    out["connected"] = after["connected"]
    return out


def run_cell(checker: Checker, args, layout: str, qos: int) -> dict:
    spec = LAYOUTS[layout]
    write([(M + ".IsEnabled", "FALSE")])
    wait_idle()
    write([(M + ".QoSLevel", str(qos)),
           (M + ".SlowTagsPerMessage", str(spec["tags"][0])), (M + ".FastTagsPerMessage", str(spec["tags"][1])),
           (M + ".SlowPublishers", str(spec["publishers"][0])), (M + ".FastPublishers", str(spec["publishers"][1])),
           (M + ".ResetStats", "TRUE"), ("PLC_PRG.ResetStats", "TRUE")])
    time.sleep(1)
    before = plc_state()
    offset_ms = sntp_offset_ms()
    checker.take()
    write([(M + ".IsEnabled", "TRUE")])
    started = time.time()
    samples = []
    while time.time() - started < args.seconds:
        time.sleep(min(args.sample_s, max(0.0, args.seconds - (time.time() - started))))
        names = ["%s.%s.%s" % (M, s["fb"], f) for s in STREAMS.values() for f in ("RoundsDone", "Skipped")]
        values = read(names + ["PLC_PRG.IsBrokerConnected"])
        sample = {"t": round(time.time() - started, 1), **{k.replace(M + ".", ""): v for k, v in values.items()}}
        samples.append(sample)
        print("   %s" % json.dumps(sample), flush=True)
    write([(M + ".IsEnabled", "FALSE")])
    seconds = time.time() - started
    wait_idle()
    time.sleep(2)  # the last QoS 0 messages on their way to this subscriber
    after = plc_state()
    rounds = {s: range(before[s]["Round"] + 1, after[s]["Round"] + 1) for s in STREAMS}
    tags = {"S": spec["tags"][0], "F": spec["tags"][1]}
    row = {"layout": layout, "qos": qos, "seconds": round(seconds, 1), "tagsPerMessage": tags,
           "publishers": {"S": spec["publishers"][0], "F": spec["publishers"][1]}, "pcClockOffsetMs": round(offset_ms, 1),
           "plc": summarize_plc(before, after, seconds),
           "broker": checker.check(checker.take(), rounds, tags, offset_ms), "samples": samples}
    plc, broker = row["plc"], row["broker"]
    row["ok"] = all(plc[s]["timeouts"] == 0 and plc[s]["overflows"] == 0 and broker[s]["partsMissing"] == 0
                    and broker[s]["partsDuplicated"] == 0 and broker[s]["partsBad"] == 0 for s in STREAMS)
    row["keptUp"] = all(plc[s]["skipped"] == 0 and plc[s]["skippedOffline"] == 0 for s in STREAMS)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layouts", nargs="+", default=list(LAYOUTS), choices=list(LAYOUTS))
    parser.add_argument("--qos", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--seconds", type=float, default=300)
    parser.add_argument("--sample-s", type=float, default=30)
    parser.add_argument("--budget-us", type=int, default=4000, help="client time per scan while a message is in flight")
    parser.add_argument("--label", default="", help="free text stored with the results, e.g. the task interval")
    parser.add_argument("--out")
    args = parser.parse_args()
    out = Path(args.out) if args.out else None
    setup = [(path, str(args.budget_us) if path == "PLC_PRG.ClientBudgetUs" else value) for path, value in CLIENT_SETUP]
    checker = Checker()
    report = {"label": args.label, "started": time.strftime("%Y-%m-%d %H:%M:%S"), "clientSetup": setup,
              "taskMs": read(["PLC_PRG.IntervalUs"])["PLC_PRG.IntervalUs"] // 1000, "rows": []}
    write(QUIET + setup)
    try:
        for layout in args.layouts:
            for qos in args.qos:
                print("== %s QoS %d" % (layout, qos), flush=True)
                row = run_cell(checker, args, layout, qos)
                report["rows"].append(row)
                print(json.dumps({k: v for k, v in row.items() if k != "samples"}), flush=True)
                if out:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    finally:
        write(RESTORE)
        checker.client.loop_stop()
        checker.client.disconnect()
    report["success"] = all(r["ok"] for r in report["rows"])
    if out:
        out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
