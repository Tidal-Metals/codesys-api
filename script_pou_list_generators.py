"""Generated IronPython scripts for POU and textual IEC object listing."""

import json


def generate_pou_list_script(params):
    """Generate script to list textual IEC objects in the project tree."""
    parent_path = params.get("parentPath", "")
    include_non_pou = params.get("includeNonPou", True)

    return """
import scriptengine
import sys
import traceback

try:
    parent_path = @@PARENT_PATH@@.replace("\\\\", "/").strip("/")
    include_non_pou = @@INCLUDE_NON_POU@@

    project = scriptengine.projects.primary
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        pous = []
        seen = {}
        stack = []

        try:
            for child in project.get_children():
                stack.append((child, ""))
        except Exception as root_error:
            result = {"success": False, "error": "Unable to enumerate project children: " + str(root_error)}

        while 'result' not in locals() and stack:
            obj, parent = stack.pop(0)

            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)

            path = name if not parent else parent + "/" + name
            normalized_path = path.replace("\\\\", "/").strip("/")

            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, normalized_path))
                except:
                    pass

            if parent_path:
                if normalized_path != parent_path and not normalized_path.startswith(parent_path + "/"):
                    continue

            has_declaration = False
            has_implementation = False
            if hasattr(obj, 'has_textual_declaration'):
                try:
                    has_declaration = bool(obj.has_textual_declaration)
                except:
                    has_declaration = False
            elif hasattr(obj, 'textual_declaration'):
                has_declaration = True

            if hasattr(obj, 'has_textual_implementation'):
                try:
                    has_implementation = bool(obj.has_textual_implementation)
                except:
                    has_implementation = False
            elif hasattr(obj, 'textual_implementation'):
                has_implementation = True

            if not has_declaration and not has_implementation:
                continue

            kind = "Pou"
            if has_declaration and not has_implementation:
                kind = "Declaration"
            elif has_implementation and not has_declaration:
                kind = "Member"

            if not include_non_pou and kind != "Pou":
                continue

            key = normalized_path
            if key in seen:
                continue
            seen[key] = True

            language = ""
            if hasattr(obj, 'implementation_language'):
                try:
                    language = str(obj.implementation_language).split('.')[-1]
                except:
                    language = str(obj.implementation_language)
            elif hasattr(obj, 'implementation') and hasattr(obj.implementation, 'language'):
                try:
                    language = str(obj.implementation.language).split('.')[-1]
                except:
                    language = str(obj.implementation.language)

            object_type = ""
            if hasattr(obj, 'type'):
                try:
                    object_type = str(obj.type)
                except:
                    object_type = ""

            entry = {
                "name": name,
                "path": normalized_path,
                "kind": kind,
                "type": object_type,
                "language": language,
                "hasDeclaration": has_declaration,
                "hasImplementation": has_implementation
            }
            pous.append(entry)

        if 'result' not in locals():
            if hasattr(session, 'created_pous') and session.created_pous:
                for created_name, created_obj in session.created_pous.items():
                    already_listed = False
                    for entry in pous:
                        if entry.get("name") == created_name:
                            already_listed = True
                            break
                    if not already_listed:
                        pous.append({
                            "name": created_name,
                            "path": created_name,
                            "kind": "Pou",
                            "type": "",
                            "language": "",
                            "hasDeclaration": hasattr(created_obj, 'textual_declaration'),
                            "hasImplementation": hasattr(created_obj, 'textual_implementation'),
                            "source": "session_cache"
                        })

            result = {
                "success": True,
                "pous": pous,
                "count": len(pous),
                "parentPath": parent_path
            }
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in POU listing script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@PARENT_PATH@@", json.dumps(parent_path)) \
   .replace("@@INCLUDE_NON_POU@@", "True" if include_non_pou else "False")
