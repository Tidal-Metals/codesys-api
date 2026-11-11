"""The PLC's will and birth under real failures, per the device liveness contract
(scada-greenfield-rewrite docs/41-device-liveness-contract.md), library 1.4.0.0.

    python examples/mqtt_large_payload/will_failure_test.py [--out results/exp/sfw/will_failure.json]

The PLC connects (MQTT 5, contract settings, will 'offline' / birth 'online' on STATUS_TOPIC) to the temporary
MQTTug on the dev VM through mqtt_link_proxy.py, run on the VM on PROXY_PORT, so the link can be frozen. Cases:
  1. re-assert: a fresh 'online' about every 60 s while connected (BirthReassertTime T#60S);
  2. silent link loss: the proxy is frozen (SIGSTOP; TCP stays open, nothing flows): the broker publishes 'offline'
     after its keep-alive check (1.5 x 8 s); SIGCONT: the PLC reconnects and publishes 'online';
  3. the PLC application stops (bench API): 'offline'; started again: 'online';
  4. MqttClient.DoDisconnect (closes without a DISCONNECT): 'offline' at once, then 'online' after the reconnect.
Needs the PLC reserved (tmp/mqtt5_bench/reservation.json). Afterwards the PLC is back on MQTT 3.1.1 at HQ with the
library's default will, the proxy stopped.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import will_test as wt  # noqa: E402

VM = "ktritz@192.168.50.142"
HOST, PROXY_PORT, BROKER_PORT = "192.168.50.142", 1888, 1887
STATUS_TOPIC = wt.STATUS_TOPIC
C = m5.C


def vm(command: str) -> str:
    return subprocess.run(["ssh", "-n", VM, command], capture_output=True, text=True, timeout=60).stdout.strip()


def start_proxy() -> str:
    """mqtt_link_proxy.py on the VM, 1888 -> the broker; started by ~/tmp/sfw-bench/proxy/vm_proxy_start.sh
    (codesys-api tmp/mqtt5_bench/vm_proxy_start.sh), since a background launch straight from ssh hangs."""
    return vm("~/tmp/sfw-bench/proxy/vm_proxy_start.sh").splitlines()[-1]


class TimedWatcher:
    """Records (seconds since start, payload) for every message on the status topic."""

    def __init__(self):
        self.start = time.time()
        self.events = []
        self.lock = threading.Lock()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="observer-will-failure",
                                  protocol=mqtt.MQTTv5)
        self.client.username_pw_set("token", wt.token("sfw_observer.token"))
        self.client.on_message = self._on_message
        self.client.on_connect = lambda c, u, f, rc, p: c.subscribe(STATUS_TOPIC, qos=1)
        self.client.connect(HOST, BROKER_PORT, keepalive=15)
        self.client.loop_start()
        time.sleep(1.5)

    def _on_message(self, client, userdata, message):
        with self.lock:
            self.events.append((round(time.time() - self.start, 1), bytes(message.payload).decode("utf-8", "replace")))

    def mark(self) -> float:
        return round(time.time() - self.start, 1)

    def wait_for(self, payload: str, after: float, seconds: float):
        """Seconds from `after` to the first `payload` received after it, or None."""
        end = time.time() + seconds
        while time.time() < end:
            with self.lock:
                for at, text in self.events:
                    if at >= after and text == payload:
                        return round(at - after, 1)
            time.sleep(0.2)
        return None

    def since(self, after: float):
        with self.lock:
            return [e for e in self.events if e[0] >= after]

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


def app(command: str) -> str:
    """POST plc/app/<command> on the bench API with the reservation."""
    import urllib.request
    repo = HERE.parents[1]
    key = json.loads((repo / "api_keys.json").read_text())
    key = next(iter(key)) if isinstance(key, dict) else key[0]
    reservation = json.loads((m5.BENCH / "reservation.json").read_text())["reservation"]["token"]
    request = urllib.request.Request("http://127.0.0.1:8081/api/v1/plc/app/%s" % command, data=b"{}", method="POST",
                                     headers={"Authorization": "ApiKey %s" % key, "X-Bench-Reservation": reservation,
                                              "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read().decode()[:120]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    nowill = wt.token("sfw_plc_nowill.token")
    results = {"started": time.strftime("%Y-%m-%d %H:%M:%S")}
    proxy = start_proxy()
    results["proxy_pid"] = proxy
    wt.clear_retained(nowill)
    watcher = TimedWatcher()
    try:
        proxied_url = "token:%s@%s:%d" % (nowill, HOST, PROXY_PORT)
        t0 = watcher.mark()
        results["connect"] = wt.connect_plc(proxied_url, "5", wt.CONTRACT)
        results["birth_after_connect_s"] = watcher.wait_for("online", t0, 20)

        # 1. re-assert
        t1 = watcher.mark()
        time.sleep(130)
        results["reassert_events"] = watcher.since(t1)

        # 2. silent link loss through the frozen proxy
        t2 = watcher.mark()
        vm("kill -STOP %s" % proxy)
        results["frozen_offline_after_s"] = watcher.wait_for("offline", t2, 40)
        t2b = watcher.mark()
        vm("kill -CONT %s" % proxy)
        results["unfrozen_online_after_s"] = watcher.wait_for("online", t2b, 40)

        # 3. the application stops
        time.sleep(5)
        t3 = watcher.mark()
        results["app_stop"] = app("stop")
        results["app_stop_offline_after_s"] = watcher.wait_for("offline", t3, 40)
        t3b = watcher.mark()
        results["app_start"] = app("start")
        results["app_start_online_after_s"] = watcher.wait_for("online", t3b, 40)

        # 4. DoDisconnect
        time.sleep(5)
        t4 = watcher.mark()
        m5.write([(C + ".DoDisconnect", "TRUE")])
        results["dodisconnect_offline_after_s"] = watcher.wait_for("offline", t4, 30)
        results["dodisconnect_online_after_s"] = watcher.wait_for("online", t4, 40)
        results["all_events"] = watcher.since(0)
    finally:
        watcher.close()
        try:
            m5.write(wt.DEFAULT_WILL)
            m5.reconnect(m5.HQ_URL, "4")
        finally:
            vm("kill -CONT %s; kill %s" % (proxy, proxy))
            wt.clear_retained(nowill)
    print(json.dumps(results, indent=1))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
