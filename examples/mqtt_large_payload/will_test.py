"""The will and birth options of library 1.4.0.0 (MQTT_IN_OUT.IsWillEnabled, WillQoS, BirthMessage) on the bench PLC,
against the device liveness contract (scada-greenfield-rewrite docs/41-device-liveness-contract.md).

    python examples/mqtt_large_payload/will_test.py [--out results/exp/sfw/will.json]

Against the temporary MQTTug on the dev VM (192.168.50.142:1887):
  1. the default will (<ClientID>/MQTTWill/<ClientID>/DEAD) with a token whose rules do not cover it: refused (16#87);
  2. the will off, the same token: the PLC connects, and a session takeover publishes nothing;
  3. the contract: will 'offline' and birth 'online', retained, QoS 1, on STATUS_TOPIC (the bench stands in for
     status/<group>/<node>, which the bench tokens don't allow): a fresh subscriber reads 'online' after the connect,
     a takeover publishes 'offline', and the PLC's reconnect publishes 'online' again;
  4. MQTT 3.1.1 at HQ with the will off, then with the default will: both connect.
A takeover is a second client connecting with the PLC's client id and token: MQTTug closes the PLC's connection
(16#8E) and publishes its will; the PLC reconnects and takes the session back. Tokens:
tmp/mqtt5_bench/sfw_plc_nowill.token (the PLC: client id BENCH_MQTT_DEMO, publish raw_data/sfw/#),
sfw_clear.token (client ids BENCH_SFW*, publish raw_data/sfw/#: clears the retained status between runs) and
sfw_observer.token (subscribe raw_data/sfw/#). Afterwards the PLC is back on MQTT 3.1.1 at HQ with
the library's default will.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402

HOST, PORT = "192.168.50.142", 1887
CLIENT_ID = "BENCH_MQTT_DEMO"
STATUS_TOPIC = "raw_data/sfw/status"
C = m5.C
STATE = ["PLC_PRG.IsBrokerConnected", C + ".MQTT_INFO.ConnectReasonCode", C + ".MQTT_INFO.DisconnectReasonCode",
         C + ".counts.CountConnectAttempt"]
DEFAULT_WILL = [("PLC_PRG.MqttLink.IsWillEnabled", "TRUE"), ("PLC_PRG.MqttLink.BuildWillTopicAndMessage", "TRUE"),
                ("PLC_PRG.MqttLink.ClientWillTopic", "'DEAD'"), ("PLC_PRG.MqttLink.ClientWillMessage", "'DIED'"),
                ("PLC_PRG.MqttLink.WillQoS", "2"), ("PLC_PRG.MqttLink.BirthMessage", "''")]
NO_WILL = [("PLC_PRG.MqttLink.IsWillEnabled", "FALSE")] + DEFAULT_WILL[1:]
CONTRACT = [("PLC_PRG.MqttLink.IsWillEnabled", "TRUE"), ("PLC_PRG.MqttLink.BuildWillTopicAndMessage", "FALSE"),
            ("PLC_PRG.MqttLink.ClientWillTopic", "'%s'" % STATUS_TOPIC),
            ("PLC_PRG.MqttLink.ClientWillMessage", "'offline'"), ("PLC_PRG.MqttLink.WillQoS", "1"),
            ("PLC_PRG.MqttLink.BirthMessage", "'online'"), ("PLC_PRG.MqttLink.BirthReassertTime", "T#60S")]


def token(name: str) -> str:
    return (m5.BENCH / name).read_text(encoding="utf-8").strip()


def url(secret: str) -> str:
    return "token:%s@%s:%d" % (secret, HOST, PORT)


def short(values: dict) -> dict:
    return {k.split(".")[-1]: v for k, v in values.items()}


def connect_plc(target_url: str, version: str, will_settings, seconds: float = 15) -> dict:
    """Point the PLC at target_url with these will settings; wait for a connection or a refusal."""
    before = int(m5.read([C + ".counts.CountConnectAttempt"])[C + ".counts.CountConnectAttempt"])
    m5.write(list(will_settings) + [("PLC_PRG.BrokerUrl", "'%s'" % target_url),
                                    ("PLC_PRG.MqttLink.ProtocolVersion", version), (C + ".DoDisconnect", "TRUE")])
    end = time.time() + seconds
    values = m5.read(STATE)
    while time.time() < end:
        values = m5.read(STATE)
        if int(values[C + ".counts.CountConnectAttempt"]) > before and (
                values["PLC_PRG.IsBrokerConnected"] == "TRUE"
                or values[C + ".MQTT_INFO.ConnectReasonCode"] not in ("0", "")):
            break
        time.sleep(0.5)
    return short(values)


class Watcher:
    """MQTT 5 subscriber on the status topic; records (payload, retain flag) per message."""

    def __init__(self, client_id: str):
        self.messages = []
        self.lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, protocol=mqtt.MQTTv5)
        self.client.username_pw_set("token", token("sfw_observer.token"))
        self.client.on_message = self._on_message
        self.client.on_connect = lambda c, u, f, rc, p: c.subscribe(STATUS_TOPIC, qos=1)
        self.client.connect(HOST, PORT, keepalive=15)
        self.client.loop_start()
        time.sleep(1.5)

    def _on_message(self, client, userdata, message):
        with self.lock:
            self.messages.append((bytes(message.payload).decode("utf-8", "replace"), bool(message.retain)))

    def take(self):
        with self.lock:
            messages, self.messages = self.messages, []
        return messages

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def retained_now() -> list:
    """What a fresh subscriber reads: the retained status, if any."""
    watcher = Watcher("observer-status-fresh")
    messages = watcher.take()
    watcher.close()
    return messages


def clear_retained(_unused: str = "") -> None:
    """An empty retained publish removes the status a previous run left. Uses tmp/mqtt5_bench/sfw_clear.token
    (client id pattern BENCH_SFW*, publish raw_data/sfw/#): the PLC's tokens allow only the PLC's own client id.
    Raises when the broker refuses or the PUBACK doesn't come."""
    result = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="BENCH_SFW_clear", protocol=mqtt.MQTTv5)
    client.username_pw_set("token", token("sfw_clear.token"))
    client.on_connect = lambda c, u, f, rc, p: result.setdefault("rc", rc)
    client.connect(HOST, PORT, keepalive=10)
    client.loop_start()
    try:
        info = client.publish(STATUS_TOPIC, b"", qos=1, retain=True)
        info.wait_for_publish(5)
        if result.get("rc") is None or result["rc"].is_failure or not info.is_published():
            raise RuntimeError("clearing the retained status failed (CONNACK %s)" % result.get("rc"))
    finally:
        client.loop_stop()
        client.disconnect()


def take_over(secret: str) -> str:
    """Connect once with the PLC's client id (no automatic reconnect): MQTTug closes the PLC's session (16#8E)."""
    result = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID, protocol=mqtt.MQTTv5,
                         reconnect_on_failure=False)
    client.username_pw_set("token", secret)
    client.on_connect = lambda c, u, f, rc, p: result.setdefault("rc", str(rc))
    client.connect(HOST, PORT, keepalive=10)
    client.loop_start()
    time.sleep(1.5)
    client.loop_stop()
    client.disconnect()
    return result.get("rc", "no CONNACK")


def wait_connected(seconds: float = 20) -> dict:
    values = m5.wait_for(STATE, lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE", seconds)
    return short(values) if values else {"connected": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    nowill = token("sfw_plc_nowill.token")
    results = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "cases": {}}
    cases = results["cases"]
    watcher = None
    try:
        clear_retained(nowill)
        cases["1_default_will_token_without_rule"] = connect_plc(url(nowill), "5", DEFAULT_WILL)
        watcher = Watcher("observer-status")
        cases["2_will_off"] = connect_plc(url(nowill), "5", NO_WILL)
        watcher.take()
        cases["2_takeover_will_off"] = {"connack": take_over(nowill), "status": (time.sleep(2.0), watcher.take())[1],
                                        "reconnected": wait_connected()}
        clear_retained(nowill)
        watcher.take()
        cases["3_contract_connect"] = connect_plc(url(nowill), "5", CONTRACT)
        time.sleep(2.0)
        cases["3_status_after_connect"] = watcher.take()
        cases["3_retained_after_connect"] = retained_now()
        cases["3_takeover"] = {"connack": take_over(nowill)}
        time.sleep(1.0)
        cases["3_status_after_takeover"] = watcher.take()
        cases["3_reconnected"] = wait_connected()
        time.sleep(2.0)
        cases["3_status_after_reconnect"] = watcher.take()
        cases["3_retained_after_reconnect"] = retained_now()
        clear_retained(nowill)
        cases["4_hq_v311_will_off"] = connect_plc(m5.HQ_URL, "4", NO_WILL)
        cases["4_hq_v311_default_will"] = connect_plc(m5.HQ_URL, "4", DEFAULT_WILL)
    finally:
        if watcher:
            watcher.close()
        m5.write(DEFAULT_WILL)
        m5.reconnect(m5.HQ_URL, "4")
    print(json.dumps(results, indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
