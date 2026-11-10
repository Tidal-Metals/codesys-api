"""Tables from mixed_rate_test.py results: QoS 0 vs QoS 1 per layout and stream.

Usage: python examples/mqtt_large_payload/show_mixed.py results/exp/qos_mixed/mixed_100ms.json [more.json ...]
"""
import json
import sys
from pathlib import Path


def row_text(row: dict, stream: str) -> str:
    plc, broker = row["plc"][stream], row["broker"][stream]
    age = broker["messageAgeMs"] or {}
    gap = broker["roundGapMs"] or {}
    return ("| %s | %d | %s | %d/%d | %d | %s | %s / %s | %s / %s | %s / %s | %s / %s | %s / %s | %d/%d/%d |" % (
        row["layout"], row["qos"], stream, plc["roundsStarted"], plc["periodsDue"], plc["skipped"],
        plc["keptUpPercent"], plc["buildMs"], plc["maxBuildMs"], plc["sendMs"], plc["maxSendMs"],
        plc["sendScans"], plc["maxSendScans"], age.get("p50"), age.get("p99"), gap.get("p50"), gap.get("max"),
        broker["partsMissing"], broker["partsDuplicated"], broker["partsBad"]))


def main() -> None:
    for path in sys.argv[1:]:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        print("\n## %s %s\n" % (path, report.get("label", "")))
        print("| layout | QoS | stream | rounds/due | skipped | kept up % | build ms avg / max | send ms avg / max "
              "| send scans avg / max | age ms p50 / p99 | gap ms p50 / max | missing/dup/bad |")
        print("|" + "---|" * 12)
        for row in report["rows"]:
            for stream in ("S", "F"):
                print(row_text(row, stream))
        print("\n| layout | QoS | scan ms avg / max | client ms avg / max | client calls/scan | task load % "
              "| interval ms | reconnects | ok | kept up |")
        print("|" + "---|" * 10)
        for row in report["rows"]:
            scan = row["plc"]["scan"]
            print("| %s | %d | %s / %s | %s / %s | %s | %s | %s | %d | %s | %s |" % (
                row["layout"], row["qos"], scan["cycleMs"], scan["maxCycleMs"], scan["clientMs"], scan["maxClientMs"],
                scan["clientCallsPerScan"], scan["taskLoadPercent"], scan["intervalMs"], row["plc"]["reconnects"],
                row["ok"], row["keptUp"]))


if __name__ == "__main__":
    main()
