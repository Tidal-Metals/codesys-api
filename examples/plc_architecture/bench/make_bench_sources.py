"""Generate the two-task bench sources: the architecture skeleton with an N-tag table, plus the bench programs.

Usage: python examples/plc_architecture/bench/make_bench_sources.py <tag_count> <out_dir>
Tag mix as in the MQTT scale test: 50 % BOOL, 25 % INT, 25 % REAL, names <prefix>-<4 digits>[suffix]; the
skeleton's four example tags stay first so its hand-written logic compiles. PRG_Comms gets bench topics and
its own client id, so the bench can never pose as the real PLC on the broker, and its two tuning constants
become variables that can be written online.
"""
import json
import re
import shutil
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
SKELETON = BENCH.parent
count = int(sys.argv[1])
out = Path(sys.argv[2])

if out.exists():
    shutil.rmtree(out)
shutil.copytree(SKELETON / "st", out / "st")
for source in (BENCH / "st").glob("*.st"):
    shutil.copy(source, out / "st" / source.name)


def row(index):
    number = 1000 + index
    if index % 4 in (0, 1):
        return "(Name := 'XS-%04d', Kind := E_TagKind.BOOL_TAG, MaxValue := 1.0, Source := 1)" % number
    if index % 4 == 2:
        return "(Name := 'FQI-%04d', Kind := E_TagKind.INT_TAG, MaxValue := 100000.0, Source := 2)" % number
    if index % 40 == 3:   # one REAL in ten is a writable setpoint
        return ("(Name := 'TIC-%04d_SP', Kind := E_TagKind.REAL_TAG, MaxValue := 500.0, DefaultValue := 20.0, "
                "IsWritable := TRUE)" % number)
    return ("(Name := 'TIT-%04d', Kind := E_TagKind.REAL_TAG, Scale := 0.1, MaxValue := 500.0, Deadband := 0.5, "
            "Source := 1)" % number)


def patch(path, replacements):
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        assert text.count(old) == 1, (path.name, old[:60])
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


gvl_path = out / "st" / "GVL_Tags.st"
gvl = gvl_path.read_text(encoding="utf-8")
original_rows = re.search(r"OF ST_TagConfig := \[(.*?)\];", gvl, re.S).group(1)
rows = ",\n\t\t".join([original_rows.rstrip()] + [row(i) for i in range(5, count + 1)])
gvl_path.write_text(gvl.replace(original_rows, rows).replace("TAG_COUNT : INT := 4;", "TAG_COUNT : INT := %d;" % count),
                    encoding="utf-8")

patch(out / "st" / "PRG_Comms.st", [
    ("VAR CONSTANT\n\tTAGS_PER_CALL : INT := 250;", "VAR\n\tTAGS_PER_CALL : INT := 250;"),
    ("TopicData : STRING(64) := 'raw_data';", "TopicData : STRING(64) := 'raw_data_demo/arch';"),
    ("TopicCommands : STRING(64) := 'plc_commands/CONC-BCNF-PLC';", "TopicCommands : STRING(64) := 'plc_commands/BENCH-ARCH-TEST';"),
    ("TopicAcks : STRING(64) := 'plc_acks/CONC-BCNF-PLC';", "TopicAcks : STRING(64) := 'plc_acks/BENCH-ARCH-TEST';"),
    ("Payload : STRING(32000);", "Payload : STRING(%d);" % (count * 44)),
])
patch(out / "st" / "PRG_Comms.st", [("MqttLink.ClientID := 'CONC-BCNF-PLC';", "MqttLink.ClientID := 'BENCH-ARCH-TEST';")])
# FULL_REFRESH_EVERY = 1 means every message carries all tags (MOD 1 is never 1).
patch(out / "st" / "PRG_Comms.PublishData.st", [
    ("IsFullRefresh := IsForceFullRefresh OR (PublishCount MOD FULL_REFRESH_EVERY) = 1;",
     "IsFullRefresh := IsForceFullRefresh OR FULL_REFRESH_EVERY <= 1 OR (PublishCount MOD FULL_REFRESH_EVERY) = 1;")])
text = (out / "st" / "PRG_Comms.st").read_text(encoding="utf-8")
assert "CONC-BCNF" not in text and "'raw_data'" not in text, "production names left in PRG_Comms"

manifest = json.loads((SKELETON / "manifest.json").read_text(encoding="utf-8"))
for name in ("PRG_SimInputs", "PRG_ControlTask", "PRG_CommsTask"):
    manifest["objects"].append({"kind": "program", "name": name})
manifest["tasks"] = {"MainTask": {"pous": ["PRG_ControlTask"], "priority": "1", "interval": "t#50ms"},
                     "CommsTask": {"pous": ["PRG_CommsTask"], "priority": "10", "interval": "t#50ms"}}
manifest.pop("callers", None)
(out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
print("%d tags -> %s" % (count, out))
