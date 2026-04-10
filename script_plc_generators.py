"""Generated IronPython scripts for safe PLC deployment discovery."""

import json


def _literal(value):
    return json.dumps(value if value is not None else "")


def _bool_literal(value):
    return "True" if bool(value) else "False"


def _int_literal(value, default):
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(default)


def generate_plc_targets_script(params):
    """Generate script to list candidate devices and applications for deployment."""
    return """
import scriptengine
import sys
import traceback

try:
    project = scriptengine.projects.primary
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        nodes = []
        devices = []
        applications = []
        stack = []

        try:
            for child in project.get_children():
                stack.append((child, ""))
        except Exception as root_error:
            result = {"success": False, "error": "Unable to enumerate project children: " + str(root_error)}

        while 'result' not in locals() and stack:
            obj, parent_path = stack.pop(0)
            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)

            path = name if not parent_path else parent_path + "/" + name
            object_type = ""
            if hasattr(obj, 'type'):
                try:
                    object_type = str(obj.type)
                except:
                    object_type = ""

            has_children = hasattr(obj, 'get_children')
            has_device_identification = hasattr(obj, 'get_device_identification')
            is_application = hasattr(obj, 'create_boot_application') and hasattr(obj, 'build')

            entry = {
                "name": name,
                "path": path,
                "type": object_type,
                "isApplication": is_application,
                "isDevice": has_device_identification,
                "hasChildren": has_children
            }
            nodes.append(entry)

            if has_device_identification:
                try:
                    did = obj.get_device_identification()
                    entry["deviceType"] = int(did.type)
                    entry["deviceId"] = str(did.id)
                    entry["deviceVersion"] = str(did.version)
                except:
                    pass
                devices.append(entry)

            if is_application:
                applications.append(entry)

            if has_children:
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        if 'result' not in locals():
            result = {
                "success": True,
                "devices": devices,
                "applications": applications,
                "nodes": nodes,
                "counts": {
                    "devices": len(devices),
                    "applications": len(applications),
                    "nodes": len(nodes)
                }
            }
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC target discovery script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
"""


def generate_plc_gateways_script(params):
    """Generate script to list configured CODESYS gateways."""
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

    gateways = []
    if not hasattr(scriptengine.online, 'gateways'):
        result = {"success": False, "error": "CODESYS online gateway API is not available"}
    else:
        for gateway in scriptengine.online.gateways:
            entry = {
                "name": safe_text(getattr(gateway, 'name', '')),
                "guid": safe_text(getattr(gateway, 'guid', '')),
                "driver": safe_text(getattr(gateway, 'gateway_driver', '')),
                "config": {}
            }
            try:
                params = gateway.config_params
                if params is not None:
                    for key in params:
                        entry["config"][safe_text(key)] = safe_text(params[key])
            except:
                pass
            gateways.append(entry)

        result = {
            "success": True,
            "gateways": gateways,
            "count": len(gateways)
        }
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC gateway discovery script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
"""


def generate_plc_scan_script(params):
    """Generate script to scan for PLC targets through a configured gateway."""
    gateway_key = params.get("gateway", params.get("gatewayName", params.get("gatewayGuid", "")))
    ip = params.get("ip", params.get("host", ""))
    port = params.get("port", 11740)
    cached = params.get("cached", True)
    if isinstance(cached, str):
        cached = cached.lower() not in ("0", "false", "no")

    return """
import scriptengine
import sys
import traceback

try:
    gateway_key = @@GATEWAY_KEY@@
    ip_or_host = @@IP_OR_HOST@@
    port = @@PORT@@
    cached = @@CACHED@@

    def safe_text(value):
        try:
            if value is None:
                return ""
            return str(value)
        except:
            return ""

    def target_entry(target):
        entry = {
            "deviceName": safe_text(getattr(target, 'device_name', '')),
            "typeName": safe_text(getattr(target, 'type_name', '')),
            "vendorName": safe_text(getattr(target, 'vendor_name', '')),
            "deviceId": safe_text(getattr(target, 'device_id', '')),
            "address": safe_text(getattr(target, 'address', '')),
            "parentAddress": safe_text(getattr(target, 'parent_address', '')),
            "lockedInCache": False,
            "blockDriver": safe_text(getattr(target, 'block_driver', '')),
            "blockDriverAddress": safe_text(getattr(target, 'block_driver_address', ''))
        }
        try:
            entry["lockedInCache"] = bool(target.locked_in_cache)
        except:
            pass
        return entry

    def select_gateway(key):
        gateways = scriptengine.online.gateways
        if key:
            try:
                return gateways[key]
            except:
                pass
            matches = []
            for candidate in gateways:
                if safe_text(getattr(candidate, 'name', '')) == key or safe_text(getattr(candidate, 'guid', '')) == key:
                    matches.append(candidate)
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise Exception("Gateway name is ambiguous: " + key)
            raise Exception("Gateway not found: " + key)

        gateway_list = []
        for candidate in gateways:
            gateway_list.append(candidate)
        if len(gateway_list) == 0:
            return None
        return gateway_list[0]

    if not hasattr(scriptengine.online, 'gateways'):
        result = {"success": False, "error": "CODESYS online gateway API is not available"}
    else:
        gateway = select_gateway(gateway_key)
        if gateway is None:
            result = {
                "success": True,
                "mode": "noGateways",
                "gateway": None,
                "targets": [],
                "count": 0,
                "warning": "No configured CODESYS gateways found"
            }
        else:
            gateway_info = {
                "name": safe_text(getattr(gateway, 'name', '')),
                "guid": safe_text(getattr(gateway, 'guid', ''))
            }

        if 'result' not in locals() and ip_or_host:
            address = gateway.find_address_by_ip(ip_or_host, port)
            result = {
                "success": True,
                "mode": "findAddressByIp",
                "gateway": gateway_info,
                "ip": ip_or_host,
                "port": port,
                "address": safe_text(address),
                "targets": [{"address": safe_text(address)}]
            }
        elif 'result' not in locals():
            scan_result = gateway.get_cached_network_scan_result() if cached else gateway.perform_network_scan()
            targets = []
            for target in scan_result:
                targets.append(target_entry(target))
            result = {
                "success": True,
                "mode": "cachedScan" if cached else "networkScan",
                "gateway": gateway_info,
                "targets": targets,
                "count": len(targets)
            }
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC network scan script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@GATEWAY_KEY@@", _literal(gateway_key)) \
   .replace("@@IP_OR_HOST@@", _literal(ip)) \
   .replace("@@PORT@@", _int_literal(port, 11740)) \
   .replace("@@CACHED@@", _bool_literal(cached))


def generate_plc_status_script(params):
    """Generate script to inspect application deploy/online status."""
    application_path = params.get("applicationPath", params.get("application", ""))
    login = params.get("login", params.get("connect", False))
    include_signatures = params.get("includeSignatures", False)
    if isinstance(login, str):
        login = login.lower() in ("1", "true", "yes")
    if isinstance(include_signatures, str):
        include_signatures = include_signatures.lower() in ("1", "true", "yes")

    return """
import scriptengine
import sys
import traceback
from scriptengine import OnlineChangeOption

try:
    application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")
    login_requested = @@LOGIN@@
    include_signatures = @@INCLUDE_SIGNATURES@@

    def safe_text(value):
        try:
            if value is None:
                return ""
            return str(value)
        except:
            return ""

    def get_project():
        project = scriptengine.projects.primary
        if project is None and hasattr(session, 'active_project'):
            project = session.active_project
        return project

    def find_application(project, wanted_path):
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

        if wanted_path:
            matches = []
            for obj, entry in applications:
                if entry["path"] == wanted_path or entry["name"] == wanted_path:
                    matches.append((obj, entry))
            if len(matches) == 1:
                return matches[0][0], matches[0][1], applications
            if len(matches) > 1:
                raise Exception("Application path is ambiguous: " + wanted_path)
            raise Exception("Application not found: " + wanted_path)

        if len(applications) == 1:
            return applications[0][0], applications[0][1], applications
        raise Exception("applicationPath required; found " + str(len(applications)) + " applications")

    def read_bool(obj, property_name):
        try:
            return bool(getattr(obj, property_name))
        except Exception as read_error:
            return {"error": str(read_error)}

    def collect_signatures(application):
        signatures = []
        stack = [(application, "")]
        while stack:
            obj, parent_path = stack.pop(0)
            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)
            path = name if not parent_path else parent_path + "/" + name
            if hasattr(obj, 'get_signature_crc'):
                try:
                    crc = obj.get_signature_crc(application, None)
                    if crc is not None:
                        signatures.append({"name": name, "path": path, "signatureCrc": safe_text(crc)})
                except:
                    pass
            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass
        return signatures

    project = get_project()
    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        application, application_info, applications = find_application(project, application_path)
        status = {
            "success": True,
            "application": application_info,
            "online": {
                "loginAttempted": False,
                "isLoggedIn": False,
                "applicationState": "",
                "operationState": ""
            },
            "build": {
                "isUptodate": read_bool(application, "is_uptodate"),
                "isOnlineChangePossible": read_bool(application, "is_online_change_possible")
            },
            "availableApplications": [entry for obj, entry in applications]
        }

        if include_signatures:
            status["signatures"] = collect_signatures(application)

        if login_requested:
            online_app = None
            try:
                online_app = scriptengine.online.create_online_application(application)
                online_app.login(OnlineChangeOption.Keep, False)
                status["online"]["loginAttempted"] = True
                status["online"]["isLoggedIn"] = bool(online_app.is_logged_in)
                status["online"]["applicationState"] = safe_text(online_app.application_state)
                status["online"]["operationState"] = safe_text(online_app.operation_state)
                status["build"]["isUptodate"] = read_bool(application, "is_uptodate")
                status["build"]["isOnlineChangePossible"] = read_bool(application, "is_online_change_possible")
            finally:
                if online_app is not None:
                    try:
                        online_app.logout()
                    except:
                        pass
                    try:
                        online_app.Dispose()
                    except:
                        pass

        result = status
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC status script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@APPLICATION_PATH@@", _literal(application_path)) \
   .replace("@@LOGIN@@", _bool_literal(login)) \
   .replace("@@INCLUDE_SIGNATURES@@", _bool_literal(include_signatures))


def generate_plc_validate_deploy_script(params):
    """Generate script to validate deploy inputs without connecting or downloading."""
    application_path = params.get("applicationPath", params.get("application", ""))
    device_path = params.get("devicePath", params.get("device", ""))

    return """
import scriptengine
import sys
import traceback

try:
    application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")
    device_path = @@DEVICE_PATH@@.replace("\\\\", "/").strip("/")

    project = scriptengine.projects.primary
    if project is None and hasattr(session, 'active_project'):
        project = session.active_project

    if project is None:
        result = {"success": False, "error": "No active project in session"}
    else:
        found_application = None
        found_device = None
        applications = []
        devices = []
        stack = []

        try:
            for child in project.get_children():
                stack.append((child, ""))
        except Exception as root_error:
            result = {"success": False, "error": "Unable to enumerate project children: " + str(root_error)}

        while 'result' not in locals() and stack:
            obj, parent_path = stack.pop(0)
            try:
                name = obj.get_name() if hasattr(obj, 'get_name') else str(obj)
            except:
                name = str(obj)

            path = name if not parent_path else parent_path + "/" + name
            is_application = hasattr(obj, 'create_boot_application') and hasattr(obj, 'build')
            is_device = hasattr(obj, 'get_device_identification')

            if is_application:
                entry = {"name": name, "path": path}
                applications.append(entry)
                if application_path and (path == application_path or name == application_path):
                    found_application = entry

            if is_device:
                entry = {"name": name, "path": path}
                try:
                    did = obj.get_device_identification()
                    entry["deviceType"] = int(did.type)
                    entry["deviceId"] = str(did.id)
                    entry["deviceVersion"] = str(did.version)
                except:
                    pass
                devices.append(entry)
                if device_path and (path == device_path or name == device_path):
                    found_device = entry

            if hasattr(obj, 'get_children'):
                try:
                    for child in obj.get_children():
                        stack.append((child, path))
                except:
                    pass

        if 'result' not in locals():
            errors = []
            if application_path and found_application is None:
                errors.append("Application not found: " + application_path)
            if device_path and found_device is None:
                errors.append("Device not found: " + device_path)
            if not application_path and len(applications) == 1:
                found_application = applications[0]
            if not device_path and len(devices) == 1:
                found_device = devices[0]
            if not application_path and len(applications) != 1:
                errors.append("applicationPath required; found " + str(len(applications)) + " applications")
            if not device_path and len(devices) != 1:
                errors.append("devicePath required; found " + str(len(devices)) + " devices")

            result = {
                "success": len(errors) == 0,
                "valid": len(errors) == 0,
                "errors": errors,
                "application": found_application,
                "device": found_device,
                "availableApplications": applications,
                "availableDevices": devices
            }
            if errors:
                result["error"] = "; ".join(errors)
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("Error in PLC deploy validation script: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@APPLICATION_PATH@@", _literal(application_path)) \
   .replace("@@DEVICE_PATH@@", _literal(device_path))
