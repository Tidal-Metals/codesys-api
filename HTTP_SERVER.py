#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CODESYS API HTTP server entry point."""

from functools import partial

try:
    from http.server import HTTPServer
except ImportError:
    from BaseHTTPServer import HTTPServer

from api_handler import CodesysApiHandler
from auth import ApiKeyManager
from codesys_process import CodesysProcessManager
from script_executor import ScriptExecutor
from script_generator import ScriptGenerator
from server_config import (
    API_KEY_FILE,
    CODESYS_PATH,
    PERSISTENT_SCRIPT,
    REQUEST_DIR,
    RESULT_DIR,
    SERVER_HOST,
    SERVER_PORT,
    initialize_directories,
    logger,
)


def create_handler(process_manager, script_executor, script_generator, api_key_manager):
    return partial(
        CodesysApiHandler,
        process_manager=process_manager,
        script_executor=script_executor,
        script_generator=script_generator,
        api_key_manager=api_key_manager,
    )


def run_server():
    """Run the HTTP server."""
    initialize_directories()
    process_manager = CodesysProcessManager(CODESYS_PATH, PERSISTENT_SCRIPT)
    process_manager.ensure_singleton()
    script_executor = ScriptExecutor(REQUEST_DIR, RESULT_DIR)
    script_generator = ScriptGenerator()
    api_key_manager = ApiKeyManager(API_KEY_FILE)

    try:
        handler = create_handler(process_manager, script_executor, script_generator, api_key_manager)
        server = HTTPServer((SERVER_HOST, SERVER_PORT), handler)
        print("Starting server on {0}:{1}".format(SERVER_HOST, SERVER_PORT))
        logger.info("Starting server on %s:%d", SERVER_HOST, SERVER_PORT)
        server.serve_forever()
    except KeyboardInterrupt:
        print("Server stopped")
    except Exception as e:
        print("Error starting server: " + str(e))
        logger.error("Error starting server: %s", str(e))
    finally:
        process_manager.stop()


if __name__ == "__main__":
    run_server()
