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


def _indent(text, spaces):
    prefix = " " * spaces
    return "\n".join(prefix + line if line else "" for line in text.strip("\n").splitlines())


def _plc_application_common(extra_imports=""):
    return """
import scriptengine
import sys
import traceback
@@EXTRA_IMPORTS@@

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

def get_session_online_state(application_path):
    if hasattr(session, 'get_online_application_state'):
        return session.get_online_application_state(application_path)
    return None

def ensure_session_online_application(application_path, login_requested):
    if hasattr(session, 'ensure_online_application'):
        return session.ensure_online_application(application_path, login_requested)
    return None

def dispose_session_online_application(application_path, logout_first):
    if hasattr(session, 'dispose_online_application'):
        return session.dispose_online_application(application_path, logout_first)
    return False

def register_session_certificate_trust(application_path):
    if hasattr(session, 'register_trusts_certificate_for_application'):
        return session.register_trusts_certificate_for_application(application_path)
    return None

def try_register_session_certificate_trust(application_path):
    try:
        if hasattr(session, 'register_trusts_certificate_for_application'):
            return {"success": True, "result": session.register_trusts_certificate_for_application(application_path)}
        return {"success": True, "result": None}
    except Exception as trust_error:
        return {"success": False, "error": str(trust_error)}

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
""".replace("@@EXTRA_IMPORTS@@", extra_imports)


def _wrap_plc_script(body, error_label, extra_imports=""):
    return """\
@@COMMON@@

try:
@@BODY@@
except Exception as e:
    error_type, error_value, error_traceback = sys.exc_info()
    print("@@ERROR_LABEL@@: " + str(error_value))
    print(traceback.format_exc())
    result = {"success": False, "error": str(error_value)}
""".replace("@@COMMON@@", _plc_application_common(extra_imports)).replace(
        "@@BODY@@", _indent(body, 4)
    ).replace("@@ERROR_LABEL@@", error_label)


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
    logout_after = params.get("logoutAfter", params.get("logout_after", False))
    include_signatures = params.get("includeSignatures", False)
    if isinstance(login, str):
        login = login.lower() in ("1", "true", "yes")
    if isinstance(logout_after, str):
        logout_after = logout_after.lower() in ("1", "true", "yes")
    if isinstance(include_signatures, str):
        include_signatures = include_signatures.lower() in ("1", "true", "yes")

    body = """
application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")
login_requested = @@LOGIN@@
logout_after = @@LOGOUT_AFTER@@
include_signatures = @@INCLUDE_SIGNATURES@@

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
            "cached": False,
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

    cached_state = get_session_online_state(application_info["path"])
    if cached_state is not None and "online" in cached_state:
        status["online"] = cached_state["online"]

    if login_requested:
        online_app = None
        owns_online_app = False
        try:
            trust_result = try_register_session_certificate_trust(application_info["path"])
            if trust_result.get("success") and trust_result.get("result") is not None:
                status["online"]["certificateTrust"] = trust_result.get("result")
            elif not trust_result.get("success"):
                status["online"]["certificateTrustError"] = trust_result.get("error")
            online_app = ensure_session_online_application(application_info["path"], True)
            if online_app is None:
                online_app = scriptengine.online.create_online_application(application)
                owns_online_app = True
                online_app.login(OnlineChangeOption.Keep, False)
            status["online"]["loginAttempted"] = True
            status["online"]["cached"] = not owns_online_app
            status["online"]["isLoggedIn"] = bool(online_app.is_logged_in)
            status["online"]["applicationState"] = safe_text(online_app.application_state)
            status["online"]["operationState"] = safe_text(online_app.operation_state)
            status["build"]["isUptodate"] = read_bool(application, "is_uptodate")
            status["build"]["isOnlineChangePossible"] = read_bool(application, "is_online_change_possible")
        finally:
            if online_app is not None and logout_after and not owns_online_app:
                dispose_session_online_application(application_info["path"], True)
            elif online_app is not None and logout_after:
                try:
                    online_app.logout()
                except:
                    pass
            if online_app is not None and owns_online_app:
                try:
                    online_app.Dispose()
                except:
                    pass

    result = status
"""
    return _wrap_plc_script(
        body.replace("@@APPLICATION_PATH@@", _literal(application_path))
        .replace("@@LOGIN@@", _bool_literal(login))
        .replace("@@LOGOUT_AFTER@@", _bool_literal(logout_after))
        .replace("@@INCLUDE_SIGNATURES@@", _bool_literal(include_signatures)),
        "Error in PLC status script",
        "from scriptengine import OnlineChangeOption",
    )


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


def generate_plc_deploy_script(params):
    """Generate script to login, download, and optionally start an application."""
    application_path = params.get("applicationPath", params.get("application", ""))
    start_app = params.get("start", True)
    logout_after = params.get("logoutAfter", params.get("logout_after", False))
    skip_save = params.get("skipSave", params.get("skip_save", False))
    if isinstance(start_app, str):
        start_app = start_app.lower() in ("1", "true", "yes")
    if isinstance(logout_after, str):
        logout_after = logout_after.lower() in ("1", "true", "yes")
    if isinstance(skip_save, str):
        skip_save = skip_save.lower() in ("1", "true", "yes")

    body = """
application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")
start_requested = @@START@@
logout_after = @@LOGOUT_AFTER@@
skip_save = @@SKIP_SAVE@@

project = get_project()
if project is None:
    result = {"success": False, "error": "No active project in session"}
else:
    application, application_info, applications = find_application(project, application_path)
    deploy = {
        "success": False,
        "application": application_info,
        "availableApplications": [entry for obj, entry in applications],
        "steps": []
    }

    online_app = None
    owns_online_app = False
    try:
        trust_result = try_register_session_certificate_trust(application_info["path"])
        if trust_result.get("success") and trust_result.get("result") is not None:
            deploy["certificateTrust"] = trust_result.get("result")
        elif not trust_result.get("success"):
            deploy["certificateTrustError"] = trust_result.get("error")

        if skip_save:
            deploy["steps"].append({"step": "save_project", "status": "skipped", "reason": "skipSave=true"})
        else:
            deploy["steps"].append({"step": "save_project", "status": "started"})
            if not hasattr(project, 'save'):
                raise Exception("Active project does not support save()")
            project.save()
            deploy["steps"][-1]["status"] = "ok"
            try:
                deploy["steps"][-1]["path"] = safe_text(project.path)
            except:
                pass
            try:
                deploy["steps"][-1]["dirty"] = bool(project.dirty)
            except:
                pass

        deploy["steps"].append({"step": "create_online_application", "status": "started"})
        online_app = ensure_session_online_application(application_info["path"], False)
        if online_app is None:
            online_app = scriptengine.online.create_online_application(application)
            owns_online_app = True
        deploy["steps"][-1]["status"] = "ok"
        deploy["steps"][-1]["cached"] = not owns_online_app

        deploy["steps"].append({"step": "login", "status": "started"})
        if owns_online_app:
            online_app.login(OnlineChangeOption.Keep, False)
        else:
            online_app = ensure_session_online_application(application_info["path"], True)
        deploy["steps"][-1]["status"] = "ok"
        deploy["steps"][-1]["isLoggedIn"] = bool(online_app.is_logged_in)
        deploy["steps"][-1]["applicationState"] = safe_text(online_app.application_state)
        deploy["steps"][-1]["operationState"] = safe_text(online_app.operation_state)

        deploy["steps"].append({"step": "source_download", "status": "started"})
        download_result = online_app.source_download()
        deploy["steps"][-1]["status"] = "ok"
        deploy["steps"][-1]["result"] = safe_text(download_result)
        deploy["steps"][-1]["applicationState"] = safe_text(online_app.application_state)
        deploy["steps"][-1]["operationState"] = safe_text(online_app.operation_state)

        if start_requested:
            deploy["steps"].append({"step": "start", "status": "started"})
            current_state = safe_text(online_app.application_state).lower()
            if current_state == "run":
                deploy["steps"][-1]["status"] = "ok"
                deploy["steps"][-1]["result"] = "already running"
                deploy["steps"][-1]["applicationState"] = safe_text(online_app.application_state)
                deploy["steps"][-1]["operationState"] = safe_text(online_app.operation_state)
            else:
                start_result = online_app.start()
                deploy["steps"][-1]["status"] = "ok"
                deploy["steps"][-1]["result"] = safe_text(start_result)
                deploy["steps"][-1]["applicationState"] = safe_text(online_app.application_state)
                deploy["steps"][-1]["operationState"] = safe_text(online_app.operation_state)

        deploy["online"] = {
            "isLoggedIn": bool(online_app.is_logged_in),
            "applicationState": safe_text(online_app.application_state),
            "operationState": safe_text(online_app.operation_state)
        }
        deploy["success"] = True
        result = deploy
    except Exception as deploy_error:
        deploy["error"] = str(deploy_error)
        if online_app is not None:
            try:
                deploy["online"] = {
                    "isLoggedIn": bool(online_app.is_logged_in),
                    "applicationState": safe_text(online_app.application_state),
                    "operationState": safe_text(online_app.operation_state)
                }
            except:
                pass
        result = deploy
    finally:
        if online_app is not None and logout_after and not owns_online_app:
            dispose_session_online_application(application_info["path"], True)
        elif online_app is not None and logout_after:
            try:
                online_app.logout()
            except:
                pass
        if online_app is not None and owns_online_app:
            try:
                online_app.Dispose()
            except:
                pass
"""
    return _wrap_plc_script(
        body.replace("@@APPLICATION_PATH@@", _literal(application_path))
        .replace("@@START@@", _bool_literal(start_app))
        .replace("@@LOGOUT_AFTER@@", _bool_literal(logout_after))
        .replace("@@SKIP_SAVE@@", _bool_literal(skip_save)),
        "Error in PLC deploy script",
        "from scriptengine import OnlineChangeOption",
    )


def generate_plc_login_script(params):
    """Generate script to login an online application without downloading or logging out."""
    application_path = params.get("applicationPath", params.get("application", ""))

    body = """
application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")

project = get_project()
if project is None:
    result = {"success": False, "error": "No active project in session"}
else:
    application, application_info, applications = find_application(project, application_path)
    login_result = {
        "success": False,
        "application": application_info,
        "availableApplications": [entry for obj, entry in applications],
        "online": {
            "cached": False,
            "isLoggedIn": False,
            "applicationState": "",
            "operationState": ""
        }
    }
    try:
        trust_result = try_register_session_certificate_trust(application_info["path"])
        if trust_result.get("success") and trust_result.get("result") is not None:
            login_result["certificateTrust"] = trust_result.get("result")
        elif not trust_result.get("success"):
            login_result["certificateTrustError"] = trust_result.get("error")

        before_state = get_session_online_state(application_info["path"])
        if before_state is not None and "online" in before_state:
            login_result["online"]["beforeLogin"] = before_state["online"]

        online_app = ensure_session_online_application(application_info["path"], False)
        if online_app is None:
            online_app = scriptengine.online.create_online_application(application)
            login_result["online"]["cached"] = False
        else:
            login_result["online"]["cached"] = True

        if "beforeLogin" not in login_result["online"]:
            login_result["online"]["beforeLogin"] = {
                "cached": login_result["online"]["cached"],
                "isLoggedIn": bool(online_app.is_logged_in),
                "applicationState": safe_text(online_app.application_state),
                "operationState": safe_text(online_app.operation_state)
            }

        if login_result["online"]["cached"]:
            online_app = ensure_session_online_application(application_info["path"], True)
        else:
            online_app.login(OnlineChangeOption.Keep, False)

        if not login_result["online"]["cached"]:
            try:
                online_app.Dispose()
            except:
                pass
            online_app = ensure_session_online_application(application_info["path"], False)

        login_result["success"] = True
        login_result["loggedIn"] = True
        before_login = login_result["online"].get("beforeLogin")
        login_result["online"] = {
            "cached": True,
            "isLoggedIn": bool(online_app.is_logged_in),
            "applicationState": safe_text(online_app.application_state),
            "operationState": safe_text(online_app.operation_state),
            # Kept so callers can tell a stop they caused from one they found.
            "beforeLogin": before_login
        }
        login_result["note"] = ("Login uses OnlineChangeOption.Keep (no application download), but the IDE "
                                "may still transfer download information afterwards; check the IDE status "
                                "bar and GET /api/v1/bench before the next online operation.")
        result = login_result
    except Exception as login_error:
        login_result["error"] = str(login_error)
        current_state = get_session_online_state(application_info["path"])
        if current_state is not None and "online" in current_state:
            login_result["online"] = current_state["online"]
        result = login_result
"""
    return _wrap_plc_script(
        body.replace("@@APPLICATION_PATH@@", _literal(application_path)),
        "Error in PLC login script",
        "from scriptengine import OnlineChangeOption",
    )


def generate_plc_logout_script(params):
    """Generate script to logout an online application without downloading."""
    application_path = params.get("applicationPath", params.get("application", ""))

    body = """
application_path = @@APPLICATION_PATH@@.replace("\\\\", "/").strip("/")

project = get_project()
if project is None:
    result = {"success": False, "error": "No active project in session"}
else:
    application, application_info, applications = find_application(project, application_path)
    logout_result = {
        "success": True,
        "application": application_info,
        "availableApplications": [entry for obj, entry in applications],
        "online": {
            "cached": False,
            "isLoggedIn": False,
            "applicationState": "",
            "operationState": ""
        }
    }
    before_state = get_session_online_state(application_info["path"])
    if before_state is not None and "online" in before_state:
        logout_result["online"]["beforeLogout"] = before_state["online"]
        logout_result["online"] = before_state["online"]

    _disposed = bool(dispose_session_online_application(application_info["path"], True))
    logout_result["disposedCachedHandle"] = _disposed
    logout_result["loggedOut"] = _disposed

    _force_logout = False
    if not _disposed:
        try:
            _online_app = scriptengine.online.create_online_application(application)
            try:
                if bool(_online_app.is_logged_in):
                    _online_app.logout()
                    _force_logout = True
            finally:
                try:
                    _online_app.Dispose()
                except:
                    pass
        except Exception as force_logout_error:
            logout_result["forceLogoutError"] = str(force_logout_error)

    if _force_logout:
        logout_result["loggedOut"] = True

    after_state = get_session_online_state(application_info["path"])
    if after_state is not None and "online" in after_state:
        logout_result["online"] = after_state["online"]
    else:
        logout_result["online"] = {
            "cached": False,
            "isLoggedIn": False,
            "applicationState": "",
            "operationState": ""
        }

    result = logout_result
"""
    return _wrap_plc_script(
        body.replace("@@APPLICATION_PATH@@", _literal(application_path)),
        "Error in PLC logout script",
    )
