"""Generated IronPython scripts for PLC communication bindings."""

import json


def _literal(value):
    return json.dumps(value if value is not None else "")


def _int_literal(value, default):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(default)


def _bool_literal(value):
    return "True" if bool(value) else "False"


def _coerce_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in ("1", "true", "yes")
    return bool(value)


def generate_plc_bindings_script(params):
    """Generate script to list current project device gateway/address bindings."""
    return """
import scriptengine
import sys
import traceback

try:
    def safe_text(value):
        try:
            if value is None:
                return ""
            return str(value)
        except:
            return ""

    def decode_ip_from_address(address):
        parts = address.split(".")
        if len(parts) < 5:
            return ""
        try:
            part_a = int(parts[-2], 16)
            part_b = int(parts[-1], 16)
            return ".".join([
                str((part_a >> 8) & 255),
                str(part_a & 255),
                str((part_b >> 8) & 255),
                str(part_b & 255)
            ])
        except:
            return ""

    project = scriptengine.projects.primary
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        devices = []
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

            if hasattr(obj, 'get_device_identification'):
                entry = {"name": name, "path": path, "gatewayGuid": "", "address": "", "decodedIp": ""}
                try:
                    entry["gatewayGuid"] = safe_text(obj.get_gateway())
                except Exception as gateway_error:
                    entry["gatewayError"] = str(gateway_error)
                try:
                    entry["address"] = safe_text(obj.get_address())
                    entry["decodedIp"] = decode_ip_from_address(entry["address"])
                except Exception as address_error:
                    entry["addressError"] = str(address_error)
                devices.append(entry)

            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        result = {"success": True, "bindings": devices, "count": len(devices)}
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC binding list script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
"""


def generate_plc_bind_ip_script(params):
    """Generate script to ensure a local gateway and bind a project device by IP."""
    device_path = params.get("devicePath", params.get("device", "P2CDS622"))
    ip = params.get("ip", params.get("ipAddress", ""))
    port = params.get("port", 11740)
    gateway_name = params.get("gatewayName", params.get("gateway", "Local Gateway"))
    gateway_host = params.get("gatewayHost", "localhost")
    gateway_port = params.get("gatewayPort", 1217)
    save = _coerce_bool(params.get("save"), False)
    confirm = _coerce_bool(params.get("confirmBind"), False)

    return """
import scriptengine
import sys
import traceback

try:
    device_path = @@DEVICE_PATH@@.replace("\\\\", "/").strip("/")
    ip_address = @@IP_ADDRESS@@
    port = @@PORT@@
    gateway_name = @@GATEWAY_NAME@@
    gateway_host = @@GATEWAY_HOST@@
    gateway_port = @@GATEWAY_PORT@@
    save_project = @@SAVE_PROJECT@@
    confirm_bind = @@CONFIRM_BIND@@

    def safe_text(value):
        try:
            if value is None:
                return ""
            return str(value)
        except:
            return ""

    def decode_ip_from_address(address):
        parts = address.split(".")
        if len(parts) < 5:
            return ""
        try:
            part_a = int(parts[-2], 16)
            part_b = int(parts[-1], 16)
            return ".".join([
                str((part_a >> 8) & 255),
                str(part_a & 255),
                str((part_b >> 8) & 255),
                str(part_b & 255)
            ])
        except:
            return ""

    def get_project():
        project = scriptengine.projects.primary
        if project is None and hasattr(session, 'active_project'):
            project = session.active_project
        return project

    def snapshot_device(device):
        entry = {"gatewayGuid": "", "address": "", "decodedIp": ""}
        try:
            entry["gatewayGuid"] = safe_text(device.get_gateway())
        except Exception as gateway_error:
            entry["gatewayError"] = str(gateway_error)
        try:
            entry["address"] = safe_text(device.get_address())
            entry["decodedIp"] = decode_ip_from_address(entry["address"])
        except Exception as address_error:
            entry["addressError"] = str(address_error)
        return entry

    def find_device(project, wanted_path):
        devices = []
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
            if hasattr(obj, 'get_device_identification'):
                devices.append((obj, {"name": name, "path": path}))
            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        matches = []
        for obj, entry in devices:
            if entry["path"] == wanted_path or entry["name"] == wanted_path:
                matches.append((obj, entry))
        if len(matches) == 1:
            return matches[0][0], matches[0][1], [entry for obj, entry in devices]
        if len(matches) > 1:
            raise Exception("Device path is ambiguous: " + wanted_path)
        raise Exception("Device not found: " + wanted_path)

    def ensure_gateway():
        gateways = scriptengine.online.gateways
        matches = []
        for candidate in gateways:
            if safe_text(getattr(candidate, 'name', '')) == gateway_name:
                matches.append(candidate)
        if len(matches) > 0:
            return matches[0], False

        driver = scriptengine.online.gateway_drivers.default_driver
        gateway = gateways.add_new_gateway(
            gateway_name,
            {"IP-Address": gateway_host, "Port": gateway_port},
            driver
        )
        return gateway, True

    if not ip_address:
        result = {"success": False, "error": "Missing required parameter: ip"}
    elif not confirm_bind:
        result = {
            "success": False,
            "error": "Binding a project to a different PLC requires confirmBind=true"
        }
    else:
        project = get_project()
        if project is None:
            result = {"success": False, "error": "No active project in session"}
        else:
            device, device_info, available_devices = find_device(project, device_path)
            before = snapshot_device(device)
            gateway, gateway_created = ensure_gateway()
            device.set_gateway_and_ip_address(gateway, ip_address, port)
            after = snapshot_device(device)

            saved = False
            if save_project:
                if hasattr(project, 'save'):
                    project.save()
                    saved = True
                elif hasattr(scriptengine.projects, 'save_project'):
                    scriptengine.projects.save_project()
                    saved = True
                else:
                    raise Exception("Unable to save project: no supported save method found")

            result = {
                "success": True,
                "device": device_info,
                "gateway": {
                    "name": safe_text(getattr(gateway, 'name', '')),
                    "guid": safe_text(getattr(gateway, 'guid', '')),
                    "created": gateway_created,
                    "host": gateway_host,
                    "port": gateway_port
                },
                "target": {"ip": ip_address, "port": port},
                "before": before,
                "after": after,
                "saved": saved,
                "availableDevices": available_devices
            }
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC bind IP script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@DEVICE_PATH@@", _literal(device_path)) \
   .replace("@@IP_ADDRESS@@", _literal(ip)) \
   .replace("@@PORT@@", _int_literal(port, 11740)) \
   .replace("@@GATEWAY_NAME@@", _literal(gateway_name)) \
   .replace("@@GATEWAY_HOST@@", _literal(gateway_host)) \
   .replace("@@GATEWAY_PORT@@", _int_literal(gateway_port, 1217)) \
   .replace("@@SAVE_PROJECT@@", _bool_literal(save)) \
   .replace("@@CONFIRM_BIND@@", _bool_literal(confirm))
