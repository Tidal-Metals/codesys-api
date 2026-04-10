"""Generated IronPython scripts for POU creation."""

def generate_pou_create_script(params):
    """Generate script to create a POU."""
    name = params.get("name", "")
    pou_type = params.get("type", "FunctionBlock")
    language = params.get("language", "ST")
    parent_path = params.get("parentPath", "")
    
    # Create a more robust script that handles potential enum issues
    return """
import scriptengine
import json
import sys
import traceback

try:
    print("Starting POU creation script for {0}")
    
    # Check if we have an active project
    if not hasattr(session, 'active_project') or session.active_project is None:
        print("No active project in session")
        result = {{"success": False, "error": "No active project in session"}}
    else:
        # Get active project
        project = session.active_project
        print("Got active project")
        
        # Try to get application
        if not hasattr(project, 'active_application') or project.active_application is None:
            print("Project has no active application")
            result = {{"success": False, "error": "Project has no active application"}}
        else:
            # Get application
            application = project.active_application
            print("Got active application")
            
            # The application itself should implement IecLanguageObjectContainer
            # We'll try to use it directly
            container = application
            print("Using application object directly for POU creation")
            
            # Handle parent path navigation if needed
            if "{2}":
                print("Navigating to parent path: {2}")
                try:
                    # Navigate to parent container
                    path_parts = "{2}".split('/')
                    current = application
                    for part in path_parts:
                        if not part:
                            continue
                        if hasattr(current, 'find_object'):
                            current = current.find_object(part)
                        elif hasattr(current, 'get_object'):
                            current = current.get_object(part)
                        else:
                            raise ValueError("Cannot navigate to " + part)
                    
                    if hasattr(current, 'pou_container'):
                        container = current.pou_container
                    else:
                        container = current
                    print("Navigation to parent path successful")
                except Exception as e:
                    print("Error navigating to parent path: " + str(e))
                    result = {{"success": False, "error": "Error navigating to parent path: " + str(e)}}
            
            # Use the properly defined POU types and implementation languages
            if not 'result' in locals():  # Only proceed if we haven't set an error result
                try:
                    # Map the string name to the actual PouType enum value
                    print("Determining POU type for: {1}")
                    
                    # Define POU type map according to the working example code
                    pou_type_map = {{
                        "Program": scriptengine.PouType.Program,
                        "FunctionBlock": scriptengine.PouType.FunctionBlock,
                        "Function": scriptengine.PouType.Function
                    }}
                    
                    # Get the POU type from the map
                    if "{1}" in pou_type_map:
                        pou_type_value = pou_type_map["{1}"]
                        print("Set POU type to {1}")
                    else:
                        print("Unknown POU type: {1}")
                        result = {{"success": False, "error": "Unknown POU type: {1}"}}
                        
                    # Set language to None (let CODESYS default based on parent/settings)
                    language_value = None
                    print("Using default language: ST (None)")
                    
                    # Handle return type for functions
                    return_type = None
                    if "{1}" == "Function":
                        # For functions, return type is required - use INT as default
                        return_type = "INT" 
                        print("Setting return type for function: INT")
                except Exception as e:
                    print("Error resolving type values: " + str(e))
                    result = {{"success": False, "error": "Error resolving type values: " + str(e)}}
            
            # Create POU with the correct parameters
            if not 'result' in locals() and 'pou_type_value' in locals() and pou_type_value is not None:
                try:
                    print("Creating POU: {0}")
                    
                    # Call with keyword arguments as shown in the example
                    if "{1}" == "Function":
                        # For functions, return_type is required
                        pou = container.create_pou(
                            name="{0}",
                            type=pou_type_value,
                            language=language_value,
                            return_type=return_type
                        )
                        print("Created function with return type")
                    else:
                        # For programs and function blocks, return_type should not be specified
                        pou = container.create_pou(
                            name="{0}",
                            type=pou_type_value,
                            language=language_value
                        )
                        print("Created POU without return type")
                    
                    if pou is not None:
                        print("POU created successfully")
                        
                        # Store POU reference in session for easier later access
                        if not hasattr(session, 'created_pous'):
                            session.created_pous = {{}}
                        session.created_pous["{0}"] = pou
                        print("Stored POU reference in session.created_pous['{0}']")
                        
                        # Add a small delay to allow CODESYS to update internal structures
                        import time
                        time.sleep(0.5)
                        print("Allowed time for CODESYS to update after POU creation")
                        
                        result = {{
                            "success": True,
                            "pou": {{
                                "name": "{0}",
                                "type": "{1}",
                                "language": "{3}"
                            }}
                        }}
                    else:
                        print("POU creation failed - returned None")
                        result = {{"success": False, "error": "POU creation failed - returned None"}}
                except Exception as e:
                    print("Error creating POU: " + str(e))
                    result = {{"success": False, "error": "Error creating POU: " + str(e)}}
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in POU creation script: " + str(error_value))
    print(traceback.format_exc())
    result = {{"success": False, "error": str(error_value)}}
""".format(name, pou_type, parent_path, language)
    
