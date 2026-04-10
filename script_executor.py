"""Filesystem-backed CODESYS persistent-session script executor."""

import json
import os
import tempfile
import time
import traceback
import uuid

from server_config import logger

class ScriptExecutor:
    """Executes scripts through the CODESYS persistent session."""
    
    def __init__(self, request_dir, result_dir):
        self.request_dir = request_dir
        self.result_dir = result_dir
        
    def execute_script(self, script_content, timeout=60):
        """Execute a script and return the result.
        
        Args:
            script_content (str): The script content to execute
            timeout (int): Timeout in seconds (default: 60 seconds)
            
        Returns:
            dict: The result of the script execution
        """
        request_id = str(uuid.uuid4())
        script_path = None
        result_path = None
        request_path = None
        
        try:
            # Log script execution start with more info
            logger.info("Executing script (request ID: %s, timeout: %s seconds)", request_id, timeout)
            script_preview = script_content[:500].replace('\n', ' ')
            logger.info("Script preview: %s...", script_preview)
            
            # Create dedicated directory for this request to avoid path issues
            request_dir = os.path.join(tempfile.gettempdir(), f"codesys_req_{request_id}")
            if not os.path.exists(request_dir):
                os.makedirs(request_dir)
                logger.debug("Created request directory: %s", request_dir)
            
            # Create temporary script file with UTF-8 encoding explicitly
            script_path = os.path.join(request_dir, "script.py")
            try:
                with open(script_path, 'w', encoding='utf-8') as f:
                    f.write(script_content)
                logger.info("Created script file: %s", script_path)
                logger.debug("Script file size: %d bytes", os.path.getsize(script_path))
            except Exception as e:
                logger.error("Failed to write script file: %s", str(e))
                return {"success": False, "error": "Failed to write script file: " + str(e)}
                
            # Create result file path in same dedicated directory
            result_path = os.path.join(request_dir, "result.json")
            
            # Create request file with backslash-escaped paths for Windows
            request_path = os.path.join(self.request_dir, "{0}.request".format(request_id))
            try:
                with open(request_path, 'w', encoding='utf-8') as f:
                    # Use double backslashes for Windows path escaping
                    request_data = {
                        "script_path": script_path.replace("\\", "\\\\"),
                        "result_path": result_path.replace("\\", "\\\\"),
                        "timestamp": time.time(),
                        "request_id": request_id
                    }
                    f.write(json.dumps(request_data))
                logger.info("Created request file: %s", request_path)
                logger.debug("Request data: %s", json.dumps(request_data))
            except Exception as e:
                logger.error("Failed to write request file: %s", str(e))
                return {"success": False, "error": "Failed to write request file: " + str(e)}
                
            # Wait for result with progressive polling
            logger.info("Waiting for script execution to complete (max: %s seconds)...", timeout)
            start_time = time.time()
            check_count = 0
            last_log_time = start_time
            
            # Use progressive polling intervals - start fast, then get slower
            poll_interval = 0.1  # Start with checking every 100ms
            
            while time.time() - start_time < timeout:
                check_count += 1
                
                # Check for result file
                if os.path.exists(result_path):
                    # Log result found
                    elapsed = time.time() - start_time
                    logger.info("Result file found after %.2f seconds (%d checks)", elapsed, check_count)
                    
                    # Read result with retry for potentially incomplete files
                    retry_count = 0
                    max_retries = 5
                    file_size = os.path.getsize(result_path)
                    
                    while retry_count < max_retries:
                        try:
                            # Wait a moment for the file to be fully written
                            time.sleep(0.2)
                            
                            # Check if file size changed
                            new_size = os.path.getsize(result_path)
                            if new_size != file_size:
                                logger.debug("Result file size changed from %d to %d bytes, waiting...", 
                                            file_size, new_size)
                                file_size = new_size
                                retry_count += 1
                                continue
                            
                            with open(result_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                try:
                                    result = json.loads(content)
                                    
                                    # Log result summary
                                    if result.get('success', False):
                                        logger.info("Script execution successful")
                                    else:
                                        error = result.get('error', 'Unknown error')
                                        logger.warning("Script execution failed: %s", error)
                                    
                                    # Cleanup files
                                    self._cleanup_files(script_path, result_path, request_path, request_dir)
                                    
                                    return result
                                except json.JSONDecodeError as je:
                                    logger.warning("Invalid JSON in result file (attempt %d/%d): %s", 
                                                 retry_count+1, max_retries, str(je))
                                    logger.debug("Result file content: %s", content)
                                    
                                    # Try again after a short delay
                                    retry_count += 1
                                    time.sleep(0.5)
                        except Exception as e:
                            logger.warning("Error reading result file (attempt %d/%d): %s", 
                                         retry_count+1, max_retries, str(e))
                            retry_count += 1
                            time.sleep(0.5)
                    
                    # If we get here, we've exhausted retries
                    logger.error("Failed to read valid result after %d retries", max_retries)
                    return {"success": False, "error": f"Failed to read valid result after {max_retries} retries"}
                
                # Periodic status logging
                current_time = time.time()
                if current_time - last_log_time > 10:  # Log every 10 seconds
                    elapsed = current_time - start_time
                    logger.info("Still waiting for script execution (elapsed: %.2f seconds, checks: %d)", 
                               elapsed, check_count)
                    
                    # Log if script and request files still exist
                    if os.path.exists(script_path):
                        logger.debug("Script file still exists (%d bytes)", os.path.getsize(script_path))
                    else:
                        logger.warning("Script file no longer exists!")
                        
                    if os.path.exists(request_path):
                        logger.debug("Request file still exists (%d bytes)", os.path.getsize(request_path))
                    else:
                        logger.warning("Request file no longer exists!")
                    
                    last_log_time = current_time
                            
                # Progressive polling - start fast, then slow down
                current_elapsed = time.time() - start_time
                if current_elapsed < 5:
                    poll_interval = 0.1  # First 5 seconds: check every 100ms
                elif current_elapsed < 30:
                    poll_interval = 0.5  # 5-30 seconds: check every 500ms
                else:
                    poll_interval = 1.0  # After 30 seconds: check every second
                
                time.sleep(poll_interval)
            
            # If we've timed out, don't create a fake success - report the timeout as an error
            logger.error("Script execution timed out after %.2f seconds", time.time() - start_time)
            
            # Create an error result file for future reference
            try:
                with open(result_path, 'w', encoding='utf-8') as f:
                    error_result = {
                        "success": False, 
                        "error": "Script execution timed out after {:.2f} seconds".format(time.time() - start_time),
                        "timeout": True
                    }
                    json.dump(error_result, f)
            except Exception as e:
                logger.error("Error creating timeout result file: %s", str(e))
            
            # Clean up files
            self._cleanup_files(script_path, None, request_path, request_dir)
            
            # Return error response
            return {
                "success": False, 
                "error": "Script execution timed out after {:.2f} seconds".format(time.time() - start_time),
                "timeout": True
            }
            
            # Timeout
            elapsed = time.time() - start_time
            logger.error("Script execution timed out after %.2f seconds (%d checks)", elapsed, check_count)
            
            # Create error result file for reference
            try:
                with open(result_path, 'w', encoding='utf-8') as f:
                    error_result = {
                        "success": False,
                        "error": f"Script execution timed out after {timeout} seconds",
                        "checks": check_count,
                        "request_id": request_id
                    }
                    json.dump(error_result, f)
                logger.debug("Created timeout error result file")
            except Exception as e:
                logger.error("Error creating timeout error result file: %s", str(e))
            
            # Clean up files but keep script for debugging
            self._cleanup_files(None, None, request_path, None)
            logger.info("Kept script file for debugging: %s", script_path)
            
            return {
                "success": False, 
                "error": f"Script execution timed out after {timeout} seconds",
                "script_path": script_path,
                "result_path": result_path,
                "request_id": request_id
            }
        except Exception as e:
            logger.error("Error executing script (request ID: %s): %s", request_id, str(e))
            logger.error(traceback.format_exc())
            # Attempt to clean up files
            if script_path or result_path or request_path:
                self._cleanup_files(script_path, result_path, request_path, request_dir)
            return {"success": False, "error": str(e)}
            
    def _cleanup_files(self, script_path, result_path, request_path, request_dir=None):
        """Clean up temporary files.
        
        Args:
            script_path (str): Path to the script file
            result_path (str): Path to the result file
            request_path (str): Path to the request file
            request_dir (str): Path to the request directory (optional)
        """
        # First clean up individual files
        for path in [script_path, result_path, request_path]:
            if not path:
                continue
                
            try:
                if os.path.exists(path):
                    os.remove(path)
                    logger.debug("Removed temporary file: %s", path)
            except Exception as e:
                logger.warning("Failed to remove temporary file %s: %s", path, str(e))
        
        # Then clean up the request directory if specified
        if request_dir and os.path.exists(request_dir):
            try:
                # Check if directory is empty
                if not os.listdir(request_dir):
                    os.rmdir(request_dir)
                    logger.debug("Removed empty request directory: %s", request_dir)
                else:
                    logger.warning("Request directory not empty, not removing: %s", request_dir)
                    # List files left in directory
                    logger.debug("Files remaining in request directory: %s", os.listdir(request_dir))
            except Exception as e:
                logger.warning("Failed to remove request directory %s: %s", request_dir, str(e))
