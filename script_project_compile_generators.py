"""Generated IronPython scripts for project compilation."""

def generate_project_compile_script(params):
    """Generate script to compile the current project."""
    clean_build = params.get("clean_build", False)
    
    return """
import scriptengine
import json
import sys
import traceback

try:
    print("Starting project compilation script")
    clean_build = {0}
    print("Clean build: " + str(clean_build))
    
    # Check if we have an active project
    if not hasattr(session, 'active_project') or session.active_project is None:
        print("No active project in session")
        result = {{"success": False, "error": "No active project in session"}}
    else:
        # Get active project
        project = session.active_project
        print("Got active project: " + str(project.path))
        
        # Get the active application - this is required for compilation
        if not hasattr(project, 'active_application') or project.active_application is None:
            print("Project has no active application")
            result = {{"success": False, "error": "Project has no active application"}}
        else:
            # Get application
            application = project.active_application
            print("Got active application")
            
            # Clear any previous messages
            if hasattr(scriptengine, 'System'):
                system = scriptengine.System()
                if hasattr(system, 'clear_messages'):
                    try:
                        system.clear_messages()
                        print("Cleared previous messages")
                    except Exception as clear_e:
                        print("Warning: Could not clear messages: " + str(clear_e))
            
            try:
                # Compile the application according to CODESYS documentation
                print("Starting compilation...")
                
                if clean_build:
                    # Perform clean build (rebuild)
                    if hasattr(application, 'rebuild'):
                        print("Performing rebuild...")
                        application.rebuild()
                    else:
                        print("Rebuild method not available, using build instead")
                        application.build()
                else:
                    # Perform regular build
                    print("Performing build...")
                    application.build()
                
                print("Build command completed")
                
                # Check for compilation messages/errors as per documentation
                compilation_messages = []
                if hasattr(scriptengine, 'System'):
                    system = scriptengine.System()
                    if hasattr(system, 'get_messages'):
                        try:
                            messages = system.get_messages()
                            print("Retrieved " + str(len(messages)) + " compilation messages")
                            for msg in messages:
                                compilation_messages.append({{
                                    "text": str(msg),
                                    "level": "info"
                                }})
                        except Exception as msg_e:
                            print("Warning: Could not get compilation messages: " + str(msg_e))
                    
                    if hasattr(system, 'get_message_objects'):
                        try:
                            message_objects = system.get_message_objects()
                            print("Retrieved " + str(len(message_objects)) + " message objects")
                            for msg_obj in message_objects:
                                try:
                                    msg_text = str(msg_obj)
                                    msg_level = "info"
                                    if hasattr(msg_obj, 'severity'):
                                        severity = str(msg_obj.severity).lower()
                                        if 'error' in severity:
                                            msg_level = "error"
                                        elif 'warning' in severity:
                                            msg_level = "warning"
                                    
                                    compilation_messages.append({{
                                        "text": msg_text,
                                        "level": msg_level
                                    }})
                                except Exception as parse_msg_e:
                                    print("Warning: Could not parse message object: " + str(parse_msg_e))
                        except Exception as msg_obj_e:
                            print("Warning: Could not get message objects: " + str(msg_obj_e))
                
                # Check if there were any errors in the messages
                has_errors = any(msg.get("level") == "error" for msg in compilation_messages)
                
                if has_errors:
                    print("Compilation completed with errors")
                    result = {{
                        "success": False,
                        "error": "Compilation completed with errors",
                        "messages": compilation_messages,
                        "build_type": "rebuild" if clean_build else "build"
                    }}
                else:
                    print("Compilation completed successfully")
                    result = {{
                        "success": True,
                        "message": "Project compiled successfully",
                        "messages": compilation_messages,
                        "build_type": "rebuild" if clean_build else "build"
                    }}
                    
            except Exception as build_e:
                print("Error during build: " + str(build_e))
                print(traceback.format_exc())
                result = {{
                    "success": False,
                    "error": "Compilation failed: " + str(build_e),
                    "build_type": "rebuild" if clean_build else "build"
                }}
                
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in project compilation script: " + str(error_value))
    print(traceback.format_exc())
    result = {{"success": False, "error": str(error_value)}}
""".format("True" if clean_build else "False")

