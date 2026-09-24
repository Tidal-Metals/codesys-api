"""Project endpoint handlers."""

import os
import time

from server_config import logger


class ProjectHandlersMixin:
    @staticmethod
    def _normalize_path(path):
        try:
            return os.path.normcase(os.path.abspath(str(path)))
        except Exception:
            return str(path)

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

        current_script = """
import scriptengine
import os

try:
    project = None
    if hasattr(scriptengine, 'projects') and hasattr(scriptengine.projects, 'primary'):
        try:
            project = scriptengine.projects.primary
        except:
            project = None
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": True, "project": None}
    else:
        project_path = ""
        project_dirty = False
        if hasattr(project, 'path'):
            try:
                project_path = str(project.path)
            except:
                project_path = ""
        if hasattr(project, 'dirty'):
            try:
                project_dirty = bool(project.dirty)
            except:
                project_dirty = False
        result = {"success": True, "project": {"path": project_path, "dirty": project_dirty}}
except:
    import sys
    error_type, error_value, error_traceback = sys.exc_info()
    result = {"success": False, "error": str(error_value)}
"""
        current_result = self.script_executor.execute_script(current_script, timeout=15)
        current_project = current_result.get("project") if current_result.get("success", False) else None
        if current_project and current_project.get("path"):
            current_path = self._normalize_path(current_project.get("path", ""))
            requested_path = self._normalize_path(path)
            if current_path == requested_path:
                logger.info("Requested project is already active; skipping reopen")
                self.send_json_response({
                    "success": True,
                    "project": current_project,
                    "already_open": True,
                })
                return
        
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
            failure_payload = dict(result)
            failure_payload["success"] = False
            failure_payload["error"] = error_msg
            self.send_json_response(failure_payload, 500)
