"""Tables from split_test.py results: the same 26 KB as 1 .. 1625 messages, per QoS and scan allowance.

    python examples/mqtt_large_payload/show_split.py split [--markdown]
Each cell: time to deliver all parts (ms, scans in brackets) / worst client time in one scan (ms).
"""
import argparse
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results" / "exp"


def cell(row: dict) -> str:
    if row is None:
        return ""
    if not row["rounds"]:
        return "no round"
    text = "%s (%s) / %.1f" % (format(row["roundMs"], ".0f"), format(row["roundScans"], "g"), row["maxScanClientMs"])
    return text if row["ok"] else text + " FAIL"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    data = json.loads((RESULTS / args.label / "split.json").read_text(encoding="utf-8"))
    rows = data["rows"]
    publishers = sorted({r["publishers"] for r in rows if r["publishers"] in (1, 8, 32)})
    parts = sorted({r["parts"] for r in rows})
    for allowance in ("call1", "budget5"):
        for qos in (0, 1, 2):
            subset = [r for r in rows if r["allowance"] == allowance and r["qos"] == qos]
            if not subset:
                continue
            title = "QoS %d, %s" % (qos, {"call1": "1 client call per scan", "budget5": "5 ms client budget"}[allowance])
            header = ["parts", "bytes each"] + ["%d publisher%s" % (p, "" if p == 1 else "s") for p in publishers]
            lines = []
            for count in parts:
                by_publishers = {min(r["publishers"], 32): r for r in subset if r["parts"] == count}
                # with fewer parts than publishers the cell ran with one publisher per part
                found = {p: next((r for r in subset if r["parts"] == count and r["publishers"] == min(p, count)), None)
                         for p in publishers}
                if not by_publishers:
                    continue
                size = next(iter(by_publishers.values()))["partBytes"]
                lines.append([str(count), str(size)] + [cell(found[p]) for p in publishers])
            if args.markdown:
                print("**%s** (ms to deliver all (scans) / worst client ms in a scan)\n" % title)
                print("| " + " | ".join(header) + " |")
                print("|" + "---|" * len(header))
                for line in lines:
                    print("| " + " | ".join(line) + " |")
                print()
            else:
                print("== " + title)
                widths = [max(len(x) for x in column) for column in zip(header, *lines)]
                for line in [header] + lines:
                    print("  " + "  ".join(x.rjust(w) for x, w in zip(line, widths)))
    bad = [r for r in rows if not r["ok"]]
    print("%d cells, %d failed" % (len(rows), len(bad)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
