"""Do subscriptions survive reconnects when the client is called several times a scan (the recommended pattern)?

Run from the repo root after deploy_demo.py:
    python examples/mqtt_large_payload/resubscribe_test.py --out examples/mqtt_large_payload/results/exp/validation/resubscribe.json
With up to 32 client calls per scan (5 ms budget) and ScaleTest's full refresh keeping a send in flight, the client
can drop and restore the link between two calls of EdgeTest's MQTTSubscribe. Upstream's subscriber then never saw
the disconnect, kept SubscribeWasSended for a request the client had discarded, and never subscribed again: the
PLC silently stopped receiving. This forces --reconnects reconnects (DoDisconnect) and after each sends 3 commands
on EdgeTest's topic and checks they arrive.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

BROKER, COMMANDS = "192.168.50.240", "raw_data_demo/edge_in"
WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE = """
on = session.ensure_online_application('', True)
def t(p):
    return str(on.read_value(p)).split('#')[-1]
result = {'success': True, 'connected': t('PLC_PRG.IsBrokerConnected') == 'TRUE', 'received': int(t('EdgeTest.Receiver.ReceivedCount')),
          'attempts': int(t('PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt')),
          'subDone': t('EdgeTest.Subscriber.SubscribeDone'), 'subBusy': t('EdgeTest.Subscriber.busy')}
"""


CLIENT_ID = """
on = session.ensure_online_application('', True)
result = {'success': True, 'clientId': str(on.read_value('PLC_PRG.MqttLink.ClientID')).strip("'")}
"""


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state(tries: int = 4) -> dict:
    # an online read can time out (once seen just after a broker kick); a failed read has no values
    for _ in range(tries):
        current = execute(STATE, 60)
        if "connected" in current:
            return current
        print("state read failed: %s" % current.get("error"), flush=True)
        time.sleep(1)
    raise RuntimeError("no online state after %d reads" % tries)


def wait_for(predicate, seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        current = state()
        if predicate(current):
            return current
        time.sleep(0.3)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reconnects", type=int, default=15)
    parser.add_argument("--kick", action="store_true", help="drop the PLC from the broker side (client id takeover) instead of DoDisconnect")
    parser.add_argument("--out")
    args = parser.parse_args()
    write([("PLC_PRG.ClientCallsPerScan", "32"), ("PLC_PRG.ClientBudgetUs", "5000"), ("ScaleTest.IsEnabled", "TRUE"),
           ("ScaleTest.IsQos1", "FALSE"), ("EdgeTest.SubscribeQoS", "1"), ("EdgeTest.IsEnabled", "TRUE")])
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="resubscribe-test")
    client.connect(BROKER, 1883, keepalive=30)
    client.loop_start()
    rows = []
    try:
        client_id = execute(CLIENT_ID, 60)["clientId"]
        for n in range(args.reconnects):
            before = state()
            if args.kick:
                # the broker drops the PLC at once (session takeover by its own client id): the fast path, where the
                # client reconnects within one scan's calls (DoDisconnect's graceful close takes longer than that)
                intruder = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
                intruder.connect(BROKER, 1883, keepalive=30)
                intruder.loop(timeout=0.2)
                intruder.disconnect()
            else:
                write([("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
            back = wait_for(lambda s: s["connected"] and s["attempts"] > before["attempts"], 30)
            time.sleep(2)
            start = state()["received"]
            for k in range(3):
                client.publish(COMMANDS, b"resub-%d-%d" % (n, k), qos=1)
                time.sleep(0.3)
            time.sleep(2)
            after = state()
            rows.append({"reconnect": n + 1, "reconnected": back is not None, "commandsArrived": after["received"] - start,
                         "subscribeDone": after["subDone"], "subscriberBusy": after["subBusy"]})
            print(json.dumps(rows[-1]), flush=True)
    finally:
        client.loop_stop()
        client.disconnect()
        write([("PLC_PRG.ClientCallsPerScan", "1"), ("ScaleTest.IsEnabled", "FALSE")])
    report = {"rows": rows, "deadAfterReconnect": sum(1 for r in rows if r["commandsArrived"] == 0),
              "success": all(r["reconnected"] and r["commandsArrived"] == 3 for r in rows)}
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print("success:", report["success"], "dead after reconnect:", report["deadAfterReconnect"])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
