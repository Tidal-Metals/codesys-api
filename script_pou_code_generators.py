"""Generated IronPython scripts for POU code reads and updates."""

import json


def _literal(value):
    return json.dumps(value if value is not None else "")


def _pou_leaf_name(path):
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1]


def generate_pou_code_read_script(params):
    """Generate script to read POU declaration and implementation text."""
    return _generate_pou_code_script(
        pou_path=params.get("path", ""),
        declaration=None,
        implementation=None,
        save=False,
        verify=False,
        write=False,
    )


def generate_pou_code_script(params):
    """Generate script to set POU code and return the text read back from CODESYS."""
    pou_path = params.get("path", "")
    declaration = params.get("declaration")
    implementation = params.get("implementation")
    legacy_code = params.get("code")
    if implementation is None and legacy_code is not None:
        implementation = legacy_code

    return _generate_pou_code_script(
        pou_path=pou_path,
        declaration=declaration,
        implementation=implementation,
        save=params.get("save", True),
        verify=params.get("verify", True),
        write=True,
    )


def _generate_pou_code_script(pou_path, declaration, implementation, save, verify, write):
    pou_name = _pou_leaf_name(pou_path)
    declaration_present = declaration is not None
    implementation_present = implementation is not None

    return """
import scriptengine
import sys
import traceback

try:
    pou_path = @@POU_PATH@@
    pou_name = @@POU_NAME@@
    declaration_input = @@DECLARATION@@
    implementation_input = @@IMPLEMENTATION@@
    declaration_present = @@DECLARATION_PRESENT@@
    implementation_present = @@IMPLEMENTATION_PRESENT@@
    should_write = @@SHOULD_WRITE@@
    should_save = @@SHOULD_SAVE@@
    should_verify = @@SHOULD_VERIFY@@

    result = None
    project = scriptengine.projects.primary
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        pou = None
        matches = []

        if hasattr(session, 'created_pous') and pou_name in session.created_pous:
            pou = session.created_pous[pou_name]
            matches = [pou]
        else:
            try:
                exact_matches = project.find(pou_path, recursive=True)
                if exact_matches:
                    matches = list(exact_matches)
            except:
                matches = []

            if not matches:
                try:
                    leaf_matches = project.find(pou_name, recursive=True)
                    if leaf_matches:
                        matches = list(leaf_matches)
                except:
                    matches = []

            if not matches and hasattr(project, 'active_application') and project.active_application:
                try:
                    app_matches = project.active_application.find(pou_name, recursive=True)
                    if app_matches:
                        matches = list(app_matches)
                except:
                    matches = []

            if len(matches) == 1:
                pou = matches[0]
            elif len(matches) > 1:
                result = {
                    "success": False,
                    "error": "Ambiguous POU path: " + pou_path,
                    "matches": len(matches)
                }

        if result is None and pou is None:
            result = {"success": False, "error": "POU not found: " + pou_path}

        if result is None:
            actual_pou_name = pou.get_name() if hasattr(pou, 'get_name') else pou_name
            language = ""
            operations = []

            if hasattr(pou, 'implementation_language'):
                language = str(pou.implementation_language)
            elif hasattr(pou, 'implementation') and hasattr(pou.implementation, 'language'):
                language = str(pou.implementation.language)

            has_declaration = False
            has_implementation = False
            if hasattr(pou, 'has_textual_declaration'):
                try:
                    has_declaration = bool(pou.has_textual_declaration)
                except:
                    has_declaration = False
            elif hasattr(pou, 'textual_declaration'):
                has_declaration = True

            if hasattr(pou, 'has_textual_implementation'):
                try:
                    has_implementation = bool(pou.has_textual_implementation)
                except:
                    has_implementation = False
            elif hasattr(pou, 'textual_implementation'):
                has_implementation = True

            if should_write and declaration_present:
                if not has_declaration or not hasattr(pou, 'textual_declaration'):
                    result = {"success": False, "error": "POU has no textual declaration"}
                else:
                    try:
                        pou.textual_declaration.replace(new_text=declaration_input)
                        operations.append("declaration")
                    except TypeError:
                        pou.textual_declaration.replace(declaration_input)
                        operations.append("declaration")

            if result is None and should_write and implementation_present:
                if not has_implementation or not hasattr(pou, 'textual_implementation'):
                    result = {"success": False, "error": "POU has no textual implementation"}
                else:
                    try:
                        pou.textual_implementation.replace(new_text=implementation_input)
                        operations.append("implementation")
                    except TypeError:
                        pou.textual_implementation.replace(implementation_input)
                        operations.append("implementation")

            saved = False
            if result is None and should_write and should_save:
                try:
                    project.save()
                    saved = True
                except Exception as save_error:
                    result = {"success": False, "error": "Failed to save project: " + str(save_error)}

            if result is None:
                declaration_text = ""
                implementation_text = ""
                read_errors = []

                if has_declaration and hasattr(pou, 'textual_declaration'):
                    try:
                        decl_doc = pou.textual_declaration
                        if hasattr(decl_doc, 'text'):
                            declaration_text = str(decl_doc.text)
                        else:
                            declaration_text = str(decl_doc.get_text(offset=0, length=decl_doc.length))
                    except Exception as read_decl_error:
                        read_errors.append("declaration: " + str(read_decl_error))

                if has_implementation and hasattr(pou, 'textual_implementation'):
                    try:
                        impl_doc = pou.textual_implementation
                        if hasattr(impl_doc, 'text'):
                            implementation_text = str(impl_doc.text)
                        else:
                            implementation_text = str(impl_doc.get_text(offset=0, length=impl_doc.length))
                    except Exception as read_impl_error:
                        read_errors.append("implementation: " + str(read_impl_error))

                verified = None
                verification_errors = []
                if should_write and should_verify:
                    verified = True
                    if declaration_present and declaration_text != declaration_input:
                        verified = False
                        verification_errors.append("declaration read-back mismatch")
                    if implementation_present and implementation_text != implementation_input:
                        verified = False
                        verification_errors.append("implementation read-back mismatch")

                result = {
                    "success": len(read_errors) == 0 and (verified is not False),
                    "pou": {
                        "name": actual_pou_name,
                        "path": pou_path,
                        "language": language,
                        "hasDeclaration": has_declaration,
                        "hasImplementation": has_implementation,
                        "declaration": declaration_text,
                        "implementation": implementation_text
                    },
                    "operations": operations,
                    "saved": saved,
                    "verified": verified,
                    "readErrors": read_errors,
                    "verificationErrors": verification_errors
                }
                if not result["success"]:
                    result["error"] = "; ".join(read_errors + verification_errors)
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in POU code script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@POU_PATH@@", _literal(pou_path)) \
   .replace("@@POU_NAME@@", _literal(pou_name)) \
   .replace("@@DECLARATION@@", _literal(declaration)) \
   .replace("@@IMPLEMENTATION@@", _literal(implementation)) \
   .replace("@@DECLARATION_PRESENT@@", "True" if declaration_present else "False") \
   .replace("@@IMPLEMENTATION_PRESENT@@", "True" if implementation_present else "False") \
   .replace("@@SHOULD_WRITE@@", "True" if write else "False") \
   .replace("@@SHOULD_SAVE@@", "True" if save else "False") \
   .replace("@@SHOULD_VERIFY@@", "True" if verify else "False")
