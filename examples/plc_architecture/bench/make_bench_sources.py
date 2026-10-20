"""Generate the bench sources: the architecture skeleton with an N-tag table, its Modbus bus, and the bench programs.

Usage: python examples/plc_architecture/bench/make_bench_sources.py <tag_count> <out_dir>
Tag mix as in the MQTT scale test: 50 % BOOL, 25 % INT, 25 % REAL, names <prefix>-<4 digits>[suffix]; the
skeleton's four example tags stay first so its hand-written logic compiles. Bus (GVL_Bus), bench sources:
  line 1  TCP to the NA111-E (192.168.50.67:502) -> RS485 115200 -> simulated units 11-40 (bus_sim.py)
          each unit: FC03 registers 0-9; 0-3 -> INT tags, 4-7 -> REAL tags (x0.1); unit 11 also register 9 ->
          the read-back of a setpoint written from a TIC-..._SP tag, and coils 0-9 -> BOOL tags
  line 2  the PLC's terminal block (COM2) -> USB adapter COM12 -> simulated units 1-10 shaped like the Ebyte
          ME31 thermocouple module, 9600 8N1: FC04 registers 400-405 -> six temperatures (x0.1, -999 = open)
Every other tag is local (source 0) and moved by PRG_SimInputs. PRG_Comms gets bench topics and its own
client id, and its tuning constants become variables. Also writes expected_bus_values.json for verify_arch.py.
"""
import json
import re
import shutil
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parent
SKELETON = BENCH.parent
sys.path.insert(0, str(BENCH))
import bus_sim  # noqa: E402

count = int(sys.argv[1])
out = Path(sys.argv[2])
GATEWAY = (192, 168, 50, 67)
SERIAL_COM = 2                      # the PLC's terminal block (COM1 is the RJ12 jack, unused)
COIL_PATTERN = bus_sim.COILS


def base_row(index):
    number = 1000 + index
    if index % 4 in (0, 1):
        return {"Name": "XS-%04d" % number, "Kind": "BOOL_TAG", "MaxValue": "1.0"}
    if index % 4 == 2:
        return {"Name": "FQI-%04d" % number, "Kind": "INT_TAG", "MaxValue": "100000.0"}
    if index % 40 == 3:
        return {"Name": "TIC-%04d_SP" % number, "Kind": "REAL_TAG", "MaxValue": "500.0", "DefaultValue": "20.0", "IsWritable": "TRUE"}
    return {"Name": "TIT-%04d" % number, "Kind": "REAL_TAG", "Scale": "0.1", "MaxValue": "500.0", "Deadband": "0.5"}


rows = dict((i, base_row(i)) for i in range(5, count + 1))
free = {"INT": [i for i in rows if rows[i]["Kind"] == "INT_TAG"],
        "REAL": [i for i in rows if rows[i]["Name"].startswith("TIT")],
        "BOOL": [i for i in rows if rows[i]["Kind"] == "BOOL_TAG"],
        "SP": [i for i in rows if rows[i].get("IsWritable")]}


def take(kind):
    return free[kind].pop(0)


blocks, entries, writes, expected = [], [], [], {}
SOURCE_COUNT = len(bus_sim.UNITS) + len(bus_sim.SERIAL_UNITS)


def add_block(line, unit, function, start, count_, period, source, block_entries):
    blocks.append({"Line": line, "UnitId": unit, "ReadFunction": "E_BusFunction." + function, "Start": start,
                   "Count": count_, "PeriodMs": period, "FirstEntry": len(entries) + 1, "EntryCount": len(block_entries),
                   "Source": source})
    entries.extend(block_entries)


for source, unit in enumerate(bus_sim.UNITS, start=1):
    block_entries = []
    for register in range(4):
        tag = take("INT")
        rows[tag].update(Source=str(source))
        block_entries.append({"Offset": register, "Format": "E_BusFormat.UINT16", "TagIndex": tag})
        expected[rows[tag]["Name"]] = unit * 100 + register
    for register in range(4, 8):
        tag = take("REAL")
        rows[tag].update(Source=str(source))
        block_entries.append({"Offset": register, "Format": "E_BusFormat.UINT16", "TagIndex": tag})
        expected[rows[tag]["Name"]] = round((unit * 100 + register) * 0.1, 2)
    if unit == bus_sim.UNITS[0]:
        feedback = take("REAL")
        rows[feedback].update(Source=str(source))
        block_entries.append({"Offset": bus_sim.SETPOINT_REGISTER, "Format": "E_BusFormat.INT16", "TagIndex": feedback})
        setpoint = take("SP")
        rows[setpoint].update(Scale="0.1")
        writes.append({"TagIndex": setpoint, "Line": 1, "UnitId": unit, "Register": bus_sim.SETPOINT_REGISTER})
        expected["_setpoint"] = rows[setpoint]["Name"]
        expected["_setpoint_feedback"] = rows[feedback]["Name"]
    add_block(1, unit, "READ_HOLDING_REGISTERS", 0, bus_sim.REGISTERS, 500 if unit == bus_sim.UNITS[0] else 1000, source, block_entries)
    if unit == bus_sim.UNITS[0]:
        coil_entries = []
        for bit, state in enumerate(COIL_PATTERN):
            tag = take("BOOL")
            rows[tag].update(Source=str(source))
            coil_entries.append({"Offset": bit, "Format": "E_BusFormat.SINGLE_BIT", "TagIndex": tag})
            expected[rows[tag]["Name"]] = state
        add_block(1, unit, "READ_COILS", 0, len(COIL_PATTERN), 1000, source, coil_entries)

for number, unit in enumerate(bus_sim.SERIAL_UNITS):
    source = len(bus_sim.UNITS) + 1 + number
    me31_entries = []
    for channel in range(bus_sim.CHANNELS):
        tag = take("REAL")
        rows[tag].update(Source=str(source), MinValue="-250.0", MaxValue="1400.0")
        me31_entries.append({"Offset": channel, "Format": "E_BusFormat.INT16", "HasSentinel": "TRUE", "Sentinel": -999, "TagIndex": tag})
        raw = bus_sim.temperature_raw(unit, channel)
        expected[rows[tag]["Name"]] = "nan" if raw == -999 else round(raw * 0.1, 2)
    add_block(2, unit, "READ_INPUT_REGISTERS", bus_sim.TEMPERATURE_REGISTER, bus_sim.CHANNELS, 1000, source, me31_entries)
for index in rows:
    rows[index].setdefault("Source", "0")


def literal(fields):
    return "(" + ", ".join("%s := %s" % (key, "'%s'" % value if key == "Name" else value) for key, value in fields.items()) + ")"


def tag_literal(fields):
    fields = dict(fields)
    fields["Kind"] = "E_TagKind." + fields["Kind"]
    return literal(fields)


def patch(path, replacements):
    text = path.read_text(encoding="utf-8")
    for old, new in replacements:
        assert text.count(old) == 1, (path.name, old[:60])
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


if out.exists():
    shutil.rmtree(out)
shutil.copytree(SKELETON / "st", out / "st")
for source_file in (BENCH / "st").glob("*.st"):
    shutil.copy(source_file, out / "st" / source_file.name)

gvl_path = out / "st" / "GVL_Tags.st"
gvl = gvl_path.read_text(encoding="utf-8")
original_rows = re.search(r"OF ST_TagConfig := \[(.*?)\];", gvl, re.S).group(1)
table = ",\n\t\t".join([original_rows.rstrip()] + [tag_literal(rows[i]) for i in range(5, count + 1)])
gvl = gvl.replace(original_rows, table).replace("TAG_COUNT : INT := 4;", "TAG_COUNT : INT := %d;" % count)
gvl = gvl.replace("SOURCE_COUNT : INT := 2;", "SOURCE_COUNT : INT := %d;" % SOURCE_COUNT)
gvl = gvl.replace("SourceIsHealthy : ARRAY[0..SOURCE_COUNT] OF BOOL := [TRUE, FALSE, FALSE];",
                  "SourceIsHealthy : ARRAY[0..SOURCE_COUNT] OF BOOL := [%d(TRUE)];" % (SOURCE_COUNT + 1))
gvl_path.write_text(gvl, encoding="utf-8")
# The skeleton's AIT-1508 and LSS-E-STOP name sources 1 and 2; on the bench those are bus devices, so they go local.
patch(gvl_path, [("StaleAfter := T#3S, Source := 1),", "StaleAfter := T#3S, Source := 0),"),
                 ("StaleAfter := T#3S, Source := 2)", "StaleAfter := T#3S, Source := 0)")])

lines = ("(Address := [%d, %d, %d, %d], Port := 502, ReplyTimeoutMs := 500)" % GATEWAY,
         "(IsSerial := TRUE, ComPort := %d, Baudrate := 9600, Parity := 0, ReplyTimeoutMs := 500)" % SERIAL_COM)
gvl_bus = (SKELETON / "st" / "GVL_Bus.st").read_text(encoding="utf-8")
header, rest = gvl_bus.split("{attribute 'qualified_only'}", 1)
body = rest[rest.index("\t// Bus task -> control task."):]
bus_sources = ", ".join(["FALSE"] + ["TRUE"] * SOURCE_COUNT)
gvl_bus = ("// Bench bus, generated by bench/make_bench_sources.py: NA111-E units 11-40 and units 1-10 on the PLC's terminal block.\n"
           "{attribute 'qualified_only'}\nVAR_GLOBAL CONSTANT\n"
           "\tLINE_COUNT : INT := 2;\n\tBLOCK_COUNT : INT := %d;\n\tENTRY_COUNT : INT := %d;\n\tWRITE_COUNT : INT := %d;\n"
           "\tFAIL_LIMIT : UINT := 3;\n\tBACKOFF_MS : UDINT := 5000;\nEND_VAR\nVAR_GLOBAL\n"
           "\t// Settings, writable online (a line reads them when it connects: PRG_Bus.Reconnect)\n"
           "\tLines : ARRAY[1..LINE_COUNT] OF ST_BusLine := [\n\t\t%s];\n"
           "\tBlocks : ARRAY[1..BLOCK_COUNT] OF ST_BusBlock := [\n\t\t%s];\n"
           "\tEntries : ARRAY[1..ENTRY_COUNT] OF ST_BusEntry := [\n\t\t%s];\n"
           "\tWrites : ARRAY[1..WRITE_COUNT] OF ST_BusWrite := [\n\t\t%s];\n"
           "\tIsBusSource : ARRAY[0..GVL_Tags.SOURCE_COUNT] OF BOOL := [%s];\n\n"
           % (len(blocks), len(entries), len(writes), ",\n\t\t".join(lines), ",\n\t\t".join(literal(b) for b in blocks),
              ",\n\t\t".join(literal(e) for e in entries), ",\n\t\t".join(literal(w) for w in writes), bus_sources)
           + body.replace("OF BOOL := [TRUE, TRUE, TRUE];", "OF BOOL := [%d(TRUE)];" % (SOURCE_COUNT + 1)))
(out / "st" / "GVL_Bus.st").write_text(gvl_bus, encoding="utf-8")

patch(out / "st" / "PRG_Comms.st", [
    ("VAR CONSTANT\n\tTAGS_PER_CALL : INT := 250;", "VAR\n\tTAGS_PER_CALL : INT := 250;"),
    ("TopicData : STRING(64) := 'raw_data';", "TopicData : STRING(64) := 'raw_data_demo/arch';"),
    ("TopicCommands : STRING(64) := 'plc_commands/CONC-BCNF-PLC';", "TopicCommands : STRING(64) := 'plc_commands/BENCH-ARCH-TEST';"),
    ("TopicAcks : STRING(64) := 'plc_acks/CONC-BCNF-PLC';", "TopicAcks : STRING(64) := 'plc_acks/BENCH-ARCH-TEST';"),
    ("Payload : STRING(32000);", "Payload : STRING(%d);" % (count * 44)),
    ("MqttLink.ClientID := 'CONC-BCNF-PLC';", "MqttLink.ClientID := 'BENCH-ARCH-TEST';"),
])
# FULL_REFRESH_EVERY = 1 means every message carries all tags (MOD 1 is never 1).
patch(out / "st" / "PRG_Comms.PublishData.st", [
    ("IsFullRefresh := IsForceFullRefresh OR (PublishCount MOD FULL_REFRESH_EVERY) = 1;",
     "IsFullRefresh := IsForceFullRefresh OR FULL_REFRESH_EVERY <= 1 OR (PublishCount MOD FULL_REFRESH_EVERY) = 1;")])
text = (out / "st" / "PRG_Comms.st").read_text(encoding="utf-8")
assert "CONC-BCNF" not in text and "'raw_data'" not in text, "production names left in PRG_Comms"

manifest = json.loads((SKELETON / "manifest.json").read_text(encoding="utf-8"))
for name in ("PRG_SimInputs", "PRG_ControlTask", "PRG_CommsTask", "PRG_BusTask"):
    manifest["objects"].append({"kind": "program", "name": name})
manifest["tasks"] = {"MainTask": {"pous": ["PRG_ControlTask"], "priority": "1", "interval": "t#50ms"},
                     "BusTask": {"pous": ["PRG_BusTask"], "priority": "5", "interval": "t#5ms"},
                     "CommsTask": {"pous": ["PRG_CommsTask"], "priority": "10", "interval": "t#50ms"}}
manifest["deviceParameters"] = {"8000": "16#0003", "8001": "16#0003"}   # RJ12 and terminal-block serial ports: RS485
manifest.pop("callers", None)
(out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
(out / "expected_bus_values.json").write_text(json.dumps(expected, indent=1), encoding="utf-8")
print("%d tags, %d sources, %d blocks, %d entries, %d writes -> %s" % (count, SOURCE_COUNT, len(blocks), len(entries), len(writes), out))
