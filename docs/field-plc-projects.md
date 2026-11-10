# Field PLC projects: inspect, diagnose and change a site PLC

How to work on a `.project` someone downloaded from a site PLC, and on that PLC over the network, through
this repo's IDE session. Written from the DEH COM_TB Modbus diagnosis (2026-11-10, report:
[Doc Shelf](https://docs.local.tidalmetals.org/documents/projects/codesys/deh-com-tb-modbus-2026-11-10/latest/)).
Bench-specific procedures are in [modbus-bench.md](modbus-bench.md); its Modbus configuration rules apply
here too.

## Ground rules for a real PLC

- Diagnose read-only first: inspect the project offline, then log in with `OnlineChangeOption.Keep` (no
  download) and read. The user decides every download, application start or stop, and when to do it.
- Report the application state you find at login (`on.application_state`); it may already be stopped.
- A download (`OnlineChangeOption.Try` falls back to one when an online change isn't possible) resets
  non-retained values, including setpoints that arrive over MQTT. Say so before downloading.
- Work on a copy: put the download in `~/projects/codesys_projects/<name>/` and keep the original untouched.
  To make online change possible on a copy, also copy the original's
  `<project>.<device>.Application.<guid>.compileinfo` (and `.bootinfo*`) under the copy's name. Once the PLC
  runs your copy, the original project no longer matches it; tell the user which file is now authoritative.
- Log out when done.

## Driving the IDE

`python run_ide_script.py <script.py> --timeout N` runs an IronPython 2.7 script inside the open IDE (via
`PERSISTENT_SESSION.py`; no API key involved) and prints the dict the script assigns to `result`. Import
`from scriptengine import projects, system, OnlineChangeOption` as needed; `session` persists between scripts,
so keep objects there (`session.my_online = on`). Write scripts as files (under `tmp/`, gitignored); the
inline-script guard blocks multi-line `python -c`. API stubs: `ScriptLib/Stubs/scriptengine/`.

- **Open without disturbing the user's project:** `projects.open(path, primary=False)` opens a background
  project for offline inspection, export and edits.
- **Only the primary project can go online** ("Online application must be of primary project"). Switching
  primary means closing the current one. If it has unsaved changes, ask the user whether to save; closing a
  project that is logged in raises a logout dialog someone must click.
- **Modal dialogs block the script thread** (the request times out, `/session/status` shows `busy`):
  certificate-expiry on login, logout-on-close, "no connection to device". Ask the user to clear them; the
  script then completes.
- Build: `app.build()`, then read `system.get_message_categories(True)` / `system.get_message_objects(cat)`
  (severity, text).

## Connecting to the site PLC

- The PLC's IP is in the project: `<PLC>_NetConfig` parameters `ET1: IP Address` (and the device address's
  last two groups, `0A02.281E` = 10.2.40.30). Check reachability first: ping and TCP 11740.
- A downloaded project carries its author's gateway GUID, so login fails with "Gateway not configured
  properly". Rebind the copy to the local gateway:
  `plc_device.set_gateway_and_ip_address(gateway, "<ip>", 11740)` with `gateway` from
  `scriptengine.online.gateways` (here `Gateway-1`), then save.
- Login: `on = scriptengine.online.create_online_application(app)`;
  `on.login(OnlineChangeOption.Keep, False)`. `Keep` never downloads. If `read_value` on project variables
  works afterwards, the PLC's application matches the project.

## Reading Modbus state online

- `on.read_value(name)` reads one value; over the site link each read takes roughly 0.2–0.5 s, so sample a
  short list.
- Per slave (instance name = device name): `<slave>.byModbusError` (`RESPONSE_SUCCESS`, `RESPONSE_TIMEOUT`,
  `ILLEGAL_DATA_ADDRESS`, … ; `UNDEFINED` = no request completed: disabled, in flight, or a broken channel),
  `.xError`, `.xDone`, `.xBusy`.
- **Unmapped channels are readable as raw input words:** `on.read_value("%IW12")`. Get each channel's
  address from `device.export_io_mappings_as_csv(path)` (columns: mapped variable, parameter, unit,
  description, IEC address, device). An empty first column means the channel is mapped to nothing, and the
  program never sees its data.
- The Modbus master keeps polling and `%IW` keeps updating while the application is stopped.
- `parameter.read_online_value()` fails with "Gateway not configured properly" even while logged in; read the
  instance variables instead.

## Inspecting and changing Modbus configuration

Walk `proj.get_children(True)`; for each device, `connector.host_parameters` gives `id`, `name`, `value`, and
struct fields by index (`p[i].value`). Serial Modbus parameter IDs:

| Object | ID | Meaning |
|---|---|---|
| COM port (`Modbus_COM_*`) | 9200 / 9202 / 9203 / 9204 | baud / parity / data bits / stop bits |
| | 9206 | ComPort: 1 = RJ12, 2 = terminal block (P2CDS-622) |
| Master (`Modbus_Master_COM_Port*`) | 9001 / 9002 / 9005 | response timeout ms / time between frames ms / auto-restart |
| Slave | 9100 / 9101 | slave address / response timeout ms (overrides the master's) |
| Slave channel | `0xSS100000` | config: FC, read offset, read length, write offset, write length, trigger (5 cyclic, 6 rising edge), cycle ms, error handling |
| | `0xSS44OOOO` | that channel's I/O parameter; the ID carries the register offset |
| CPU | 8000 / 8001 | RJ12 / terminal-block serial mode (`16#0003` = RS485) |

- Changing scalars (`p.value = "500"`), cycle time (`p[6].value`) and `device.disable()` in place works.
  Changing a channel's offset, length or function code by script breaks it; see "A channel's shape can't be
  changed by script in place" in [modbus-bench.md](modbus-bench.md).
- Map channels by editing an exported I/O CSV's first column to `Application.<GVL>.<variable>` and
  `device.import_io_mappings_from_csv(path)`; re-export to confirm. A mapped variable that no code reads stays 0
  unless `device.driver_info.always_update_variables = scriptengine.AlwaysUpdateVariablesMode.AlwaysInBusCycle`
  (master and slaves). To prove data reaches variables without touching program logic, map to a throwaway GVL.
- Before mapping into program variables, check the program's scaling against its setpoints: raw words mapped
  into a ×1.0 conversion can trip interlocks the moment the application runs.

## Known sites

| Site PLC | Address | Notes |
|---|---|---|
| DEH (P2CDS-622, `PLC_DEH_*.project`) | 10.2.40.30 (ETH1), .31 (ETH2) | Reachable from the office desktop. COM_TB: pH controllers 41–49, GA-180 gas 111–112, 9600 8N1. Since 2026-11-10 it runs `PLC_DEH_11_10_2026_comtb_fix.project` (see the report). |
