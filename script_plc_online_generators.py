"""IronPython scripts for online PLC access: read, write, watch, diagnostics, start/stop.

Each script resolves the application, reuses the session's cached online
application and refuses to act unless it is logged in (``login: true`` logs
in with OnlineChangeOption.Keep, never downloading). Results carry a
``code`` on failure so handlers can map it to an HTTP status. Callers must
run these through ``wrap_shared_namespace``: the helpers call each other.
"""

import json

from script_plc_generators import _wrap_plc_script

MODBUS_MASTER_TYPES = (88, 90)  # Modbus TCP client, Modbus serial (COM) master
MODBUS_SLAVE_TYPES = (89, 91)  # remote Modbus TCP server child, Modbus serial slave
MASTER_MEMBERS = ("xStop", "uiConnectedSlaves", "xError")
SLAVE_MEMBERS = ("xError", "byModbusError")
MAX_WATCH_SAMPLES = 20000


def as_bool(value):
    """JSON true or the strings true/1/yes/on; the handlers use the same rule for reservation checks."""
    return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")


def application_path(params):
    return params.get("applicationPath", params.get("application", ""))

_ONLINE_PRELUDE = """
payload = json.loads(@@PAYLOAD@@)

class OnlineError(Exception):
    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code

def online_state(online_app):
    return {
        "isLoggedIn": bool(online_app.is_logged_in),
        "applicationState": safe_text(online_app.application_state),
        "operationState": safe_text(online_app.operation_state),
    }

def open_online():
    application_path = payload.get("applicationPath", "").replace("\\\\", "/").strip("/")
    project = get_project()
    if project is None:
        raise OnlineError("no_project", "No project open in the IDE session; open the PLC project first")
    application, application_info, applications = find_application(project, application_path)
    online_app = ensure_session_online_application(application_info["path"], bool(payload.get("login")))
    if online_app is None:
        raise OnlineError("unsupported_session", "This PERSISTENT_SESSION.py cannot cache online applications")
    if not bool(online_app.is_logged_in):
        raise OnlineError("not_logged_in", "Not logged in to " + application_info["path"] +
                          "; POST /api/v1/plc/login first or pass login: true")
    return online_app, application_info

def read_one(online_app, name):
    try:
        return safe_text(online_app.read_value(name)), None
    except Exception as read_error:
        return None, str(read_error)

def iec_number(text):
    try:
        return int(str(text).split("#")[-1])
    except:
        return None

def progress(data):
    if hasattr(session, "report_progress"):
        session.report_progress(data)

def run_online(action):
    try:
        online_app, application_info = open_online()
        body = action(online_app)
        body.setdefault("success", True)
        body["application"] = application_info
        body["online"] = online_state(online_app)
        return body
    except OnlineError as online_error:
        return {"success": False, "code": online_error.code, "error": str(online_error)}
"""


def _online_script(action_source, payload, error_label):
    body = _ONLINE_PRELUDE.replace("@@PAYLOAD@@", json.dumps(json.dumps(payload))) + action_source
    return _wrap_plc_script(body, error_label, "from scriptengine import OnlineChangeOption")


def generate_plc_online_read_script(params):
    """Read expressions: {names: [...], applicationPath?, login?}."""
    action = """
def action(online_app):
    values, errors = {}, {}
    for name in payload["names"]:
        value, error = read_one(online_app, name)
        if error is None:
            values[name] = value
        else:
            errors[name] = error
    return {"success": not errors, "values": values, "errors": errors, "readAt": time.time()}

result = run_online(action)
"""
    return _online_script(action, _payload(params, "names"), "Error in PLC online read script")


def generate_plc_online_write_script(params):
    """Write prepared values: {values: {name: iecText}, force?: bool to override others' prepared values}."""
    action = """
def iec_integer(text):
    # BYTE#91, 16#5B, BYTE#16#5B and 2#0101_1011 are all 91; None if not an integer.
    parts = str(text).strip().upper().replace("_", "").split("#")
    try:
        if len(parts) >= 2 and parts[-2] in ("2", "8", "16"):
            return int(parts[-1], int(parts[-2]))
        return int(parts[-1])
    except ValueError:
        return None

def matches(desired, actual):
    if actual is None:
        return False
    desired, actual = str(desired).strip().upper(), str(actual).strip().upper()
    if actual == desired or actual.split("#")[-1] == desired.split("#")[-1]:
        return True
    number = iec_integer(desired)
    return number is not None and number == iec_integer(actual)

def action(online_app):
    pending = [str(e) for e in (online_app.get_prepared_expressions() or [])]
    if pending and not payload.get("force"):
        raise OnlineError("prepared_values_pending",
                          "Other prepared values are pending: " + ", ".join(pending) + "; pass force: true to discard them")
    for expression in pending:
        # Unprepare, or write_prepared_values() would commit them with ours.
        online_app.set_prepared_value(expression, "")
    previous = {}
    for name in payload["values"]:
        previous[name], error = read_one(online_app, name)
        if error is not None:
            raise OnlineError("bad_expression", name + ": " + error)
    for name, value in payload["values"].items():
        online_app.set_prepared_value(name, str(value))
    online_app.write_prepared_values()
    readback = {}
    deadline = time.time() + 3.0
    while True:
        readback = dict((name, read_one(online_app, name)[0]) for name in payload["values"])
        confirmed = all(matches(payload["values"][n], readback[n]) for n in readback)
        if confirmed or time.time() >= deadline:
            break
        time.sleep(0.2)
    return {"success": confirmed, "previous": previous, "written": payload["values"], "readback": readback,
            "discardedPrepared": pending, "confirmed": confirmed,
            "code": None if confirmed else "readback_mismatch",
            "error": None if confirmed else "Values were written but readback did not match within 3 s"}

result = run_online(action)
"""
    return _online_script(action, _payload(params, "values"), "Error in PLC online write script")


def generate_plc_online_watch_script(params):
    """Sample {names, intervalMs, durationSeconds} and summarize each expression."""
    action = """
def action(online_app):
    names = payload["names"]
    interval = max(0.1, float(payload.get("intervalMs", 1000)) / 1000.0)
    duration = float(payload.get("durationSeconds", 10))
    limit = int(payload.get("maxSamples", @@MAX_SAMPLES@@))
    samples = []
    started = time.time()
    last_progress = -1.0  # report on the first sample, then about once a second
    while True:
        now = time.time() - started
        row = {"t": round(now, 3), "values": {}}
        for name in names:
            row["values"][name] = read_one(online_app, name)[0]
        if len(samples) < limit:
            samples.append(row)
        if now - last_progress >= 1.0:
            progress({"elapsedSeconds": round(now, 1), "durationSeconds": duration, "samples": len(samples),
                      "latest": row["values"]})
            last_progress = now
        if now >= duration:
            break
        remaining = duration - (time.time() - started)
        time.sleep(max(0.0, min(interval - (time.time() - started - now), remaining)))
    summary = {}
    for name in names:
        series = [s["values"][name] for s in samples]
        valid = [v for v in series if v is not None]
        entry = {"first": valid[0] if valid else None, "last": valid[-1] if valid else None,
                 "distinctValues": len(set(valid)), "unreadable": len(series) - len(valid)}
        first, last = iec_number(entry["first"]), iec_number(entry["last"])
        if first is not None and last is not None:
            entry["delta"] = last - first
        summary[name] = entry
    return {"samples": samples, "summary": summary, "sampleCount": len(samples),
            "elapsedSeconds": round(time.time() - started, 3), "truncated": len(samples) >= limit}

result = run_online(action)
""".replace("@@MAX_SAMPLES@@", str(MAX_WATCH_SAMPLES))
    return _online_script(action, _payload(params, "names"), "Error in PLC online watch script")


def generate_plc_online_diagnostics_script(params):
    """App state plus every Modbus master/slave's status members, found by device type."""
    action = """
def device_type(obj):
    try:
        return int(obj.get_device_identification().type)
    except:
        return None

def modbus_devices(project):
    found = []
    stack = [(child, None) for child in project.get_children()]
    while stack:
        obj, master = stack.pop(0)
        kind = device_type(obj)
        name = safe_text(obj.get_name()) if hasattr(obj, "get_name") else ""
        if kind in @@MASTERS@@:
            found.append({"name": name, "role": "master", "type": kind})
            master = name
        elif kind in @@SLAVES@@:
            found.append({"name": name, "role": "slave", "type": kind, "master": master})
        if hasattr(obj, "get_children"):
            try:
                for child in obj.get_children():
                    stack.append((child, master))
            except:
                pass
    return found

def action(online_app):
    devices = modbus_devices(get_project())
    unhealthy = []
    for device in devices:
        members = @@MASTER_MEMBERS@@ if device["role"] == "master" else @@SLAVE_MEMBERS@@
        device["values"] = {}
        for member in members:
            value, error = read_one(online_app, device["name"] + "." + member)
            if error is None:
                device["values"][member] = value
        if str(device["values"].get("xError", "")).upper() == "TRUE":
            unhealthy.append(device["name"])
    warnings = []
    state = safe_text(online_app.application_state)
    if "run" not in state.lower():
        warnings.append("Application state is '" + (state or "unknown") + "', not running: values are frozen and no Modbus polling happens")
    for device in devices:
        if device["role"] != "master":
            continue
        slave_count = len([d for d in devices if d.get("master") == device["name"]])
        connected = iec_number(device["values"].get("uiConnectedSlaves"))
        if slave_count and connected is not None and connected < slave_count:
            warnings.append("%s: %d of %d slaves connected" % (device["name"], connected, slave_count))
    extra = {}
    for name in payload.get("names", []):
        extra[name] = read_one(online_app, name)[0]
    return {"modbusDevices": devices, "unhealthyDevices": unhealthy, "warnings": warnings,
            "healthy": not unhealthy and not warnings, "values": extra, "readAt": time.time()}

result = run_online(action)
""".replace("@@MASTERS@@", repr(MODBUS_MASTER_TYPES)).replace("@@SLAVES@@", repr(MODBUS_SLAVE_TYPES)).replace(
        "@@MASTER_MEMBERS@@", repr(list(MASTER_MEMBERS))).replace("@@SLAVE_MEMBERS@@", repr(list(SLAVE_MEMBERS)))
    return _online_script(action, _payload(params), "Error in PLC online diagnostics script")


def generate_plc_app_control_script(params, command):
    """Start or stop the application: command is 'start' or 'stop'."""
    if command not in ("start", "stop"):
        raise ValueError("command must be start or stop")
    action = """
def action(online_app):
    before = online_state(online_app)
    command_error = None
    try:
        online_app.@@COMMAND@@()
    except Exception as call_error:
        # CODESYS may raise a timeout while waiting for the state; the poll below decides.
        command_error = str(call_error)
    deadline = time.time() + 5.0
    reached = False
    while not reached:
        state = safe_text(online_app.application_state).lower()
        reached = ("@@COMMAND@@" == "start" and "run" in state) or ("@@COMMAND@@" == "stop" and "stop" in state)
        if reached or time.time() >= deadline:
            break
        time.sleep(0.2)
    if not reached:
        raise OnlineError("state_not_reached", "@@COMMAND@@ sent but the application is still " +
                          safe_text(online_app.application_state) + " after 5 s" +
                          ("" if command_error is None else " (" + command_error + ")"))
    return {"before": before, "command": "@@COMMAND@@"}

result = run_online(action)
""".replace("@@COMMAND@@", command)
    return _online_script(action, _payload(params), "Error in PLC app control script")


def _payload(params, required=None):
    payload = {
        "applicationPath": application_path(params),
        "login": as_bool(params.get("login", False)),
        "force": as_bool(params.get("force", False)),
    }
    for key in ("names", "values", "intervalMs", "durationSeconds", "maxSamples"):
        if key in params:
            payload[key] = params[key]
    if required == "names":
        names = params.get("names")
        if not isinstance(names, list) or not names or not all(isinstance(n, str) and n for n in names):
            raise ValueError("names must be a non-empty list of expressions")
    if required == "values":
        values = params.get("values")
        if not isinstance(values, dict) or not values:
            raise ValueError("values must be a non-empty object of expression: IEC value text")
        payload["values"] = dict((k, str(v)) for k, v in values.items())
    return payload
