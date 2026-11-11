"""MQTTug restart-safe delivery (stage B) with the bench PLC: does a broker restart during a collector outage leave a hole
in Marigraf's history?

    python examples/mqtt_large_payload/restart_test.py --persistence on --stop clean --out results/exp/sfw/restart_a.json

StoreForwardTest pushes a sequence every 100 ms on raw_data/sfw/bench through MqttStoreForward (MQTT 5, hold on 16#10)
to the temporary MQTTug on the dev VM (192.168.50.142:1887); Marigraf stores them. The sequence:
  1. steady pushing (--before s);
  2. Marigraf stops; the broker queues for its persistent session (--marigraf-away s);
  3. the broker stops, cleanly (SIGTERM) or killed (--stop kill), for --broker-down s, while the PLC buffers;
  4. the broker starts; the PLC reconnects and drains: into Marigraf's restored session (16#00), or held on 16#10 if
     nobody subscribes (--after-restart s);
  5. Marigraf starts and catches up; pushing stops once the PLC has drained; Marigraf's rows are checked.
--persistence on|off rewrites the broker's config ([persistence] enabled, messages and retained "shutdown") and restarts
it before the run. The PLC's sequence number is read at every event, so a gap maps to a phase. Needs what sfw_test.py
needs. Afterwards the PLC is back on MQTT 3.1.1 at HQ with the test off.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import sfw_test as sf  # noqa: E402

BROKER_DIR = "~/tmp/sfw-bench/broker"
PERSISTENCE = """
[persistence]
enabled = true
dir = "/home/ktritz/tmp/sfw-bench/broker/store"
messages = "shutdown"
retained = "shutdown"
"""
WATCH = [sf.B + n for n in ("QueuedCount", "InFlightCount", "IsHeld", "NoSubscriberCount", "OldestAgeMs",
                            "DeliveredCount", "DroppedCount")] + ["PLC_PRG.IsBrokerConnected"]


def set_persistence(is_on: bool) -> str:
    """Rewrite mqttug.toml from its base (everything before a [persistence] table), then restart the broker."""
    script = ("cd %s && sed -n '/^\\[persistence\\]/q;p' mqttug.toml > mqttug.base.toml && cp mqttug.base.toml mqttug.toml"
              % BROKER_DIR)
    if is_on:
        script += " && printf '%%s' '%s' >> mqttug.toml" % PERSISTENCE
    # Marigraf restarts too, so it subscribes at once rather than after its reconnect back-off (up to 60 s)
    out = sf.vm(script + " && {0}/broker-stop.sh && {0}/broker-start.sh && {0}/marigraf-stop.sh && {0}/marigraf-start.sh"
                " && sleep 5 && grep -c '^\\[persistence\\]' mqttug.toml".format(sf.VM_BIN))
    return out


def next_seq() -> int:
    return int(m5.read([sf.T + "NextSequence"])[sf.T + "NextSequence"])


def watch(timeline, start, seconds, stop_when=None):
    end = time.time() + seconds
    while time.time() < end:
        values = sf.ints(m5.read(WATCH))
        timeline.append((round(time.time() - start, 1), values))
        if stop_when and stop_when(values):
            return True
        time.sleep(2)
    return False


def parse_marigraf(text: str) -> dict:
    out = {"missing_ranges": [], "dup_seq": 0}
    for line in text.splitlines():
        parts = line.split()
        if parts[:1] == ["rows"]:
            out.update(rows=int(parts[1]), distinct=int(parts[3]), min=int(parts[5]), max=int(parts[7]))
        elif parts[:1] == ["missing_count"]:
            out["missing"] = int(parts[1])
        elif parts[:1] == ["missing"]:
            out["missing_ranges"].append([int(parts[1]), int(parts[3])])
        elif parts[:1] == ["dup_seq"]:
            out["dup_seq"] += 1
    return out


def phase_of(seq: int, marks: dict) -> str:
    order = ["marigraf_stop", "broker_stop", "broker_start", "marigraf_start", "push_stop"]
    phase = "before"
    for name in order:
        if name in marks and seq >= marks[name]:
            phase = "after_" + name
    return phase


def run(args) -> dict:
    marks, timeline = {}, []
    first = sf.start_pushing()
    start, start_ms = time.time(), int(time.time() * 1000)
    watch(timeline, start, args.before)
    marks["marigraf_stop"] = next_seq()
    sf.vm("%s/marigraf-stop.sh" % sf.VM_BIN)
    watch(timeline, start, args.marigraf_away)
    marks["broker_stop"] = next_seq()
    stop_out = sf.vm("%s/broker-stop.sh%s" % (sf.VM_BIN, " --kill" if args.stop == "kill" else ""))
    watch(timeline, start, args.broker_down)
    marks["broker_start"] = next_seq()
    sf.vm("%s/broker-start.sh" % sf.VM_BIN)
    restart_at = time.time()
    connected = m5.wait_for(["PLC_PRG.IsBrokerConnected"], lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE", 60)
    reconnect_s = round(time.time() - restart_at, 1) if connected else None
    watch(timeline, start, args.after_restart)
    marks["marigraf_start"] = next_seq()
    sf.vm("%s/marigraf-start.sh" % sf.VM_BIN)
    drained = watch(timeline, start, args.drain_limit,
                    lambda v: v["QueuedCount"] == 0 and v["IsHeld"] == "FALSE" and v["OldestAgeMs"] < 1000)
    watch(timeline, start, 10)
    marks["push_stop"] = next_seq()
    last = sf.stop_pushing()
    sf.wait_drained(60)
    time.sleep(15)      # Marigraf's queue and batch writes
    stored = parse_marigraf(sf.marigraf(start_ms - 60000, int(time.time() * 1000) + 60000))
    lost = [[lo, hi, phase_of(lo, marks), hi - lo + 1] for lo, hi in stored["missing_ranges"]]
    if stored.get("min", first) > first:
        lost.insert(0, [first, stored["min"] - 1, "before", stored["min"] - first])
    if stored.get("max", last) < last:
        lost.append([stored["max"] + 1, last, phase_of(stored["max"] + 1, marks), last - stored["max"]])
    return {"persistence": args.persistence, "stop": args.stop, "broker_stop": stop_out, "first": first, "last": last,
            "pushed": last - first + 1, "marks": marks, "plc_reconnected_s": reconnect_s, "plc_drained": drained,
            "marigraf": stored, "lost": lost, "lost_total": sum(r[3] for r in lost), "plc": sf.snapshot(),
            "timeline": timeline}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--persistence", choices=["on", "off"], required=True)
    parser.add_argument("--stop", choices=["clean", "kill"], default="clean")
    parser.add_argument("--before", type=float, default=15)
    parser.add_argument("--marigraf-away", type=float, default=30)
    parser.add_argument("--broker-down", type=float, default=10)
    parser.add_argument("--after-restart", type=float, default=30)
    parser.add_argument("--drain-limit", type=float, default=180)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    print("persistence:", set_persistence(args.persistence == "on"), flush=True)
    if not sf.vm("%s/status.sh | grep -c running" % sf.VM_BIN).startswith("2"):
        sys.exit("broker and marigraf must both run on the VM (%s/status.sh)" % sf.VM_BIN)
    saved_loop = m5.read(sf.LOOP_SETTINGS)
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        m5.write(sf.RECOMMENDED_LOOP)
        if m5.reconnect(sf.plc_url(), "5") is None:
            sys.exit("the PLC did not connect to %s:%d" % (sf.BROKER_HOST, sf.BROKER_PORT))
        result["config"] = sf.configure([(sf.T + "Topic", "'%s'" % sf.TOPIC)])
        result.update(run(args))
    finally:
        m5.write([(sf.T + "IsEnabled", "FALSE"), (sf.T + "IsPushing", "TRUE")])
        m5.write([(k, v.split("#")[-1]) for k, v in saved_loop.items()])
        m5.reconnect(m5.HQ_URL, "4")
        if sf.vm("%s/status.sh | grep -c running" % sf.VM_BIN) != "2":
            sf.vm("%s/marigraf-start.sh; %s/broker-start.sh" % (sf.VM_BIN, sf.VM_BIN))
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "timeline"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
