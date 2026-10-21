# -*- coding: utf-8 -*-
# IronPython 2.7. Turns a copy of the bench project into the MQTT large-payload demo and builds it.
#
# Headless (separate IDE): CODESYS.exe --noUI --runscript=build_demo_project.py with
#   DEMO_PROJECT = the bench project copy, DEMO_REPORT = JSON report path,
#   DEMO_SOURCE_DIR = this folder (--runscript does not define __file__).
# In the API session: apply_session.py runs this file against the open primary project.
import io
import json
import os
import traceback

from scriptengine import PouType  # a global under --runscript, but not inside the API session

IMPLEMENTATION_MARKER = "// ---- implementation ----"
LIBRARY_PLACEHOLDERS = [
    ("MQTT", "MQTT, 1.2.0.7 (Stefan Dreyer)"),
    ("PRO_JSON", "PRO JSON, 1.0.0.16 (Pro Electric)"),
]
LIBRARIES = ["SysTime, 3.5.17.0 (System)", "SysTimeCore, 3.5.17.0 (System)",  # SysTimeGetUs for the performance counters
             "CAA Memory, 3.5.12.0 (CAA Technical Workgroup)",  # MEM.MemMove, timed as the MQTT library uses it
             "SysTimeRtc, 3.5.17.0 (System)",  # wall-clock timestamps in the scale test
             "SNTP Service SL, 1.9.0.0 (CODESYS)"]  # ClockSync: UTC from the NTP server
REMOVED_DEVICES = ["Modbus_TCP_Client"]
# The MQTT library allocates its buffers with __NEW; BCNF uses 50000.
DYNAMIC_MEMORY_BYTES = 100000
# Source paths are relative to st/ without ".st".
FUNCTIONS = [("AppendText", "BOOL", "AppendText"), ("NowUs", "ULINT", "NowUs"),
             ("AppendTagLine", "BOOL", "bcnf_style/AppendTagLine"), ("AppendZ", "BOOL", "scale/AppendZ")]
# BCNF's StringPublication (verbatim) and the 2,000-tag scale test, both called by PLC_PRG
PROGRAMS = [("BcnfStringPublicationCopy", "bcnf_style/BcnfStringPublicationCopy"),
            ("ScaleTest", "scale/ScaleTest"), ("ClockSync", "clock/ClockSync"), ("EdgeTest", "edge/EdgeTest")]
# MQTT library edge-case test (edge_test.py): its subscription callback
FUNCTION_BLOCKS = [("FB_EdgeReceiver", "edge/FB_EdgeReceiver")]
METHODS = [("FB_EdgeReceiver", "PublishReceived", "BOOL", "edge/FB_EdgeReceiver.PublishReceived")]
ACTIONS = [("PLC_PRG", "BuildLine", "PLC_PRG.BuildLine"),
           ("BcnfStringPublicationCopy", "BuildTagValue", "bcnf_style/BcnfStringPublicationCopy.BuildTagValue"),
           ("ScaleTest", "UpdateValues", "scale/ScaleTest.UpdateValues"),
           ("ScaleTest", "BuildTag", "scale/ScaleTest.BuildTag"),
           ("ScaleTest", "DetectChanges", "scale/ScaleTest.DetectChanges")]


def read_source(source_dir, name):
    with io.open(os.path.join(source_dir, "st", name + ".st"), encoding="utf-8") as handle:
        text = handle.read()
    declaration, implementation = text.split(IMPLEMENTATION_MARKER + "\n", 1)
    return declaration.rstrip() + "\n", implementation


def find_child(parent, predicate):
    for child in parent.get_children(True):
        if predicate(child):
            return child
    raise Exception("object not found under %s" % parent.get_name())


def direct_child(parent, name):
    matches = [obj for obj in parent.get_children(False) if obj.get_name() == name]
    return matches[0] if matches else None


def set_dynamic_memory(application, size):
    # Application Properties > Build > "Use dynamic memory allocation"; not exposed to scripting,
    # so it goes through the object manager, as in temp/coil_proof.
    import System
    assemblies = dict((str(a.GetName().Name), a) for a in System.AppDomain.CurrentDomain.GetAssemblies())
    instances = assemblies["SystemInstances"].GetType("_3S.CoDeSys.Core.SystemInstances")
    object_manager = instances.GetProperty("ObjectMgr").GetValue(None, None)
    engine = instances.GetProperty("Engine").GetValue(None, None)
    project_handle = engine.Projects.PrimaryProject.Handle
    modifiable = object_manager.GetObjectToModify(project_handle, System.Guid(str(application.guid)))
    try:
        modifiable.Object.SizeForDynamicMemory = size
        object_manager.SetObject(modifiable, True, None)
        modifiable = None
    finally:
        if modifiable is not None:
            object_manager.SetObject(modifiable, False, None)


def add_libraries(libman, steps):
    existing = set(ref.name for ref in libman.references)
    for name, resolution in LIBRARY_PLACEHOLDERS:
        if "#" + name not in existing:
            libman.add_placeholder(name, resolution)
            steps.append("added placeholder %s -> %s" % (name, resolution))
    for display_name in LIBRARIES:
        if display_name not in existing:
            libman.add_library(display_name)
            steps.append("added library " + display_name)


def write_sources(application, source_dir, steps):
    for name, return_type, source_name in FUNCTIONS:
        pou = direct_child(application, name) or application.create_pou(
            name=name, type=PouType.Function, return_type=return_type)
        declaration, implementation = read_source(source_dir, source_name)
        pou.textual_declaration.replace(declaration)
        pou.textual_implementation.replace(implementation)
    for name, source_name in FUNCTION_BLOCKS:
        pou = direct_child(application, name) or application.create_pou(name=name, type=PouType.FunctionBlock)
        declaration, implementation = read_source(source_dir, source_name)
        pou.textual_declaration.replace(declaration)
        pou.textual_implementation.replace(implementation or u"")
    for parent_name, method_name, return_type, source_name in METHODS:
        parent = direct_child(application, parent_name)
        method = direct_child(parent, method_name) or parent.create_method(method_name, return_type)
        declaration, implementation = read_source(source_dir, source_name)
        method.textual_declaration.replace(declaration)
        method.textual_implementation.replace(implementation)
    for name, source_name in PROGRAMS:
        pou = direct_child(application, name) or application.create_pou(name=name, type=PouType.Program)
        declaration, implementation = read_source(source_dir, source_name)
        pou.textual_declaration.replace(declaration)
        pou.textual_implementation.replace(implementation)
    for parent_name, action_name, source_name in ACTIONS:
        parent = direct_child(application, parent_name)
        action = direct_child(parent, action_name) or parent.create_action(action_name)
        action.textual_implementation.replace(read_source(source_dir, source_name)[1])
    program = direct_child(application, "PLC_PRG")
    declaration, implementation = read_source(source_dir, "PLC_PRG")
    program.textual_declaration.replace(declaration)
    program.textual_implementation.replace(implementation)
    steps.append("sources written")


def collect_messages():
    messages = []
    for category in system.get_message_categories(True):
        for message in system.get_message_objects(category):
            # IronPython's json fails on non-ASCII text (library messages contain e.g. a euro sign).
            text = u"".join(c if ord(c) < 128 else u"?" for c in unicode(message.text))
            messages.append({"severity": str(message.severity), "text": text})
    return messages


def apply_demo(proj, source_dir, steps):
    """Edit and rebuild the open project; returns the build report fields."""
    for name in REMOVED_DEVICES:
        for obj in proj.find(name, True):
            obj.remove()
            steps.append("removed " + name)
    application = find_child(proj, lambda obj: getattr(obj, "is_application", False))
    set_dynamic_memory(application, DYNAMIC_MEMORY_BYTES)
    steps.append("dynamic memory %d bytes" % DYNAMIC_MEMORY_BYTES)
    libman = find_child(application, lambda obj: getattr(obj, "is_libman", False))
    add_libraries(libman, steps)
    write_sources(application, source_dir, steps)
    for category in system.get_message_categories(True):
        system.clear_messages(category)
    steps.append("rebuilding")
    application.rebuild()
    messages = collect_messages()
    errors = [m for m in messages if "error" in m["severity"].lower()]
    return {
        "errors": errors,
        "warningCount": len([m for m in messages if "warning" in m["severity"].lower()]),
        "messages": messages[:80],
        "libraries": [ref.name for ref in libman.references],
        "success": not errors,
    }


def run_headless():
    report_path = os.environ["DEMO_REPORT"]

    def write_report(report):
        # Rewritten after every step: a dialog in --noUI mode ends the process without an exception.
        with io.open(report_path, "w", encoding="utf-8") as handle:
            handle.write(unicode(json.dumps(report, indent=1)))

    class StepLog(list):
        def append(self, step):
            list.append(self, step)
            write_report(report)

    report = {"project": os.environ["DEMO_PROJECT"], "steps": StepLog()}
    try:
        report["steps"].append("opening")
        proj = projects.open(os.environ["DEMO_PROJECT"])
        report.update(apply_demo(proj, os.environ["DEMO_SOURCE_DIR"], report["steps"]))
        proj.save()
        report["saved"] = True
        proj.close()
    except Exception:
        report["success"] = False
        report["exception"] = traceback.format_exc()
    write_report(report)


if os.environ.get("DEMO_PROJECT") and not globals().get("DEMO_IN_SESSION"):
    run_headless()
