"""Configuration and filesystem setup for the CODESYS API server."""

import logging
import os
import tempfile

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='codesys_api_server.log'
)
logger = logging.getLogger('codesys_api_server')

SERVER_HOST = '0.0.0.0'
SERVER_PORT = 8080
CODESYS_PATH = r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe"
CODESYS_PROFILE = "CODESYS V3.5 SP22 Patch 1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PERSISTENT_SCRIPT = os.path.join(SCRIPT_DIR, "PERSISTENT_SESSION.py")
API_KEY_FILE = os.path.join(SCRIPT_DIR, "api_keys.json")
REQUEST_DIR = os.path.join(SCRIPT_DIR, "requests")
RESULT_DIR = os.path.join(SCRIPT_DIR, "results")
TERMINATION_SIGNAL_FILE = os.path.join(SCRIPT_DIR, "terminate.signal")
STATUS_FILE = os.path.join(SCRIPT_DIR, "session_status.json")
LOG_FILE = os.path.join(SCRIPT_DIR, "session.log")


def ensure_directory(path):
    """Ensure directory exists with proper permissions."""
    if not os.path.exists(path):
        try:
            os.makedirs(path)
            logger.info("Created directory: %s", path)
        except Exception as e:
            logger.error("Error creating directory %s: %s", path, str(e))
            raise

    if not os.access(path, os.W_OK):
        logger.error("Directory %s is not writable", path)
        raise PermissionError("Directory {} is not writable".format(path))

    return path


def initialize_directories():
    ensure_directory(REQUEST_DIR)
    ensure_directory(RESULT_DIR)
    ensure_directory(tempfile.gettempdir())
