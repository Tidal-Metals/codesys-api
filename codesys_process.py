"""CODESYS process lifecycle management."""

import json
import os
import subprocess
import threading
import time

from server_config import (
    CODESYS_PROFILE,
    LOG_FILE,
    SCRIPT_DIR,
    STATUS_FILE,
    TERMINATION_SIGNAL_FILE,
    logger,
)

class CodesysProcessManager:
    """Manages the CODESYS process."""
    
    def __init__(self, codesys_path, script_path):
        self.codesys_path = codesys_path
        self.script_path = script_path
        self.process = None
        self.running = False
        self.lock = threading.Lock()

    def _persistent_session_processes(self):
        """Return running CODESYS processes using this persistent session script."""
        script_name = os.path.basename(self.script_path)
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process | "
                "Where-Object { $_.Name -eq 'CODESYS.exe' -and $_.CommandLine -like '*%s*' } | "
                "Select-Object ProcessId,CreationDate,CommandLine | ConvertTo-Json -Compress"
            ) % script_name,
        ]

        try:
            output = subprocess.check_output(command, stderr=subprocess.DEVNULL, text=True)
        except Exception as e:
            logger.warning("Unable to enumerate CODESYS persistent sessions: %s", str(e))
            return []

        output = output.strip()
        if not output:
            return []

        try:
            parsed = json.loads(output)
        except Exception as e:
            logger.warning("Unable to parse CODESYS process list: %s", str(e))
            return []

        if isinstance(parsed, dict):
            return [parsed]
        if isinstance(parsed, list):
            return parsed
        return []

    def ensure_singleton(self):
        """Ensure only one CODESYS persistent session process is running."""
        processes = self._persistent_session_processes()
        if len(processes) <= 1:
            return processes

        processes.sort(key=lambda proc: str(proc.get("CreationDate", "")))
        keep = processes[0]
        duplicates = processes[1:]
        logger.warning(
            "Detected %d CODESYS persistent sessions; keeping PID %s and stopping duplicates",
            len(processes),
            keep.get("ProcessId"),
        )

        for proc in duplicates:
            pid = proc.get("ProcessId")
            if pid is None:
                continue
            try:
                logger.warning("Stopping duplicate CODESYS persistent session PID %s", pid)
                subprocess.call(
                    ["powershell", "-NoProfile", "-Command", "Stop-Process -Id %s -Force" % int(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                logger.warning("Failed to stop duplicate CODESYS PID %s: %s", pid, str(e))

        remaining = self._persistent_session_processes()
        remaining_pids = set(int(proc.get("ProcessId")) for proc in remaining if proc.get("ProcessId") is not None)
        if self.process is not None and self.process.pid not in remaining_pids:
            self.process = None
        return remaining
        
    def start(self):
        """Start the CODESYS process.
        
        Returns:
            bool: True if process started successfully, False otherwise
        """
        with self.lock:
            try:
                self.ensure_singleton()

                # Check if CODESYS is already running
                if self.is_running():
                    logger.info("CODESYS process already running")
                    return True
                
                # Verify CODESYS executable exists
                if not os.path.exists(self.codesys_path):
                    logger.error("CODESYS executable not found at path: %s", self.codesys_path)
                    return False
                
                # Verify script exists
                if not os.path.exists(self.script_path):
                    logger.error("CODESYS script not found at path: %s", self.script_path)
                    return False
                    
                logger.info("Starting CODESYS process with script: %s", self.script_path)
                
                # Clear any existing termination signal
                if os.path.exists(TERMINATION_SIGNAL_FILE):
                    os.remove(TERMINATION_SIGNAL_FILE)
                
                # Delete any existing status file to ensure we don't detect an old one
                if os.path.exists(STATUS_FILE):
                    try:
                        os.remove(STATUS_FILE)
                        logger.info("Removed existing status file")
                    except Exception as e:
                        logger.warning("Could not remove existing status file: %s", str(e))
                
                # Create logs directory if needed
                log_dir = os.path.dirname(LOG_FILE)
                if log_dir and not os.path.exists(log_dir):
                    os.makedirs(log_dir)
                
                # Start CODESYS with script and proper Python path
                try:
                    # Get ScriptLib directory path for Python imports
                    script_lib_path = os.path.join(SCRIPT_DIR, "ScriptLib")
                    
                    # Set up environment with PYTHONPATH
                    env = os.environ.copy()
                    if "PYTHONPATH" in env:
                        env["PYTHONPATH"] = script_lib_path + os.pathsep + env["PYTHONPATH"]
                    else:
                        env["PYTHONPATH"] = script_lib_path
                    
                    logger.info("Starting CODESYS with PYTHONPATH: %s", env["PYTHONPATH"])
                    # Use the exact command format that worked in pure_test.bat
                    # Construct full command with proper quoting
                    command = f"\"{self.codesys_path}\" --Profile=\"{CODESYS_PROFILE}\" --runscript=\"{self.script_path}\""
                    
                    logger.info("Starting CODESYS with command: %s", command)
                    self.process = subprocess.Popen(
                        command,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=env,
                        shell=True  # Use shell to handle the command as a string
                    )
                except subprocess.SubprocessError as se:
                    logger.error("SubprocessError starting CODESYS: %s", str(se))
                    return False
                except FileNotFoundError:
                    logger.error("CODESYS executable not found. Check the path: %s", self.codesys_path)
                    return False
                
                # Wait for process to be visibly running
                logger.info("Waiting for CODESYS process to start...")
                max_wait = 30  # seconds
                wait_interval = 1
                total_waited = 0
                
                while total_waited < max_wait:
                    time.sleep(wait_interval)
                    total_waited += wait_interval
                    
                    # Check if process is still running
                    if not self.is_running():
                        try:
                            stdout, stderr = self.process.communicate(timeout=1)
                            stderr_text = stderr.decode('utf-8', errors='replace') if stderr else "No error output"
                            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else "No standard output"
                            logger.error("CODESYS process failed to start:\nStderr: %s\nStdout: %s", stderr_text, stdout_text)
                        except Exception as e:
                            logger.error("Error communicating with failed process: %s", str(e))
                        return False
                    
                    # Check if status file exists, indicating the script has started
                    if os.path.exists(STATUS_FILE):
                        logger.info("Status file detected after %.1f seconds", total_waited)
                        break
                    
                    logger.debug("Waiting for CODESYS initialization... (%.1f seconds elapsed)", total_waited)
                
                # Now wait for CODESYS to fully initialize
                # Even if status file exists, we want to wait a bit longer for full initialization
                logger.info("CODESYS process has started. Waiting for full initialization...")
                
                # Additional wait to ensure CODESYS is fully initialized
                additional_wait = 10  # seconds
                logger.info("Waiting additional %d seconds for full initialization...", additional_wait)
                time.sleep(additional_wait)
                
                # Final check if the process is running
                if not self.is_running():
                    logger.error("CODESYS process failed to initialize properly")
                    return False
                    
                # Create a status file if it doesn't exist
                # This is a workaround for when CODESYS starts but doesn't create the status file
                if not os.path.exists(STATUS_FILE):
                    logger.warning("CODESYS started but didn't create status file. Creating a default one.")
                    try:
                        with open(STATUS_FILE, 'w') as f:
                            f.write(json.dumps({
                                "state": "initialized",
                                "timestamp": time.time()
                            }))
                    except Exception as e:
                        logger.error("Error creating default status file: %s", str(e))
                    
                self.running = True
                logger.info("CODESYS process started and fully initialized")
                return True
            except Exception as e:
                logger.error("Error starting CODESYS process: %s", str(e))
                return False
                
    def stop(self):
        """Stop the CODESYS process.
        
        Returns:
            bool: True if process stopped successfully or was not running, False otherwise
        """
        with self.lock:
            if not self.is_running():
                logger.info("CODESYS process not running")
                return True
                
            try:
                logger.info("Stopping CODESYS process")
                
                # Signal termination through file
                try:
                    with open(TERMINATION_SIGNAL_FILE, 'w') as f:
                        f.write("TERMINATE")
                    logger.debug("Created termination signal file")
                except Exception as e:
                    logger.warning("Could not create termination signal file: %s", str(e))
                    # Continue with process termination anyway
                    
                # Wait for process to terminate gracefully
                max_wait = 10  # seconds
                wait_interval = 0.5
                waited = 0
                
                while waited < max_wait:
                    if not self.is_running():
                        break
                    time.sleep(wait_interval)
                    waited += wait_interval
                
                # Force termination if still running
                if self.is_running():
                    logger.info("Process still running after %s seconds, sending TERMINATE signal", waited)
                    try:
                        if self.process is not None:
                            self.process.terminate()
                        else:
                            for proc in self._persistent_session_processes():
                                pid = proc.get("ProcessId")
                                if pid is not None:
                                    subprocess.call(
                                        ["powershell", "-NoProfile", "-Command", "Stop-Process -Id %s -Force" % int(pid)],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                    )
                    except Exception as e:
                        logger.warning("Error terminating process: %s", str(e))
                        
                    # Wait again for termination
                    time.sleep(2)
                    
                    # Kill if still running
                    if self.is_running():
                        logger.warning("Process still running after TERMINATE signal, sending KILL signal")
                        try:
                            if self.process is not None:
                                self.process.kill()
                            else:
                                for proc in self._persistent_session_processes():
                                    pid = proc.get("ProcessId")
                                    if pid is not None:
                                        subprocess.call(
                                            ["powershell", "-NoProfile", "-Command", "Stop-Process -Id %s -Force" % int(pid)],
                                            stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL,
                                        )
                        except Exception as e:
                            logger.error("Error killing process: %s", str(e))
                            return False
                
                # Clean up
                self.process = None
                self.running = False
                
                # Remove termination signal file if it exists
                if os.path.exists(TERMINATION_SIGNAL_FILE):
                    try:
                        os.remove(TERMINATION_SIGNAL_FILE)
                    except Exception as e:
                        logger.warning("Could not remove termination signal file: %s", str(e))
                
                logger.info("CODESYS process stopped successfully")
                return True
            except Exception as e:
                logger.error("Error stopping CODESYS process: %s", str(e))
                return False
                
    def is_running(self):
        """Check if CODESYS process is running."""
        if self.process is None:
            return len(self._persistent_session_processes()) > 0

        if self.process.poll() is not None:
            self.process = None
            return len(self._persistent_session_processes()) > 0
            
        return self.process.poll() is None
        
    def get_status(self):
        """Get CODESYS session status."""
        try:
            if not os.path.exists(STATUS_FILE):
                return {"state": "unknown", "timestamp": time.time()}
                
            with open(STATUS_FILE, 'r') as f:
                return json.loads(f.read())
        except Exception as e:
            logger.error("Error getting CODESYS status: %s", str(e))
            return {"state": "error", "timestamp": time.time(), "error": str(e)}
