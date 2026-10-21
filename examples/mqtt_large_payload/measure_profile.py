"""Where the MQTT client's time goes: read MqttClient.Profile (MQTT 1.3.0.0 Tidal Metals and later) per scenario.

Run from the repo root after deploy_demo.py with a profiling-capable library (session logged in):
    python examples/mqtt_large_payload/measure_profile.py --out results/profile/<label>.json
Scenarios: idle (nothing to send, one client call per scan), and the 2,000-tag tag:value full refresh
(26 KB, QoS 0) at 1 and at 16 client calls per scan. For each: profiled calls, and per section the mean
and the worst microseconds per call. Settings are restored afterwards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

SECTIONS = ["PREPARE", "PARSE_IN", "STATE_IN", "STATE_OUT", "SEND_OUT", "SEND_IN", "CASE_REST", "CONTROL", "TAIL", "TOTAL"]

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state
P = 'PLC_PRG.MqttLink.clientFB.Profile'
SECTIONS = @@SECTIONS@@

def number(path):
    text = str(on.read_value(path)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for path, value in values:
        on.set_prepared_value(path, value)
    on.write_prepared_values()

def profile(seconds):
    write([(P + '.IsEnabled', 'TRUE'), (P + '.Reset', 'TRUE')])
    time.sleep(seconds)
    calls = number(P + '.Calls')
    out = {'calls': calls, 'meanUs': {}, 'maxUs': {}}
    for i, name in enumerate(SECTIONS):
        total = number('%s.TotalUs[%d]' % (P, i))
        out['meanUs'][name] = round(float(total) / calls, 1) if calls else None
        out['maxUs'][name] = number('%s.MaxUs[%d]' % (P, i))
    write([(P + '.IsEnabled', 'FALSE')])
    return out

previous_period = str(on.read_value('PLC_PRG.PublishPeriod'))
write([('PLC_PRG.PublishPeriod', 'T#1H'), ('PLC_PRG.IsTagValueEnabled', 'FALSE'), ('PLC_PRG.IsBcnfEveryScanEnabled', 'FALSE'),
       ('ScaleTest.IsEnabled', 'FALSE'), ('PLC_PRG.ClientCallsPerScan', '1'), ('PLC_PRG.ClientBudgetUs', '1000000'),
       ('PLC_PRG.IsClientLoopGated', 'TRUE')])
time.sleep(3)
result = {'scenarios': {}}
result['scenarios']['idle_calls1'] = profile(@@SECONDS@@)
for calls in (1, 16):
    write([('ScaleTest.IsTagValueFormat', 'TRUE'), ('ScaleTest.TagsPerScan', '2000'), ('ScaleTest.IsQos1', 'FALSE'),
           ('ScaleTest.OnlyKind', '0'), ('ScaleTest.TimestampMode', '0'), ('PLC_PRG.ClientCallsPerScan', str(calls)),
           ('ScaleTest.IsEnabled', 'TRUE')])
    time.sleep(3)
    result['scenarios']['fullrefresh_calls%d' % calls] = profile(@@SECONDS@@)
    result['scenarios']['fullrefresh_calls%d' % calls]['lastPublishUs'] = number('ScaleTest.LastPublishUs')
    write([('ScaleTest.IsEnabled', 'FALSE')])
    time.sleep(2)
write([('PLC_PRG.ClientCallsPerScan', '1'), ('PLC_PRG.ClientBudgetUs', '5000'), ('PLC_PRG.PublishPeriod', previous_period)])
result['success'] = True
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--out")
    args = parser.parse_args()
    code = CODE.replace("@@SECTIONS@@", repr(SECTIONS)).replace("@@SECONDS@@", repr(args.seconds))
    result = execute(code, 600)
    text = json.dumps(result, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    if not result.get("success"):
        print(text)
        return 1
    print("%-12s" % "section" + "".join("%26s" % name for name in result["scenarios"]))
    print("%-12s" % "" + "".join("%26s" % "mean / max us" for _ in result["scenarios"]))
    for section in SECTIONS:
        row = "%-12s" % section
        for scenario in result["scenarios"].values():
            row += "%26s" % ("%s / %s" % (scenario["meanUs"][section], scenario["maxUs"][section]))
        print(row)
    print("%-12s" % "calls" + "".join("%26s" % s["calls"] for s in result["scenarios"].values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
