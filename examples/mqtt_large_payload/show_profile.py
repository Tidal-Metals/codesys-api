"""Print one scenario of measure_profile.py results side by side for several experiments.

    python examples/mqtt_large_payload/show_profile.py fullrefresh_calls1 base buf16k freenow
Reads results/exp/<label>/profile.json; mean and worst us per section.
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "exp"


def main() -> int:
    scenario, labels = sys.argv[1], sys.argv[2:]
    data = {}
    for label in labels:
        path = RESULTS / label / "profile.json"
        if path.exists():
            data[label] = json.loads(path.read_text(encoding="utf-8"))["scenarios"].get(scenario)
    print("%-11s" % scenario + "".join("%22s" % label for label in data))
    sections = next(iter(data.values()))["meanUs"].keys()
    for section in sections:
        print("%-11s" % section + "".join("%22s" % ("%s / %s" % (d["meanUs"][section], d["maxUs"][section])) for d in data.values()))
    print("%-11s" % "calls" + "".join("%22s" % d["calls"] for d in data.values()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
