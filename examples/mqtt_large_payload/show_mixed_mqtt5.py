"""Table of the mixed_rate_mqtt5.py benchmark cells in results/exp/mqtt5/bench_*.json.

    python examples/mqtt_large_payload/show_mixed_mqtt5.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ["hq_v4", "mqttug_v4", "mqttug_v5"]

print("%-11s %-4s %-3s %-4s %-6s %-9s %-9s %-7s %-8s %-8s %-11s %-11s"
      % ("config", "stop", "QoS", "ok", "keptUp", "client ms", "max cl ms", "calls", "load %", "max scan",
         "fast age p50", "p99 ms"))
for config in ORDER:
    for stop in ("off", "on"):
        path = HERE / "results" / "exp" / "mqtt5" / ("bench_%s_stop-%s.json" % (config, stop))
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8"))["rows"]:
            scan = row["plc"]["scan"]
            age = row["broker"]["F"]["messageAgeMs"]
            print("%-11s %-4s %-3d %-4s %-6s %-9.2f %-9.2f %-7.1f %-8.2f %-8.2f %-11.1f %-11.1f"
                  % (config, stop, row["qos"], "yes" if row["ok"] else "NO", "yes" if row["keptUp"] else "NO",
                     scan["clientMs"], scan["maxClientMs"], scan["clientCallsPerScan"], scan["taskLoadPercent"],
                     scan["maxCycleMs"], age["p50"], age["p99"]))
