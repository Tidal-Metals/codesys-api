# -*- coding: utf-8 -*-
# IronPython, headless: compile the architecture skeleton (st/*.st, listed in manifest.json) inside a
# throwaway copy of a project that already references the MQTT library (the MQTT demo project) and has
# AppendZ. Nothing is saved back to the original project.
#
# CODESYS.exe --noUI --runscript=check_compile.py with SKELETON_DIR = this folder, SKELETON_PROJECT = the
# copy, SKELETON_REPORT = JSON report path.
import io
import json
import os
import traceback

from scriptengine import PouType, DutType

HERE = os.environ["SKELETON_DIR"]
MARKER = u"// ---- implementation ----\n"


def read(name):
    with io.open(os.path.join(HERE, "st", name + ".st"), encoding="utf-8") as handle:
        text = handle.read()
    if MARKER in text:
        declaration, implementation = text.split(MARKER, 1)
        return declaration.rstrip() + u"\n", implementation
    return text, None


def child(parent, name):
    for obj in parent.get_children(False):
        if obj.get_name() == name:
            return obj
    raise Exception("%s not found under %s" % (name, parent.get_name()))


def create(app, item):
    kind, name = item["kind"], item["name"]
    source = name if "parent" not in item else item["parent"] + "." + name
    declaration, implementation = read(source)
    if kind == "enum":
        obj = app.create_dut(name, DutType.Enumeration)
    elif kind == "struct":
        obj = app.create_dut(name, DutType.Structure)
    elif kind == "gvl":
        obj = app.create_gvl(name)
    elif kind == "fb":
        obj = app.create_pou(name=name, type=PouType.FunctionBlock)
    elif kind == "function":
        obj = app.create_pou(name=name, type=PouType.Function, return_type=item["returns"])
    elif kind == "program":
        obj = app.create_pou(name=name, type=PouType.Program)
    elif kind == "method":
        obj = child(app, item["parent"]).create_method(name, item["returns"])
    elif kind == "action":
        obj = child(app, item["parent"]).create_action(name)
    else:
        raise Exception("unknown kind " + kind)
    if kind != "action":
        obj.textual_declaration.replace(declaration)
    if implementation is not None and getattr(obj, "has_textual_implementation", False):
        obj.textual_implementation.replace(implementation)


report = {"steps": []}
try:
    with io.open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    proj = projects.open(os.environ["SKELETON_PROJECT"])
    app = proj.active_application
    libman = [obj for obj in app.get_children(True) if getattr(obj, "is_libman", False)][0]
    existing = set(ref.name for ref in libman.references)
    for library in manifest["libraries"]:
        if library not in existing:
            libman.add_library(library)
    for item in manifest["objects"]:
        create(app, item)
        report["steps"].append("added %s %s" % (item["kind"], item.get("parent", "") + "." + item["name"] if "parent" in item else item["name"]))
    program = child(app, "PLC_PRG")
    program.textual_implementation.replace(program.textual_implementation.text + u"\n" + u"\n".join(manifest["callers"]) + u"\n")
    for category in system.get_message_categories(True):
        system.clear_messages(category)
    app.rebuild()
    messages = []
    for category in system.get_message_categories(True):
        for message in system.get_message_objects(category):
            text = u"".join(c if ord(c) < 128 else u"?" for c in unicode(message.text))
            messages.append({"severity": str(message.severity), "text": text})
    report["errors"] = [m for m in messages if "error" in m["severity"].lower()]
    report["warnings"] = [m["text"] for m in messages if "warning" in m["severity"].lower() and "STRING(253)" not in m["text"]]
    report["success"] = not report["errors"]
    proj.close()
except Exception:
    report["success"] = False
    report["exception"] = traceback.format_exc()

with io.open(os.environ["SKELETON_REPORT"], "w", encoding="utf-8") as handle:
    handle.write(unicode(json.dumps(report, indent=1)))
