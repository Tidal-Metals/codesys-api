"""Online change that changes the MQTT library itself, while the client is busy (the full review's finding 1).

Run from the repo root with BENCH_RESERVATION set, after a bench_cycle deploy of the fork build:
    python examples/mqtt_large_payload/library_online_change_test.py --out examples/mqtt_large_payload/results/exp/validation/library_online.json
Builds a test version of the fork, 1.3.0.99, whose MqttClient has one more variable, installs it, points the demo open
in the session at it and logs in with OnlineChangeOption.Force: the client's instance layout changes, so CODESYS copies
it and calls FB_Exit(bInCopyCode := TRUE). Upstream freed the client's memory there and the copy went on using it.
(Reinstalling the same version does not work: CODESYS keeps its copy of a version already loaded.) Measured: did it
apply, does the application run, is the new variable there, did the client reconnect, how long were commands
unanswered. The fork's src/ is restored right after the build; the next bench_cycle deploy returns the PLC to 1.3.0.0.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
sys.path.insert(0, str(HERE))
import bench_cycle as bc  # noqa: E402
import online_change_test as oct  # noqa: E402

CLIENT = bc.FORK / "src" / "MQTT" / "Function Blocks" / "MqttClient.st"
ANCHOR = "\tFullReceiveCalls : UINT;"
MARKER = "\tLibraryOnlineChangeMarker : UDINT := 7;\t// TEMPORARY: library_online_change_test.py\n"
TEST_VERSION = "1.3.0.99"
TEST_NAME = "MQTT %s (Tidal Metals test)" % TEST_VERSION
SWITCH = """
repository = [r for r in scriptengine.librarymanager.repositories if unicode(r.name) == u'System'][0]
installed = scriptengine.librarymanager.install_library(@@LIBRARY@@, repository, True)
name = unicode(installed.displayname)
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('mqtt_large_payload_demo_tm/mqtt_large_payload_demo.project'), p.path
replaced = []
for libman in [o for o in p.get_children(True) if getattr(o, 'is_libman', False)]:
    old = [unicode(r.name) for r in libman.references if unicode(r.name).startswith(u'MQTT, ')]
    for ref_name in old:
        libman.remove_library(ref_name)
        replaced.append(ref_name)
    if old:
        libman.add_library(name)
        for ref in libman.references:
            if unicode(ref.name) == name:
                ref.namespace = u'MQTT'
result = {'success': bool(replaced), 'installed': name, 'replaced': replaced}
"""
READ_MARKER = """
on = session.ensure_online_application('', True)
result = {'success': True, 'marker': str(on.read_value('PLC_PRG.MqttLink.clientFB.LibraryOnlineChangeMarker'))}
"""


def build_test_library() -> Path:
    spec = json.loads((bc.FORK / "build.json").read_text(encoding="utf-8"))
    spec["output_name"] = TEST_NAME
    spec["project_info"]["version"] = TEST_VERSION
    spec_path = bc.FORK / "tmp" / "build_test_version.json"
    spec_path.parent.mkdir(exist_ok=True)
    # build.json's base and src paths are relative to its folder; keep them so from tmp/
    spec["base"] = str((bc.FORK / spec["base"]).resolve())
    spec["src"] = str((bc.FORK / spec["src"]).resolve())
    spec_path.write_text(json.dumps(spec, indent=1), encoding="utf-8")
    subprocess.run([bc.PY, "tools/build_library.py", "--spec", str(spec_path)], cwd=bc.FORK, check=True,
                   capture_output=True, timeout=900)
    library = spec_path.parent / "dist" / (TEST_NAME + ".library")   # build_library.py writes dist/ next to the spec
    assert library.exists(), library
    return library


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--settle", type=float, default=15)
    parser.add_argument("--out")
    args = parser.parse_args()
    original = CLIENT.read_text(encoding="utf-8")
    assert ANCHOR in original and "LibraryOnlineChangeMarker" not in original
    try:
        CLIENT.write_bytes(original.replace(ANCHOR, MARKER + ANCHOR, 1).encode("utf-8"))
        library = build_test_library()
    finally:
        CLIENT.write_bytes(original.encode("utf-8"))
    report = {"testLibrary": library.name}
    oct.run(oct.WRITE.replace("@@VALUES@@", repr(oct.ENABLE_TRAFFIC)))
    switched = oct.run(SWITCH.replace("@@LIBRARY@@", repr(str(library).replace("\\", "/"))))
    report["switch"] = {k: switched.get(k) for k in ("installed", "replaced")}
    traffic = oct.Traffic()
    try:
        time.sleep(5)
        row = oct.step(traffic, "library change", oct.CHANGE.replace("@@KIND@@", "'code'").replace("@@N@@", "301"),
                       301, args.settle)
        try:
            row["newLibraryVariable"] = oct.run(READ_MARKER).get("marker")
        except RuntimeError as error:
            row["newLibraryVariable"] = "not readable: %s" % str(error)[:120]
        report["libraryChange"] = row
    finally:
        traffic.stop()
    row = report.get("libraryChange", {})
    report["success"] = bool(row.get("applied") and row.get("running") and row.get("connected")
                             and str(row.get("newLibraryVariable", "")).endswith("7")
                             and row.get("longestEchoGapSeconds", 99) < 5)
    text = json.dumps(report, indent=1)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
