"""Measure building and sending BCNF's values as tag:value lines (one message, once a second).

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_tag_value.py --qos 0 --out results/tag_value_qos0.json
The large demo payload is paused (PublishPeriod = 1 h) so the only MQTT traffic is the tag:value
message, as it would be on BCNF. Previous settings are restored afterwards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

STATS = ["CycleUs", "MaxCycleUs", "MaxIntervalUs", "MaxClientUs", "LastTagValueLength",
         "LastTagValueBuildUs", "MaxTagValueBuildUs", "TagValueBuildCount", "TagValueBuildTotalUs",
         "LastTagValuePublishUs", "MaxTagValuePublishUs", "LastTagValuePublishCycles", "MaxTagValuePublishCycles",
         "TagValueSentCount", "TagValueTimeoutCount"]

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state

def number(name):
    text = str(on.read_value('PLC_PRG.' + name)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for name, value in values:
        on.set_prepared_value('PLC_PRG.' + name, value)
    on.write_prepared_values()

previous = dict((name, str(on.read_value('PLC_PRG.' + name))) for name in ('PublishPeriod', 'IsQos1'))
write([('PublishPeriod', 'T#1H'), ('IsBcnfEveryScanEnabled', 'FALSE'), ('IsQos1', @@QOS1@@),
       ('IsTagValueEnabled', 'TRUE')])
time.sleep(@@SETTLE@@)
write([('ResetStats', 'TRUE')])
sent_before = number('TagValueSentCount')
samples = []
end = time.time() + @@SECONDS@@
while time.time() < end:
    samples.append(number('CycleUs'))
    time.sleep(0.5)
values = dict((name, number(name)) for name in @@STATS@@)
values['cycleSamplesUs'] = samples
values['sentDuringWindow'] = values['TagValueSentCount'] - sent_before
write([('IsTagValueEnabled', 'FALSE'), ('PublishPeriod', previous['PublishPeriod']), ('IsQos1', previous['IsQos1'])])
result = {'success': True, 'run': values, 'restored': previous}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qos", type=int, choices=[0, 1], default=0)
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--settle", type=float, default=4)
    parser.add_argument("--out")
    args = parser.parse_args()
    code = (CODE.replace("@@STATS@@", repr(STATS)).replace("@@SECONDS@@", repr(args.seconds))
            .replace("@@SETTLE@@", repr(args.settle)).replace("@@QOS1@@", repr("TRUE" if args.qos else "FALSE")))
    result = execute(code, int(args.seconds + args.settle) + 90)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    run = result["run"]
    samples = run["cycleSamplesUs"]
    run["cycleSampleMeanUs"] = round(sum(samples) / len(samples)) if samples else None
    if run.get("TagValueBuildCount"):
        run["tagValueBuildMeanUs"] = round(run["TagValueBuildTotalUs"] / run["TagValueBuildCount"])
    run.update(qos=args.qos, seconds=args.seconds)
    text = json.dumps({"run": run, "restored": result["restored"]}, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
