"""System metadata and log endpoint handlers."""

import os

from server_config import CODESYS_PATH, LOG_FILE, PERSISTENT_SCRIPT


class SystemHandlersMixin:
    def handle_system_info(self):
        """Handle system/info endpoint."""
        info = {
            "version": "0.1",
            "process_manager": {
                "status": self.process_manager.is_running()
            },
            "codesys_path": CODESYS_PATH,
            "persistent_script": PERSISTENT_SCRIPT
        }
        
        self.send_json_response({
            "success": True,
            "info": info
        })
        
    def handle_system_logs(self):
        """Handle system/logs endpoint."""
        logs = []
        
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, 'r') as f:
                    logs = f.readlines()
            except:
                pass
                
        self.send_json_response({
            "success": True,
            "logs": logs
        })
