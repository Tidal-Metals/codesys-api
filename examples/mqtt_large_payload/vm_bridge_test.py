"""The bench PLC on the VM dev bridge (mochi 2.7.9 with per-PLC users): bridge restarts and a duplicate client id.

Run from the repo root after deploy_demo.py and `acl_bridge_user.py add` (the user's password contains '@' and ':',
so connecting at all also checks the URL parsing of credentials):
    python examples/mqtt_large_payload/vm_bridge_test.py --out examples/mqtt_large_payload/results/exp/validation/vm_bridge.json
Restarts mqtt-bridge.service on the VM (each is a few seconds without the dev broker). While commands arrive every
0.5 s and EdgeTest publishes a QoS 1 message every second, it measures:
  restart     the bridge restarted twice: time to reconnect, traffic afterwards, and no message given up as Rejected
  duplicate   another client connects with the PLC's client id (mochi takes the session over): once, then
              reconnecting every second for 20 s; the PLC's reconnects, Rejected messages, and recovery afterwards
The PLC goes back to the HQ broker at the end.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
VM, HOST, PORT, USER = "ktritz@192.168.50.142", "192.168.50.142", 18883, "plc-bench-mqtt-test"
HQ_URL = "192.168.50.240:1883"
COMMANDS, ECHO = "raw_data_demo/edge_in", "raw_data_demo/edge_echo"

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE = """
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path))
def number(path):
    return int(text(path).split('#')[-1])
C = 'PLC_PRG.MqttLink.clientFB'
result = {'success': True, 'connected': text('PLC_PRG.IsBrokerConnected') == 'TRUE', 'attempts': number(C + '.counts.CountConnectAttempt'),
          'peerCloses': number(C + '.counts.CountPeerCloses'), 'rejected': number('EdgeTest.RejectedCount'),
          'done': number('EdgeTest.DoneSequence'), 'send': number('EdgeTest.SendSequence'), 'echoes': number('EdgeTest.EchoCount'),
          'clientId': text('PLC_PRG.MqttLink.ClientID').strip("'")}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state() -> dict:
    return execute(STATE, 60)


def wait_for(predicate, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        current = state()
        if predicate(current):
            return current
        time.sleep(0.5)
    return None


class Traffic:
    """Commands every 0.5 s (QoS 1), and an EdgeTest QoS 1 publish every second; records echo arrival times."""

    def __init__(self, password: str) -> None:
        self.password = password
        self.lock = threading.Lock()
        self.echoes = []
        self.running = True
        self.client = self.connect("vm-bridge-test-traffic", subscribe=True)
        threading.Thread(target=self.loop, daemon=True).start()

    def connect(self, client_id: str, subscribe: bool = False):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        client.username_pw_set(USER, self.password)
        if subscribe:
            # in on_connect: a bridge restart ends the (clean) session, and the subscription with it
            client.on_connect = lambda c, u, f, r, p=None: c.subscribe(ECHO, qos=1)
            client.on_message = lambda c, u, m: self.record()
        client.connect(HOST, PORT, keepalive=30)
        client.loop_start()
        return client

    def record(self) -> None:
        with self.lock:
            self.echoes.append(time.time())

    def loop(self) -> None:
        n = 0
        while self.running:
            n += 1
            self.client.publish(COMMANDS, b"cmd-%d" % n, qos=1)
            time.sleep(0.5)

    def echoes_between(self, start: float, end: float) -> int:
        with self.lock:
            return sum(1 for t in self.echoes if start <= t <= end)

    def stop(self) -> None:
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()


def publisher_loop(stop: threading.Event) -> None:
    """EdgeTest: a 16-byte QoS 1 message every second (so one is often in flight when the link drops)."""
    seq = state()["send"]
    while not stop.is_set():
        seq += 1
        try:
            write([("EdgeTest.SendSequence", str(seq))])
        except RuntimeError:
            pass
        stop.wait(1.0)


def restart_bridge(traffic: Traffic) -> dict:
    before = state()
    started = time.time()
    subprocess.run(["ssh", "-o", "BatchMode=yes", VM, "sudo systemctl restart mqtt-bridge.service"], timeout=60, check=True)
    back = wait_for(lambda s: s["connected"] and s["attempts"] > before["attempts"], 60)
    reconnect_seconds = round(time.time() - started, 1) if back else None
    time.sleep(10)
    after = state()
    return {"reconnectedAfterSeconds": reconnect_seconds, "peerCloses": after["peerCloses"] - before["peerCloses"],
            "reconnects": after["attempts"] - before["attempts"], "rejected": after["rejected"] - before["rejected"],
            "plcEchoesSince": after["echoes"] - before["echoes"],
            "echoesInLast10s": traffic.echoes_between(time.time() - 10, time.time()), "connected": after["connected"]}


def duplicate_client(traffic: Traffic, client_id: str, fight_seconds: float) -> dict:
    before = state()
    intruder = traffic.connect(client_id)          # mochi takes the session over: the PLC is disconnected
    time.sleep(5)
    intruder.loop_stop()
    intruder.disconnect()
    once = state()
    # the intruder reconnects every second: each connect kicks the PLC, each PLC reconnect kicks the intruder
    end = time.time() + fight_seconds
    while time.time() < end:
        intruder = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv311)
        intruder.username_pw_set(USER, traffic.password)
        try:
            intruder.connect(HOST, PORT, keepalive=30)
            intruder.loop(timeout=0.5)
        except OSError:
            pass
        time.sleep(1)
        intruder.disconnect()
    fight = state()
    recovered = wait_for(lambda s: s["connected"], 30)
    time.sleep(10)
    after = state()
    return {"onceReconnects": once["attempts"] - before["attempts"],
            "fightReconnects": fight["attempts"] - once["attempts"], "fightSeconds": fight_seconds,
            "rejectedDuring": after["rejected"] - before["rejected"], "recovered": recovered is not None,
            "plcEchoesAfterRecovery": after["echoes"] - (recovered or after)["echoes"],
            "echoesInLast10s": traffic.echoes_between(time.time() - 10, time.time())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--restarts", type=int, default=2)
    parser.add_argument("--fight-seconds", type=float, default=20)
    parser.add_argument("--out")
    args = parser.parse_args()
    password = (ROOT / "tmp" / "mochi_test_user.txt").read_text().strip()
    report = {"broker": "%s:%d (mochi 2.7.9)" % (HOST, PORT), "passwordHasAtAndColon": "@" in password and ":" in password}
    write([("PLC_PRG.PublishPeriod", "T#1H"), ("ScaleTest.IsEnabled", "FALSE"), ("SplitTest.IsEnabled", "FALSE"),
           ("EdgeTest.TopicOut", "'raw_data_demo/edge'"), ("EdgeTest.IsQos1", "TRUE"), ("EdgeTest.IsQos2", "FALSE"),
           ("EdgeTest.SendSize", "16"), ("EdgeTest.IsEchoEnabled", "TRUE"), ("EdgeTest.IsEnabled", "TRUE"),
           ("PLC_PRG.BrokerUrl", "'%s:%s@%s:%d'" % (USER, password, HOST, PORT)),
           ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
    stop = threading.Event()
    traffic = None
    try:
        report["connectedWithCredentials"] = wait_for(lambda s: s["connected"], 30) is not None
        if not report["connectedWithCredentials"]:
            raise RuntimeError("the PLC did not connect to the VM bridge with the test user")
        traffic = Traffic(password)
        threading.Thread(target=publisher_loop, args=(stop,), daemon=True).start()
        time.sleep(5)
        report["restarts"] = [restart_bridge(traffic) for _ in range(args.restarts)]
        report["duplicateClientId"] = duplicate_client(traffic, state()["clientId"], args.fight_seconds)
    finally:
        stop.set()
        if traffic is not None:
            traffic.stop()
        write([("PLC_PRG.BrokerUrl", "'%s'" % HQ_URL), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE"),
               ("EdgeTest.IsQos1", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE"), ("PLC_PRG.PublishPeriod", "T#1S")])
        report["backOnHq"] = wait_for(lambda s: s["connected"], 30) is not None
    restarts = report.get("restarts", [])
    duplicate = report.get("duplicateClientId", {})
    report["success"] = bool(report.get("connectedWithCredentials")
                             and all(r["reconnectedAfterSeconds"] and r["rejected"] == 0 and r["echoesInLast10s"] > 5
                                     for r in restarts)
                             and duplicate.get("recovered") and duplicate.get("echoesInLast10s", 0) > 5
                             and report["backOnHq"])
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
