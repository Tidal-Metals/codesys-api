"""HTTP request routing for the CODESYS API server."""

import json
import logging
import sys

from api_plc_handlers import PlcHandlersMixin
from api_pou_handlers import PouHandlersMixin
from api_project_handlers import ProjectHandlersMixin
from api_session_handlers import SessionHandlersMixin
from api_system_handlers import SystemHandlersMixin
from modbus_handlers import ModbusHandler, match_route as modbus_match
from openapi import load_openapi_schema, swagger_ui_html

try:
    from http.server import BaseHTTPRequestHandler
    import urllib.parse as urlparse
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler
    import urlparse

logger = logging.getLogger('codesys_api_server')


class CodesysApiHandler(
    SessionHandlersMixin,
    ProjectHandlersMixin,
    PouHandlersMixin,
    PlcHandlersMixin,
    SystemHandlersMixin,
    BaseHTTPRequestHandler,
):
    """HTTP request handler for CODESYS API."""
    
    server_version = "CodesysApiServer/0.1"
    
    def __init__(self, *args, **kwargs):
        self.process_manager = kwargs.pop('process_manager', None)
        self.script_executor = kwargs.pop('script_executor', None)
        self.script_generator = kwargs.pop('script_generator', None)
        self.api_key_manager = kwargs.pop('api_key_manager', None)
        self.modbus = ModbusHandler(self.script_executor)
        BaseHTTPRequestHandler.__init__(self, *args, **kwargs)

    def try_modbus_route(self, method, path, params):
        """Try to match and handle a modbus route. Returns True if handled."""
        handler_name, groups = modbus_match(method, path)
        if handler_name is None:
            return False
        result = self.modbus.dispatch(handler_name, params, groups)
        self.send_json_response(result)
        return True
        
    def do_GET(self):
        """Handle GET requests."""
        try:
            # Parse URL
            parsed_url = urlparse.urlparse(self.path)
            path = parsed_url.path.strip('/')
            query = urlparse.parse_qs(parsed_url.query)
            
            # Single-value query params
            params = {}
            for key, values in query.items():
                if values:
                    params[key] = values[0]

            # Public documentation routes
            if path in ("openapi.json", "api/docs/openapi.json"):
                self.send_json_response(load_openapi_schema())
                return
            if path in ("docs", "api/docs"):
                self.send_html_response(swagger_ui_html())
                return
                    
            # Check authentication
            if not self.authenticate():
                self.send_error(401, "Unauthorized")
                return
                
            # Route request
            if path == "api/v1/session/status":
                self.handle_session_status()
            elif path == "api/v1/project/list":
                self.handle_project_list()
            elif path == "api/v1/pou/list":
                self.handle_pou_list(params)
            elif path == "api/v1/pou/code":
                self.handle_pou_code_get(params)
            elif path == "api/v1/plc/targets":
                self.handle_plc_targets(params)
            elif path == "api/v1/plc/gateways":
                self.handle_plc_gateways(params)
            elif path == "api/v1/plc/bindings":
                self.handle_plc_bindings(params)
            elif path == "api/v1/system/info":
                self.handle_system_info()
            elif path == "api/v1/system/logs":
                self.handle_system_logs()
            elif not self.try_modbus_route("GET", path, params):
                self.send_error(404, "Not Found")
        except ConnectionAbortedError as e:
            logger.warning("Connection aborted during GET request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except BrokenPipeError as e:
            logger.warning("Broken pipe during GET request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except ConnectionResetError as e:
            logger.warning("Connection reset during GET request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except Exception as e:
            logger.error("Error handling GET request: %s", str(e))
            try:
                self.send_error(500, str(e))
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                # Connection already closed, can't send error
                pass
            
    def do_POST(self):
        """Handle POST requests."""
        try:
            # Parse URL
            parsed_url = urlparse.urlparse(self.path)
            path = parsed_url.path.strip('/')
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            
            # Python 3 compatibility for reading binary data
            if sys.version_info[0] >= 3:
                post_data = self.rfile.read(content_length).decode('utf-8')
            else:
                post_data = self.rfile.read(content_length)
            
            params = {}
            if content_length > 0:
                params = json.loads(post_data)
                
            # Check authentication
            if not self.authenticate():
                self.send_error(401, "Unauthorized")
                return
                
            # Route request
            if path == "api/v1/session/start":
                self.handle_session_start()
            elif path == "api/v1/session/stop":
                self.handle_session_stop()
            elif path == "api/v1/session/restart":
                self.handle_session_restart()
            elif path == "api/v1/project/create":
                self.handle_project_create(params)
            elif path == "api/v1/project/open":
                self.handle_project_open(params)
            elif path == "api/v1/project/save":
                self.handle_project_save()
            elif path == "api/v1/project/close":
                self.handle_project_close()
            elif path == "api/v1/project/compile":
                self.handle_project_compile(params)
            elif path == "api/v1/pou/create":
                self.handle_pou_create(params)
            elif path == "api/v1/pou/code":
                self.handle_pou_code(params)
            elif path == "api/v1/plc/validate-deploy":
                self.handle_plc_validate_deploy(params)
            elif path == "api/v1/plc/scan":
                self.handle_plc_scan(params)
            elif path == "api/v1/plc/status":
                self.handle_plc_status(params)
            elif path == "api/v1/plc/bind-ip":
                self.handle_plc_bind_ip(params)
            elif path == "api/v1/script/execute":
                self.handle_script_execute(params)
            elif not self.try_modbus_route("POST", path, params):
                self.send_error(404, "Not Found")
        except ConnectionAbortedError as e:
            logger.warning("Connection aborted during POST request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except BrokenPipeError as e:
            logger.warning("Broken pipe during POST request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except ConnectionResetError as e:
            logger.warning("Connection reset during POST request: %s", str(e))
            # Don't try to send an error response as the connection is already broken
        except Exception as e:
            logger.error("Error handling POST request: %s", str(e))
            try:
                self.send_error(500, str(e))
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                # Connection already closed, can't send error
                pass
            
    def _handle_body_method(self, method):
        """Generic handler for DELETE/PATCH/PUT — parse body, auth, delegate to modbus."""
        try:
            parsed_url = urlparse.urlparse(self.path)
            path = parsed_url.path.strip('/')
            content_length = int(self.headers.get('Content-Length', 0))
            params = {}
            if content_length > 0:
                post_data = self.rfile.read(content_length).decode('utf-8')
                params = json.loads(post_data)

            if not self.authenticate():
                self.send_error(401, "Unauthorized")
                return

            if not self.try_modbus_route(method, path, params):
                self.send_error(404, "Not Found")
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError) as e:
            logger.warning("Connection error during %s request: %s", method, str(e))
        except Exception as e:
            logger.error("Error handling %s request: %s", method, str(e))
            try:
                self.send_error(500, str(e))
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                pass

    def do_DELETE(self):
        self._handle_body_method("DELETE")

    def do_PATCH(self):
        self._handle_body_method("PATCH")

    def do_PUT(self):
        self._handle_body_method("PUT")

    def authenticate(self):
        """Validate API key."""
        auth_header = self.headers.get('Authorization', '')
        
        if auth_header.startswith('ApiKey '):
            api_key = auth_header[7:]  # Remove 'ApiKey ' prefix
            return self.api_key_manager.validate_key(api_key)
            
        return False
        
    def send_json_response(self, data, status=200):
        """Send JSON response."""
        try:
            response = json.dumps(data)
            
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            
            # Python 3 compatibility for content length
            if sys.version_info[0] >= 3:
                self.send_header('Content-Length', len(response.encode('utf-8')))
            else:
                self.send_header('Content-Length', len(response))
                
            self.end_headers()
            
            # Python 3 compatibility for writing binary data
            if sys.version_info[0] >= 3:
                self.wfile.write(response.encode('utf-8'))
            else:
                self.wfile.write(response)
        except ConnectionAbortedError as e:
            logger.warning("Connection aborted while sending response: %s", str(e))
        except BrokenPipeError as e:
            logger.warning("Broken pipe while sending response: %s", str(e))
        except ConnectionResetError as e:
            logger.warning("Connection reset while sending response: %s", str(e))
        except Exception as e:
            logger.error("Error sending JSON response: %s", str(e))

    def send_html_response(self, html, status=200):
        """Send HTML response."""
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            if sys.version_info[0] >= 3:
                self.send_header('Content-Length', len(html.encode('utf-8')))
            else:
                self.send_header('Content-Length', len(html))
            self.end_headers()
            if sys.version_info[0] >= 3:
                self.wfile.write(html.encode('utf-8'))
            else:
                self.wfile.write(html)
        except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError) as e:
            logger.warning("Connection closed while sending HTML response: %s", str(e))
        except Exception as e:
            logger.error("Error sending HTML response: %s", str(e))
        
    # Handler methods
