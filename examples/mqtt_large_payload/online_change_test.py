"""Online changes and resets of the bench PLC while the MQTT client is busy (fork 1.3.0.0, HQ broker).

Run from the repo root after a bench_cycle deploy (the demo with OnlineChangeProbe, session project = the fork copy):
    python examples/mqtt_large_payload/online_change_test.py --out examples/mqtt_large_payload/results/exp/online/online.json
While commands arrive every 0.5 s (QoS 1, answered by EdgeTest's echo) and ScaleTest publishes its full refresh
every second, this makes, in the session project, then downloads with OnlineChangeOption.Force (online change or
nothing, never a full download):
  code      OnlineChangeProbe's implementation changed (ProbeValue := n)
  variable  a variable added to PLC_PRG, the program that holds the MQTT client and its buffers (its instance can
            move: pointers into it - the client's buffers, the publishers' data - are the risk)
and then warm and cold resets (the application restarts; the client's dynamic memory must not grow).
For each step: did it apply, does the application run, how long were commands unanswered, did the client
reconnect, did dynamic memory change. The session project keeps the edits; the next bench_cycle redeploys the demo.
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

BROKER = "192.168.50.240"
COMMANDS, ECHO, SCALE = "raw_data_demo/edge_in", "raw_data_demo/edge_echo", "raw_data_demo/scale"

CHANGE = """
import time
from scriptengine import OnlineChangeOption
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('mqtt_large_payload_demo_tm/mqtt_large_payload_demo.project'), p.path
kind, n = @@KIND@@, @@N@@
probe = p.find('OnlineChangeProbe', True)[0]
probe.textual_implementation.replace(u'ProbeValue := %d;' % n)
if kind == 'variable':
    prg = p.find('PLC_PRG', True)[0]
    decl = prg.textual_declaration.text
    at = decl.find(u'END_VAR')
    prg.textual_declaration.replace(decl[:at] + u'\\tOnlineChangeExtra%d : UDINT := %d;\\n' % (n, n) + decl[at:])
on = session.ensure_online_application('', False)
try:
    logged = bool(on.is_logged_in)
except Exception:
    logged = False
if logged:
    on.logout()
started = time.time()
error = None
try:
    on.login(OnlineChangeOption.Force, False)
except Exception as exc:
    error = str(exc)
out = {'success': True, 'loginSeconds': round(time.time() - started, 1), 'error': error,
       'state': str(on.application_state)}
session.dispose_online_application(session.find_application('')[1]['path'], True)
result = out
"""
RESET = """
import time
from scriptengine import ResetOption
on = session.ensure_online_application('', True)
on.reset(ResetOption.@@KIND@@, False)
# the reset stops the application, but application_state may still read 'run' for a moment
deadline = time.time() + 10
while 'run' in str(on.application_state).lower() and time.time() < deadline:
    time.sleep(0.2)
if 'run' not in str(on.application_state).lower():
    on.start()
deadline = time.time() + 15
while 'run' not in str(on.application_state).lower() and time.time() < deadline:
    time.sleep(0.5)
result = {'success': True, 'state': str(on.application_state)}
"""
WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
STATE = """
on = session.ensure_online_application('', True)
def number(path):
    return int(str(on.read_value(path)).split('#')[-1])
result = {'success': True, 'probe': number('OnlineChangeProbe.ProbeValue'),
          'connected': str(on.read_value('PLC_PRG.IsBrokerConnected')) == 'TRUE',
          'attempts': number('PLC_PRG.MqttLink.clientFB.counts.CountConnectAttempt'),
          'dynMem': number('PLC_PRG.MqttLink.dynMemUsage'), 'echoes': number('EdgeTest.EchoCount'),
          'scaleSent': number('ScaleTest.SentCount'), 'scaleTimeouts': number('ScaleTest.TimeoutCount'),
          'state': str(on.application_state)}
"""


def run(code: str, timeout: float = 300) -> dict:
    result = execute(code, timeout)
    if not result.get("success"):
        raise RuntimeError(result)
    return result


def state() -> dict:
    return run(STATE, 60)


class Traffic:
    """Commands every 0.5 s; records when echoes and full refreshes arrive."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.echoes, self.scale = [], []
        self.running = True
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="online-change-%d" % os.getpid())
        client.on_connect = lambda c, u, f, r, p=None: c.subscribe([(ECHO, 1), (SCALE, 0)])
        client.on_message = self.on_message
        client.connect(BROKER, 1883, keepalive=30)
        client.loop_start()
        self.client = client
        threading.Thread(target=self.send_loop, daemon=True).start()

    def on_message(self, client, userdata, message) -> None:
        with self.lock:
            (self.echoes if message.topic == ECHO else self.scale).append(time.time())

    def send_loop(self) -> None:
        n = 0
        while self.running:
            n += 1
            self.client.publish(COMMANDS, b"cmd-%d" % n, qos=1)
            time.sleep(0.5)

    def gap(self, start: float, end: float, which: str) -> float:
        """The longest time without an arrival between start and end (s)."""
        with self.lock:
            stamps = sorted(t for t in (self.echoes if which == "echo" else self.scale) if start <= t <= end)
        points = [start] + stamps + [end]
        return round(max(b - a for a, b in zip(points, points[1:])), 1)

    def first_after(self, start: float, which: str):
        with self.lock:
            stamps = sorted(t for t in (self.echoes if which == "echo" else self.scale) if t >= start)
        return stamps[0] if stamps else None

    def stop(self) -> None:
        self.running = False
        self.client.loop_stop()
        self.client.disconnect()


ENABLE_TRAFFIC = [("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.IsEchoEnabled", "TRUE"), ("ScaleTest.IsEnabled", "TRUE"),
                  ("ScaleTest.IsQos1", "FALSE")]


def step(traffic: Traffic, name: str, code: str, expect_probe, settle: float) -> dict:
    is_reset = name.startswith("reset")
    before = state()
    started = time.time()
    result = run(code)
    if is_reset:
        # a reset reinitializes every variable, the test's enable flags too: switch the traffic back on, then time
        # how long until commands are answered again (the PLC's own counters restarted with it)
        run(WRITE.replace("@@VALUES@@", repr(ENABLE_TRAFFIC)))
        started = time.time()
    time.sleep(settle)
    after = state()
    ended = time.time()
    row = {"step": name, "applied": result.get("error") is None, "error": result.get("error"),
           "loginSeconds": result.get("loginSeconds"), "running": "run" in after["state"].lower(),
           "probe": after["probe"], "connected": after["connected"], "dynMemBefore": before["dynMem"],
           "dynMemAfter": after["dynMem"], "scaleTimeouts": after["scaleTimeouts"] - (0 if is_reset else before["scaleTimeouts"])}
    if is_reset:
        first = traffic.first_after(started, "echo")
        row["secondsUntilAnswered"] = round(first - started, 1) if first else None
        row["longestEchoGapAfterThat"] = traffic.gap(first, ended, "echo") if first else None
        row["echoesSince"] = after["echoes"]
    else:
        row["reconnects"] = after["attempts"] - before["attempts"]
        row["longestEchoGapSeconds"] = traffic.gap(started, ended, "echo")
        row["longestRefreshGapSeconds"] = traffic.gap(started, ended, "scale")
        row["echoesDuring"] = after["echoes"] - before["echoes"]
    if expect_probe is not None:
        row["probeOk"] = after["probe"] == expect_probe
    print(json.dumps(row), flush=True)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code-changes", type=int, default=5)
    parser.add_argument("--variable-changes", type=int, default=3)
    parser.add_argument("--settle", type=float, default=12, help="seconds after each step before reading")
    parser.add_argument("--resets", nargs="*", default=["Warm", "Warm", "Cold"], choices=["Warm", "Cold"])
    parser.add_argument("--out")
    args = parser.parse_args()
    run(WRITE.replace("@@VALUES@@", repr([("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.IsEchoEnabled", "TRUE"),
                                         ("ScaleTest.IsEnabled", "TRUE"), ("ScaleTest.IsQos1", "FALSE")])))
    traffic = Traffic()
    time.sleep(5)
    report = {"steps": []}
    n = 100
    try:
        for _ in range(args.code_changes):
            n += 1
            code = CHANGE.replace("@@KIND@@", "'code'").replace("@@N@@", str(n))
            report["steps"].append(step(traffic, "code change %d" % n, code, n, args.settle))
        for _ in range(args.variable_changes):
            n += 1
            code = CHANGE.replace("@@KIND@@", "'variable'").replace("@@N@@", str(n))
            report["steps"].append(step(traffic, "variable added to PLC_PRG %d" % n, code, n, args.settle))
        for kind in args.resets:
            report["steps"].append(step(traffic, "reset %s" % kind.lower(), RESET.replace("@@KIND@@", kind), None,
                                        args.settle + 8))
    finally:
        traffic.stop()
    changes = [r for r in report["steps"] if not r["step"].startswith("reset")]
    resets = [r for r in report["steps"] if r["step"].startswith("reset")]
    report["success"] = (all(r["applied"] and r["running"] and r.get("probeOk") and r["reconnects"] == 0
                             and r["dynMemAfter"] == r["dynMemBefore"] and r["longestEchoGapSeconds"] < 3 for r in changes)
                         and all(r["running"] and r["connected"] and r["secondsUntilAnswered"] is not None
                                 and r["secondsUntilAnswered"] < 15 for r in resets)
                         # a leak would grow the client's allocation, or fail it, from one reset to the next
                         and len({r["dynMemAfter"] for r in resets}) <= 1)
    text = json.dumps(report, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print("success:", report["success"])
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
