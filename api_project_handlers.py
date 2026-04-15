"""Project endpoint handlers."""

import os
import time

from server_config import logger


class ProjectHandlersMixin:
    def handle_project_create(self, params):
        """Handle project/create endpoint."""
        if "path" not in params:
            # If path is not provided, use the current directory
            script_dir = os.path.dirname(os.path.abspath(__file__))
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            default_path = os.path.join(script_dir, f"CODESYS_Project_{timestamp}.project")
            logger.info("No path provided, using default path: %s", default_path)
            params["path"] = default_path
        
        # Allow specifying a template path (optional)
        template_path = params.get("template_path", "")
        if template_path:
            logger.info("Using template from: %s", template_path)
        else:
            logger.info("No template specified, will try to use standard template")
        
        path = params.get("path", "")
        # Normalize path to use backslashes for Windows
        path = path.replace("/", "\\")
        logger.info("Project creation request for path: %s (executing script in CODESYS)", path)
        
        # Make sure CODESYS is running and fully initialized
        if not self.process_manager.is_running():
            logger.warning("CODESYS not running, attempting to start it")
            if not self.process_manager.start():
                error_msg = "Failed to start CODESYS process"
                logger.error(error_msg)
                self.send_json_response({
                    "success": False,
                    "error": error_msg
                }, 500)
                return
            # The start method now includes a wait for full initialization
        
        # Generate the script (IronPython 2.7 compatible)
        script = self.script_generator.generate_project_create_script(params)
        
        logger.info("Executing project creation script in CODESYS")
        # Execute the script with a reasonable timeout
        result = self.script_executor.execute_script(script, timeout=120)
        
        logger.info("Script execution result: %s", result)
        
        if result.get("success", False):
            logger.info("Project creation successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error creating project: %s", error_msg)
            
            # Send error response
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
    def handle_project_open(self, params):
        """Handle project/open endpoint."""
        if "path" not in params:
            self.send_json_response({
                "success": False,
                "error": "Missing required parameter: path"
            }, 400)
            return
        
        path = params.get("path", "")
        logger.info("Project open request for path: %s (executing script in CODESYS)", path)
        
        # Generate and execute project open script
        script = self.script_generator.generate_project_open_script(params)
        result = self.script_executor.execute_script(script, timeout=120)
        
        if result.get("success", False):
            logger.info("Project opening successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error opening project: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_project_save(self):
        """Handle project/save endpoint."""
        logger.info("Project save request (executing script in CODESYS)")
        
        # Generate and execute project save script
        script = self.script_generator.generate_project_save_script()
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("Project save successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error saving project: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_project_close(self):
        """Handle project/close endpoint."""
        logger.info("Project close request (executing script in CODESYS)")
        
        # Generate and execute project close script
        script = self.script_generator.generate_project_close_script()
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("Project close successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error closing project: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_project_list(self):
        """Handle project/list endpoint."""
        logger.info("Project list request (executing script in CODESYS)")
        
        # Generate and execute project list script
        script = self.script_generator.generate_project_list_script()
        result = self.script_executor.execute_script(script, timeout=30)
        
        if result.get("success", False):
            logger.info("Project listing successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error listing projects: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
        
        
    def handle_project_compile(self, params):
        """Handle project/compile endpoint."""
        clean_build = params.get("clean_build", False)
        
        logger.info("Project compile request (clean_build=%s) - executing script in CODESYS", clean_build)
        
        # Generate and execute project compilation script
        script = self.script_generator.generate_project_compile_script(params)
        result = self.script_executor.execute_script(script, timeout=120)  # Compilation can take longer
        
        if result.get("success", False):
            logger.info("Project compilation successful")
            self.send_json_response(result)
        else:
            error_msg = result.get("error", "Unknown error")
            logger.error("Error compiling project: %s", error_msg)
            self.send_json_response({
                "success": False,
                "error": error_msg
            }, 500)
