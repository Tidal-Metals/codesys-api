"""Generated IronPython scripts for project compilation."""

def generate_project_compile_script(params):
    """Generate script to compile the current project."""
    clean_build = params.get("clean_build", False)
    
    return """
import scriptengine
import json
import sys
import traceback
import re

try:
    print("Starting project compilation script")
    clean_build = {0}
    print("Clean build: " + str(clean_build))

    system = None
    if hasattr(scriptengine, 'system'):
        system = scriptengine.system
    elif hasattr(session, 'system'):
        system = session.system

    project = None
    if hasattr(session, 'active_project') and session.active_project is not None:
        project = session.active_project
    elif hasattr(scriptengine, 'projects') and hasattr(scriptengine.projects, 'primary'):
        try:
            project = scriptengine.projects.primary
        except:
            project = None

    # Check if we have an active project
    if project is None:
        print("No active project in session")
        result = {{"success": False, "error": "No active project in session"}}
    else:
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
            if system is not None:
                _cleared_categories = 0
                if hasattr(system, 'get_message_categories') and hasattr(system, 'clear_messages'):
                    try:
                        active_categories = system.get_message_categories(True)
                        for category in active_categories:
                            try:
                                system.clear_messages(category)
                                _cleared_categories += 1
                            except Exception as clear_cat_e:
                                print("Warning: Could not clear category " + str(category) + ": " + str(clear_cat_e))
                        print("Cleared previous messages from " + str(_cleared_categories) + " categories")
                    except Exception as clear_e:
                        print("Warning: Could not enumerate/clear messages: " + str(clear_e))
            
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
                if system is not None:
                    try:
                        if hasattr(system, 'process_messageloop'):
                            system.process_messageloop()
                        if hasattr(system, 'delay'):
                            system.delay(500)
                    except Exception as loop_e:
                        print("Warning: Could not process message loop: " + str(loop_e))
                
                # Check for compilation messages/errors as per documentation
                compilation_messages = []
                if system is not None:
                    _seen_messages = {{}}
                    if hasattr(system, 'get_message_categories') and hasattr(system, 'get_message_objects'):
                        try:
                            active_categories = system.get_message_categories(True)
                            print("Retrieved " + str(len(active_categories)) + " active message categories")
                            _preferred_categories = []
                            _other_categories = []
                            for category in active_categories:
                                category_desc = ""
                                try:
                                    if hasattr(system, 'get_message_category_description'):
                                        category_desc = str(system.get_message_category_description(category))
                                except:
                                    category_desc = ""
                                _category_record = (category, category_desc)
                                _desc_lower = category_desc.lower()
                                if _desc_lower in ("build", "additional code checks", "compile", "compiler"):
                                    _preferred_categories.append(_category_record)
                                else:
                                    _other_categories.append(_category_record)

                            _ordered_categories = _preferred_categories + _other_categories
                            for category, category_desc in _ordered_categories:
                                try:
                                    message_objects = system.get_message_objects(category)
                                    print("Category " + str(category_desc or category) + " returned " + str(len(message_objects)) + " message objects")
                                    for msg_obj in message_objects:
                                        try:
                                            msg_text = str(msg_obj)
                                            msg_level = "info"
                                            severity_text = ""
                                            if hasattr(msg_obj, 'severity'):
                                                try:
                                                    severity_text = str(msg_obj.severity)
                                                except:
                                                    severity_text = ""
                                            severity_lower = severity_text.lower()
                                            if 'error' in severity_lower:
                                                msg_level = "error"
                                            elif 'warning' in severity_lower:
                                                msg_level = "warning"
                                            elif 'information' in severity_lower or 'text' in severity_lower:
                                                msg_level = "info"
                                            if msg_level == "info":
                                                msg_text_lower = msg_text.lower()
                                                _compile_summary = re.search(r'(\\d+)\\s+errors?,\\s+(\\d+)\\s+warnings?', msg_text_lower)
                                                if _compile_summary is not None:
                                                    try:
                                                        _error_count = int(_compile_summary.group(1))
                                                    except:
                                                        _error_count = 0
                                                    try:
                                                        _warning_count = int(_compile_summary.group(2))
                                                    except:
                                                        _warning_count = 0
                                                    if _error_count > 0:
                                                        msg_level = "error"
                                                    elif _warning_count > 0:
                                                        msg_level = "warning"
                                                elif '[error]' in msg_text_lower or ' error:' in msg_text_lower:
                                                    msg_level = "error"
                                                elif '[warning]' in msg_text_lower or ' warning:' in msg_text_lower:
                                                    msg_level = "warning"
                                            _msg_key = str(category) + "|" + severity_text + "|" + msg_text
                                            if _msg_key in _seen_messages:
                                                continue
                                            _seen_messages[_msg_key] = True
                                            compilation_messages.append({{
                                                "text": msg_text,
                                                "level": msg_level,
                                                "severity": severity_text,
                                                "category": str(category),
                                                "categoryDescription": category_desc
                                            }})
                                        except Exception as parse_msg_e:
                                            print("Warning: Could not parse message object: " + str(parse_msg_e))
                                except Exception as cat_e:
                                    print("Warning: Could not get messages for category " + str(category) + ": " + str(cat_e))
                        except Exception as msg_obj_e:
                            print("Warning: Could not enumerate message categories: " + str(msg_obj_e))
                
                # Check if there were any errors in the messages
                error_messages = []
                warning_messages = []
                info_messages = []
                for _msg in compilation_messages:
                    _level = _msg.get("level", "info")
                    if _level == "error":
                        error_messages.append(_msg)
                    elif _level == "warning":
                        warning_messages.append(_msg)
                    else:
                        info_messages.append(_msg)
                has_errors = any(msg.get("level") == "error" for msg in compilation_messages)
                
                if has_errors:
                    print("Compilation completed with errors")
                    result = {{
                        "success": False,
                        "error": "Compilation completed with errors",
                        "messages": compilation_messages,
                        "errors": error_messages,
                        "warnings": warning_messages,
                        "info": info_messages,
                        "build_type": "rebuild" if clean_build else "build"
                    }}
                else:
                    print("Compilation completed successfully")
                    result = {{
                        "success": True,
                        "message": "Project compiled successfully",
                        "messages": compilation_messages,
                        "errors": error_messages,
                        "warnings": warning_messages,
                        "info": info_messages,
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

