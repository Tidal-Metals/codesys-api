"""Measure the 2,000-tag scale test (ScaleTest) in one format, build split and QoS.

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_scale.py --format tagvalue --tags-per-scan 2000 --qos 0
The demo's own large payload is paused (PLC_PRG.PublishPeriod = 1 h) so ScaleTest is the only MQTT
traffic. Previous settings are restored afterwards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

SCALE_STATS = ["LastPayloadLength", "LastBuildUs", "MaxBuildUs", "BuildTotalUs", "BuildCount", "MaxBuildScanUs",
               "LastBuildScans", "LastPublishUs", "MaxPublishUs", "LastPublishCycles", "MaxPublishCycles",
               "SentCount", "TimeoutCount", "OverflowCount", "SkippedBusyCount", "ValueUpdateUs", "NamesInitUs"]
PRG_STATS = ["CycleUs", "MaxCycleUs", "MaxIntervalUs", "MinIntervalUs", "MaxClientUs"]

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state

def number(path):
    text = str(on.read_value(path)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for path, value in values:
        on.set_prepared_value(path, value)
    on.write_prepared_values()

previous_period = str(on.read_value('PLC_PRG.PublishPeriod'))
write([('PLC_PRG.PublishPeriod', 'T#1H'), ('PLC_PRG.IsTagValueEnabled', 'FALSE'), ('PLC_PRG.IsBcnfEveryScanEnabled', 'FALSE'),
       ('ScaleTest.IsTagValueFormat', @@TAGVALUE@@), ('ScaleTest.TagsPerScan', '@@PER_SCAN@@'),
       ('ScaleTest.IsQos1', @@QOS1@@), ('ScaleTest.IsEnabled', 'TRUE')])
time.sleep(@@SETTLE@@)
write([('ScaleTest.ResetStats', 'TRUE'), ('PLC_PRG.ResetStats', 'TRUE')])
sent_before = number('ScaleTest.SentCount')
samples = []
end = time.time() + @@SECONDS@@
while time.time() < end:
    samples.append(number('PLC_PRG.CycleUs'))
    time.sleep(0.5)
values = dict((name, number('ScaleTest.' + name)) for name in @@SCALE_STATS@@)
values.update(dict((name, number('PLC_PRG.' + name)) for name in @@PRG_STATS@@))
values['cycleSamplesUs'] = samples
values['sentDuringWindow'] = values['SentCount'] - sent_before
write([('ScaleTest.IsEnabled', 'FALSE'), ('PLC_PRG.PublishPeriod', previous_period)])
time.sleep(2)
result = {'success': True, 'run': values, 'restoredPublishPeriod': previous_period}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--format", choices=["tagvalue", "positional"], default="tagvalue")
    parser.add_argument("--tags-per-scan", type=int, default=2000)
    parser.add_argument("--qos", type=int, choices=[0, 1], default=0)
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--settle", type=float, default=5)
    parser.add_argument("--out")
    args = parser.parse_args()
    code = (CODE.replace("@@SCALE_STATS@@", repr(SCALE_STATS)).replace("@@PRG_STATS@@", repr(PRG_STATS))
            .replace("@@TAGVALUE@@", repr("TRUE" if args.format == "tagvalue" else "FALSE"))
            .replace("@@PER_SCAN@@", str(args.tags_per_scan)).replace("@@QOS1@@", repr("TRUE" if args.qos else "FALSE"))
            .replace("@@SECONDS@@", repr(args.seconds)).replace("@@SETTLE@@", repr(args.settle)))
    result = execute(code, int(args.seconds + args.settle) + 120)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    run = result["run"]
    samples = run.pop("cycleSamplesUs")
    run["cycleSampleMeanUs"] = round(sum(samples) / len(samples)) if samples else None
    run["cycleSampleMaxUs"] = max(samples) if samples else None
    if run.get("BuildCount"):
        run["buildMeanUs"] = round(run["BuildTotalUs"] / run["BuildCount"])
    run.update(format=args.format, tagsPerScan=args.tags_per_scan, qos=args.qos, seconds=args.seconds)
    text = json.dumps(run, indent=1)
    print(json.dumps(run))
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
