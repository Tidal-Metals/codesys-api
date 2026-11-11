"""Summarize sfw_test.py realistic runs (26 KB at 1 Hz + 5 KB at 10 Hz through an outage) side by side.

    python examples/mqtt_large_payload/show_realistic.py results/exp/sfw/realistic_*.json
"""
import json
import sys
from pathlib import Path


def delay(d: dict) -> str:
    return "%s / %s" % (d.get("p95", "-"), d.get("max", "-")) if d else "-"


def missing_marigraf(text: str) -> str:
    for line in (text or "").splitlines():
        if line.startswith("missing_count"):
            return line.split()[1]
    return "?"


def main() -> int:
    print("| run | stream | pushed | received | dropped (gap) | dup | Marigraf missing | extra delay p95 / max ms: before | live during drain | after | drain s |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for path in sys.argv[1:]:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        for case in report.get("cases", []):
            name = "%s %s" % (Path(path).stem.replace("realistic_", ""), case.get("case", ""))
            for stream, s in case.get("streams", {}).items():
                observer = s.get("observer", {})
                print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    name, stream, s.get("pushed"), observer.get("received", "-"), observer.get("missing", "-"),
                    observer.get("duplicates", "-"), missing_marigraf(s.get("marigraf")),
                    delay(s.get("extra_delay_ms_before")), delay(s.get("extra_delay_ms_live_during_drain")),
                    delay(s.get("extra_delay_ms_after_drain")), case.get("drain_s")))
    print()
    print("| run | block | capacity | pages x bytes | dropped | live deferred | live dropped | max client us/scan | max block us | max push us slow / fast |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for path in sys.argv[1:]:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        for case in report.get("cases", []):
            name = "%s %s" % (Path(path).stem.replace("realistic_", ""), case.get("case", ""))
            plc = case.get("plc", {})
            for block, b in case.get("plc_blocks", {}).items():
                pages = "%s x %s" % (b.get("CapacityBytes", "-"), b.get("PageBytes", "-")) if "PageBytes" in b else "-"
                print("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s / %s |" % (
                    name, block, b.get("Capacity"), pages, b.get("DroppedCount"), b.get("LiveDeferredCount"),
                    b.get("LiveDroppedCount", "-"), plc.get("MaxScanClientUs"),
                    plc.get("MaxSlowBlockUs") if block == "slow" else plc.get("MaxFastBlockUs"),
                    plc.get("MaxSlowPushUs"), plc.get("MaxFastPushUs")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
