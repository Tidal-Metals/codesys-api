"""Measure what BCNF's every-scan payload rebuild costs, using a verbatim copy of its StringPublication.

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_bcnf_every_scan.py --out results/bcnf_every_scan.json
Publishing is paused (PublishPeriod = 1 h) so the scan holds only the MQTT client and, in the second
window, BCNF's string building. The previous settings are restored afterwards.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

STATS = ["CycleUs", "MaxCycleUs", "MaxIntervalUs", "LastBcnfBuildUs", "MaxBcnfBuildUs",
         "BcnfBuildCount", "BcnfBuildTotalUs", "LargeSentCount"]

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

previous_period = str(on.read_value('PLC_PRG.PublishPeriod'))
write([('PublishPeriod', 'T#1H'), ('IsBcnfEveryScanEnabled', 'FALSE')])
time.sleep(@@SETTLE@@)
windows = {}
for label, enabled in (('baseline', 'FALSE'), ('bcnfEveryScan', 'TRUE')):
    write([('IsBcnfEveryScanEnabled', enabled)])
    time.sleep(1)
    write([('ResetStats', 'TRUE')])
    sent_before = number('LargeSentCount')
    samples = []
    end = time.time() + @@SECONDS@@
    while time.time() < end:
        samples.append(number('CycleUs'))
        time.sleep(0.5)
    values = dict((name, number(name)) for name in @@STATS@@)
    values['cycleSamplesUs'] = samples
    values['publishesDuringWindow'] = values['LargeSentCount'] - sent_before
    windows[label] = values
write([('IsBcnfEveryScanEnabled', 'FALSE'), ('PublishPeriod', previous_period)])
result = {'success': True, 'windows': windows, 'restoredPublishPeriod': previous_period}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=30)
    parser.add_argument("--settle", type=float, default=4)
    parser.add_argument("--out")
    args = parser.parse_args()
    code = (CODE.replace("@@STATS@@", repr(STATS)).replace("@@SECONDS@@", repr(args.seconds))
            .replace("@@SETTLE@@", repr(args.settle)))
    result = execute(code, int(2 * args.seconds + args.settle) + 90)
    if not result.get("success"):
        print(json.dumps(result, indent=1))
        return 1
    for values in result["windows"].values():
        samples = values["cycleSamplesUs"]
        values["cycleSampleMeanUs"] = round(sum(samples) / len(samples)) if samples else None
        if values.get("BcnfBuildCount"):
            values["bcnfBuildMeanUs"] = round(values["BcnfBuildTotalUs"] / values["BcnfBuildCount"])
    text = json.dumps({"windows": result["windows"], "restoredPublishPeriod": result["restoredPublishPeriod"]}, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
