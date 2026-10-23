"""BCNF's own MQTT code (BcnfComms in the demo: two client connections, CallbackCollector + ReceiveString at QoS 2,
seven QoS 0 publishers, an MQTTState) on the bench PLC with the fork, against the HQ or VM dev bridge only.

Run from the repo root after deploy_demo.py:
    python examples/mqtt_large_payload/bcnf_test.py --out examples/mqtt_large_payload/results/exp/bcnf/bcnf.json
Refuses to run unless BcnfComms.BrokerUrl is one of ALLOWED_BROKERS (never BCNF's production broker); the topics are
under raw_data_demo/bcnf/ and the client ids are BENCH_BCNF_PUB/SUB. Checks: both connections come up next to the
demo's own client; paced commands and status messages each reach ReceiveString; BCNF's seven strings arrive once a
second; MQTTState publishes each change; the SUB connection recovers and resubscribes after a forced disconnect;
the demo's own client keeps working throughout (EdgeTest echo).
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

ALLOWED_BROKERS = {"192.168.50.240:1883": ("192.168.50.240", 1883), "192.168.50.142:18883": ("192.168.50.142", 18883)}
B = "BcnfComms"
COMMANDS, STATUS = "raw_data_demo/bcnf/commands", "raw_data_demo/bcnf/status"
RAW, STATE = "raw_data_demo/bcnf/raw", "raw_data_demo/bcnf/state"

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE_READ = """
on = session.ensure_online_application('', True)
def text(path):
    return str(on.read_value(path))
def number(path):
    return int(text(path).split('#')[-1])
B = 'BcnfComms'
result = {'success': True, 'url': text(B + '.BrokerUrl').strip("'"), 'pub': text(B + '.PubConnected') == 'TRUE',
          'sub': text(B + '.SubConnected') == 'TRUE', 'message': text(B + '.LastMessage').strip("'"),
          'ready': text(B + '.LastReady').strip("'"), 'commandChanges': number(B + '.CommandChanges'),
          'readyChanges': number(B + '.ReadyChanges'),
          'subAttempts': number(B + '.MQTT_SUBSCRIBE.clientFB.counts.CountConnectAttempt'),
          'pubAttempts': number(B + '.MQTT_PUBLISH.clientFB.counts.CountConnectAttempt'),
          'mainConnected': text('PLC_PRG.IsBrokerConnected') == 'TRUE',
          'echoes': number('EdgeTest.EchoCount'), 'wild': text(B + '.LastWild').strip("'"),
          'wildChanges': number(B + '.WildChanges'), 'wildChild': text(B + '.LastWildChild').strip("'"),
          'subTooBig': number(B + '.MQTT_SUBSCRIBE.clientFB.counts.CountToBigTopics')}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state() -> dict:
    return execute(STATE_READ, 60)


def wait_for(predicate, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        current = state()
        if predicate(current):
            return current
        time.sleep(0.5)
    return None


class Watcher:
    """Subscribes to BCNF's publish topics and counts what arrives."""

    def __init__(self, host: str, port: int) -> None:
        self.lock = threading.Lock()
        self.raw, self.state = [], []
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="bcnf-test-%d" % os.getpid())
        client.on_connect = lambda c, u, f, r, p=None: c.subscribe([(RAW, 0), (STATE, 1)])
        client.on_message = self.on_message
        client.connect(host, port, keepalive=30)
        client.loop_start()
        self.client = client

    def on_message(self, client, userdata, message) -> None:
        with self.lock:
            (self.raw if message.topic == RAW else self.state).append((time.time(), message.payload.decode(errors="replace")))

    def take(self):
        with self.lock:
            raw, state, self.raw, self.state = self.raw, self.state, [], []
        return raw, state


def paced(watcher, topic: str, qos: int, count: int, key: str, changes: str) -> dict:
    before = state()
    delivered = 0
    for n in range(count):
        text = "%s-%s-%d-%d" % (key, qos, n, int(time.time() * 1000) % 100000)
        watcher.client.publish(topic, text.encode(), qos=qos)
        time.sleep(1.0)
        if state()[key] == text:
            delivered += 1
    after = state()
    return {"topic": topic, "qos": qos, "sent": count, "seenInReceiveString": delivered,
            "changes": after[changes] - before[changes], "subReconnects": after["subAttempts"] - before["subAttempts"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--commands", type=int, default=10)
    parser.add_argument("--out")
    args = parser.parse_args()
    current = state()
    if current["url"] not in ALLOWED_BROKERS:
        sys.exit("refusing: BcnfComms.BrokerUrl is %r, not one of %s" % (current["url"], sorted(ALLOWED_BROKERS)))
    host, port = ALLOWED_BROKERS[current["url"]]
    watcher = Watcher(host, port)
    report = {"broker": current["url"]}
    write([("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.IsEchoEnabled", "TRUE"), (B + ".IsEnabled", "TRUE")])
    try:
        up = wait_for(lambda s: s["pub"] and s["sub"], 30)
        report["bothConnected"] = up is not None
        time.sleep(3)  # subscriptions
        watcher.take()
        # BCNF's seven strings once a second, and the demo's own client alongside (EchoCount)
        before = state()
        time.sleep(10)
        raw, _ = watcher.take()
        after = state()
        report["publish"] = {"seconds": 10, "rawMessages": len(raw), "perSecond": round(len(raw) / 10, 1),
                             "groups": sorted({payload.split(":")[0] for _, payload in raw})}
        report["mainClientDuringBcnf"] = {"connected": after["mainConnected"]}
        # commands and status, paced (ReceiveString keeps only the newest message, as in BCNF)
        report["commands"] = [paced(watcher, COMMANDS, qos, args.commands, "message", "commandChanges") for qos in (1, 2)]
        report["status"] = paced(watcher, STATUS, 1, 5, "ready", "readyChanges")
        # MQTTState: three changes, each published once at QoS 1
        watcher.take()
        for value in ("TRUE", "FALSE", "TRUE"):
            write([(B + ".StateFlag", value)])
            time.sleep(1.5)
        _, states = watcher.take()
        report["mqttState"] = {"changes": 3, "published": [payload for _, payload in states]}
        # '#' subscription: its parent level and a child level must both arrive
        wild = []
        for topic in ("raw_data_demo/bcnf/wild", "raw_data_demo/bcnf/wild/child"):
            text = "wild-%s-%d" % (topic.rsplit("/", 1)[-1], int(time.time() * 1000) % 100000)
            watcher.client.publish(topic, text.encode(), qos=1)
            time.sleep(1.5)
            key = "wild" if topic.endswith("/wild") else "wildChild"
            wild.append({"topic": topic, "delivered": state()[key] == text})
        report["wildcard"] = wild
        # Oversize commands on the SUB connection (default MaxPayloadSize 2,000 bytes)
        before = state()
        watcher.client.publish(COMMANDS, b"X" * 2500, qos=1)
        time.sleep(3)
        mid = state()
        watcher.client.publish(COMMANDS, b"Y" * 20000, qos=1)
        time.sleep(2)
        recovered = wait_for(lambda s: s["sub"], 30)
        time.sleep(3)
        report["oversize"] = {
            "2500 bytes": {"tooBigCounted": mid["subTooBig"] - before["subTooBig"],
                           "reconnects": mid["subAttempts"] - before["subAttempts"],
                           "deliveredToReceiveString": mid["message"].startswith("XXXX")},
            "20000 bytes": {"reconnects": (recovered or state())["subAttempts"] - mid["subAttempts"],
                            "recovered": recovered is not None,
                            "afterwards": paced(watcher, COMMANDS, 1, 2, "message", "commandChanges")}}
        # SUB connection: forced disconnect, reconnect and resubscribe
        before = state()
        write([(B + ".MQTT_SUBSCRIBE.clientFB.DoDisconnect", "TRUE")])
        time.sleep(1)
        back = wait_for(lambda s: s["sub"], 30)
        time.sleep(3)
        report["subReconnect"] = {"reconnected": back is not None,
                                  "afterReconnect": paced(watcher, COMMANDS, 2, 3, "message", "commandChanges")}
        end = state()
        report["mainClientEnd"] = {"connected": end["mainConnected"], "echoAcknowledgedSinceStart": end["echoes"] - current["echoes"]}
    finally:
        write([(B + ".IsEnabled", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE")])
        watcher.client.loop_stop()
        watcher.client.disconnect()
    report["success"] = bool(report.get("bothConnected") and report["publish"]["perSecond"] >= 6
                             and all(c["seenInReceiveString"] == c["sent"] for c in report["commands"])
                             and report["status"]["seenInReceiveString"] == report["status"]["sent"]
                             and report["mqttState"]["published"] == ["flag:on", "flag:off", "flag:on"]
                             and all(w["delivered"] for w in report["wildcard"])
                             and report["oversize"]["20000 bytes"]["recovered"]
                             and report["oversize"]["20000 bytes"]["afterwards"]["seenInReceiveString"] == 2
                             and report["subReconnect"]["reconnected"]
                             and report["subReconnect"]["afterReconnect"]["seenInReceiveString"] == 3
                             and report["mainClientEnd"]["connected"])
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
