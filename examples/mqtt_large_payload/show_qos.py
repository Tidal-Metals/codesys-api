"""Print qos_test.py and qos_broker_test.py results compactly.

    python examples/mqtt_large_payload/show_qos.py qos_baseline [qos_fixed ...]
"""
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "exp"


def main() -> int:
    for label in sys.argv[1:]:
        print("== %s" % label)
        matrix = RESULTS / label / "qos.json"
        if matrix.exists():
            data = json.loads(matrix.read_text(encoding="utf-8"))
            for row in data["incoming"]:
                print("  in  sub %(subscribeQoS)d pub %(publishQoS)d %(kind)-5s sent %(sent)3d in order %(inOrder)3d "
                      "dup %(duplicates)2d lost %(gaps)2d reconnects %(reconnects)d  %(verdict)s"
                      % dict(row, kind="paced" if row["paceSeconds"] else "burst", verdict="ok" if row["ok"] else "FAIL"))
            for row in data["outgoing"]:
                print("  out qos %(qos)d sent %(sent)d delivered %(delivered)d dup %(duplicates)d missing %(missing)d "
                      "timeouts %(timeouts)d  %(verdict)s" % dict(row, verdict="ok" if row["ok"] else "FAIL"))
        scripted = RESULTS / label / "scripted.json"
        if scripted.exists():
            for name, row in json.loads(scripted.read_text(encoding="utf-8"))["scenarios"].items():
                verdict = {True: "ok", False: "FAIL", None: "?"}[row.get("ok")]
                details = {k: v for k, v in row.items() if k != "ok"}
                print("  %-15s %-4s %s" % (name, verdict, json.dumps(details)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
