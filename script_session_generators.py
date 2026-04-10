"""Generated IronPython scripts for session operations."""

def generate_session_start_script():
    """Generate script to start a session."""
    return """
import scriptengine
import json
import sys
import warnings

# Silence deprecation warnings for sys.exc_clear() in IronPython 2.7
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    # Use the global system instance provided by scriptengine
    # IMPORTANT: scriptengine.system is a pre-existing instance
    print("Using global scriptengine.system instance")
    system = scriptengine.system
    
    # Store system instance
    session.system = system
    
    # Return success
    result = {"success": True, "message": "Session started"}
except:
    # IronPython 2.7 style exception handling (no 'as e' syntax)
    error_type, error_value, error_traceback = sys.exc_info()
    result = {"success": False, "error": str(error_value)}
"""
    
def generate_session_status_script():
    """Generate script to get session status."""
    return """
import scriptengine
import json

try:
    # Get system status
    system = session.system
    
    result = {
        "success": True,
        "status": {
            "session_active": system is not None,
            "project_open": session.active_project is not None
        }
    }
    
    if session.active_project:
        result["status"]["project"] = {
            "path": session.active_project.path,
            "dirty": session.active_project.dirty
        }
except Exception as e:
    result = {"success": False, "error": str(e)}
"""
    
