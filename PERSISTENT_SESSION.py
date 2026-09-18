"""
CODESYS Persistent Session Script

This script runs as a persistent session inside CODESYS.
It handles commands from the REST API server and executes
operations within the CODESYS environment.

Usage:
    This script is meant to be launched by CODESYS.exe with:
    CODESYS.exe --runscript="PERSISTENT_SESSION.py"

Note:
    This script is written for Python 2.7 compatibility since
    CODESYS uses IronPython 2.7.
"""

import scriptengine
import os
import sys
import time
import json
import traceback
import warnings

# Silence deprecation warnings for sys.exc_clear() in IronPython 2.7
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Check Python version - CODESYS uses IronPython 2.7
PYTHON_VERSION = sys.version_info[0]
IRONPYTHON = 'Iron' in sys.version

# Constants
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REQUEST_DIR = os.path.join(SCRIPT_DIR, "requests")
RESULT_DIR = os.path.join(SCRIPT_DIR, "results")
TERMINATION_SIGNAL_FILE = os.path.join(SCRIPT_DIR, "terminate.signal")
STATUS_FILE = os.path.join(SCRIPT_DIR, "session_status.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "session.log")

# Ensure directories exist
for directory in [REQUEST_DIR, RESULT_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

class CodesysPersistentSession(object):
    """Maintains a persistent CODESYS session."""

    def __init__(self):
        self.system = None
        self.active_project = None
        self.online_apps = {}
        self.trust_certificate_callbacks = {}
        self.running = True
        self.init_success = False

    def _safe_text(self, value):
        try:
            if value is None:
                return ""
            return str(value)
        except:
            return ""

    def _normalize_path(self, value):
        try:
            return self._safe_text(value).replace("\\", "/").strip("/")
        except:
            return ""

    def _current_project_path(self):
        project = self.active_project
        if project is None:
            return ""
        try:
            return self._normalize_path(project.path)
        except:
            return ""

    def _online_key(self, application_path):
        return self._current_project_path() + "::" + self._normalize_path(application_path)

    def get_project(self):
        project = None
        try:
            project = scriptengine.projects.primary
        except:
            project = None

        if project is None:
            project = self.active_project

        if project is not None and project is not self.active_project:
            old_path = self._current_project_path()
            new_path = ""
            try:
                new_path = self._normalize_path(project.path)
            except:
                new_path = ""
            if self.active_project is not None and old_path and new_path and old_path != new_path:
                self.log("Project object changed; clearing cached online handles")
                self.dispose_all_online_applications(False)
                self.unregister_all_trusts_certificate()
            self.active_project = project

        return project

    def find_application(self, wanted_path):
        project = self.get_project()
        if project is None:
            raise Exception("No active project in session")

        applications = []
        stack = []
        for child in project.get_children():
            stack.append((child, ""))

        while stack:
            obj, parent_path = stack.pop(0)
            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)
            path = name if not parent_path else parent_path + "/" + name
            is_application = hasattr(obj, 'create_boot_application') and hasattr(obj, 'build')
            if is_application:
                applications.append((obj, {"name": name, "path": path}))
            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        normalized_wanted_path = self._normalize_path(wanted_path)
        if normalized_wanted_path:
            matches = []
            for obj, entry in applications:
                entry_path = self._normalize_path(entry["path"])
                entry_name = self._normalize_path(entry["name"])
                if entry_path == normalized_wanted_path or entry_name == normalized_wanted_path:
                    matches.append((obj, entry))
            if len(matches) == 1:
                return matches[0][0], matches[0][1], applications
            if len(matches) > 1:
                raise Exception("Application path is ambiguous: " + normalized_wanted_path)
            raise Exception("Application not found: " + normalized_wanted_path)

        if len(applications) == 1:
            return applications[0][0], applications[0][1], applications

        raise Exception("applicationPath required; found " + str(len(applications)) + " applications")

    def find_object_by_path(self, wanted_path):
        project = self.get_project()
        if project is None:
            raise Exception("No active project in session")

        normalized_wanted_path = self._normalize_path(wanted_path)
        if not normalized_wanted_path:
            raise Exception("Object path is required")

        stack = []
        for child in project.get_children():
            stack.append((child, ""))

        while stack:
            obj, parent_path = stack.pop(0)
            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)
            path = name if not parent_path else parent_path + "/" + name
            if self._normalize_path(path) == normalized_wanted_path:
                return obj, {"name": name, "path": path}
            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        raise Exception("Object not found: " + normalized_wanted_path)

    def _dispose_online_entry(self, key, logout_first):
        entry = self.online_apps.get(key)
        if entry is None:
            return False

        online_app = entry.get("online_app")
        if online_app is not None:
            if logout_first:
                try:
                    online_app.logout()
                except Exception, logout_error:
                    self.log("Error logging out online app %s: %s" % (key, str(logout_error)))
            try:
                online_app.Dispose()
            except Exception, dispose_error:
                self.log("Error disposing online app %s: %s" % (key, str(dispose_error)))

        try:
            del self.online_apps[key]
        except:
            pass
        return True

    def unregister_all_trusts_certificate(self):
        try:
            scriptengine.online.unregister_all_trusts_certificate()
        except Exception, unregister_error:
            self.log("Error unregistering certificate trust callbacks: %s" % str(unregister_error))
        self.trust_certificate_callbacks = {}

    def register_trusts_certificate_for_device(self, device_path, current_node_name=None):
        obj, info = self.find_object_by_path(device_path)
        key = self._current_project_path() + "::" + self._normalize_path(info["path"]) + "::" + self._safe_text(current_node_name)
        existing = self.trust_certificate_callbacks.get(key)
        if existing is not None:
            return {
                "registered": True,
                "cached": True,
                "device": info,
                "nodeName": self._safe_text(current_node_name)
            }

        session_ref = self
        device_path_text = info["path"]
        node_name_text = self._safe_text(current_node_name)

        def trusts_certificate(certificate, chain, node_name):
            try:
                details = []
                try:
                    details.append("subject=" + session_ref._safe_text(certificate.Subject))
                except:
                    pass
                try:
                    details.append("thumbprint=" + session_ref._safe_text(certificate.Thumbprint))
                except:
                    pass
                try:
                    details.append("notAfter=" + session_ref._safe_text(certificate.NotAfter))
                except:
                    pass
                details.append("node=" + session_ref._safe_text(node_name))
                session_ref.log("Trusting PLC certificate for %s (%s)" % (device_path_text, ", ".join(details)))
            except:
                pass
            return True

        scriptengine.online.register_trusts_certificate(obj, trusts_certificate, current_node_name)
        self.trust_certificate_callbacks[key] = {
            "device_path": info["path"],
            "callback": trusts_certificate,
            "current_node_name": current_node_name
        }
        return {
            "registered": True,
            "cached": False,
            "device": info,
            "nodeName": self._safe_text(current_node_name)
        }

    def register_trusts_certificate_for_application(self, application_path):
        application, application_info, applications = self.find_application(application_path)
        application_segments = self._normalize_path(application_info["path"]).split("/")
        if len(application_segments) == 0 or not application_segments[0]:
            raise Exception("Unable to derive root device from application path: " + application_info["path"])
        root_device_path = application_segments[0]
        return self.register_trusts_certificate_for_device(root_device_path, None)

    def dispose_online_application(self, application_path, logout_first):
        key = self._online_key(application_path)
        return self._dispose_online_entry(key, logout_first)

    def dispose_all_online_applications(self, logout_first):
        keys = self.online_apps.keys()
        for key in keys:
            self._dispose_online_entry(key, logout_first)

    def _is_online_app_alive(self, online_app):
        try:
            bool(online_app.is_logged_in)
            self._safe_text(online_app.application_state)
            self._safe_text(online_app.operation_state)
            return True
        except:
            return False

    def get_cached_online_application(self, application_path):
        key = self._online_key(application_path)
        entry = self.online_apps.get(key)
        if entry is None:
            return None

        online_app = entry.get("online_app")
        if online_app is None:
            try:
                del self.online_apps[key]
            except:
                pass
            return None

        if not self._is_online_app_alive(online_app):
            self.log("Cached online app is no longer valid for %s; disposing it" % key)
            self._dispose_online_entry(key, False)
            return None

        return online_app

    def ensure_online_application(self, application_path, login_requested):
        normalized_application_path = self._normalize_path(application_path)
        application, application_info, applications = self.find_application(normalized_application_path)
        key = self._online_key(application_info["path"])
        online_app = self.get_cached_online_application(application_info["path"])

        if online_app is None:
            self.log("Creating cached online application for %s" % application_info["path"])
            online_app = scriptengine.online.create_online_application(application)
            self.online_apps[key] = {
                "application_path": application_info["path"],
                "application_name": application_info["name"],
                "project_path": self._current_project_path(),
                "online_app": online_app
            }

        if login_requested:
            try:
                is_logged_in = bool(online_app.is_logged_in)
            except:
                is_logged_in = False

            if not is_logged_in:
                from scriptengine import OnlineChangeOption
                self.log("Logging into cached online application for %s" % application_info["path"])
                online_app.login(OnlineChangeOption.Keep, False)

        return online_app

    def get_online_application_state(self, application_path):
        normalized_application_path = self._normalize_path(application_path)
        application, application_info, applications = self.find_application(normalized_application_path)
        online_app = self.get_cached_online_application(application_info["path"])

        state = {
            "cached": online_app is not None,
            "isLoggedIn": False,
            "applicationState": "",
            "operationState": ""
        }

        if online_app is not None:
            try:
                state["isLoggedIn"] = bool(online_app.is_logged_in)
            except:
                state["isLoggedIn"] = False
            try:
                state["applicationState"] = self._safe_text(online_app.application_state)
            except:
                pass
            try:
                state["operationState"] = self._safe_text(online_app.operation_state)
            except:
                pass

        return {
            "application": application_info,
            "availableApplications": [entry for obj, entry in applications],
            "online": state
        }
        
    def initialize(self):
        """Initialize the CODESYS environment."""
        try:
            # Log initialization with more details
            self.log("Initializing CODESYS session - started")
            self.log("Python version: " + sys.version)
            self.log("IronPython: " + str(IRONPYTHON))
            self.log("Script directory: " + SCRIPT_DIR)
            self.log("Request directory: " + REQUEST_DIR)
            self.log("Result directory: " + RESULT_DIR)
            
            # Write early status file to indicate script has started
            try:
                with open(STATUS_FILE, 'w') as f:
                    f.write(json.dumps({
                        "state": "starting",
                        "timestamp": time.time()
                    }))
                self.log("Created early status file")
            except Exception, e:
                self.log("Warning: Could not create early status file: " + str(e))
            
            # Check if directories exist and are accessible
            for directory in [REQUEST_DIR, RESULT_DIR]:
                if not os.path.exists(directory):
                    self.log("Creating directory: " + directory)
                    os.makedirs(directory)
                else:
                    self.log("Directory exists: " + directory)

            # Test if scriptengine module is available
            if 'scriptengine' not in sys.modules:
                self.log("WARNING: scriptengine module not properly imported")
                self.log("Available modules: " + str(sys.modules.keys()))
            else:
                self.log("ScriptEngine module loaded successfully")
                if hasattr(scriptengine, 'version'):
                    self.log("ScriptEngine version: " + str(scriptengine.version))
            
            # Try loading scriptengine directly to see if it's a module import issue
            try:
                import_result = __import__('scriptengine')
                self.log("Direct import result: " + str(import_result))
                if hasattr(import_result, 'ScriptSystem'):
                    self.log("ScriptSystem class exists in direct import")
                else:
                    self.log("ScriptSystem class NOT found in direct import")
            except:
                error_type, error_value, error_traceback = sys.exc_info()
                self.log("Error directly importing scriptengine: " + str(error_value))
                
            # Initialize the system with retries
            self.system = None
            max_attempts = 3
            
            for attempt in range(max_attempts):
                try:
                    self.log("Getting global scriptengine.system instance (attempt %d of %d)..." % (attempt+1, max_attempts))
                    # Use the global system instance provided by scriptengine
                    self.system = scriptengine.system
                    self.log("Global system instance accessed successfully")
                    
                    # Test system properties
                    if hasattr(self.system, 'version'):
                        self.log("CODESYS version: " + str(self.system.version))
                    elif hasattr(self.system, 'get_version'):
                        self.log("CODESYS version (via method): " + str(self.system.get_version()))
                    else:
                        self.log("System instance accessed but version information not available")
                        
                    # Basic test of system functionality - check if scriptengine.projects is available 
                    if 'projects' in dir(scriptengine):
                        project_count = len(scriptengine.projects) if hasattr(scriptengine.projects, '__len__') else "unknown"
                        self.log("Projects available via global scriptengine.projects: " + str(project_count))
                        # Success - no need for more attempts
                        break
                    else:
                        self.log("Global scriptengine.projects not available, which is unusual")
                        # Try again
                        self.system = None
                        
                except AttributeError, ae:
                    self.log("AttributeError in system initialization (attempt %d): %s" % (attempt+1, str(ae)))
                    self.log("This usually means scriptengine module is not fully loaded or initialized")
                    # Continue with retry
                    self.system = None
                except Exception, e:
                    self.log("Error creating ScriptSystem (attempt %d): %s" % (attempt+1, str(e)))
                    self.log(traceback.format_exc())
                    # Continue with retry
                    self.system = None
                    
                # Wait briefly before retry
                if attempt < max_attempts - 1:
                    self.log("Waiting before retry...")
                    time.sleep(1)
            
            # Create initial status file - mark as initialized even if system creation failed
            # since the primary requirement is that CODESYS is visible
            self.log("Creating status file...")
            self.update_status({
                "state": "initialized",  # Always use 'initialized' instead of 'error'
                "timestamp": time.time(),
                "project": None,
                "system_available": self.system is not None
            })
            
            self.init_success = True
            if self.system is not None:
                self.log("Initialization successful with working system")
            else:
                self.log("Initialization completed with visible CODESYS but non-functional system")
            return True
        except Exception, e:
            self.log("Initialization failed: %s" % str(e))
            self.log(traceback.format_exc())
            
            # Try to write error to status file - but still use 'initialized' state
            # to avoid breaking the API when CODESYS is at least visible
            try:
                self.update_status({
                    "state": "initialized",  # Use 'initialized' instead of 'error'
                    "timestamp": time.time(),
                    "system_available": False,
                    "error": str(e)
                })
            except:
                pass
                
            return False
            
    def run(self):
        """Run the persistent session."""
        if not self.init_success:
            self.log("Cannot run - initialization failed")
            return False

        # Main loop
        try:
            self.log("Entering main loop")
            self.log("Processing requests on the main thread to avoid STA/OLE UI access issues")

            while self.running:
                # Check for termination signal
                if os.path.exists(TERMINATION_SIGNAL_FILE):
                    self.log("Termination signal detected")
                    self.running = False
                    try:
                        os.remove(TERMINATION_SIGNAL_FILE)
                    except:
                        pass
                    break

                # Execute any pending requests on the main thread.
                self.process_pending_requests()

                # Perform periodic tasks
                self.periodic_tasks()

                # Sleep to prevent CPU hogging
                time.sleep(0.1)
                
            self.log("Exiting main loop")
            return True
        except Exception, e:
            self.log("Error in main loop: %s" % str(e))
            self.log(traceback.format_exc())
            return False
        finally:
            # Cleanup
            self.cleanup()

    def process_pending_requests(self):
        """Process all queued request files once on the current thread."""
        try:
            request_files = []
            for filename in os.listdir(REQUEST_DIR):
                if filename.endswith(".request"):
                    request_files.append(filename)
            request_files.sort()

            for filename in request_files:
                request_path = os.path.join(REQUEST_DIR, filename)

                # Process request
                self.process_request(request_path)

                # Remove request file
                try:
                    os.remove(request_path)
                except:
                    pass
        except Exception, e:
            self.log("Error processing requests: %s" % str(e))
            self.log(traceback.format_exc())
            
    def process_request(self, request_path):
        """Process a single request."""
        result_path = None
        script_path = None
        request_id = "unknown"
        
        try:
            # Read request
            with open(request_path, 'r') as f:
                request_content = f.read()
                self.log("Request content: %s" % request_content[:200])
                request = json.loads(request_content)
                
            # Get script path and result path
            script_path = request.get("script_path")
            result_path = request.get("result_path")
            request_id = request.get("request_id", "unknown")
            
            if not script_path or not result_path:
                raise ValueError("Invalid request - missing script_path or result_path")
                
            # Log request with more details
            self.log("Processing request ID: %s" % request_id)
            self.log("Script path: %s" % script_path)
            self.log("Result path: %s" % result_path)
            
            # Check if script file exists
            if not os.path.exists(script_path):
                self.log("Script file not found at: %s" % script_path)
                self.log("Current directory: %s" % os.getcwd())
                
                # Try to list parent directory
                try:
                    parent_dir = os.path.dirname(script_path)
                    if os.path.exists(parent_dir):
                        self.log("Parent directory exists, contents: %s" % str(os.listdir(parent_dir)))
                    else:
                        self.log("Parent directory does not exist: %s" % parent_dir)
                except Exception, dir_e:
                    self.log("Error listing parent directory: %s" % str(dir_e))
                
                raise IOError("Script file not found: %s" % script_path)
                
            # Log script size
            try:
                script_size = os.path.getsize(script_path)
                self.log("Script file size: %d bytes" % script_size)
            except Exception, size_e:
                self.log("Could not get script file size: %s" % str(size_e))
                
            # Execute script
            self.log("Starting script execution...")
            result = self.execute_script(script_path)
            self.log("Script execution completed")
            
            # Add request_id to result for tracing
            if isinstance(result, dict):
                result["request_id"] = request_id
            
            # Write result - create directory if needed
            result_dir = os.path.dirname(result_path)
            if not os.path.exists(result_dir):
                self.log("Creating result directory: %s" % result_dir)
                os.makedirs(result_dir)
            
            self.log("Writing result to: %s" % result_path)
            with open(result_path, 'w') as f:
                result_json = json.dumps(result)
                f.write(result_json)
                self.log("Result written successfully (%d bytes)" % len(result_json))
                
            # Log completion
            self.log("Request completed: %s" % request_id)
        except Exception, e:
            self.log("Error processing request %s: %s" % (request_id, str(e)))
            self.log(traceback.format_exc())
            
            # Write error result if result_path is available
            if result_path:
                try:
                    # Ensure result directory exists
                    result_dir = os.path.dirname(result_path)
                    if not os.path.exists(result_dir):
                        os.makedirs(result_dir)
                        
                    self.log("Writing error result to: %s" % result_path)
                    with open(result_path, 'w') as f:
                        error_result = {
                            "success": False,
                            "error": str(e),
                            "traceback": traceback.format_exc(),
                            "request_id": request_id,
                            "environment": {
                                "current_dir": os.getcwd(),
                                "script_path": script_path,
                                "script_exists": os.path.exists(script_path) if script_path else False,
                                "python_version": sys.version
                            }
                        }
                        result_json = json.dumps(error_result)
                        f.write(result_json)
                        self.log("Error result written successfully (%d bytes)" % len(result_json))
                except Exception, write_e:
                    self.log("Error writing result file: %s" % str(write_e))
                    self.log(traceback.format_exc())
                    
    def execute_script(self, script_path):
        """Execute a Python script in the CODESYS environment."""
        try:
            # Log execution start
            self.log("Executing script: %s" % script_path)
            
            # Create globals dict with access to the session
            globals_dict = {
                "session": self,
                "system": self.system,
                "active_project": self.active_project,
                "json": json,
                "os": os,
                "time": time,
                "scriptengine": scriptengine,
                "traceback": traceback,
                "sys": sys
            }
            
            # Load script
            self.log("Loading script content...")
            try:
                with open(script_path, 'r') as f:
                    script_code = f.read()
                self.log("Script loaded successfully (%d bytes)" % len(script_code))
                
                # Log first few lines of script for debugging
                first_lines = script_code.split('\n')[:5]
                self.log("Script preview: %s" % '\n'.join(first_lines))
                
            except Exception, load_e:
                self.log("Error loading script: %s" % str(load_e))
                self.log(traceback.format_exc())
                return {
                    "success": False,
                    "error": "Error loading script: %s" % str(load_e),
                    "traceback": traceback.format_exc()
                }
                
            # Execute script
            self.log("Executing script code...")
            local_vars = {}
            try:
                exec(script_code, globals_dict, local_vars)
                self.log("Script execution completed successfully")
            except Exception, exec_e:
                self.log("Error executing script: %s" % str(exec_e))
                self.log(traceback.format_exc())
                return {
                    "success": False,
                    "error": str(exec_e),
                    "traceback": traceback.format_exc(),
                    "execution_failed": True
                }
            
            # Check for result
            self.log("Checking for result variable...")
            if "result" in local_vars:
                self.log("Result variable found")
                result = local_vars["result"]
                
                # Add execution metadata
                if isinstance(result, dict):
                    result["execution_time"] = time.time()
                    result["executed_by"] = "CODESYS PersistentSession"
                
                return result
            else:
                self.log("No result variable found, returning default success")
                return {
                    "success": True, 
                    "message": "Script executed successfully (no result variable)",
                    "execution_time": time.time(),
                    "executed_by": "CODESYS PersistentSession"
                }
        except Exception, e:
            self.log("Unhandled error in execute_script: %s" % str(e))
            self.log(traceback.format_exc())
            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "execution_time": time.time(),
                "executed_by": "CODESYS PersistentSession"
            }
            
    def periodic_tasks(self):
        """Perform periodic tasks."""
        # Update session status
        project_path = None
        if self.active_project:
            try:
                project_path = self.active_project.path
            except:
                project_path = "Unknown"
                
        self.update_status({
            "state": "running",
            "timestamp": time.time(),
            "project": project_path
        })
        
    def cleanup(self):
        """Clean up resources before termination."""
        self.log("Cleaning up session")

        try:
            self.dispose_all_online_applications(True)
        except Exception, dispose_error:
            self.log("Error disposing cached online applications: %s" % str(dispose_error))
        try:
            self.unregister_all_trusts_certificate()
        except Exception, unregister_error:
            self.log("Error during certificate trust cleanup: %s" % str(unregister_error))

        # Close active project
        if self.active_project:
            try:
                self.log("Closing project: %s" % self.active_project.path)
                
                # Save project if dirty
                if self.active_project.dirty:
                    self.active_project.save()
                    
                # Close project
                self.active_project = None
            except Exception, e:
                self.log("Error closing project: %s" % str(e))
                
        # Update status
        self.update_status({
            "state": "terminated",
            "timestamp": time.time(),
            "project": None
        })
        
        self.log("Cleanup complete")
        
    def update_status(self, status):
        """Update session status file."""
        try:
            with open(STATUS_FILE, 'w') as f:
                f.write(json.dumps(status))
        except Exception, e:
            self.log("Error updating status: %s" % str(e))
            
    def log(self, message):
        """Log a message."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        log_message = "[%s] %s\n" % (timestamp, message)
        
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(log_message)
        except:
            # Fall back to stdout if log file is not accessible
            try:
                sys.stdout.write(log_message)
            except:
                pass
            
# Main entry point
if __name__ == "__main__":
    # Create and run session
    session = CodesysPersistentSession()
    
    if session.initialize():
        session.run()
    
    # Exit with appropriate code
    sys.exit(0 if session.init_success else 1)
