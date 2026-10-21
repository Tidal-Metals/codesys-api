"""Link loss on the bench PLC's MQTT connection: detection, reconnect, and recovery of publishing and commands.

Run from the repo root after deploy_demo.py (session logged in), with mqtt_link_proxy.py copied to the VM:
    python examples/mqtt_large_payload/measure_link_loss.py --out results/.../link_loss.json
Points PLC_PRG.BrokerUrl at the proxy on the Claude VM (192.168.50.142:1884, forwarding to the HQ broker),
runs the 2,000-tag full refresh once a second and a command every 200 ms answered by EdgeTest's QoS 1 echo,
then breaks the link: kills the proxy three times (restarting it after 5 s) and freezes it once for 40 s
(SIGSTOP: the connection stays open, nothing flows). For each fault: seconds until the PLC sees the link
down, seconds until it is connected again, and whether the full refresh and the echo resume without
timeouts. Restores BrokerUrl to the HQ broker at the end.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

VM = "ktritz@192.168.50.142"
PROXY_URL = "192.168.50.142:1884"
HQ_URL = "192.168.50.240:1883"
PROXY_START = "nohup python3 /tmp/mqtt_link_proxy.py --listen 1884 > /tmp/mqtt_link_proxy.log 2>&1 &"
# Anchored on the interpreter so the ssh shell (whose command line contains the pattern) is never matched.
PROXY_PIDS = "pgrep -f '^python3 /tmp/mqtt_link_proxy.py'"

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
          'scaleSent': int(text('ScaleTest.SentCount')), 'scaleTimeouts': int(text('ScaleTest.TimeoutCount')),
          'echoes': int(text('EdgeTest.EchoCount')), 'received': int(text('EdgeTest.Receiver.ReceivedCount')),
          'connectAttempts': int(text(C + '.counts.CountConnectAttempt'))}
"""


def vm(command: str) -> str:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", VM, command], capture_output=True, text=True, timeout=30).stdout


def proxy(action: str) -> None:
    if action == "start":
        vm(PROXY_START)
        time.sleep(1)
    else:
        signal = {"kill": "-9", "freeze": "-STOP", "thaw": "-CONT"}[action]
        vm("for p in $(%s); do kill %s $p; done" % (PROXY_PIDS, signal))


def write(values) -> None:
    result = execute(WRITE.replace("@@VALUES@@", repr(values)), 60)
    if not result.get("success"):
        raise RuntimeError(result)


def state() -> dict:
    return execute(STATE, 60)


def wait_for(predicate, seconds: float) -> tuple:
    started = time.time()
    while time.time() - started < seconds:
        current = state()
        if predicate(current):
            return round(time.time() - started, 1), current
        time.sleep(0.2)
    return None, state()


def connect_to(url: str) -> float:
    write([("PLC_PRG.BrokerUrl", "'%s'" % url), ("PLC_PRG.MqttLink.clientFB.DoDisconnect", "TRUE")])
    seconds, _ = wait_for(lambda s: s["connected"], 30)
    return seconds


def recovered(before: dict, seconds: float = 12) -> dict:
    time.sleep(seconds)
    after = state()
    return {"scaleSentSince": after["scaleSent"] - before["scaleSent"],
            "scaleTimeoutsSince": after["scaleTimeouts"] - before["scaleTimeouts"],
            "echoesSince": after["echoes"] - before["echoes"], "connected": after["connected"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kills", type=int, default=3)
    parser.add_argument("--freeze-seconds", type=float, default=40)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = {"faults": []}
    if not vm(PROXY_PIDS).strip():
        proxy("start")
    echoes, stop = [], threading.Event()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="linkloss-%d" % os.getpid())
    client.on_connect = lambda c, u, f, r, p=None: c.subscribe("raw_data_demo/edge_echo", qos=1)
    client.on_message = lambda c, u, m: echoes.append((time.time(), m.payload.decode(errors="replace")))
    client.connect("192.168.50.240", 1883, keepalive=30)
    client.loop_start()

    def commands() -> None:
        n = 0
        while not stop.is_set():
            client.publish("raw_data_demo/edge_in", b"cmd%d" % n, qos=1)
            n += 1
            time.sleep(0.2)

    try:
        report["connectViaProxySeconds"] = connect_to(PROXY_URL)
        write([("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.IsEchoEnabled", "TRUE"), ("ScaleTest.IsTagValueFormat", "TRUE"),
               ("ScaleTest.TagsPerScan", "2000"), ("ScaleTest.IsQos1", "FALSE"), ("PLC_PRG.ClientCallsPerScan", "1"),
               ("ScaleTest.IsEnabled", "TRUE")])
        threading.Thread(target=commands, daemon=True).start()
        time.sleep(8)
        for trial in range(args.kills):
            time.sleep(2.0 + 0.3 * trial)  # vary where in the 1 s publish cycle the link breaks
            before = state()
            proxy("kill")
            detect, _ = wait_for(lambda s: not s["connected"], 60)
            time.sleep(5)
            proxy("start")
            reconnect, _ = wait_for(lambda s: s["connected"], 60)
            report["faults"].append({"kind": "kill", "detectSeconds": detect, "reconnectSeconds": reconnect,
                                     **recovered(before)})
        before = state()
        proxy("freeze")
        detect, _ = wait_for(lambda s: not s["connected"], args.freeze_seconds)
        proxy("thaw")
        reconnect, _ = wait_for(lambda s: s["connected"], 60)
        report["faults"].append({"kind": "freeze", "frozenSeconds": args.freeze_seconds, "detectSeconds": detect,
                                 "reconnectSeconds": reconnect, **recovered(before)})
    finally:
        stop.set()
        write([("ScaleTest.IsEnabled", "FALSE"), ("EdgeTest.IsEchoEnabled", "FALSE")])
        report["restoreSeconds"] = connect_to(HQ_URL)
        client.loop_stop()
        client.disconnect()
    report["echoesTotal"] = len(echoes)
    report["duplicateEchoes"] = len(echoes) - len({payload for _, payload in echoes})
    ok = all(f["reconnectSeconds"] is not None and f["connected"] and f["scaleSentSince"] > 3
             and f["scaleTimeoutsSince"] == 0 and f["echoesSince"] > 3 for f in report["faults"])
    report["success"] = ok
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
