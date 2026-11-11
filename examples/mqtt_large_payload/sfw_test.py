"""MqttStoreForward (library 1.4.0.0) on the bench PLC, end to end: StoreForwardTest pushes sequence-numbered samples
stamped with the PLC's capture time (_TS) on raw_data/sfw/bench, through the block, to a temporary MQTTug on the dev VM
(192.168.50.142:1887); Marigraf stores them in a throwaway Postgres there, and an observer on this desktop records
arrival times.

    python examples/mqtt_large_payload/sfw_test.py [case ...] [--outage 120] [--out results/exp/sfw/<name>.json]

Cases: steady, outage (observer subscribed), outage_marigraf (no observer: the PLC must hold on 0x10 until Marigraf is
back), overflow, large (32 KB samples), refused, v311 (HQ, MQTT 3.1.1, no outage), realistic and realistic_marigraf.
The realistic cases run RealisticSfwTest instead: a slow stream (26 KB a second on raw_data/sfw/slow) and a fast one
(5 KB every 100 ms on raw_data/sfw/fast) through two blocks (--two-blocks, the default) or one (--one-block), a 30 s
broker outage unless --outage is given, then a drain; per stream sequences, losses and delays (the observer subscribes
raw_data/sfw/#; realistic_marigraf has none) and Marigraf's rows of SFW/slow_seq and SFW/fast_seq.
Needs the demo copy patched by patch_demo_store_forward.py, the VM stack from ~/tmp/sfw-bench/bin (broker, marigraf,
postgres) and the tokens in tmp/mqtt5_bench/sfw_plc.token and sfw_observer.token. Afterwards the PLC is back on
MQTT 3.1.1 at HQ with the tests off and the client loop settings it had.
"""
import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402

VM = "ktritz@192.168.50.142"
VM_BIN = "~/tmp/sfw-bench/bin"
BROKER_HOST, BROKER_PORT = "192.168.50.142", 1887
HQ_HOST, HQ_PORT = "192.168.50.240", 1883
TOPIC = "raw_data/sfw/bench"
T = "StoreForwardTest."
B = T + "Telemetry."
COUNTERS = [B + n for n in ("IsReady", "ConfigError", "Capacity", "QueuedCount", "InFlightCount", "OldestAgeMs",
                            "PushedCount", "DeliveredCount", "DroppedCount", "RefusedCount", "LiveDeferredCount",
                            "NotAcceptedCount", "InvalidCount", "QuickCloseCount", "NoSubscriberCount",
                            "LastRefuseReason", "IsHeld", "HasWork", "IsSettingClamped")]
STATS = [T + n for n in ("NextSequence", "PushFailCount", "MaxPushUs", "MaxBlockUs", "LiveHandOffScans",
                         "CheckCount", "CheckFailCount")] + \
        ["PLC_PRG.MaxScanClientUs", "PLC_PRG.MaxCycleUs", "PLC_PRG.IsBrokerConnected",
         "PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt"]
LOOP_SETTINGS = ["PLC_PRG.ClientCallsPerScan", "PLC_PRG.ClientBudgetUs", "PLC_PRG.IsSecondClientCallEnabled",
                 "PLC_PRG.SecondCallBudgetUs", "PLC_PRG.IsEarlyStopEnabled"]
# OPTIMIZATION.md's recommended loop, with the end-of-scan call the block needs (PLC_PRG also makes it when
# StoreForwardTest.IsLiveHandedOff) and the early stop on IsUnsentPending while the test is enabled
RECOMMENDED_LOOP = [("PLC_PRG.ClientCallsPerScan", "32"), ("PLC_PRG.ClientBudgetUs", "4000"),
                    ("PLC_PRG.IsSecondClientCallEnabled", "TRUE"), ("PLC_PRG.SecondCallBudgetUs", "2000"),
                    ("PLC_PRG.IsEarlyStopEnabled", "TRUE")]
# RealisticSfwTest: two streams, through BlockSlow and BlockFast or BlockSlow alone
R = "RealisticSfwTest."
REALISTIC_TOPICS = "raw_data/sfw/#"
STREAM_TAGS = {"slow": "SFW/slow_seq", "fast": "SFW/fast_seq"}
STREAM_NEXT_SEQ = {"slow": R + "SlowNextSeq", "fast": R + "FastNextSeq"}
BLOCK_OUTPUTS = ["IsReady", "ConfigError", "LastConfigureError", "Capacity", "QueuedCount", "InFlightCount",
                 "OldestAgeMs", "PushedCount", "DeliveredCount", "DroppedCount", "RefusedCount", "LiveDeferredCount",
                 "NotAcceptedCount", "InvalidCount", "QuickCloseCount", "NoSubscriberCount", "LastRefuseReason",
                 "IsHeld", "HasWork", "IsSettingClamped"]
# outputs only the adaptive-storage version has: read when present, never required
ADAPTIVE_OUTPUTS = ["CapacityBytes", "UsedBytes", "PageBytes", "LiveDroppedCount"]  # the paged storage
TIMELINE_OUTPUTS = ["QueuedCount", "InFlightCount", "OldestAgeMs", "DroppedCount", "IsHeld", "NoSubscriberCount"]
REALISTIC_STATS = [R + n for n in ("IsConfigured", "IsTwoBlocksConfigured", "ConfigureCount", "SlowSlotBytes",
                                   "FastSlotBytes", "SlowStorageBytes", "FastStorageBytes", "LastSlowConfigureError",
                                   "LastFastConfigureError", "SlowNextSeq", "FastNextSeq", "SlowPushFailCount",
                                   "FastPushFailCount", "SlowSkippedCount", "FastSkippedCount", "MaxSlowPushUs",
                                   "MaxFastPushUs", "MaxSlowBlockUs", "MaxFastBlockUs", "LiveHandOffScans",
                                   "HasWork")] + \
                  ["PLC_PRG.MaxScanClientUs", "PLC_PRG.MaxCycleUs", "PLC_PRG.IsBrokerConnected",
                   "PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt"]


def token(name: str) -> str:
    return (m5.BENCH / name).read_text(encoding="utf-8").strip()


def vm(command: str) -> str:
    return subprocess.run(["ssh", VM, command], capture_output=True, text=True, timeout=120).stdout.strip()


def ints(values: dict, prefixes=(B, T, "PLC_PRG.")) -> dict:
    out = {}
    for key, value in values.items():
        short = key
        for prefix in prefixes:
            short = short.replace(prefix, "")
        try:
            out[short] = int(value)
        except ValueError:
            out[short] = value
    return out


SEQ_KEYS = {"sfw_seq": "bench", "sfw_slow_seq": "slow", "sfw_fast_seq": "fast"}


def parse(payload: bytes):
    """(_TS, sequence, stream) from the first lines; the rest is padding (RealisticSfwTest) or sfw_pad."""
    head = payload[:256].decode("ascii", "replace").split("\n")[:3]
    fields = dict(line.split(":", 1) for line in head if ":" in line)
    for key, stream in SEQ_KEYS.items():
        if key in fields:
            return int(fields.get("_TS", 0)), int(fields[key]), stream
    return int(fields.get("_TS", 0)), 0, ""


class Observer:
    """MQTT 5 subscriber with a persistent session; records (arrival, _TS, seq, duplicate flag, stream) per message."""

    def __init__(self, host: str, port: int, secret, client_id: str = "observer-sfw-test", topic: str = TOPIC):
        self.records = []
        self.topic = topic
        self.lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        if secret:
            self.client.username_pw_set("token", secret)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=1)
        properties = Properties(PacketTypes.CONNECT)
        properties.SessionExpiryInterval = 3600
        self.client.connect(host, port, keepalive=15, clean_start=False, properties=properties)
        self.client.loop_start()
        time.sleep(1.0)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self.topic, qos=1)

    def _on_message(self, client, userdata, message):
        stamp, sequence, stream = parse(bytes(message.payload))
        with self.lock:
            self.records.append((time.time(), stamp, sequence, bool(message.dup), stream))

    def take(self):
        with self.lock:
            records, self.records = self.records, []
        return records

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def plc_url() -> str:
    return "token:%s@%s:%d" % (token("sfw_plc.token"), BROKER_HOST, BROKER_PORT)


def configure(settings) -> dict:
    """Write the test's settings, then reconfigure the block (Reset with discard, Configure)."""
    m5.write(list(settings) + [(T + "ConfigureRequest", "TRUE")])
    time.sleep(1.0)
    return ints(m5.read([B + "IsReady", B + "ConfigError", B + "Capacity"]))


def wait_drained(seconds: float) -> dict:
    values = m5.wait_for([B + "HasWork"], lambda v: v[B + "HasWork"] == "FALSE", seconds)
    return {"drained": values is not None}


def summarize(records, first_seq: int, last_seq: int) -> dict:
    seqs = [r[2] for r in records]
    seen = set(seqs)
    expected = set(range(first_seq, last_seq + 1))
    missing = sorted(expected - seen)
    return {"received": len(records), "distinct": len(seen), "duplicates": len(seqs) - len(seen),
            "missing": len(missing), "missing_first": missing[:20], "missing_ranges": ranges(missing)[:50],
            "first": first_seq, "last": last_seq}


def ranges(values) -> list:
    """Sorted integers as [first, last] runs."""
    runs = []
    for value in values:
        if runs and value == runs[-1][1] + 1:
            runs[-1][1] = value
        else:
            runs.append([value, value])
    return runs


def ages_ms(records, offset_ms: float = 0.0) -> dict:
    """Arrival minus capture (_TS), less offset_ms: with the steady-state median as the offset, the delay a sample had
    beyond the usual (the PLC's clock and this desktop's differ by seconds)."""
    ages = sorted((r[0] * 1000.0 - r[1] - offset_ms) for r in records)
    if not ages:
        return {}
    return {"n": len(ages), "p50": round(statistics.median(ages), 1),
            "p95": round(ages[max(int(len(ages) * 0.95) - 1, 0)], 1), "max": round(ages[-1], 1),
            "min": round(ages[0], 1)}


def clock_offset_ms(records) -> float:
    """The median of arrival minus capture in steady state: the clock offset plus the usual delay."""
    return statistics.median(r[0] * 1000.0 - r[1] for r in records)


def marigraf(first_ms: int, last_ms: int, tag: str = "SFW/seq") -> str:
    return vm("%s/query.sh %d %d %s" % (VM_BIN, first_ms, last_ms, tag))


def start_pushing(period: str = "T#100MS", pad: int = 0) -> int:
    first = int(m5.read([T + "NextSequence"])[T + "NextSequence"])
    m5.write([(T + "PushPeriod", period), (T + "PadBytes", str(pad)), (T + "IsPushing", "TRUE"),
              (T + "ResetStats", "TRUE"), ("PLC_PRG.ResetStats", "TRUE"), (T + "IsEnabled", "TRUE")])
    return max(first, 1)


def stop_pushing() -> int:
    m5.write([(T + "IsPushing", "FALSE")])
    time.sleep(0.5)
    return int(m5.read([T + "NextSequence"])[T + "NextSequence"]) - 1


def snapshot() -> dict:
    return ints(m5.read(COUNTERS + STATS))


def run_steady(args, observer) -> dict:
    first = start_pushing()
    start_ms = int(time.time() * 1000)
    time.sleep(args.seconds)
    last = stop_pushing()
    drained = wait_drained(30)
    time.sleep(2)
    records = [r for r in observer.take() if r[2] >= first]
    offset = clock_offset_ms(records) if records else 0.0
    return {"case": "steady", "plc": snapshot(), **drained, "observer": summarize(records, first, last),
            "clock_offset_ms": round(offset, 1), "extra_delay_ms": ages_ms(records, offset),
            "marigraf": marigraf(start_ms - 60000, int(time.time() * 1000) + 60000)}


def outage(args, observer, label: str, period: str = "T#100MS", pad: int = 0) -> dict:
    """Push, stop the broker for args.outage s, start it, keep pushing through the drain, then stop."""
    first = start_pushing(period, pad)
    start_ms = int(time.time() * 1000)
    time.sleep(args.before)
    before = observer.take() if observer else []
    stop_at = time.time()
    vm("%s/broker-stop.sh" % VM_BIN)
    timeline = []
    while time.time() - stop_at < args.outage:
        timeline.append((round(time.time() - stop_at, 1), ints(m5.read([B + "QueuedCount", B + "InFlightCount",
                                                                         B + "OldestAgeMs", B + "DroppedCount"]))))
        time.sleep(5)
    vm("%s/broker-start.sh" % VM_BIN)
    restart_at = time.time()
    connected = m5.wait_for(["PLC_PRG.IsBrokerConnected"], lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE", 60)
    reconnect_at = time.time()
    drain_end = None
    peak = 0
    while time.time() - restart_at < args.drain_limit:
        v = ints(m5.read([B + "QueuedCount", B + "InFlightCount", B + "IsHeld", B + "NoSubscriberCount",
                          B + "OldestAgeMs"]))
        peak = max(peak, v["QueuedCount"])
        timeline.append((round(time.time() - stop_at, 1), v))
        if v["QueuedCount"] == 0 and v["OldestAgeMs"] < 1000:
            drain_end = time.time()
            break
        time.sleep(1)
    time.sleep(args.after)
    last = stop_pushing()
    drained = wait_drained(60)
    time.sleep(3)
    records = observer.take() if observer else []
    result = {"case": label, "outage_s": args.outage, "plc_reconnected_s": round(reconnect_at - restart_at, 1)
              if connected else None, "drain_s": round(drain_end - reconnect_at, 1) if drain_end else None,
              "queue_peak": peak, "plc": snapshot(), **drained, "timeline": timeline,
              "marigraf": marigraf(start_ms - 60000, int(time.time() * 1000) + 60000)}
    if observer:
        result.update(outage_delays(before, records, first, last, reconnect_at, drain_end))
        result["times"] = {"stop": stop_at, "restart": restart_at, "reconnect": reconnect_at, "drain_end": drain_end}
    return result


def outage_delays(before, records, first: int, last: int, reconnect_at: float, drain_end) -> dict:
    """One stream's observer records around an outage: losses, duplicates, and the delay beyond the usual (clock
    offset from the pre-outage samples) before, live during the drain and after it."""
    all_records = before + records
    steady = [r for r in before if r[2] >= first]
    offset = clock_offset_ms(steady) if steady else 0.0
    # capture time on this desktop's clock: _TS + offset (the usual delay is a few ms of it)
    end_ms = (drain_end or time.time()) * 1000
    live = [r for r in records if r[1] + offset >= reconnect_at * 1000]
    drain_live = [r for r in live if r[1] + offset <= end_ms]
    after = [r for r in live if r[1] + offset > end_ms]
    backlog = [r for r in records if r[1] + offset < reconnect_at * 1000]
    return {"observer": summarize(all_records, first, last), "clock_offset_ms": round(offset, 1),
            "extra_delay_ms_before": ages_ms(steady, offset),
            "extra_delay_ms_live_during_drain": ages_ms(drain_live, offset),
            "extra_delay_ms_after_drain": ages_ms(after, offset),
            "backlog_delivered": len(backlog),
            "records": [[round(r[0] * 1000, 1), r[1], r[2]] for r in all_records]}


def run_overflow(args, observer) -> dict:
    # 30 slots of 256 B payload; a 20 s outage at 10 a second overflows by about 170
    stride = (64 + 1 + 256 + 3) // 4 * 4
    config = configure([(T + "SlotPayloadSize", "256"), (T + "StorageBytes", str(30 * stride))])
    saved = (args.outage, args.drain_limit)
    args.outage, args.drain_limit = 20, 60
    try:
        result = outage(args, observer, "overflow")
    finally:
        args.outage, args.drain_limit = saved
        configure([(T + "SlotPayloadSize", "2048"), (T + "StorageBytes", "262144")])
    result["config"] = config
    plc = result["plc"]
    result["accounting"] = {"pushed": plc["PushedCount"], "delivered": plc["DeliveredCount"],
                            "dropped": plc["DroppedCount"], "refused": plc["RefusedCount"],
                            "balanced": plc["PushedCount"] == plc["DeliveredCount"] + plc["DroppedCount"]
                            + plc["RefusedCount"]}
    return result


def run_large(args, observer) -> dict:
    config = configure([(T + "SlotPayloadSize", "32768")])
    saved = (args.outage, args.before)
    args.outage, args.before = 30, 15
    try:
        result = outage(args, observer, "large", "T#500MS", 30000)
    finally:
        args.outage, args.before = saved
        m5.write([(T + "PadBytes", "0"), (T + "PushPeriod", "T#100MS")])
        configure([(T + "SlotPayloadSize", "2048")])
    result["config"] = config
    return result


def run_refused(args, observer) -> dict:
    before = ints(m5.read([B + "RefusedCount", B + "DeliveredCount"]))
    m5.write([(T + "Topic", "'raw_data/other/bench'")])
    first = start_pushing()
    time.sleep(5)
    m5.write([(T + "Topic", "'%s'" % TOPIC)])
    time.sleep(5)
    last = stop_pushing()
    wait_drained(20)
    time.sleep(2)
    after = snapshot()
    records = observer.take()
    return {"case": "refused", "refused": after["RefusedCount"] - before["RefusedCount"],
            "last_reason": after["LastRefuseReason"], "plc": after,
            "observer_after_switch": len([r for r in records if r[2] >= first])}


def run_v311(args, _observer) -> dict:
    hq = Observer(HQ_HOST, HQ_PORT, None, "observer-sfw-test-hq")
    try:
        if m5.reconnect(m5.HQ_URL, "4") is None:
            return {"case": "v311", "error": "PLC did not connect to HQ"}
        first = start_pushing()
        time.sleep(30)
        last = stop_pushing()
        drained = wait_drained(30)
        time.sleep(2)
        records = [r for r in hq.take() if r[2] >= first]
        offset = clock_offset_ms(records) if records else 0.0
        return {"case": "v311", "plc": snapshot(), **drained, "observer": summarize(records, first, last),
                "extra_delay_ms": ages_ms(records, offset)}
    finally:
        hq.close()
        m5.reconnect(plc_url(), "5")


def run_outage_marigraf(args, observer) -> dict:
    # the observer's subscription would match and hide the 0x10s: it disconnects, and the broker restart drops its
    # session, so after the restart only Marigraf subscribes
    observer.close()
    try:
        return outage(args, None, "outage_marigraf")
    finally:
        observer.__init__(BROKER_HOST, BROKER_PORT, token("sfw_observer.token"))


def realistic_blocks(two_blocks: bool) -> dict:
    """Block name -> path prefix of the blocks in use."""
    blocks = {"slow": R + "BlockSlow."}
    if two_blocks:
        blocks["fast"] = R + "BlockFast."
    return blocks


def read_blocks(blocks: dict, outputs) -> dict:
    """{block: {output: value}} in one read."""
    values = m5.read([prefix + n for prefix in blocks.values() for n in outputs])
    return {name: ints({k: v for k, v in values.items() if k.startswith(prefix)}, (prefix,))
            for name, prefix in blocks.items()}


def read_adaptive(blocks: dict):
    """The adaptive version's outputs, or None when the block has none of them (1.4.0.0)."""
    try:
        values = read_blocks(blocks, ADAPTIVE_OUTPUTS)
    except (RuntimeError, KeyError, ValueError):
        return None
    numeric = all(isinstance(v, int) for block in values.values() for v in block.values())
    return values if numeric else None


def realistic_configure(two_blocks: bool) -> dict:
    """RealisticSfwTest off, then Reset with discard and Configure in the chosen mode."""
    m5.write([(R + "IsEnabled", "FALSE"), (R + "IsTwoBlocks", "TRUE" if two_blocks else "FALSE"),
              (R + "ConfigureRequest", "TRUE")])
    time.sleep(1.0)
    config = ints(m5.read([R + n for n in ("IsConfigured", "IsTwoBlocksConfigured", "SlowSlotBytes", "FastSlotBytes",
                                           "SlowStorageBytes", "FastStorageBytes", "LastSlowConfigureError",
                                           "LastFastConfigureError")]), (R,))
    config["blocks"] = read_blocks(realistic_blocks(two_blocks), ["IsReady", "ConfigError", "Capacity"])
    return config


def realistic_next_seqs() -> dict:
    values = m5.read(list(STREAM_NEXT_SEQ.values()))
    return {stream: int(values[path]) for stream, path in STREAM_NEXT_SEQ.items()}


def realistic(args, observer, label: str) -> dict:
    """RealisticSfwTest: push both streams, stop the broker (args.outage s, 30 unless given), start it, wait for every
    block to drain, keep pushing args.after s, stop pushing and wait for the blocks to empty."""
    outage_s = args.outage if args.outage_given else 30
    blocks = realistic_blocks(args.two_blocks)
    config = realistic_configure(args.two_blocks)
    adaptive = read_adaptive(blocks) is not None
    watched = TIMELINE_OUTPUTS + (["UsedBytes", "LiveDroppedCount"] if adaptive else [])
    first = {stream: max(seq, 1) for stream, seq in realistic_next_seqs().items()}
    if observer:
        observer.take()
    m5.write([(R + "IsPushing", "TRUE"), (R + "ResetStats", "TRUE"), ("PLC_PRG.ResetStats", "TRUE"),
              (R + "IsEnabled", "TRUE")])
    start_ms = int(time.time() * 1000)
    time.sleep(args.before)
    before = observer.take() if observer else []
    stop_at = time.time()
    vm("%s/broker-stop.sh" % VM_BIN)
    timeline = []
    while time.time() - stop_at < outage_s:
        timeline.append((round(time.time() - stop_at, 1), read_blocks(blocks, watched)))
        time.sleep(5)
    vm("%s/broker-start.sh" % VM_BIN)
    restart_at = time.time()
    connected = m5.wait_for(["PLC_PRG.IsBrokerConnected"], lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE", 60)
    reconnect_at = time.time()
    drain_end = None
    peak = {name: 0 for name in blocks}
    while time.time() - restart_at < args.drain_limit:
        values = read_blocks(blocks, watched)
        timeline.append((round(time.time() - stop_at, 1), values))
        for name, v in values.items():
            peak[name] = max(peak[name], v["QueuedCount"])
        if all(v["QueuedCount"] == 0 and v["OldestAgeMs"] < 2000 for v in values.values()):
            drain_end = time.time()
            break
        time.sleep(1)
    time.sleep(args.after)
    m5.write([(R + "IsPushing", "FALSE")])
    time.sleep(0.5)
    last = {stream: seq - 1 for stream, seq in realistic_next_seqs().items()}
    drained = m5.wait_for([R + "HasWork"], lambda v: v[R + "HasWork"] == "FALSE", 60)
    time.sleep(3)
    records = observer.take() if observer else []
    end_ms = int(time.time() * 1000) + 60000
    plc_blocks = read_blocks(blocks, BLOCK_OUTPUTS)
    if adaptive:
        for name, values in (read_adaptive(blocks) or {}).items():
            plc_blocks[name].update(values)
    result = {"case": label, "mode": "two_blocks" if args.two_blocks else "one_block", "outage_s": outage_s,
              "config": config, "adaptive_outputs": adaptive,
              "plc_reconnected_s": round(reconnect_at - restart_at, 1) if connected else None,
              "drain_s": round(drain_end - reconnect_at, 1) if drain_end else None,
              "queue_peak": peak, "drained": drained is not None, "plc_blocks": plc_blocks,
              "plc": ints(m5.read(REALISTIC_STATS), (R, "PLC_PRG.")), "timeline": timeline,
              "times": {"stop": stop_at, "restart": restart_at, "reconnect": reconnect_at, "drain_end": drain_end},
              "streams": {}}
    for stream, tag in STREAM_TAGS.items():
        entry = {"pushed": last[stream] - first[stream] + 1, "first": first[stream], "last": last[stream],
                 "marigraf": marigraf(start_ms - 60000, end_ms, tag)}
        if observer:
            entry.update(outage_delays([r for r in before if r[4] == stream], [r for r in records if r[4] == stream],
                                       first[stream], last[stream], reconnect_at, drain_end))
        result["streams"][stream] = entry
    return result


def run_realistic(args, _observer) -> dict:
    # its own observer on both streams' topics (the shared one subscribes StoreForwardTest's topic only)
    observer = Observer(BROKER_HOST, BROKER_PORT, token("sfw_observer.token"), "observer-sfw-realistic",
                        REALISTIC_TOPICS)
    try:
        return realistic(args, observer, "realistic")
    finally:
        observer.close()


def run_realistic_marigraf(args, _observer) -> dict:
    # no subscriber but Marigraf on the realistic topics (the shared observer's raw_data/sfw/bench does not match
    # them), so the PLC must hold on 0x10 until Marigraf is back after the broker restart
    return realistic(args, None, "realistic_marigraf")


CASES = {"steady": run_steady, "outage": lambda a, o: outage(a, o, "outage"),
         "outage_marigraf": run_outage_marigraf, "overflow": run_overflow,
         "large": run_large, "refused": run_refused, "v311": run_v311,
         "realistic": run_realistic, "realistic_marigraf": run_realistic_marigraf}


def printable(result: dict) -> dict:
    """A case's result without the timeline and the raw records (they stay in the JSON)."""
    out = {k: v for k, v in result.items() if k not in ("timeline", "records", "streams")}
    if "streams" in result:
        out["streams"] = {name: {k: v for k, v in entry.items() if k != "records"}
                          for name, entry in result["streams"].items()}
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*", default=["steady", "outage", "outage_marigraf"])
    parser.add_argument("--seconds", type=float, default=60, help="steady case length")
    parser.add_argument("--outage", type=float, help="broker down, seconds (default 120, realistic cases 30)")
    parser.add_argument("--before", type=float, default=20, help="pushing before the outage, seconds")
    parser.add_argument("--after", type=float, default=15, help="pushing after the drain, seconds")
    parser.add_argument("--drain-limit", type=float, default=240)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--two-blocks", dest="two_blocks", action="store_true", default=True,
                      help="realistic cases: BlockSlow and BlockFast, a share of Storage each (default)")
    mode.add_argument("--one-block", dest="two_blocks", action="store_false",
                      help="realistic cases: BlockSlow alone for both streams")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    unknown = [name for name in args.cases if name not in CASES]
    if unknown:
        parser.error("unknown case(s) %s; cases: %s" % (", ".join(unknown), ", ".join(CASES)))
    args.outage_given = args.outage is not None
    if not args.outage_given:
        args.outage = 120
    if not vm("%s/status.sh | grep -c running" % VM_BIN).startswith("2"):
        sys.exit("broker and marigraf must both run on the VM (%s/status.sh)" % VM_BIN)
    saved_loop = m5.read(LOOP_SETTINGS)
    results = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "loop": RECOMMENDED_LOOP, "cases": []}
    observer = None
    try:
        m5.write(RECOMMENDED_LOOP)
        if m5.reconnect(plc_url(), "5") is None:
            sys.exit("the PLC did not connect to %s:%d" % (BROKER_HOST, BROKER_PORT))
        results["config"] = configure([(T + "Topic", "'%s'" % TOPIC)])
        observer = Observer(BROKER_HOST, BROKER_PORT, token("sfw_observer.token"))
        for name in args.cases:
            observer.take()
            print("== %s" % name, flush=True)
            result = CASES[name](args, observer)
            results["cases"].append(result)
            print(json.dumps(printable(result), indent=1), flush=True)
    finally:
        if observer:
            observer.close()
        m5.write([(T + "IsEnabled", "FALSE"), (T + "IsPushing", "TRUE")])
        if any(name.startswith("realistic") for name in args.cases):
            m5.write([(R + "IsEnabled", "FALSE"), (R + "IsPushing", "TRUE")])
        m5.write([(k, v.split("#")[-1]) for k, v in saved_loop.items()])
        m5.reconnect(m5.HQ_URL, "4")
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
