"""Session endpoint handlers."""

import time

from server_config import logger


class SessionHandlersMixin:
    def _try_attach_existing_session(self, timeout=5):
        """Try to bind the API to an already-running persistent session."""
        script = self.script_generator.generate_session_start_script()
        logger.info("Probing for an existing CODESYS persistent session")
        result = self.script_executor.execute_script(script, timeout=timeout)
        if result.get("success", False):
            logger.info("Attached to existing CODESYS persistent session")
        else:
            logger.info("No attachable persistent session detected: %s", result.get("error"))
        return result

    def handle_session_start(self):
        """Handle session/start endpoint."""
        try:
            logger.info("Session start requested - checking CODESYS process")
            self.process_manager.ensure_singleton()

            attach_result = self._try_attach_existing_session(timeout=5)
            if attach_result.get("success", False):
                attach_result["attached"] = True
                self.send_json_response(attach_result)
                return
            
            # First check if the process is already running
            if self.process_manager.is_running():
                logger.info("CODESYS process already running, using existing process")
            else:
                logger.info("CODESYS process not running, attempting to start")
                
                # Start the CODESYS process
                if not self.process_manager.start():
                    error_msg = "Failed to start CODESYS process"
                    logger.error(error_msg)
                    self.send_json_response({
                        "success": False,
                        "error": error_msg
                    }, 500)
                    return
                    
                logger.info("CODESYS process started successfully")
            
            # Generate the session start script
            script = self.script_generator.generate_session_start_script()
            
            # Execute the script to properly initialize the session
            logger.info("Executing session start script in CODESYS")
            result = self.script_executor.execute_script(script)
            
            # Return the result from the script execution
            self.send_json_response(result)
            
            # Remove all the commented out code that was causing indentation errors
                
        except Exception as e:
            logger.error("Unhandled error in session start: %s", str(e), exc_info=True)
            self.send_json_response({
                "success": False,
                "error": f"Internal server error: {str(e)}"
            }, 500)
            
    def handle_session_stop(self):
        """Handle session/stop endpoint."""
        if not self.process_manager.stop():
            self.send_json_response({
                "success": False,
                "error": "Failed to stop CODESYS session"
            }, 500)
            return
            
        self.send_json_response({
            "success": True,
            "message": "Session stopped"
        })
        
    def handle_session_restart(self):
        """Handle session/restart endpoint."""
        self.process_manager.stop()
        time.sleep(2)
        
        if not self.process_manager.start():
            self.send_json_response({
                "success": False,
                "error": "Failed to restart CODESYS session"
            }, 500)
            return
            
        # Generate the session start script
        script = self.script_generator.generate_session_start_script()
        
        # Execute the script to properly initialize the session
        logger.info("Executing session start script in CODESYS after restart")
        result = self.script_executor.execute_script(script)
        
        # Return the result from the script execution
        self.send_json_response(result)
            
    def handle_session_status(self):
        """Handle session/status endpoint."""
        self.process_manager.ensure_singleton()

        # Check process status
        process_running = self.process_manager.is_running()
        process_status = self.process_manager.get_status()
        attached = False
        
        # Execute the script to get actual session status
        if process_running:
            script = self.script_generator.generate_session_status_script()
            logger.info("Executing session status script in CODESYS")
            status_result = self.script_executor.execute_script(script)
            
            if status_result.get("success", False) and "status" in status_result:
                session_status = status_result["status"]
            else:
                session_status = {"active": process_running, "session_active": process_running, "project_open": False}
        else:
            attach_result = self._try_attach_existing_session(timeout=3)
            if attach_result.get("success", False):
                attached = True
                script = self.script_generator.generate_session_status_script()
                logger.info("Attached session detected; reading session status from CODESYS")
                status_result = self.script_executor.execute_script(script, timeout=10)
                if status_result.get("success", False) and "status" in status_result:
                    session_status = status_result["status"]
                else:
                    session_status = {"active": True, "session_active": True, "project_open": False}
            else:
                session_status = {"active": False, "session_active": False, "project_open": False}
                
        # Combine status information
        status = {
            "process": {
                "running": process_running or bool(session_status.get("session_active")),
                "state": process_status.get("state", "unknown"),
                "timestamp": process_status.get("timestamp", time.time())
            },
            "session": session_status,
            "attached": attached,
        }
        
        self.send_json_response({
            "success": True,
            "status": status
        })
