"""
Modbus REST API handlers.

Self-contained module that handles all /api/v1/modbus/* routes.
Plugs into the main HTTP server via register_routes().
"""

import re
import logging
import os
import tempfile
import uuid
from urllib.parse import unquote

import modbus_scripts
from modbus_native_export_generator import generate_modbus_slave_export

logger = logging.getLogger('codesys_api_server.modbus')


def _param(params, camel_key, snake_key=None, default=None):
    """Read REST params accepting both canonical camelCase and snake_case aliases."""
    if camel_key in params:
        return params[camel_key]
    if snake_key and snake_key in params:
        return params[snake_key]
    return default

# Route table: (method, regex_pattern, handler_name)
ROUTES = [
    # Devices
    ("GET",    r"api/v1/modbus/devices$",                                       "list_devices"),
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)$",                     "get_device"),
    ("POST",   r"api/v1/modbus/devices$",                                       "create_device"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)$",                     "delete_device"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)$",                     "update_device"),

    # Channels
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels$",            "list_channels"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/channels$",            "create_channel"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",       "create_channels_bulk"),
    ("PUT",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",       "update_channels_bulk"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",       "update_channels_bulk"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)$", "delete_channel"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)$", "update_channel"),

    # IO Mapping
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "get_mapping"),
    ("PUT",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "set_mapping"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "clear_mapping"),

    # COM / Master
    ("GET",    r"api/v1/modbus/com/(?P<device>[^/]+)$",                         "get_com"),
    ("GET",    r"api/v1/modbus/master/(?P<device>[^/]+)$",                      "get_master"),

    # Utilities
    ("POST",   r"api/v1/modbus/save$",                                          "save_project"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/export-io$",           "export_io"),
]

# Compile patterns once
_COMPILED_ROUTES = [(method, re.compile(pattern), handler) for method, pattern, handler in ROUTES]


def match_route(method, path):
    """Match a request method+path against registered routes.

    Returns (handler_name, matched_groups_dict) or (None, None).
    """
    for route_method, pattern, handler in _COMPILED_ROUTES:
        if method != route_method:
            continue
        m = pattern.match(path)
        if m:
            return handler, {key: unquote(value) for key, value in m.groupdict().items()}
    return None, None


class ModbusHandler:
    """Handles Modbus API requests by generating and executing IronPython scripts."""

    def __init__(self, script_executor):
        self.executor = script_executor

    def _exec(self, script, timeout=120):
        return self.executor.execute_script(script, timeout=timeout)

    # ── Devices ──────────────────────────────────────────────────────────

    def list_devices(self, params, groups):
        script = modbus_scripts.list_device_tree()
        return self._exec(script)

    def get_device(self, params, groups):
        script = modbus_scripts.get_device(groups["device"])
        return self._exec(script)

    def create_device(self, params, groups):
        required = ["masterPath", "name"]
        for key in required:
            if key not in params:
                return {"success": False, "error": f"Missing required parameter: {key}"}

        script = modbus_scripts.create_device(
            master_path=params["masterPath"],
            device_name=params["name"],
            slave_address=params.get("slaveAddress", 1),
            device_type=params.get("deviceType", 91),
            device_id=params.get("deviceId", "0000 0001"),
            device_version=params.get("deviceVersion", "4.5.0.0"),
        )
        return self._exec(script, timeout=180)

    def delete_device(self, params, groups):
        script = modbus_scripts.delete_device(groups["device"])
        return self._exec(script)

    def update_device(self, params, groups):
        script = modbus_scripts.update_device(
            device_name=groups["device"],
            slave_address=params.get("slaveAddress"),
            response_timeout=params.get("responseTimeout"),
        )
        return self._exec(script)

    # ── Channels ─────────────────────────────────────────────────────────

    def list_channels(self, params, groups):
        script = modbus_scripts.list_channels(groups["device"])
        return self._exec(script)

    def create_channel(self, params, groups):
        if "name" not in params:
            return {"success": False, "error": "Missing required parameter: name"}

        script = modbus_scripts.create_channel(
            device_name=groups["device"],
            channel_name=params["name"],
            access_type=_param(params, "accessType", "access_type", 3),
            read_offset=_param(params, "readOffset", "read_offset", "16#0000"),
            read_length=_param(params, "readLength", "read_length", 1),
            write_offset=_param(params, "writeOffset", "write_offset", "0"),
            write_length=_param(params, "writeLength", "write_length", "0"),
            trigger=_param(params, "trigger", default=5),
            cycle_time=_param(params, "cycleTime", "cycle_time", 100),
            error_handling=_param(params, "errorHandling", "error_handling", "true"),
            comment=_param(params, "comment", default=""),
        )
        return self._exec(script, timeout=180)

    def create_channels_bulk(self, params, groups):
        if "channels" not in params:
            return {"success": False, "error": "Missing required parameter: channels"}

        mode = str(params.get("mode", params.get("strategy", "native"))).lower()
        if mode in ("native", "export", "import_native"):
            return self._create_channels_bulk_native(params, groups)

        script = modbus_scripts.create_channels_bulk(
            device_name=groups["device"],
            channels=params["channels"],
        )
        return self._exec(script, timeout=300)

    def _create_channels_bulk_native(self, params, groups):
        master_path = params.get("masterPath") or params.get("master_path")
        if not master_path:
            return {"success": False, "error": "Missing required parameter for native mode: masterPath"}

        device_name = groups["device"]
        output_path = os.path.join(
            tempfile.gettempdir(),
            "codesys_modbus_{0}.export".format(uuid.uuid4()),
        )
        try:
            generated = generate_modbus_slave_export(
                device_name=device_name,
                slave_address=params.get("slaveAddress", params.get("slave_address", 1)),
                channels=params["channels"],
                output_path=output_path,
            )
        except Exception as e:
            return {"success": False, "error": "Failed to generate native export: {0}".format(str(e))}

        script = modbus_scripts.import_native_device(
            master_path=master_path,
            export_path=output_path,
            device_name=device_name,
            replace=params.get("replace", False),
        )
        result = self._exec(script, timeout=180)
        result["generatedExport"] = generated
        return result

    def update_channels_bulk(self, params, groups):
        if "channels" not in params:
            return {"success": False, "error": "Missing required parameter: channels"}

        script = modbus_scripts.update_channels_bulk(
            device_name=groups["device"],
            channels=params["channels"],
        )
        return self._exec(script, timeout=120)

    def delete_channel(self, params, groups):
        script = modbus_scripts.delete_channel(groups["device"], groups["channel"])
        return self._exec(script)

    def update_channel(self, params, groups):
        kwargs = {}
        for key, alias in (
            ("accessType", "access_type"),
            ("readOffset", "read_offset"),
            ("readLength", "read_length"),
            ("writeOffset", "write_offset"),
            ("writeLength", "write_length"),
            ("trigger", None),
            ("cycleTime", "cycle_time"),
            ("errorHandling", "error_handling"),
            ("comment", None),
        ):
            if key in params or (alias and alias in params):
                kwargs[key] = _param(params, key, alias)

        if not kwargs:
            return {"success": False, "error": "No fields to update"}

        script = modbus_scripts.update_channel(
            device_name=groups["device"],
            channel_name=groups["channel"],
            **kwargs,
        )
        return self._exec(script)

    # ── IO Mapping ───────────────────────────────────────────────────────

    def get_mapping(self, params, groups):
        script = modbus_scripts.get_mapping(groups["device"], groups["channel"])
        return self._exec(script)

    def set_mapping(self, params, groups):
        if "variable" not in params:
            return {"success": False, "error": "Missing required parameter: variable"}

        script = modbus_scripts.set_mapping(
            device_name=groups["device"],
            channel_name=groups["channel"],
            variable=params["variable"],
            create_variable=params.get("createVariable", True),
        )
        return self._exec(script)

    def clear_mapping(self, params, groups):
        script = modbus_scripts.clear_mapping(groups["device"], groups["channel"])
        return self._exec(script)

    # ── COM / Master ─────────────────────────────────────────────────────

    def get_com(self, params, groups):
        script = modbus_scripts.get_com_params(groups["device"])
        return self._exec(script)

    def get_master(self, params, groups):
        script = modbus_scripts.get_master_params(groups["device"])
        return self._exec(script)

    # ── Utilities ────────────────────────────────────────────────────────

    def save_project(self, params, groups):
        script = modbus_scripts.save_project()
        return self._exec(script)

    def export_io(self, params, groups):
        if "filePath" not in params:
            return {"success": False, "error": "Missing required parameter: filePath"}

        script = modbus_scripts.export_io_csv(groups["device"], params["filePath"])
        return self._exec(script)

    def dispatch(self, handler_name, params, groups):
        """Dispatch to the named handler method."""
        method = getattr(self, handler_name, None)
        if method is None:
            return {"success": False, "error": f"Unknown handler: {handler_name}"}
        return method(params, groups)
