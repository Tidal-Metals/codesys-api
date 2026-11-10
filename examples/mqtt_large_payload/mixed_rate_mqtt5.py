"""mixed_rate_test.py (QoS 0 vs QoS 1 under a mixed-rate load) on a chosen broker and MQTT version, and with the client
loop's early stop on MqttClient.IsSendPending.

    python examples/mqtt_large_payload/mixed_rate_mqtt5.py --broker mqttug --protocol 5 [--early-stop] \
        -- --layouts consolidated --qos 0 1 --seconds 90 --out examples/mqtt_large_payload/results/exp/mqtt5/<name>.json
Everything after -- goes to mixed_rate_test.py unchanged. --broker hq: 192.168.50.240:1883 (anonymous, MQTT 3.1.1 only,
as mixed_rate_test.py measures it); mqttug: the private MQTTug of mqtt5_test.py, where the PLC and this subscriber use
its tokens. --early-stop needs the demo copy patched by examples/mqtt_large_payload/patch_demo_early_stop.py (PLC_PRG.IsEarlyStopEnabled).
Needs library 1.4.0.0 on the PLC. Afterwards the PLC is back on MQTT 3.1.1 at HQ with the early stop off.
"""
import argparse
import sys
from pathlib import Path

import paho.mqtt.client as paho

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mixed_rate_test as mrt  # noqa: E402
import mqtt5_test as m5  # noqa: E402


class MqttugClient(paho.Client):
    """The benchmark's subscriber, on the private MQTTug with the observer token."""
    protocol_version = paho.MQTTv311

    def __init__(self, callback_api_version, client_id="", **kwargs):
        super().__init__(callback_api_version, client_id="observer-" + client_id,
                         protocol=MqttugClient.protocol_version, **kwargs)
        self.username_pw_set("token", m5.token("observer.token"))

    def connect(self, host, port=1883, keepalive=60, **kwargs):
        return super().connect(m5.BROKER_HOST, m5.BROKER_PORT, keepalive, **kwargs)


class PahoWithMqttug:
    """mixed_rate_test's view of paho.mqtt.client, with Client replaced."""

    def __getattr__(self, name):
        return MqttugClient if name == "Client" else getattr(paho, name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--broker", choices=["hq", "mqttug"], required=True)
    parser.add_argument("--protocol", type=int, choices=[4, 5], required=True)
    parser.add_argument("--early-stop", action="store_true")
    parser.add_argument("rest", nargs=argparse.REMAINDER, help="-- then mixed_rate_test.py's arguments")
    args = parser.parse_args()
    if args.broker == "hq" and args.protocol == 5:
        sys.exit("the HQ broker is measured on MQTT 3.1.1 only")
    rest = args.rest[1:] if args.rest[:1] == ["--"] else args.rest
    if args.broker == "mqttug":
        url = m5.plc_url(m5.token("plc.token"))
        MqttugClient.protocol_version = paho.MQTTv5 if args.protocol == 5 else paho.MQTTv311
        mrt.mqtt = PahoWithMqttug()
    else:
        url = m5.HQ_URL
    label = "broker=%s protocol=%d earlyStop=%s" % (args.broker, args.protocol, args.early_stop)
    if "--label" in rest:
        at = rest.index("--label") + 1
        rest[at] = label + " " + rest[at]
    else:
        rest += ["--label", label]
    if m5.reconnect(url, str(args.protocol)) is None:
        sys.exit("the PLC did not connect: %s" % label)
    try:
        m5.write([("PLC_PRG.IsEarlyStopEnabled", "TRUE" if args.early_stop else "FALSE")])
        sys.argv = [str(HERE / "mixed_rate_test.py")] + rest
        return mrt.main()
    finally:
        m5.write([("PLC_PRG.IsEarlyStopEnabled", "FALSE")])
        m5.reconnect(m5.HQ_URL, "4")


if __name__ == "__main__":
    sys.exit(main())
