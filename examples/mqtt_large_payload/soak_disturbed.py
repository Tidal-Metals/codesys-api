"""Long soak with disturbances on the VM dev bridge (mochi with per-PLC users): does anything drift or leak?

Run from the repo root after deploy_demo.py (session logged in), in the background:
    python examples/mqtt_large_payload/soak_disturbed.py --hours 24 --out examples/mqtt_large_payload/results/exp/soak24
Adds the test user to the dev bridge (acl_bridge_user.py add; the bridge restarts) and points the PLC at it with the
recommended client setup (budget 4 ms, up to 32 calls a scan, reply call at the end of the scan). Load: the 2,000-tag
full refresh (26 KB, QoS 0) once a second, every value checked at the broker, and a QoS 1 command every 200 ms
(EdgeTest echoes at QoS 1). Disturbances: a broker-side kick (another client takes the PLC's client id) every
--kick-minutes, and a bridge restart (systemctl restart mqtt-bridge.service on the VM) every --restart-minutes.
Every --sample-minutes it reads the PLC (memory, counters, the interval's worst scan) and appends a line to
samples.jsonl, so a run that dies early still leaves its data. Loss is allowed only in a disturbance window
(--window-seconds after a disturbance); anywhere else every command and full refresh must arrive once.
Renews the bench reservation (BENCH_RESERVATION, tmp/mqtt_demo/reservation_soak.json) every 50 minutes. At the end,
or on any failure: the PLC goes back to the HQ broker, the test user is removed, the reservation released.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from run_ide_script import execute  # noqa: E402
from verify_scale import check  # noqa: E402

VM, HOST, PORT, USER = "ktritz@192.168.50.142", "192.168.50.142", 18883, "plc-bench-mqtt-test"
HQ_URL = "192.168.50.240:1883"
COMMANDS, SCALE = "raw_data_demo/edge_in", "raw_data_demo/scale"
API = "http://127.0.0.1:8081/api/v1"
RESERVATION_FILE = ROOT / "tmp" / "mqtt_demo" / "reservation_soak.json"
PASSWORD_FILE = ROOT / "tmp" / "mochi_test_user.txt"
COMMAND_SLACK = 3      # commands in flight across a sample boundary

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path)).split('#')[-1].strip("'")
C = 'PLC_PRG.MqttLink.clientFB'
names = {'connected': 'PLC_PRG.IsBrokerConnected', 'dynMemUsage': 'PLC_PRG.MqttLink.dynMemUsage',
         'connectAttempts': C + '.counts.CountConnectAttempt', 'peerCloses': C + '.counts.CountPeerCloses',
         'refreshesSent': 'ScaleTest.SentCount', 'refreshTimeouts': 'ScaleTest.TimeoutCount',
         'refreshOverflows': 'ScaleTest.OverflowCount', 'commandsReceived': 'EdgeTest.Receiver.ReceivedCount',
         'echoes': 'EdgeTest.EchoCount', 'rejected': 'EdgeTest.RejectedCount',
         'subscribeDone': 'EdgeTest.Subscriber.SubscribeDone', 'subscriberBusy': 'EdgeTest.Subscriber.busy',
         'maxCycleUs': 'PLC_PRG.MaxCycleUs', 'maxScanClientUs': 'PLC_PRG.MaxScanClientUs', 'maxClientUs': 'PLC_PRG.MaxClientUs',
         'clientId': 'PLC_PRG.MqttLink.ClientID'}
result = {'success': True, 'values': dict((key, text(path)) for key, path in names.items())}
"""
RESET_MAXIMA = """
on.set_prepared_value('PLC_PRG.ResetStats', 'TRUE')
on.write_prepared_values()
"""
NUMBERS = ("dynMemUsage", "connectAttempts", "peerCloses", "refreshesSent", "refreshTimeouts", "refreshOverflows",
           "commandsReceived", "echoes", "rejected", "maxCycleUs", "maxScanClientUs", "maxClientUs")


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError("online write failed: %s" % result)


def read_plc(tries: int = 4, is_sample: bool = False) -> dict:
    """The PLC's values; a sample read also clears the maxima, so each sample has its interval's worst."""
    for _ in range(tries):
        result = execute(READ + (RESET_MAXIMA if is_sample else ""), 60)
        values = result.get("values")
        if values:
            for key in NUMBERS:
                values[key] = int(values[key])
            values["connected"] = values["connected"] == "TRUE"
            return values
        time.sleep(2)
    raise RuntimeError("no online values after %d reads: %s" % (tries, result))


def wait_connected(seconds: float, after_attempts: int = -1) -> float | None:
    """Seconds until the PLC reports connected (on a new connection when after_attempts is given)."""
    started = time.time()
    while time.time() - started < seconds:
        try:
            values = read_plc()
        except RuntimeError:
            values = None
        if values and values["connected"] and values["connectAttempts"] > after_attempts:
            return round(time.time() - started, 1)
        time.sleep(1)
    return None


class Reservation:
    def __init__(self) -> None:
        data = json.loads(RESERVATION_FILE.read_text(encoding="utf-8"))["reservation"]
        self.id, self.token = data["id"], data["token"]
        os.environ["BENCH_RESERVATION"] = self.token

    def call(self, method: str) -> bool:
        session = requests.Session()
        session.trust_env = False
        headers = {"Authorization": "ApiKey admin", "X-Bench-Reservation": self.token}
        try:
            response = session.request(method, "%s/bench/reservations/%s" % (API, self.id), headers=headers,
                                        json={"ttlSeconds": 4 * 3600} if method == "PUT" else None, timeout=30)
            return response.ok
        except requests.RequestException:
            return False


class BrokerSide:
    """Commands every 200 ms (QoS 1) and the full-refresh checker, both on the dev bridge with the test user."""

    def __init__(self, password: str) -> None:
        self.password = password
        self.lock = threading.Lock()
        self.commands_sent = 0
        self.refreshes, self.duplicates = 0, 0
        self.problems, self.gaps = [], []          # gaps: (time, last sequence, next sequence)
        self.last_sequence = None
        self.running = True
        self.verifier = self.connect("soak-verifier", self.on_refresh)
        self.commander = self.connect("soak-commands", None)
        threading.Thread(target=self.command_loop, daemon=True).start()

    def connect(self, client_id: str, on_message):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        client.username_pw_set(USER, self.password)
        if on_message is not None:
            client.on_connect = lambda c, u, f, r, p=None: c.subscribe(SCALE, qos=1)   # again after a bridge restart
            client.on_message = on_message
        client.reconnect_delay_set(1, 5)
        client.connect(HOST, PORT, keepalive=30)
        client.loop_start()
        return client

    def on_refresh(self, client, userdata, message) -> None:
        fmt, sequence, stamp, problem = check(message.payload)
        now = time.time()
        with self.lock:
            self.refreshes += 1
            if problem and len(self.problems) < 50:
                self.problems.append({"time": now, "sequence": sequence, "problem": problem})
            if sequence is None:
                return
            if self.last_sequence is not None:
                if sequence <= self.last_sequence:
                    self.duplicates += 1
                elif sequence != self.last_sequence + 1:
                    self.gaps.append((now, self.last_sequence, sequence))
            self.last_sequence = max(sequence, self.last_sequence or 0)

    def command_loop(self) -> None:
        n = 0
        while self.running:
            n += 1
            info = self.commander.publish(COMMANDS, b"soak-%d" % n, qos=1)
            # paho queues a QoS 1 message published while disconnected (rc NO_CONN) and sends it after the
            # reconnect, so it counts as sent; counting only SUCCESS made a bridge restart look like duplicates.
            if info.rc in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
                with self.lock:
                    self.commands_sent += 1
            time.sleep(0.2)

    def snapshot(self) -> dict:
        with self.lock:
            return {"commandsSent": self.commands_sent, "refreshes": self.refreshes, "duplicates": self.duplicates,
                    "problems": len(self.problems), "gaps": list(self.gaps)}

    def stop(self) -> None:
        self.running = False
        for client in (self.verifier, self.commander):
            client.loop_stop()
            client.disconnect()


def kick(password: str, client_id: str) -> dict:
    """Another client takes the PLC's client id; mochi drops the PLC at once."""
    intruder = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
    intruder.username_pw_set(USER, password)
    try:
        intruder.connect(HOST, PORT, keepalive=30)
        intruder.loop(timeout=0.3)
        intruder.disconnect()
        return {"ok": True}
    except OSError as error:
        return {"ok": False, "error": str(error)}


def restart_bridge() -> dict:
    try:
        subprocess.run(["ssh", "-o", "BatchMode=yes", VM, "sudo systemctl restart mqtt-bridge.service"],
                       timeout=90, check=True, capture_output=True)
        return {"ok": True}
    except (subprocess.SubprocessError, OSError) as error:
        return {"ok": False, "error": str(error)}


def in_window(when: float, disturbances: list, window: float) -> bool:
    return any(d["time"] <= when <= d["time"] + window for d in disturbances)


def judge_interval(start: float, end: float, plc_delta: dict, broker_delta: dict, disturbances: list, window: float) -> list:
    """Problems in one sample interval; loss is allowed only when a disturbance window overlaps it."""
    disturbed = any(d["time"] - window <= end and d["time"] + window >= start for d in disturbances)
    problems = []
    if plc_delta["commandsReceived"] > broker_delta["commandsSent"] + COMMAND_SLACK:
        problems.append("more commands received than sent (duplicates?)")
    if plc_delta["refreshTimeouts"]:
        problems.append("%d full-refresh timeouts" % plc_delta["refreshTimeouts"])
    if plc_delta["rejected"]:
        problems.append("%d messages given up as Rejected" % plc_delta["rejected"])
    if not disturbed:
        if abs(plc_delta["commandsReceived"] - broker_delta["commandsSent"]) > COMMAND_SLACK:
            problems.append("commands: %d sent, %d received, no disturbance" % (broker_delta["commandsSent"],
                                                                                plc_delta["commandsReceived"]))
        if abs(plc_delta["refreshesSent"] - broker_delta["refreshes"]) > 2:
            problems.append("full refreshes: %d sent, %d at the broker, no disturbance" % (plc_delta["refreshesSent"],
                                                                                          broker_delta["refreshes"]))
        if plc_delta["connectAttempts"]:
            problems.append("%d reconnects without a disturbance" % plc_delta["connectAttempts"])
    return problems


def setup_plc(password: str) -> None:
    write([("PLC_PRG.PublishPeriod", "T#1S"), ("SplitTest.IsEnabled", "FALSE"),
           ("PLC_PRG.ClientCallsPerScan", "32"), ("PLC_PRG.ClientBudgetUs", "4000"),
           ("PLC_PRG.IsSecondClientCallEnabled", "TRUE"),
           ("ScaleTest.IsTagValueFormat", "TRUE"), ("ScaleTest.TagsPerScan", "2000"), ("ScaleTest.IsQos1", "FALSE"),
           ("EdgeTest.SubscribeQoS", "1"), ("EdgeTest.IsQos1", "FALSE"), ("EdgeTest.IsEchoEnabled", "TRUE"),
           ("EdgeTest.IsEnabled", "TRUE"),
           ("PLC_PRG.BrokerUrl", "'%s:%s@%s:%d'" % (USER, password, HOST, PORT)),
           ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
    if wait_connected(60) is None:
        raise RuntimeError("the PLC did not connect to the dev bridge with the test user")
    write([("ScaleTest.IsEnabled", "TRUE")])


def restore_plc() -> dict:
    report = {}
    try:
        write([("ScaleTest.IsEnabled", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE"), ("PLC_PRG.ClientCallsPerScan", "1"),
               ("PLC_PRG.BrokerUrl", "'%s'" % HQ_URL), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
        report["backOnHq"] = wait_connected(60) is not None
    except RuntimeError as error:
        report["restoreError"] = str(error)
    return report


def run(args, out: Path, reservation: Reservation) -> dict:
    password = PASSWORD_FILE.read_text().strip()
    setup_plc(password)
    broker = BrokerSide(password)
    disturbances, intervals, problems = [], [], []
    start = time.time()
    end = start + args.hours * 3600
    next_kick = start + args.kick_minutes * 60
    next_restart = start + args.restart_minutes * 60
    next_sample = start + args.sample_minutes * 60
    next_renew = start + 50 * 60
    time.sleep(5)
    previous_plc, previous_broker, previous_time = read_plc(is_sample=True), broker.snapshot(), time.time()
    first_mem = previous_plc["dynMemUsage"]
    try:
        while time.time() < end:
            now = time.time()
            if now >= next_restart:
                before = read_plc()["connectAttempts"]
                event = {"time": now, "kind": "bridge restart", **restart_bridge()}
                event["reconnectSeconds"] = wait_connected(90, before)
                disturbances.append(event)
                next_restart += args.restart_minutes * 60
                next_kick = max(next_kick, now + args.window_seconds)      # not on top of a restart
            elif now >= next_kick:
                before = read_plc()
                event = {"time": now, "kind": "kick", **kick(password, before["clientId"])}
                event["reconnectSeconds"] = wait_connected(60, before["connectAttempts"])
                disturbances.append(event)
                next_kick += args.kick_minutes * 60
            if now >= next_renew:
                if not reservation.call("PUT"):
                    problems.append({"time": now, "problem": "reservation renewal failed"})
                next_renew += 50 * 60
            if now >= next_sample:
                plc, snap, sampled = read_plc(is_sample=True), broker.snapshot(), time.time()
                plc_delta = {k: plc[k] - previous_plc[k] for k in ("commandsReceived", "refreshesSent", "refreshTimeouts",
                                                                   "rejected", "connectAttempts", "peerCloses", "echoes")}
                broker_delta = {"commandsSent": snap["commandsSent"] - previous_broker["commandsSent"],
                                "refreshes": snap["refreshes"] - previous_broker["refreshes"]}
                found = judge_interval(previous_time, sampled, plc_delta, broker_delta, disturbances, args.window_seconds)
                row = {"time": round(sampled), "hours": round((sampled - start) / 3600, 3), "connected": plc["connected"],
                       "dynMemUsage": plc["dynMemUsage"], "maxCycleUs": plc["maxCycleUs"],
                       "maxScanClientUs": plc["maxScanClientUs"], "maxClientUs": plc["maxClientUs"],
                       "subscribeDone": plc["subscribeDone"], "subscriberBusy": plc["subscriberBusy"],
                       "plc": plc_delta, "broker": broker_delta, "verifierProblems": snap["problems"],
                       "verifierDuplicates": snap["duplicates"], "problems": found}
                intervals.append(row)
                with (out / "samples.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")
                problems.extend({"time": sampled, "problem": p} for p in found)
                previous_plc, previous_broker, previous_time = plc, snap, sampled
                next_sample += args.sample_minutes * 60
            time.sleep(1)
    finally:
        broker.stop()
    snap = broker.snapshot()
    unexplained_gaps = [g for g in snap["gaps"] if not in_window(g[0], disturbances, args.window_seconds)]
    mems = [row["dynMemUsage"] for row in intervals]
    return {
        "hours": args.hours, "broker": "%s:%d (mochi 2.7.9, user %s)" % (HOST, PORT, USER),
        "kicks": sum(1 for d in disturbances if d["kind"] == "kick"),
        "bridgeRestarts": sum(1 for d in disturbances if d["kind"] == "bridge restart"),
        "disturbancesNotRecovered": [d for d in disturbances if d.get("reconnectSeconds") is None],
        "reconnectSecondsMax": max((d["reconnectSeconds"] or 0 for d in disturbances), default=None),
        # totals over the sampled intervals, the same window on both sides
        "commandsSent": sum(row["broker"]["commandsSent"] for row in intervals),
        "commandsReceived": sum(row["plc"]["commandsReceived"] for row in intervals),
        "refreshesSent": sum(row["plc"]["refreshesSent"] for row in intervals),
        "refreshesAtBroker": sum(row["broker"]["refreshes"] for row in intervals),
        "reconnects": sum(row["plc"]["connectAttempts"] for row in intervals),
        "brokerCloses": sum(row["plc"]["peerCloses"] for row in intervals),
        "verifierProblems": snap["problems"], "verifierDuplicates": snap["duplicates"],
        "sequenceGaps": len(snap["gaps"]), "unexplainedGaps": unexplained_gaps[:20],
        "dynMemUsageFirst": first_mem, "dynMemUsageMin": min(mems, default=None), "dynMemUsageMax": max(mems, default=None),
        "maxCycleUs": max((row["maxCycleUs"] for row in intervals), default=None),
        "maxScanClientUs": max((row["maxScanClientUs"] for row in intervals), default=None),
        "intervalsOverScan10ms": sum(1 for row in intervals if row["maxCycleUs"] > 10000),
        "problems": problems[:100], "problemCount": len(problems), "disturbances": disturbances,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--kick-minutes", type=float, default=10)
    parser.add_argument("--restart-minutes", type=float, default=60)
    parser.add_argument("--sample-minutes", type=float, default=5)
    parser.add_argument("--window-seconds", type=float, default=60)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    reservation = Reservation()
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    added = subprocess.run([sys.executable, str(HERE / "acl_bridge_user.py"), "add"], cwd=ROOT).returncode == 0
    try:
        if not added:
            raise RuntimeError("acl_bridge_user.py add failed")
        report.update(run(args, out, reservation))
    except Exception as error:      # record it; the restore below must still run
        report["error"] = "%s: %s" % (type(error).__name__, error)
    finally:
        report.update(restore_plc())
        report["testUserRemoved"] = subprocess.run([sys.executable, str(HERE / "acl_bridge_user.py"), "restore"],
                                                   cwd=ROOT).returncode == 0
        report["reservationReleased"] = reservation.call("DELETE")
    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    report["success"] = bool("error" not in report and not report.get("problemCount") and not report.get("verifierProblems")
                             and not report.get("unexplainedGaps") and not report.get("disturbancesNotRecovered")
                             and report.get("dynMemUsageMin") == report.get("dynMemUsageMax") and report.get("backOnHq"))
    text = json.dumps(report, indent=1)
    (out / "soak.json").write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
