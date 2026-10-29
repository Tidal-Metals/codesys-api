# Agent-ready CODESYS IDE for PLC project preparation

Set up a CODESYS 3.5 workstation that a coding agent can use to prepare production PLC code and configuration for engineering review. Give the agent the equipment requirements, device manuals and register maps, and field I/O list. It can inspect or create a project, configure devices, write Structured Text, map signals, and compile a review candidate through the IDE's scripting API.

The workstation runs a Python HTTP API and a persistent script inside CODESYS. An agent with shell or HTTP access can use them without driving the IDE's menus. No agent-specific plugin is required.

- [Installation](#installation): prepare the Windows workstation.
- [Getting started](#getting-started): connect the agent and open a working project.
- [Prepare a production project for review](#prepare-a-production-project-for-review): turn device documentation and I/O requirements into a review candidate.
- [Documents to give your agent](#documents-to-give-your-agent): reading order and references.

## Installation

### 1. Prepare the workstation

Install these on the Windows PC that will run CODESYS:

- Git and Python 3.11 or later, with the `py` launcher available in PowerShell.
- CODESYS 3.5 with scripting support. The recorded working installation is **V3.5 SP22 Patch 1**, at `C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe`. Match the IDE/compiler version required by your project.
- The target PLC's device packages and the exact library versions the project requires. Confirm that **Tools → Scripting → Execute Script File** is available in the IDE.

You need access to the Tidal Metals GitHub repository. For eventual commissioning, the workstation also needs a network path to the PLC and its CODESYS gateway. Project preparation and compilation can be done before connecting to hardware.

This repository supplies the automation bridge, API reference, and supporting sources. Supply your own production project or target-specific starting template, device packages, and libraries. Projects referenced under `../codesys_projects/` and the separate MQTT library repository are not included in a clone.

### 2. Clone and install Python dependencies

Run in PowerShell:

```powershell
git clone https://github.com/Tidal-Metals/codesys-api.git
cd codesys-api
py -3 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

The commands below call the virtual environment's Python directly, so activating it or changing PowerShell's execution policy is unnecessary. Open subsequent terminals in this repository folder.

`pymodbus` and its serial dependency are required by the server's imports even when you are only editing projects. The requirements file pins the PyModbus version checked for API startup and project preparation. The optional Windows service wrapper additionally needs `pywin32`; it is not required for the interactive IDE workflow below.

### 3. Configure the IDE path and listener

Edit [server_config.py](server_config.py):

```python
CODESYS_PATH = r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe"
CODESYS_PROFILE = "CODESYS V3.5 SP22 Patch 1"
SERVER_HOST = '127.0.0.1'  # Agent runs on this workstation
SERVER_PORT = 8080
```

Set the path and profile to your installed IDE. For an agent on another machine, select the workstation's LAN interface or `0.0.0.0`, allow the chosen TCP port through the Windows firewall for that network, and give the agent the workstation's reachable address. The API uses plain HTTP and an `Authorization: ApiKey ...` header; use it on your trusted network.

On first start, a checkout without `api_keys.json` creates the development key `admin`. To use another key, create that file before starting the server:

```json
{
  "YOUR_CHOSEN_KEY": {"name": "PLC engineering"}
}
```

Use your chosen key in the examples below. `api_keys.json` is Git-ignored. See [existing-IDE LAN setup](FIELD_ACCESS.md) for a command that generates a random key.

### 4. Check the Python setup

```powershell
.\venv\Scripts\python.exe -c "import HTTP_SERVER; print('API imports OK')"
```

This checks dependencies without launching CODESYS. For optional service administration and further installation notes, see [Installation Guide](INSTALLATION_GUIDE.md).

## Getting started

### 1. Start the API and CODESYS bridge

For a workstation where the API will launch its own IDE session:

```powershell
.\venv\Scripts\python.exe HTTP_SERVER.py
```

Leave this terminal open. This starts the HTTP listener. In a second PowerShell terminal, set the connection details and request the CODESYS session:

```powershell
$BaseUrl = 'http://localhost:8080/api/v1'
$Headers = @{ Authorization = 'ApiKey admin' }

Invoke-RestMethod -Uri "$BaseUrl/system/info" -Headers $Headers
Invoke-RestMethod -Method Post -Uri "$BaseUrl/session/start" -Headers $Headers -ContentType 'application/json' -Body '{}' -TimeoutSec 180
Invoke-RestMethod -Uri "$BaseUrl/session/status" -Headers $Headers
```

The start request launches CODESYS with `PERSISTENT_SESSION.py` and the configured profile, or attaches to an existing bridge. Allow time for the IDE to initialize. A successful setup returns `success: true` from session start and reports an active session from session status. An open project is not required yet. A response from `/system/info` alone only confirms the HTTP server.

If port 8080 is occupied, start the server with an explicit port instead:

```powershell
.\venv\Scripts\python.exe serve_on_port.py --port 8081
```

Then set `$BaseUrl = 'http://localhost:8081/api/v1'` in the client terminal.

**Already have an IDE/project open?** In that IDE, run this checkout's `PERSISTENT_SESSION.py` using **Tools → Scripting → Execute Script File**, then start:

```powershell
.\venv\Scripts\python.exe field_api_server.py --host 127.0.0.1 --port 8081
```

Use port 8081 in the client commands. This mode leaves launching and closing the IDE to the operator. Follow [FIELD_ACCESS.md](FIELD_ACCESS.md) for LAN access. Run one bridge and one API server per checkout; both communicate through that checkout's request files.

### 2. Give the agent its workspace and task

The agent needs shell access on the workstation or HTTP access to the running API. Give it:

- The repository path, API base URL, and API key through your private agent session.
- The working project or starting template path **on the IDE workstation**, target PLC model, IDE/compiler version, and required packages/libraries.
- Equipment requirements, device manuals/register maps, the field I/O list, and any existing source, electrical drawings, and control narrative.
- A directory for the review candidate and evidence, plus the boundaries of the assignment, including whether any hardware operations are authorized.

An agent running remotely must transfer any project or script files to the workstation before asking the IDE to open them. HTTP project paths are workstation paths. Point it at the [documents below](#documents-to-give-your-agent) before it starts.

A starting task can be:

> Use the CODESYS API in this checkout to prepare a production project for engineering review. Start from the supplied project/template and work in a review copy. Read the control narrative, field I/O list, and device register documentation. Configure the specified Modbus TCP and RTU devices, map field signals to named variables, and implement the required control logic. Record manual page references, address conventions, data types, byte/word order, scaling, and unresolved questions. Compile the candidate, save it with readable source/configuration exports and build results, and explain what still requires hardware verification. This assignment ends at the review package; downloading or starting a PLC requires a separate instruction.

### 3. Open a review copy of the project

For an existing project, replace the source path below with your actual file. Run these commands on the IDE workstation. Choose a new review directory for each candidate:

```powershell
$SourceProject = 'C:\PLC-Projects\Plant\Plant.project'
$ReviewDir = Join-Path $env:USERPROFILE 'PLC-Reviews\Plant-candidate-01'
New-Item -ItemType Directory -Path $ReviewDir -ErrorAction Stop | Out-Null
$ProjectPath = Join-Path $ReviewDir 'Plant-review.project'
Copy-Item -LiteralPath $SourceProject -Destination $ProjectPath

$Body = @{ path = $ProjectPath } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$BaseUrl/project/open" -Headers $Headers -ContentType 'application/json' -Body $Body -TimeoutSec 180
Invoke-RestMethod -Uri "$BaseUrl/session/status" -Headers $Headers
Invoke-RestMethod -Uri "$BaseUrl/pou/list" -Headers $Headers -TimeoutSec 60
```

Confirm the reported active project path is the review copy. If the desired project is already open through the existing-IDE workflow, inspect that session first rather than reopening it. For a new application, use your target-specific template; `POST /project/create` accepts `path` and an optional `template_path`. A generic empty project still needs its target device, application, and task configuration.

### 4. Let the agent inspect and edit through the IDE

Use the API to list/read/write POUs, configure supported devices, and compile projects. For operations beyond the HTTP endpoints, submit a CODESYS script through `POST /api/v1/script/execute`. On the workstation, a local script can also use the same running bridge:

```powershell
.\venv\Scripts\python.exe run_ide_script.py C:\PLC-Projects\inspect_project.py --timeout 120
```

Scripts submitted to the IDE run in **IronPython 2.7**, independently of the Python 3 server. They can import `scriptengine` and should assign a JSON-serializable `result` dictionary with a `success` field. For example, this script reports the open project's top-level objects:

```python
import scriptengine

project = scriptengine.projects.primary
if project is None:
    result = {"success": False, "error": "No open project"}
else:
    result = {
        "success": True,
        "project_path": project.path,
        "objects": [obj.get_name() for obj in project.get_children(False)]
    }
```

The local runner requires `PERSISTENT_SESSION.py` to be running from the same checkout. The agent should consult the bundled [scriptengine stubs](ScriptLib/Stubs/scriptengine/) for device-tree, parameter, mapping, export, and library APIs. Use the exact object paths returned by project inspection instead of assuming names such as `Device/Application/PLC_PRG`.

## Prepare a production project for review

### Ingest the device and field I/O documentation

Supply the manuals with their model/revision, register tables, electrical I/O schedule, PLC/module part numbers, network and serial topology, and intended control behavior. The agent should turn these into an explicit configuration table before applying them to the project. Missing details belong in the review's open questions.

| Area | Configuration the agent should derive and record |
| --- | --- |
| Modbus TCP | Device IP/port, unit ID, direct TCP or TCP-to-RTU gateway topology, function codes, polling groups, periods, timeouts, and reconnect behavior |
| Modbus RTU | PLC serial port/interface, RS485 wiring assumptions, baud, parity, data/stop bits, unit IDs, polling periods, timeouts, and retry behavior |
| Register interpretation | Manual page/table, documented address, zero-based protocol offset, read/write function, register count, signedness, bit fields, byte/word order, scaling, units, and valid range |
| Field I/O | Rack/slot/module/channel, electrical signal type such as DI/DO or 4–20 mA, named PLC variable, raw and engineering ranges, polarity, fault detection, and output state on startup or fault |
| Application behavior | Scan/task assignments, equipment sequences, permissives, interlocks, command handling, communications-loss behavior, alarms, and operator overrides |

For example, a manual's holding-register label `40001` often corresponds to protocol offset `0`; confirm that manual's convention before configuring a channel. A 32-bit value may span two 16-bit registers, and its word order and scale must come from the device documentation. Reading a number successfully does not establish that it represents the intended measurement.

### Build the candidate in CODESYS

The agent uses the target's installed device definitions to build the device tree, set TCP/RTU communication parameters, configure channels and I/O mappings, and create or update the application's Structured Text. It should cross-check the saved configuration and source against the input tables, including read/write direction, address overlap, and units.

The native Modbus channel endpoints in this repository currently build **serial** server devices. Native TCP configuration may require CODESYS scripts or native imports through the same bridge; consult the installed device definitions and API stubs rather than assuming the serial endpoints configure both. For project structure and source generation rules, use [PLC architecture guidance](docs/plc-architecture-for-agents.md).

### Compile, save, and hand off

After the agent has applied the intended changes, rebuild and capture the result in the review directory created above:

```powershell
$Build = Invoke-RestMethod -Method Post -Uri "$BaseUrl/project/compile" -Headers $Headers -ContentType 'application/json' -Body '{"clean_build":true}' -TimeoutSec 180
$Build | ConvertTo-Json -Depth 30 | Set-Content -Encoding UTF8 (Join-Path $ReviewDir 'compile-result.json')
$Build | ConvertTo-Json -Depth 30

$Save = Invoke-RestMethod -Method Post -Uri "$BaseUrl/project/save" -Headers $Headers -ContentType 'application/json' -Body '{}' -TimeoutSec 60
$Save | ConvertTo-Json -Depth 10
```

Check the response's `success` field and the returned errors and warnings. An HTTP response by itself is not proof of a successful build or save. Preserve failed build results too; if PowerShell reports an HTTP error, capture its response body and resolve the diagnostics before calling the candidate ready.

The engineering handoff should contain:

- The saved candidate `.project` or project archive, with the IDE/compiler, target device, and library versions needed to reopen it.
- Readable source and configuration exports, a change summary, and the input-to-configuration tables with manual page references.
- The full compile result, explanations for remaining warnings, and the checks performed against the saved candidate.
- Open assumptions and questions, plus the commissioning checks still needed on physical I/O and devices.

A compiled candidate is ready for review; it still needs physical verification of wiring, signal scaling, device responses, and equipment behavior. Downloads, online changes, output writes, and starting an application are separate commissioning actions. The API supports them when that work is authorized.

## Documents to give your agent

Tell the agent to read these in order, then supply the equipment-specific inputs alongside them:

| Document or reference | When and why to read it |
| --- | --- |
| [README.md](README.md) | First: workstation setup, bridge operation, and the production review workflow. |
| [CLAUDE.md](CLAUDE.md) | All coding agents: repository layout, startup commands, Python/IronPython boundary, and project conventions. The filename does not limit it to Claude. |
| [FIELD_ACCESS.md](FIELD_ACCESS.md) | When attaching to an existing IDE or connecting over the LAN: session setup and key generation. |
| [openapi.json](openapi.json) and the running server's `/docs` | HTTP routes, request fields, and response schemas. Match the host/port to your server. |
| [ScriptLib/Stubs/scriptengine/README.txt](ScriptLib/Stubs/scriptengine/README.txt) and the adjacent stubs | CODESYS object model for project/device trees, parameters, I/O mapping, libraries, and exports. Consult before inventing scripting calls. |
| [CODESYS_SCRIPT_COMPATIBILITY.md](CODESYS_SCRIPT_COMPATIBILITY.md) | Syntax constraints for scripts executed inside the IDE. |
| [docs/plc-architecture-for-agents.md](docs/plc-architecture-for-agents.md) | Before writing Structured Text or generators: control/comms separation, tag tables, quality, interlocks, and command handling. |
| [examples/plc_architecture/README.md](examples/plc_architecture/README.md) and its `st/` sources | Concrete reference code for the architecture rules; adapt it to the production application's requirements. |
| [templates/modbus_device_driver_sample.json](templates/modbus_device_driver_sample.json) and [modbus_device_driver_runner.py](modbus_device_driver_runner.py) | Serial device/channel/mapping manifest format and its application code. Replace the sample's simulated-device settings with the production configuration. Inspect `--dry-run` output first and use `--skip-simulator` when applying configuration for real devices. |
| Device register manuals, field I/O schedule, electrical drawings, and control narrative supplied for the job | The sources of truth for the particular equipment: identify revisions and cite pages/rows in the review package. These are project inputs, not bundled documentation. |

`CODESYS_API_GUIDE.md` and `PROJECT_SUMMARY.md` are historical implementation notes. For exact calls, use the current API schema, stubs, and working code. Bench guides and MQTT tests are supporting validation references when relevant to an assignment.

## API and scripting reference

Interactive API documentation is served at `http://localhost:8080/docs`, with the schema at `/openapi.json`. Substitute your configured host and port. Requests under `/api/v1` use `Authorization: ApiKey YOUR_KEY`.

| Task | Operations under `/api/v1` |
| --- | --- |
| IDE session | `POST /session/start`, `GET /session/status`, `POST /session/stop` |
| Projects | `POST /project/create`, `/project/open`, `/project/save`, `/project/close`, `/project/compile`; `GET /project/list` |
| Source and variables | `GET /pou/list`, `GET /pou/code?path=...`, `POST /pou/create`, `POST /pou/code`, `GET /variables`, `POST /variables/upsert` |
| Device configuration | Modbus device/channel/mapping routes in the API schema; CODESYS scripting for other device operations |
| Custom IDE work | `POST /script/execute`; jobs under `/jobs` for longer operations |
| PLC commissioning | Target/gateway discovery, binding, deploy validation/download, online reads/writes, and application control; see schema for payloads |

`POST /pou/code` takes an object `path` and `declaration`, `implementation`, or both. `POST /script/execute` takes `script` and an optional `timeout` in seconds. The synchronous timeout is capped at 300 seconds; longer work belongs in jobs.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `ModuleNotFoundError` at startup | Use the virtual environment's Python and reinstall `requirements.txt`. |
| Port bind error or connection refused | Check the listener/port; use `serve_on_port.py --port 8081` and update the client's base URL. |
| HTTP 401 | Match the header key to a key in `api_keys.json`; restart the server after editing that file. |
| API responds but IDE work times out | Confirm that the persistent script runs in the intended IDE from this checkout and that no modal dialog is blocking it. Check `session.log`. |
| Session will not start | Check `CODESYS_PATH`, `CODESYS_PROFILE`, scripting support, and `codesys_api_server.log`. |
| Missing devices or libraries on open/build | Install the versions required by the project on the IDE workstation. |
| A project edit is rejected while online | Log out of the PLC application before changing its configuration or source. |

Stopping `HTTP_SERVER.py` with Ctrl+C also calls its IDE process manager's stop routine. Use `field_api_server.py` when the operator should retain control of IDE lifetime. Save the candidate before ending the managed session.

## Supporting documentation

- [Installation and service notes](INSTALLATION_GUIDE.md)
- [Modbus bench procedures](docs/modbus-bench.md) and [historical bench setup](docs/modbus-bench-history.md)
- [Go RTU simulator](tools/modbus-rtu-sim/README.md)
- [MQTT validation examples](examples/mqtt_large_payload/README.md)

## License

[MIT](LICENSE).
