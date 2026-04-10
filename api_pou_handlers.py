"""POU and raw script endpoint handlers."""

from server_config import logger


class PouHandlersMixin:
    def handle_pou_create(self, params):
        """Handle pou/create endpoint."""
        required = ["name", "type", "language"]
        for field in required:
            if field not in params:
                self.send_json_response({
                    "success": False,
                    "error": "Missing required parameter: " + field
                }, 400)
                return
                
        name = params.get("name", "")
        pou_type = params.get("type", "FunctionBlock")
        language = params.get("language", "ST")
        parent_path = params.get("parentPath", "")
        
        logger.info("POU create request for '%s' (executing script in CODESYS)", name)
        
        # Generate and execute POU creation script
        script = self.script_generator.generate_pou_create_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("POU creation successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error creating POU: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_pou_code(self, params):
        """Handle pou/code endpoint."""
        # Check that we have path and at least one of: code, declaration, or implementation
        if "path" not in params:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameter: path"
            }, 400)
            return
            
        # Check that we have some code to set
        has_code = any(key in params for key in ["code", "declaration", "implementation"])
        if not has_code:
            self.send_json_response({
                "success": False,
                "error": "Missing code parameter: need at least one of 'code', 'declaration', or 'implementation'"
            }, 400)
            return
                
        path = params.get("path", "")
        
        # Support both legacy and new calling conventions
        if "code" in params:
            logger.info("POU code update request (legacy mode) for '%s' (executing script in CODESYS)", path)
        else:
            parts = []
            if "declaration" in params:
                parts.append("declaration")
            if "implementation" in params:
                parts.append("implementation")
            logger.info("POU code update request (%s) for '%s' (executing script in CODESYS)", 
                       " + ".join(parts), path)
        
        # Generate and execute POU code setting script
        script = self.script_generator.generate_pou_code_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("POU code update successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error updating POU code: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)

    def handle_pou_code_get(self, params):
        """Handle pou/code GET endpoint."""
        if "path" not in params:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameter: path"
            }, 400)
            return

        path = params.get("path", "")
        logger.info("POU code read request for '%s' (executing script in CODESYS)", path)

        script = self.script_generator.generate_pou_code_read_script(params)
        result = self.script_executor.execute_script(script, timeout=30)

        if result.get("success", False):
            logger.info("POU code read successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error reading POU code: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_pou_list(self, params):
        """Handle pou/list endpoint."""
        parent_path = params.get("parentPath", "")
        
        logger.info("POU list request (executing script in CODESYS)")
        
        # Generate and execute POU listing script
        script = self.script_generator.generate_pou_list_script(params)
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("POU listing successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error listing POUs: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_script_execute(self, params):
        """Handle script/execute endpoint."""
        if "script" not in params:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameter: script"
            }, 400)
            return
            
        # Get script to execute
        script = params.get("script", "")
        first_line = script.split('\n')[0] if script else ""
        
        logger.info("Script execute request: %s", 
                    first_line[:50] + "..." if len(first_line) > 50 else first_line)
        
        # Actually execute the script in CODESYS
        result = self.script_executor.execute_script(script)
        
        # Return the result from execution
        self.send_json_response(result)
