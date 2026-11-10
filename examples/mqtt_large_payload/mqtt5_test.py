"""MQTT 5 on the bench PLC (library 1.4.0.0, CODESYS-MQTT branch mqtt5), against a private MQTTug.

    python examples/mqtt_large_payload/mqtt5_test.py [--cases connect,telemetry,...] [--keep]

Needs the demo built against 1.4.0.0 running on the PLC (reserve it first), and MQTTug with token auth on
BROKER (tmp/mqtt5_bench/: mqttug.toml, plc.token for client BENCH_MQTT_DEMO publishing raw_data_demo/# and
BENCH_MQTT_DEMO/#, subscribing raw_data_demo/#; observer.token for observer-* subscribing #). Topics outside
those rules are how the broker's refusals are produced. The PLC is switched to MQTT 5 on BROKER by online
writes (BrokerUrl, MqttLink.ProtocolVersion, a reconnect) and, unless --keep, back to MQTT 3.1.1 on HQ at the
end. Results: results/exp/mqtt5/<time>.json. Tokens are read from files and never printed.
"""
import argparse
import json
import socket
import sys
import threading
import time
import zlib
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.packettypes import PacketTypes
from paho.mqtt.properties import Properties

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO))
from run_ide_script import execute  # noqa: E402

BENCH = REPO / "tmp" / "mqtt5_bench"
BROKER_HOST, BROKER_PORT = "192.168.50.108", 1886
HQ_URL = "192.168.50.240:1883"
C = "PLC_PRG.MqttLink.clientFB"
SEND_SIZES = [1, 2, 126, 127, 128, 129, 4093, 4096, 8191, 16380, 16383, 16384, 16390, 32766, 32770]
RECEIVE_SIZES = [0, 1, 2, 126, 127, 128, 129, 1000, 4093, 4096, 8000, 16300, 16383, 16384, 20000, 40000]

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
result = {'success': True, 'values': dict((p, str(on.read_value(p)).split('#')[-1]) for p in @@PATHS@@)}
"""
INFO = ["PLC_PRG.IsBrokerConnected", C + ".counts.CountConnectAttempt", C + ".MQTT_INFO.ConnectReasonCode",
        C + ".MQTT_INFO.DisconnectReasonCode", C + ".MQTT_INFO.ReasonString", C + ".MQTT_INFO.Broker.ProtocolLevel",
        C + ".MQTT_INFO.Broker.ReceiveMaximum", C + ".MQTT_INFO.Broker.MaximumQoS",
        C + ".MQTT_INFO.Broker.IsRetainAvailable", C + ".MQTT_INFO.Broker.MaximumPacketSize",
        C + ".MQTT_INFO.Broker.TopicAliasMaximum", C + ".MQTT_INFO.Broker.HasServerKeepAlive",
        C + ".MQTT_INFO.Broker.IsSharedSubscriptionAvailable", C + ".IsSendPending", C + ".counts.CountPeerCloses"]


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def read(paths) -> dict:
    result = execute(READ.replace("@@PATHS@@", repr(list(paths))), 60)
    if not result.get("success"):
        raise RuntimeError(result)
    return result["values"]


def short(values: dict) -> dict:
    return {k.replace(C + ".", "client.").replace("PLC_PRG.", ""): v for k, v in values.items()}


def wait_for(paths, predicate, seconds: float):
    end = time.time() + seconds
    values = read(paths)
    while not predicate(values) and time.time() < end:
        time.sleep(0.3)
        values = read(paths)
    return values if predicate(values) else None


def token(name: str) -> str:
    return (BENCH / name).read_text(encoding="utf-8").strip()


def is_broker_up() -> bool:
    try:
        socket.create_connection((BROKER_HOST, BROKER_PORT), timeout=2).close()
        return True
    except OSError:
        return False


def plc_url(secret: str) -> str:
    return "token:%s@%s:%d" % (secret, BROKER_HOST, BROKER_PORT)


def reconnect(url: str, version: str) -> dict:
    """Point the client at url with the protocol version and wait for the new connection."""
    before = int(read([C + ".counts.CountConnectAttempt"])[C + ".counts.CountConnectAttempt"])
    write([("PLC_PRG.BrokerUrl", "'%s'" % url), ("PLC_PRG.MqttLink.ProtocolVersion", version),
           (C + ".DoDisconnect", "TRUE")])
    return wait_for(INFO, lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE"
                    and int(v[C + ".counts.CountConnectAttempt"]) > before, 30)


class Observer:
    """MQTT 5 client on the private broker that records every message (topic, payload, QoS, properties)."""

    def __init__(self, client_id: str = "observer-mqtt5-test"):
        self.messages = []
        self.lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        self.client.username_pw_set("token", token("observer.token"))
        self.client.on_message = self._on_message
        self.client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
        self.client.loop_start()
        self.client.subscribe("raw_data_demo/#", qos=2)
        time.sleep(0.5)

    def _on_message(self, client, userdata, message):
        with self.lock:
            self.messages.append((message.topic, bytes(message.payload), message.qos, message.retain, time.time()))

    def take(self, topic: str):
        with self.lock:
            found = [m for m in self.messages if m[0] == topic]
            self.messages = [m for m in self.messages if m[0] != topic]
        return found

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def expected_payload(size: int, sequence: int) -> bytes:
    return bytes((i * 31 + sequence) % 251 for i in range(size))


def case_connect(observer) -> dict:
    values = reconnect(plc_url(token("plc.token")), "5")
    if values is None:
        return {"ok": False, "why": "no MQTT 5 connection", "state": short(read(INFO))}
    ok = (values[C + ".MQTT_INFO.Broker.ProtocolLevel"] == "5" and values[C + ".MQTT_INFO.ConnectReasonCode"] == "0"
          and values[C + ".MQTT_INFO.Broker.ReceiveMaximum"] == "1024"
          and values[C + ".MQTT_INFO.Broker.MaximumPacketSize"] == "16777216"
          and values[C + ".MQTT_INFO.Broker.TopicAliasMaximum"] == "64")
    return {"ok": ok, "state": short(values)}


def case_telemetry(observer) -> dict:
    observer.take("raw_data_demo")
    time.sleep(6)
    found = observer.take("raw_data_demo")
    lengths = sorted({len(m[1]) for m in found})
    return {"ok": len(found) >= 3, "messages": len(found), "lengths": lengths}


def send_one(observer, size: int, qos: int) -> dict:
    sequence = int(read(["EdgeTest.SendSequence"])["EdgeTest.SendSequence"]) + 1
    write([("EdgeTest.SendSize", str(size)), ("EdgeTest.IsQos1", "TRUE" if qos == 1 else "FALSE"),
           ("EdgeTest.IsQos2", "TRUE" if qos == 2 else "FALSE")])
    write([("EdgeTest.SendSequence", str(sequence))])
    done = wait_for(["EdgeTest.DoneSequence", "EdgeTest.RejectedCount"],
                    lambda v: int(v["EdgeTest.DoneSequence"]) == sequence, 15)
    time.sleep(0.3)
    found = observer.take("raw_data_demo/edge")
    exact = [m for m in found if m[1] == expected_payload(size, sequence)]
    return {"size": size, "qos": qos, "done": done is not None, "received": len(found), "exact": len(exact),
            "receivedQos": sorted({m[2] for m in found})}


def case_send(observer) -> dict:
    write([("EdgeTest.IsEnabled", "TRUE")])
    results = [send_one(observer, size, qos) for qos in (0, 1, 2) for size in SEND_SIZES]
    bad = [r for r in results if not (r["done"] and r["received"] == 1 and r["exact"] == 1)]
    return {"ok": not bad, "sent": len(results), "bad": bad}


def case_receive(observer) -> dict:
    write([("EdgeTest.IsEnabled", "TRUE")])
    wait_for(["EdgeTest.Subscriber.SubscribeDone"], lambda v: v["EdgeTest.Subscriber.SubscribeDone"] == "TRUE", 15)
    sender = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="observer-mqtt5-sender", protocol=mqtt.MQTTv5)
    sender.username_pw_set("token", token("observer.token"))
    sender.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    sender.loop_start()
    results = []
    try:
        for qos in (0, 1, 2):
            for index, size in enumerate(RECEIVE_SIZES):
                payload = bytes((i * 7 + index + qos) % 256 for i in range(size))
                properties = Properties(PacketTypes.PUBLISH)
                properties.MessageExpiryInterval = 60
                properties.ContentType = "application/octet-stream"
                properties.UserProperty = [("source", "mqtt5_test"), ("size", str(size))]
                if index % 2:
                    properties.CorrelationData = b"corr-%d" % index
                    properties.ResponseTopic = "raw_data_demo/edge_reply"
                before = int(read(["EdgeTest.Receiver.ReceivedCount"])["EdgeTest.Receiver.ReceivedCount"])
                sender.publish("raw_data_demo/edge_in", payload, qos=qos, properties=properties).wait_for_publish(10)
                values = wait_for(["EdgeTest.Receiver.ReceivedCount", "EdgeTest.Receiver.LastSize",
                                   "EdgeTest.Receiver.LastAdler32"],
                                  lambda v: int(v["EdgeTest.Receiver.ReceivedCount"]) > before, 10)
                ok = (values is not None and int(values["EdgeTest.Receiver.ReceivedCount"]) == before + 1
                      and int(values["EdgeTest.Receiver.LastSize"]) == size
                      and int(values["EdgeTest.Receiver.LastAdler32"]) == zlib.adler32(payload))
                results.append({"size": size, "qos": qos, "ok": ok, "plc": values})
    finally:
        sender.loop_stop()
        sender.disconnect()
    bad = [r for r in results if not r["ok"]]
    return {"ok": not bad, "received": len(results), "bad": bad}


def case_publish_refused(observer) -> dict:
    """A QoS 1/2 publish outside the token's rules: PUBACK/PUBREC 0x87, Rejected, the connection stays up."""
    write([("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.TopicOut", "'denied/edge'")])
    results = []
    try:
        for qos in (1, 2):
            before = read(INFO + ["EdgeTest.RejectedCount"])
            sequence = int(read(["EdgeTest.SendSequence"])["EdgeTest.SendSequence"]) + 1
            write([("EdgeTest.SendSize", "64"), ("EdgeTest.IsQos1", "TRUE" if qos == 1 else "FALSE"),
                   ("EdgeTest.IsQos2", "TRUE" if qos == 2 else "FALSE")])
            write([("EdgeTest.SendSequence", str(sequence))])
            after = wait_for(INFO + ["EdgeTest.RejectedCount", "EdgeTest.Publisher.ReasonCode"],
                             lambda v: int(v["EdgeTest.RejectedCount"]) > int(before["EdgeTest.RejectedCount"]), 15)
            ok = (after is not None and after["EdgeTest.Publisher.ReasonCode"] == "135"
                  and after[C + ".counts.CountConnectAttempt"] == before[C + ".counts.CountConnectAttempt"]
                  and after["PLC_PRG.IsBrokerConnected"] == "TRUE")
            results.append({"qos": qos, "ok": ok, "after": short(after) if after else short(read(INFO))})
        write([("EdgeTest.SendSequence", str(int(read(["EdgeTest.SendSequence"])["EdgeTest.SendSequence"])))])
    finally:
        write([("EdgeTest.TopicOut", "'raw_data_demo/edge'")])
    # the next allowed publish still works on the same connection
    follow = send_one(observer, 100, 1)
    return {"ok": all(r["ok"] for r in results) and follow["exact"] == 1, "cases": results, "followUp": follow}


def case_subscribe_refused(observer) -> dict:
    write([("EdgeTest.IsEnabled", "FALSE")])
    time.sleep(1.5)
    write([("EdgeTest.TopicIn", "'denied/in'")])
    write([("EdgeTest.IsEnabled", "TRUE")])
    values = wait_for(["EdgeTest.Subscriber.SubscribeFail", "EdgeTest.Subscriber.ReasonCode", "EdgeTest.Subscriber.busy",
                       "PLC_PRG.IsBrokerConnected"],
                      lambda v: v["EdgeTest.Subscriber.SubscribeFail"] == "TRUE", 15)
    write([("EdgeTest.IsEnabled", "FALSE")])
    time.sleep(1.5)
    write([("EdgeTest.TopicIn", "'raw_data_demo/edge_in'"), ("EdgeTest.IsEnabled", "TRUE")])
    again = wait_for(["EdgeTest.Subscriber.SubscribeDone", "EdgeTest.Subscriber.ReasonCode"],
                     lambda v: v["EdgeTest.Subscriber.SubscribeDone"] == "TRUE", 15)
    ok = values is not None and values["EdgeTest.Subscriber.ReasonCode"] == "135" and again is not None
    return {"ok": ok, "refused": values, "resubscribed": again}


def case_takeover(observer) -> dict:
    """Another connection with the PLC's client id: the broker sends the PLC DISCONNECT 0x8E (session taken over)."""
    before = read(INFO)
    thief = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="BENCH_MQTT_DEMO", protocol=mqtt.MQTTv5)
    thief.username_pw_set("token", token("plc.token"))
    thief.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    thief.loop_start()
    time.sleep(1.0)
    thief.loop_stop()
    thief.disconnect()
    after = wait_for(INFO, lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE"
                     and int(v[C + ".counts.CountConnectAttempt"]) > int(before[C + ".counts.CountConnectAttempt"]), 30)
    ok = after is not None and after[C + ".MQTT_INFO.DisconnectReasonCode"] == "142"
    return {"ok": ok, "after": short(after) if after else short(read(INFO))}


def case_connect_refused(observer) -> dict:
    """A wrong token: CONNACK 0x86 in ConnectReasonCode; then the right one connects again."""
    write([("PLC_PRG.BrokerUrl", "'%s'" % plc_url("mqtg_wrong_token_for_the_mqtt5_test")), (C + ".DoDisconnect", "TRUE")])
    refused = wait_for(INFO, lambda v: v[C + ".MQTT_INFO.ConnectReasonCode"] == "134", 30)
    restored = reconnect(plc_url(token("plc.token")), "5")
    return {"ok": refused is not None and restored is not None,
            "refused": short(refused) if refused else short(read(INFO)), "restored": restored is not None}


def case_idle_pending(observer) -> dict:
    write([("EdgeTest.IsEnabled", "FALSE")])
    time.sleep(2)
    samples = [read([C + ".IsSendPending", C + ".counts.OutSlotsWorking"]) for _ in range(10)]
    pending = sum(1 for s in samples if s[C + ".IsSendPending"] == "TRUE")
    return {"ok": True, "pendingSamples": pending, "of": len(samples), "samples": samples[:3]}


CASES = {"connect": case_connect, "telemetry": case_telemetry, "send": case_send, "receive": case_receive,
         "publish_refused": case_publish_refused, "subscribe_refused": case_subscribe_refused,
         "takeover": case_takeover, "connect_refused": case_connect_refused, "idle_pending": case_idle_pending}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default=",".join(CASES))
    parser.add_argument("--keep", action="store_true", help="leave the PLC on MQTT 5 and the private broker")
    args = parser.parse_args()
    names = [n for n in args.cases.split(",") if n]
    if names and names[0] != "connect":
        names.insert(0, "connect")
    observer = Observer()
    report = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": {}}
    try:
        for name in names:
            print("== %s" % name, flush=True)
            if not is_broker_up():
                report["cases"][name] = {"ok": False, "why": "private broker down (not a library result)"}
                print("   SKIPPED: broker %s:%d is down" % (BROKER_HOST, BROKER_PORT), flush=True)
                continue
            try:
                report["cases"][name] = CASES[name](observer)
            except Exception as error:  # a broken case must not skip the restore below
                report["cases"][name] = {"ok": False, "exception": repr(error)}
            print("   ok" if report["cases"][name].get("ok") else "   FAILED: %s"
                  % json.dumps(report["cases"][name])[:600], flush=True)
    finally:
        observer.close()
        write([("EdgeTest.IsEnabled", "FALSE"), ("EdgeTest.IsQos1", "FALSE"), ("EdgeTest.IsQos2", "FALSE"),
               ("EdgeTest.TopicOut", "'raw_data_demo/edge'"), ("EdgeTest.TopicIn", "'raw_data_demo/edge_in'")])
        if not args.keep:
            report["restored"] = reconnect(HQ_URL, "4") is not None
    out = HERE / "results" / "exp" / "mqtt5"
    out.mkdir(parents=True, exist_ok=True)
    path = out / (time.strftime("%Y%m%d-%H%M%S") + ".json")
    path.write_text(json.dumps(report, indent=1), encoding="utf-8")
    failed = [n for n, r in report["cases"].items() if not r.get("ok")]
    print("results: %s\nfailed: %s" % (path, failed or "none"), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
