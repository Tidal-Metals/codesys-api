"""The bench PLC against a broker that enforces topic ACLs (mochi in the bridge, per-PLC users).

Run from the repo root after deploy_demo.py, with a broker user that may read and write raw_data_demo/# and
nothing else (the VM dev bridge, user plc-bench-mqtt-test: add it with acl_bridge_user.py add, remove it after):
    python examples/mqtt_large_payload/acl_test.py --out examples/mqtt_large_payload/results/exp/acl/acl.json
EdgeTest publishes to an allowed topic, then to a denied one at QoS 0, 1 and 2, then subscribes to a denied
filter. For each case it records whether the publisher reported done, whether it timed out, how often the
client reconnected while the case ran, and whether a command sent meanwhile on the allowed topic still
arrived. mochi drops a denied QoS 0 publish silently and disconnects an MQTT 3.1.1 client for a denied
QoS 1/2 publish; the question is what the library does next. The PLC goes back to the HQ broker at the end.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
HOST, PORT, USER = "192.168.50.142", 18883, "plc-bench-mqtt-test"
HQ_URL = "192.168.50.240:1883"
ALLOWED_OUT, ALLOWED_IN = "raw_data_demo/edge", "raw_data_demo/edge_in"
DENIED = "raw_data_denied/edge"

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
    return str(on.read_value(path)).split('#')[-1]
C = 'PLC_PRG.MqttLink.clientFB'
result = {'success': True, 'connected': text('PLC_PRG.IsBrokerConnected') == 'TRUE',
          'connectAttempts': int(text(C + '.counts.CountConnectAttempt')),
          'doneSequence': int(text('EdgeTest.DoneSequence')), 'sendSequence': int(text('EdgeTest.SendSequence')),
          'timeouts': int(text('EdgeTest.TimeoutCount')), 'received': int(text('EdgeTest.Receiver.ReceivedCount')),
          'rejected': int(text('EdgeTest.RejectedCount')),
          'subscribeDone': text('EdgeTest.Subscriber.SubscribeDone') == 'TRUE',
          'subscribeFail': text('EdgeTest.Subscriber.SubscribeFail') == 'TRUE'}
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
        time.sleep(0.3)
    return None


def connect_plc(url: str) -> bool:
    write([("PLC_PRG.BrokerUrl", "'%s'" % url), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
    time.sleep(1)
    return wait_for(lambda s: s["connected"] and s["subscribeDone"], 30) is not None


def commander(password: str):
    """A second client on the allowed command topic: are commands still delivered while a case runs?"""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="acl-test-commander", protocol=mqtt.MQTTv311)
    client.username_pw_set(USER, password)
    client.connect(HOST, PORT, keepalive=30)
    client.loop_start()
    return client


def publish_case(name: str, topic: str, qos: int, cmd, watch: float) -> dict:
    write([("EdgeTest.TopicOut", "'%s'" % topic), ("EdgeTest.IsQos1", "TRUE" if qos == 1 else "FALSE"),
           ("EdgeTest.IsQos2", "TRUE" if qos == 2 else "FALSE"), ("EdgeTest.SendSize", "16")])
    before = state()
    write([("EdgeTest.SendSequence", str(before["sendSequence"] + 1))])
    commands = 0
    end = time.time() + watch
    while time.time() < end:  # a command every 2 s on the allowed topic
        cmd.publish(ALLOWED_IN, b"command", qos=1)
        commands += 1
        time.sleep(2)
    after = state()
    return {"case": name, "topic": topic, "qos": qos, "watchSeconds": watch,
            "publishDone": after["doneSequence"] == before["sendSequence"] + 1,
            "timeoutsDuring": after["timeouts"] - before["timeouts"], "rejectedDuring": after["rejected"] - before["rejected"],
            "reconnectsDuring": after["connectAttempts"] - before["connectAttempts"],
            "commandsSent": commands, "commandsReceived": after["received"] - before["received"],
            "connectedAtEnd": after["connected"]}


def recover(case: dict) -> dict:
    """Point EdgeTest back at the allowed topic and send again: is the link up and does a new message get through?
    (Upstream the refused message was still pending and kept the link down; with the fix it was given up.)"""
    write([("EdgeTest.TopicOut", "'%s'" % ALLOWED_OUT)])
    before = state()
    wait_for(lambda s: s["connected"], 30)
    write([("EdgeTest.SendSequence", str(state()["sendSequence"] + 1))])
    settled = wait_for(lambda s: s["connected"] and s["doneSequence"] == s["sendSequence"], 30)
    time.sleep(10)
    after = state()
    case["recoveredAfterTopicFix"] = settled is not None
    case["reconnectsAfterFix"] = after["connectAttempts"] - before["connectAttempts"]
    return case


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--watch", type=float, default=30, help="seconds to watch each denied case")
    parser.add_argument("--out")
    args = parser.parse_args()
    password = (ROOT / "tmp" / "mochi_test_user.txt").read_text().strip()
    url = "%s:%s@%s:%d" % (USER, password, HOST, PORT)
    report = {"broker": "%s:%d (mochi 2.7.9, user %s)" % (HOST, PORT, USER), "cases": []}
    write([("PLC_PRG.PublishPeriod", "T#1H"), ("PLC_PRG.IsTagValueEnabled", "FALSE"), ("ScaleTest.IsEnabled", "FALSE"),
           ("SplitTest.IsEnabled", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE"), ("EdgeTest.SubscribeQoS", "1"),
           ("EdgeTest.TopicIn", "'%s'" % ALLOWED_IN), ("EdgeTest.IsEnabled", "TRUE")])
    cmd = None
    try:
        report["connectedWithCredentials"] = connect_plc(url)
        if not report["connectedWithCredentials"]:
            raise RuntimeError("the PLC did not connect and subscribe with the test user")
        cmd = commander(password)
        report["cases"].append(publish_case("allowed QoS 1", ALLOWED_OUT, 1, cmd, 6))
        for qos in (0, 1, 2):
            case = publish_case("denied QoS %d" % qos, DENIED, qos, cmd, args.watch)
            report["cases"].append(recover(case) if not case["publishDone"] else case)
            print(json.dumps(report["cases"][-1]), flush=True)
        # denied subscription
        write([("EdgeTest.IsEnabled", "FALSE")])
        time.sleep(2)
        write([("EdgeTest.TopicIn", "'raw_data_denied/edge_in'"), ("EdgeTest.IsEnabled", "TRUE")])
        time.sleep(4)
        sub = state()
        report["deniedSubscribe"] = {"subscribeFail": sub["subscribeFail"], "subscribeDone": sub["subscribeDone"],
                                     "connected": sub["connected"]}
    finally:
        if cmd is not None:
            cmd.loop_stop()
            cmd.disconnect()
        # never leave a refused message pending (upstream it would loop against any broker): clear it by hand
        write([("EdgeTest.IsRequested", "FALSE"), ("EdgeTest.Publisher.requestToSend", "FALSE"),
               ("EdgeTest.Publisher.dataBuild", "FALSE"), ("EdgeTest.Publisher.WasSendet", "FALSE")])
        write([("EdgeTest.IsEnabled", "FALSE"), ("EdgeTest.TopicOut", "'%s'" % ALLOWED_OUT),
               ("EdgeTest.TopicIn", "'%s'" % ALLOWED_IN), ("EdgeTest.IsQos1", "FALSE"), ("EdgeTest.IsQos2", "FALSE"),
               ("PLC_PRG.PublishPeriod", "T#1S")])
        time.sleep(1)
        write([("EdgeTest.IsEnabled", "TRUE")])
        report["backOnHq"] = connect_plc(HQ_URL)
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
