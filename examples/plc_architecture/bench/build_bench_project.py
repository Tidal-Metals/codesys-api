# -*- coding: utf-8 -*-
# IronPython, inside the API's CODESYS session (see apply_bench.py): writes generated bench sources
# (make_bench_sources.py) into the open project, sets up the two tasks and rebuilds. Idempotent: existing
# objects are rewritten, missing ones created. The project must not be logged in when objects are added.
import io
import json
import os

from scriptengine import PouType, DutType, KindOfTask

MARKER = u"// ---- implementation ----\n"


def read_source(source_dir, name):
    with io.open(os.path.join(source_dir, "st", name + ".st"), encoding="utf-8") as handle:
        text = handle.read()
    if MARKER in text:
        declaration, implementation = text.split(MARKER, 1)
        return declaration.rstrip() + u"\n", implementation
    return text, None


def find_child(parent, name):
    for obj in parent.get_children(False):
        if obj.get_name() == name:
            return obj
    return None


def ensure_object(app, item, source_dir):
    kind, name = item["kind"], item["name"]
    parent = app if "parent" not in item else find_child(app, item["parent"])
    source = name if "parent" not in item else item["parent"] + "." + name
    declaration, implementation = read_source(source_dir, source)
    obj = find_child(parent, name)
    created = obj is None
    if created:
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
            obj = parent.create_method(name, item["returns"])
        elif kind == "action":
            obj = parent.create_action(name)
        else:
            raise Exception("unknown kind " + kind)
    if kind != "action":
        obj.textual_declaration.replace(declaration)
    if implementation is not None and getattr(obj, "has_textual_implementation", False):
        obj.textual_implementation.replace(implementation)
    return created


def configure_tasks(app, tasks, steps):
    config = [obj for obj in app.get_children(True) if getattr(obj, "is_task_configuration", False)][0]
    for name, spec in sorted(tasks.items()):
        # pous.remove() silently does nothing on SP22 and remove(index) raises, so a task whose POU list is
        # wrong is deleted and created again.
        task = find_child(config, name)
        if task is not None and [str(entry) for entry in task.pous] != spec["pous"]:
            task.remove()
            task = None
        if task is None:
            task = config.create_task(name)
            for pou in spec["pous"]:
                task.pous.add(pou)
            steps.append("created task " + name)
        task.kind_of_task = KindOfTask.Cyclic
        task.interval = spec["interval"]
        task.priority = spec["priority"]
        steps.append("task %s: %s, priority %s, %s" % (name, spec["interval"], spec["priority"], ", ".join(spec["pous"])))


def apply_bench(proj, source_dir, steps):
    with io.open(os.path.join(source_dir, "manifest.json"), encoding="utf-8") as handle:
        manifest = json.load(handle)
    app = proj.active_application
    libman = [obj for obj in app.get_children(True) if getattr(obj, "is_libman", False)][0]
    existing = set(ref.name for ref in libman.references)
    for library in manifest["libraries"]:
        if library not in existing:
            libman.add_library(library)
            steps.append("added library " + library)
    created = [item["name"] for item in manifest["objects"] if ensure_object(app, item, source_dir)]
    steps.append("objects written: %d, created: %s" % (len(manifest["objects"]), ", ".join(created) or "none"))
    configure_tasks(app, manifest["tasks"], steps)
    for category in system.get_message_categories(True):
        system.clear_messages(category)
    app.rebuild()
    errors = []
    warnings = 0
    for category in system.get_message_categories(True):
        for message in system.get_message_objects(category):
            severity = str(message.severity).lower()
            text = u"".join(c if ord(c) < 128 else u"?" for c in unicode(message.text))
            if "error" in severity:
                errors.append(text)
            elif "warning" in severity:
                warnings += 1
    return {"success": not errors, "errors": errors[:20], "warningCount": warnings}
