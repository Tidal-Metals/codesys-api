"""
Modbus REST API handlers.

Thin route/dispatch wrapper around domain-specific Modbus handler mixins.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from modbus_handler_channels import ModbusChannelMixin
from modbus_handler_core import ModbusHandlerCore
from modbus_handler_devices import ModbusDeviceStatusMixin
from modbus_handler_mapping_misc import ModbusMappingMiscMixin


ROUTES = [
    # Devices
    ("GET",    r"api/v1/modbus/devices$",                                        "list_devices"),
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)$",                      "get_device"),
    ("POST",   r"api/v1/modbus/devices$",                                        "create_device"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)$",                      "delete_device"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)$",                      "update_device"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/acknowledge$",          "acknowledge_device"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/acknowledge-subtree$",  "acknowledge_device_subtree"),
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)/status$",               "get_device_status"),
    ("GET",    r"api/v1/modbus/status-map$",                                      "get_status_map"),
    ("GET",    r"api/v1/modbus/topology$",                                        "get_topology"),
    ("GET",    r"api/v1/modbus/status$",                                          "get_bus_status"),
    ("POST",   r"api/v1/modbus/acknowledge-stalled$",                            "acknowledge_stalled"),
    ("GET",    r"api/v1/modbus/simulator/status$",                               "get_simulator_status"),
    ("POST",   r"api/v1/modbus/simulator/apply$",                                "apply_simulator"),

    # Channels
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels$",             "list_channels"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/channels$",             "create_channel"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",        "create_channels_bulk"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/safe-insert$", "safe_insert_channels"),
    ("PUT",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",        "update_channels_bulk"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/bulk$",        "update_channels_bulk"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)$", "delete_channel"),
    ("PATCH",  r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)$", "update_channel"),

    # IO Mapping
    ("GET",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "get_mapping"),
    ("PUT",    r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "set_mapping"),
    ("DELETE", r"api/v1/modbus/devices/(?P<device>[^/]+)/channels/(?P<channel>[^/]+)/mapping$", "clear_mapping"),

    # COM / Master
    ("GET",    r"api/v1/modbus/com/(?P<device>[^/]+)$",                          "get_com"),
    ("PATCH",  r"api/v1/modbus/com/(?P<device>[^/]+)$",                          "update_com"),
    ("GET",    r"api/v1/modbus/master/(?P<device>[^/]+)$",                       "get_master"),
    ("PATCH",  r"api/v1/modbus/master/(?P<device>[^/]+)$",                       "update_master"),

    # Utilities
    ("POST",   r"api/v1/modbus/save$",                                           "save_project"),
    ("POST",   r"api/v1/modbus/devices/(?P<device>[^/]+)/export-io$",            "export_io"),
    ("GET",    r"api/v1/modbus/find-variable$",                                  "find_variable"),
    ("POST",   r"api/v1/modbus/find-variable$",                                  "find_variable"),
    ("GET",    r"api/v1/modbus/validate$",                                       "validate_mappings"),
    ("POST",   r"api/v1/modbus/validate$",                                       "validate_mappings"),
    ("POST",   r"api/v1/modbus/normalize$",                                      "normalize_iec_addresses"),
]

_COMPILED_ROUTES = [(method, re.compile(pattern), handler) for method, pattern, handler in ROUTES]


def match_route(method, path):
    """Match a request method+path against registered routes."""
    for route_method, pattern, handler in _COMPILED_ROUTES:
        if method != route_method:
            continue
        match = pattern.match(path)
        if match:
            return handler, {key: unquote(value) for key, value in match.groupdict().items()}
    return None, None


class ModbusHandler(
    ModbusDeviceStatusMixin,
    ModbusChannelMixin,
    ModbusMappingMiscMixin,
    ModbusHandlerCore,
):
    """Composite Modbus handler built from focused mixins."""

    pass
