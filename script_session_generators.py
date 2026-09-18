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
    
    # Prefer the already-open primary project when available.
    if hasattr(scriptengine, 'projects') and hasattr(scriptengine.projects, 'primary'):
        try:
            session.active_project = scriptengine.projects.primary
        except:
            pass

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
    system = None
    if hasattr(session, 'system'):
        system = session.system
    if system is None and hasattr(scriptengine, 'system'):
        try:
            system = scriptengine.system
            session.system = system
        except:
            system = None

    project = None
    if hasattr(session, 'active_project'):
        project = session.active_project
    if project is None and hasattr(scriptengine, 'projects') and hasattr(scriptengine.projects, 'primary'):
        try:
            project = scriptengine.projects.primary
            session.active_project = project
        except:
            project = None

    project_info = None
    if project is not None:
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
        project_info = {
            "path": project_path,
            "dirty": project_dirty
        }
    
    result = {
        "success": True,
        "status": {
            "session_active": system is not None,
            "active": system is not None,
            "project_open": project is not None
        }
    }
    
    if project_info is not None:
        result["status"]["project"] = project_info
except:
    import sys
    error_type, error_value, error_traceback = sys.exc_info()
    result = {"success": False, "error": str(error_value)}
"""
    
