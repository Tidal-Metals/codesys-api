"""Generic variable listing and editing handlers."""

from __future__ import annotations

from server_config import logger
from variable_declaration_utils import delete_variable, parse_variables, upsert_variable


class VariableHandlersMixin:
    def _read_declaration_object(self, path):
        script = self.script_generator.generate_pou_code_read_script({"path": path})
        result = self.script_executor.execute_script(script, timeout=30)
        if not result.get("success", False):
            return result

        pou = result.get("pou") or {}
        return {
            "success": True,
            "path": pou.get("path", path),
            "name": pou.get("name", path.rsplit("/", 1)[-1]),
            "declaration": pou.get("declaration", ""),
            "pou": pou,
        }

    def handle_variable_list(self, params):
        path = params.get("path", "")
        if not path:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameter: path"
            }, 400)
            return

        logger.info("Variable list request for '%s'", path)
        read_result = self._read_declaration_object(path)
        if not read_result.get("success", False):
            self.send_json_response(read_result, 500)
            return

        variables = parse_variables(read_result["declaration"], read_result["path"])
        self.send_json_response({
            "success": True,
            "path": read_result["path"],
            "object": read_result["name"],
            "count": len(variables),
            "variables": variables,
        })

    def handle_variable_upsert(self, params):
        path = params.get("path", "")
        name = params.get("name", "")
        if not path or not name:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameters: path and name"
            }, 400)
            return

        logger.info("Variable upsert request for '%s' in '%s'", name, path)
        read_result = self._read_declaration_object(path)
        if not read_result.get("success", False):
            self.send_json_response(read_result, 500)
            return

        new_declaration, change = upsert_variable(
            declaration=read_result["declaration"],
            path=read_result["path"],
            name=name,
            type_name=params.get("type"),
            initial_value=params.get("initialValue"),
            address=params.get("address"),
            comment=params.get("comment"),
            section=params.get("section"),
            declaration_line=params.get("declarationLine"),
        )

        script = self.script_generator.generate_pou_code_script({
            "path": path,
            "declaration": new_declaration,
            "save": params.get("save", False),
            "verify": params.get("verify", False),
        })
        result = self.script_executor.execute_script(script, timeout=45)
        if not result.get("success", False):
            self.send_json_response(result, 500)
            return

        self.send_json_response({
            "success": True,
            "path": path,
            "change": change,
            "pou": result.get("pou"),
            "saved": result.get("saved"),
            "verified": result.get("verified"),
            "verificationErrors": result.get("verificationErrors", []),
        })

    def handle_variable_delete(self, params):
        path = params.get("path", "")
        name = params.get("name", "")
        if not path or not name:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameters: path and name"
            }, 400)
            return

        logger.info("Variable delete request for '%s' in '%s'", name, path)
        read_result = self._read_declaration_object(path)
        if not read_result.get("success", False):
            self.send_json_response(read_result, 500)
            return

        new_declaration, change = delete_variable(
            declaration=read_result["declaration"],
            path=read_result["path"],
            name=name,
        )

        if not change.get("deleted", False):
            self.send_json_response({
                "success": True,
                "path": path,
                "change": change,
            })
            return

        script = self.script_generator.generate_pou_code_script({
            "path": path,
            "declaration": new_declaration,
            "save": params.get("save", False),
            "verify": params.get("verify", False),
        })
        result = self.script_executor.execute_script(script, timeout=45)
        if not result.get("success", False):
            self.send_json_response(result, 500)
            return

        self.send_json_response({
            "success": True,
            "path": path,
            "change": change,
            "pou": result.get("pou"),
            "saved": result.get("saved"),
            "verified": result.get("verified"),
            "verificationErrors": result.get("verificationErrors", []),
        })
