"""Generated IronPython scripts for basic project operations."""

import logging
import os

from server_config import CODESYS_PATH

logger = logging.getLogger('codesys_api_server')

def generate_project_create_script(params):
    """Generate script to create a project."""
    path = params.get("path", "")
    # Normalize path to use backslashes for Windows
    path = path.replace("/", "\\")
    
    # Get template_path parameter or build from CODESYS_PATH
    template_path = params.get("template_path", "")
    if not template_path:
        # Derive template path from CODESYS executable path
        codesys_dir = os.path.dirname(CODESYS_PATH)  # Get directory containing CODESYS.exe
        if "Common" in codesys_dir:  # Handle "Common" subfolder case
            codesys_dir = os.path.dirname(codesys_dir)  # Go up one level
        template_path = os.path.join(codesys_dir, "Templates", "Standard.project")
        logger.info("Using derived template path: %s", template_path)
        
    # Pass CODESYS_PATH to the script to help find templates
    codesys_path = CODESYS_PATH
        
    # Create a super simple script - just open the template and save as the new name
    return """
# Simple script to create a project from template - IronPython 2.7 compatible
import scriptengine
import json
import os
import sys
import warnings
import traceback

# Silence deprecation warnings for sys.exc_clear() in IronPython 2.7
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    print("Starting project creation script")
    
    # Check if standard template exists at the provided path
    template_path = "{1}"
    print("Looking for template at: " + template_path)
    
    if not os.path.exists(template_path):
        print("Template not found at: " + template_path)
        
        # Try to determine template location directly from CODESYS_PATH
        codesys_path = r"{2}"
        print("CODESYS path: " + codesys_path)
        
        # Derive template path from CODESYS executable path
        codesys_dir = os.path.dirname(codesys_path)  # Get directory containing CODESYS.exe
        if "Common" in codesys_dir:  # Handle "Common" subfolder case
            codesys_dir = os.path.dirname(codesys_dir)  # Go up one level
            
        template_path = os.path.join(codesys_dir, "Templates", "Standard.project")
        print("Trying template at: " + template_path)
    
    if not os.path.exists(template_path):
        print("Template not found! Cannot create project from template.")
        raise Exception("Template not found at: " + template_path)
    
    # Simple approach: open template, save as new name
    print("Opening template: " + template_path)
    project = scriptengine.projects.open(template_path)
    if project is None:
        print("Failed to open template project")
        raise Exception("Failed to open template project at: " + template_path)
    
    print("Template opened successfully")
    
    # Save as new project name
    print("Saving as new project: {0}")
    if hasattr(project, 'save_as'):
        project.save_as("{0}")
        print("Project saved successfully as: {0}")
        # That's it! The project is now saved with our desired name and is already the active project
    else:
        print("Project has no save_as method")
        raise Exception("Project object does not have a save_as method")
    
    # Set as active project
    print("Setting as active project")
    session.active_project = project
    
    # Check active application
    print("Checking for active application")
    if hasattr(project, 'active_application') and project.active_application is not None:
        app = project.active_application
        print("Found active application: " + str(app))
    else:
        print("No active application found in project")
    
    print("Project creation completed")
    
    # Return success result
    # Note: Project is already saved to disk at this point (save_as operation handles this)
    # There's no need to call save_project() immediately after create_project()
    result = {{
        "success": True,
        "project": {{
            "path": project.path if hasattr(project, 'path') else "{0}",
            "name": project.name if hasattr(project, 'name') else os.path.basename("{0}"),
            "dirty": project.dirty if hasattr(project, 'dirty') else False
        }}
    }}
except:
    # IronPython 2.7 style exception handling (no 'as e' syntax)
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error creating project: " + str(error_value))
    print(traceback.format_exc())
    
    result = {{
        "success": False,
        "error": str(error_value)
    }}
""".format(path.replace("\\", "\\\\"), template_path.replace("\\", "\\\\"), codesys_path.replace("\\", "\\\\"))
    
def generate_project_open_script(params):
    """Generate script to open a project."""
    path = params.get("path", "")
    
    return """
import scriptengine
import json
import sys
import os
import traceback

try:
    print("Starting project open script")
    print("Opening project at path: {0}")
    
    # Check if global instances are available
    if not hasattr(scriptengine, 'projects'):
        print("Global scriptengine.projects instance not found")
        result = {{"success": False, "error": "Global scriptengine.projects instance not found"}}
    else:
        try:
            # Open project using the global projects instance
            print("Using global scriptengine.projects instance to open project")
            project = scriptengine.projects.open("{0}")
            
            if project is None:
                print("Project open returned None")
                result = {{"success": False, "error": "Project open operation returned None"}}
            else:
                print("Project opened successfully")
                
                # Store as active project in session
                print("Storing project as active project in session")
                session.active_project = project
                
                # Get project info for result, with careful attribute checking
                project_info = {{"path": "{0}"}}  # Always include the path that was requested
                
                # Get actual path from project object if available
                if hasattr(project, 'path'):
                    project_info['path'] = project.path
                    print("Project path: " + project.path)
                    
                    # Try to extract name from path if name attribute is missing
                    if not hasattr(project, 'name'):
                        try:
                            project_info['name'] = os.path.basename(project.path)
                            print("Extracted name from path: " + project_info['name'])
                        except Exception as name_error:
                            project_info['name'] = os.path.basename("{0}")
                            print("Error extracting name from path, using request path basename instead")
                else:
                    print("Project has no path attribute, using request path")
                
                # Check for name attribute (if not already set above)
                if 'name' not in project_info and hasattr(project, 'name'):
                    project_info['name'] = project.name
                    print("Project name: " + project.name)
                elif 'name' not in project_info:
                    # Last resort - extract from the requested path
                    project_info['name'] = os.path.basename("{0}")
                    print("Using name from request path: " + project_info['name'])
                
                # Check for dirty attribute
                if hasattr(project, 'dirty'):
                    project_info['dirty'] = project.dirty
                    print("Project dirty flag: " + str(project.dirty))
                else:
                    project_info['dirty'] = False
                    print("Project has no dirty attribute, assuming False")
                
                # Return project info
                result = {{
                    "success": True,
                    "project": project_info
                }}
                print("Project open completed successfully")
        except Exception as e:
            print("Error opening project: " + str(e))
            print(traceback.format_exc())
            result = {{"success": False, "error": "Error opening project: " + str(e)}}
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in project open script: " + str(error_value))
    print(traceback.format_exc())
    result = {{"success": False, "error": str(error_value)}}
""".format(path.replace("\\", "\\\\"))
    
def generate_project_save_script():
    """Generate script to save current project."""
    return """
import scriptengine
import json
import sys
import os
import traceback

try:
    print("Starting project save script")
    
    # Check if we have an active project
    if not hasattr(session, 'active_project') or session.active_project is None:
        print("No active project in session")
        result = {"success": False, "error": "No active project in session"}
    else:
        # Get active project
        project = session.active_project
        print("Got active project")
        
        # Check if project has save method
        if not hasattr(project, 'save'):
            print("Project has no save method")
            result = {"success": False, "error": "Project object has no save method"}
        else:
            # Save project
            print("Saving project...")
            project.save()
            print("Project saved successfully")
            
            # Get project info for result, with careful attribute checking
            project_info = {}
            
            # Check for path attribute
            if hasattr(project, 'path'):
                project_info['path'] = project.path
                # Try to extract name from path if name attribute is missing
                if not hasattr(project, 'name'):
                    try:
                        project_info['name'] = os.path.basename(project.path)
                        print("Extracted name from path: " + project_info['name'])
                    except Exception as name_error:
                        project_info['name'] = "Unknown"
                        print("Error extracting name from path: " + str(name_error))
            else:
                project_info['path'] = "Unknown"
                print("Project has no path attribute")
            
            # Check for name attribute (if not already set above)
            if 'name' not in project_info and hasattr(project, 'name'):
                project_info['name'] = project.name
            
            # Check for dirty attribute
            if hasattr(project, 'dirty'):
                project_info['dirty'] = project.dirty
            else:
                project_info['dirty'] = False
                print("Project has no dirty attribute, assuming False")
            
            # Return project info
            result = {
                "success": True,
                "project": project_info
            }
            print("Project info prepared for result")
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in project save script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
"""
    
def generate_project_close_script():
    """Generate script to close current project."""
    return """
import scriptengine
import json
import sys
import os
import traceback

try:
    print("Starting project close script")
    
    # Check if we have an active project
    if not hasattr(session, 'active_project') or session.active_project is None:
        print("No active project in session")
        result = {"success": False, "error": "No active project in session"}
    else:
        # Get active project
        project = session.active_project
        print("Got active project")
        
        # Store project info for result, with careful attribute checking
        project_info = {}
        
        # Check for path attribute
        if hasattr(project, 'path'):
            project_info['path'] = project.path
            print("Project path: " + project.path)
            
            # Try to extract name from path if name attribute is missing
            if not hasattr(project, 'name'):
                try:
                    project_info['name'] = os.path.basename(project.path)
                    print("Extracted name from path: " + project_info['name'])
                except Exception as name_error:
                    project_info['name'] = "Unknown"
                    print("Error extracting name from path: " + str(name_error))
        else:
            project_info['path'] = "Unknown"
            print("Project has no path attribute")
        
        # Check for name attribute (if not already set above)
        if 'name' not in project_info and hasattr(project, 'name'):
            project_info['name'] = project.name
            print("Project name: " + project.name)
        
        # Try to close project if it has a close method
        if hasattr(project, 'close'):
            try:
                print("Closing project using project.close() method")
                project.close()
                print("Project closed via close() method")
            except Exception as close_error:
                print("Error closing project via close() method: " + str(close_error))
                print("Will still try to clear session.active_project")
        else:
            print("Project has no close() method, will just clear session.active_project")
        
        # Clear session active project
        print("Clearing session.active_project reference")
        session.active_project = None
        print("Project reference cleared from session")
        
        # Return project info
        result = {
            "success": True,
            "project": project_info
        }
        print("Project close completed successfully")
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in project close script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
"""

def generate_project_list_script():
    """Generate script to list recent projects."""
    return """
import scriptengine
import json
import os
import sys
import traceback

try:
    print("Starting project list script")
    
    # Check if global instances are available
    if not hasattr(scriptengine, 'projects'):
        print("Global scriptengine.projects instance not found")
        result = {{"success": False, "error": "Global scriptengine.projects instance not found"}}
    else:
        print("Using global scriptengine.projects instance for project listing")
        
        # Get recent projects list
        recent_projects = []
        
        try:
            # Check for recent_projects attribute on global projects instance
            if hasattr(scriptengine.projects, 'recent_projects'):
                # Direct access if available
                print("Getting projects via scriptengine.projects.recent_projects attribute")
                recent_projects = scriptengine.projects.recent_projects
            elif hasattr(scriptengine.projects, 'get_recent_projects'):
                # Function call if available
                print("Getting projects via scriptengine.projects.get_recent_projects() method")
                recent_projects = scriptengine.projects.get_recent_projects()
            else:
                print("No method found to get recent projects list")
            
            # Format project list
            print("Processing project list with " + str(len(recent_projects) if recent_projects else 0) + " projects")
            projects = []
            
            if recent_projects:
                for project in recent_projects:
                    try:
                        project_info = {{"name": "Unknown", "path": "Unknown"}}
                        
                        # Get path
                        if hasattr(project, 'path'):
                            project_info["path"] = project.path
                            print("Project path: " + project.path)
                            
                            # Try to extract name from path
                            try:
                                project_info["name"] = os.path.basename(project.path)
                                print("Extracted name from path: " + project_info["name"])
                            except Exception as name_error:
                                print("Error extracting name from path: " + str(name_error))
                        
                        # Get name if explicitly available
                        if hasattr(project, 'name'):
                            project_info["name"] = project.name
                            print("Project name: " + project.name)
                        
                        # Get last opened date if available
                        if hasattr(project, 'last_opened_date'):
                            project_info["last_opened"] = project.last_opened_date
                            print("Last opened date: " + str(project.last_opened_date))
                        
                        # Add to list
                        projects.append(project_info)
                        print("Added project to list: " + project_info["name"])
                    except Exception as project_error:
                        print("Error processing project item: " + str(project_error))
            else:
                print("No recent projects found")
            
            # Return projects list
            result = {{
                "success": True,
                "projects": projects
            }}
            print("Project list processing completed successfully")
        except Exception as e:
            print("Error processing projects list: " + str(e))
            print(traceback.format_exc())
            result = {{"success": False, "error": "Error processing projects list: " + str(e)}}
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in project list script: " + str(error_value))
    print(traceback.format_exc())
    result = {{"success": False, "error": str(error_value)}}
"""

