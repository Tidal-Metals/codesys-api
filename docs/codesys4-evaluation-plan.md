# CODESYS 4 evaluation plan

Question: is CODESYS 4 an easier target for agents than the CODESYS 3 automation in this repo
(`HTTP_SERVER.py` → file queue → IronPython `PERSISTENT_SESSION.py` inside a running IDE)? Answer it with
measurements on this desktop and the bench PLC, then decide what to build.

Written 2026-10-21 against CODESYS 4 1.0.0.0 (released 2026-09-24). Releases come every 6–8 weeks with
no service packs, so re-check the "known limits" list against the release notes before each phase.

## What CODESYS 4 1.0 is

From the vendor docs and two hands-on reviews (sources at the end):

- **Projects are folders of UTF-8 text.** ST as text, structured data as JSON, device descriptions as XML.
  `.fbsdev` device project, `.fbslib` library, `.fbsws` workspace; `ProjectInfo.json`, `DeviceTree.json`,
  `TaskConfiguration.json`, `Communication.settings.json`, `Libraries.json` + `Libraries.lock.json`
  (pinned versions, SHA384). One file per object, so agents edit files directly.
- **`c4-cli` runs headless and exits.** Known commands: `library resolve|check|save-compiled|pack`,
  `librepo install`, dependency `install|restore`, `bootapp compile`, workspace creation, controller
  login/logout/reset. No published command reference yet; whether it can download or read variables is
  unknown. Build machines need no license.
- **No scripting interface.** The replacement for `scriptengine` is file access plus `c4-cli`.
- **Same compiler, libraries, runtime and gateway as CODESYS 3.** Library projects open in both;
  `.compiled-library` files from CODESYS 4 work in CODESYS 3 projects. Device projects need a conversion
  tool that isn't released yet.
- **Free until the end of 2028.**

Also documented: Control SL runtimes only (third-party devices "technically possible, no guarantee",
installable as Content Extensions from 1.1), Modbus TCP as the only fieldbus, online monitoring without
write or force, ST and LD only, minimum runtime V3.5 SP19, and no TLS or certificate authentication for
PLC communication.

## Requirements coverage

Everything our PLC programs use today, from this repo, the BCNF field project and the bench. "Documented"
is what the 1.0 sources say; Phase 1 replaces each with a tested answer.

| Need | Where we use it | CODESYS 4 1.0, documented | Risk |
|---|---|---|---|
| P2CDS-622 as the target | bench and every field PLC | not supported: third-party device, no Content Extensions until 1.1 | blocker |
| Field I/O: Productivity2000 I/O modules on the CPU base | field PLCs | needs AutomationDirect's device package and I/O driver, which is third-party | blocker |
| Modbus TCP client (native device tree) | gateways to RTU units, `Modbus_TCP_Client` | supported | low |
| Modbus TCP server (PLC as server) | `Modbus_TCP_Server`, `modbus_tcp_server_canonical_coils` | Modbus TCP Server and Server Device supported | low |
| Modbus RTU master, native (`Modbus_COM` under a serial port) | BCNF RS485 channels, bench COM2/RJ12, VFDs | not supported (TCP only) | high |
| Modbus RTU via ModbusFB + SysCom library | `modbusfb_single_connection`, serial ModbusFB tests | not mentioned; libraries are "unchanged", so it may resolve | medium |
| ModbusFB over TCP (`FB_BusLine`) | ModbusFB benchmarks | not mentioned | medium |
| MQTT 1.2.0.7 (Stefan Dreyer) and PRO JSON 1.0.0.16 (Pro Electric) | `PRG_Comms`, `mqtt_large_payload` | not mentioned; both are third-party libraries, MQTT ships as source (`mqtt2.library`) | medium |
| Dynamic memory (Application properties › Build) | required by the MQTT library | not mentioned; find where it lives in the project files | medium |
| SNTP Service SL, SysTimeCore, SysTimeRtc | `ClockSync`, scan timing | not mentioned (libraries) | low |
| Two cyclic tasks with priorities | `PRG_Control` 50 ms, `PRG_Comms` 100 ms | `TaskConfiguration.json` | low |
| RETAIN / PERSISTENT variables | `PRG_Control.ApplyCommands` | not mentioned (language feature) | low |
| `io_always_mapping` and I/O mapping of device channels | `docs/modbus-bench.md` | channel creation and I/O variable assignment documented; the parameter isn't | medium |
| Download, start, stop | bench API, field deployments | from the UI; CLI unknown (`bootapp compile` exists) | medium |
| Online read, write, watch | `/plc/online/{read,write,watch}` | monitoring only; no write or force | high |
| Encrypted PLC communication, certificates | SP22 runtimes ask to trust certificates (`docs/modbus-bench.md`) | not supported in 1.0 | high if the runtime enforces it |
| Remote IDE access through the gateway | `FIELD_ACCESS.md` | CODESYS Gateway 3.5+ supported | low |

Two blockers mean CODESYS 4 1.0 can't replace CODESYS 3 for field PLCs, unless the P2CDS-622 package
loads as an unsupported device. Phase 1 tests that first because it decides how far the rest goes.

## Rules for every phase

- Install CODESYS 4 side by side. Don't touch CODESYS 3.5.22.10, the API on 8081 or its CODESYS session
  (restart rules are in memory: hard-terminate, never Ctrl+C).
- Work under `examples/codesys4/` (projects, scripts, results). Keep `c4-cli` versions in every result file.
- The bench PLC is shared. Reserve it (`POST /api/v1/bench/reservations`) before any login or download,
  and follow `docs/modbus-bench.md`. Never open a COM port the simulator manager owns.
- Each phase ends with a short results section appended to this file: what worked, what didn't, numbers.

## Phase 0: install and inventory

1. Install the CODESYS 4 Windows x64 package from the CODESYS Store, plus the .NET 8 desktop and
   ASP.NET Core 8 runtimes it asks for.
2. Dump the full `c4-cli --help` tree (every subcommand's help) to `docs/codesys4/cli-reference.md`.
3. Record the bundled compiler version and compare it with the CODESYS 3 install's (3.5.22.10).

Done when: the CLI reference exists and these questions have a yes/no answer from the help text: can
`c4-cli` download an application, start/stop it, read or write variables, create a device project, and
emit diagnostics as JSON or `file:line`?

## Phase 1: requirements check

Desk checks, no PLC or bench equipment. Add a "Tested" column to the requirements matrix and fill it in.

1. **Target and field I/O.** Find the AutomationDirect P2CDS-622 package in the CODESYS 3 install (device
   repository and its I/O module descriptions). Load it into a CODESYS 4 device project as a project-local
   device. Add a Productivity2000 digital input and analog input module under the CPU base, as the field
   projects do. Record whether the device, the I/O modules and their parameters appear, and whether the
   project compiles.
2. **Read the P2CDS-622's runtime version and security settings** from the CODESYS 3 device page (read
   only, no reservation needed). Below SP19, or with encrypted communication enforced, CODESYS 4 1.0
   can't connect.
3. **Libraries.** Add MQTT (Stefan Dreyer), PRO JSON, ModbusFB, SysCom, SNTP Service SL, SysTimeCore and
   SysTimeRtc to `Libraries.json` at the versions the CODESYS 3 projects use, and run `resolve`. Copy them
   from the CODESYS 3 library repository through `LibraryRepositories.prefs.json` if they aren't found.
4. **Device tree.** Look for a serial port and `Modbus_COM` in the device catalogue (expected: absent),
   the Modbus TCP Client, Server and Server Device, and the `io_always_mapping` parameter.
5. **Project settings.** Find dynamic memory, task priorities and RETAIN/PERSISTENT support in the files a
   new device project contains.

Done when: every row of the matrix has a tested answer (works, missing, or works with a workaround, with
the workaround named). If the P2CDS-622 or its I/O modules don't load, or its runtime is older than SP19
or enforces encrypted communication, CODESYS 4 can't run the field PLCs in 1.0. In that case do Phase 2
(library builds) and Phase 6, and skip Phase 4 (the bench PLC) until 1.1.

## Phase 2: headless library build (the supported path)

Port `examples/plc_architecture/st/` (via its `manifest.json`) into a `.fbslib` library and build it with
`library resolve` → `check` → `save-compiled`.

Compare against `examples/plc_architecture/check_compile.py`:

- Wall time for a clean build and for a one-file change.
- Same errors and warnings? Seed three faults (type error, undeclared variable, the `Mqtt`/`MQTT` name
  clash from the architecture guide) and check each message names the file and line.
- Byte-identical output from an unchanged source tree (the generator rule).
- Two builds in parallel in separate workspaces. The CODESYS 3 path can't do this: one IDE session.

Then reference the compiled library from a CODESYS 3 project and compile that with `check_compile.py`.

Done when: the table of numbers is written, and either the compiled library builds in CODESYS 3 or the
failure is recorded. A pass here already justifies a hybrid: generators emit text, CODESYS 4 compiles it
headless, CODESYS 3 projects consume the library.

## Phase 3: device project on the local soft PLC

Target `CODESYS Control Win V3 - x64` (installed as a service). Confirm with the user that nothing else
uses it before starting it.

This proves at runtime what Phase 1 proved by compiling: each feature works, not only builds.

1. Create one device project in the browser UI: the skeleton's two tasks, a Modbus TCP client to
   `modbus_tcp_slave_sim.py` on localhost, a Modbus TCP server, the MQTT library with dynamic memory
   enabled, SNTP clock sync, and a PERSISTENT variable.
2. Read every file the UI wrote. (In CODESYS 3 dynamic memory isn't scriptable at all.)
3. Delete the project and regenerate it from a script that writes only files. Diff against the UI's copy.
4. `bootapp compile`, then login, download and run, from the CLI if Phase 0 found the commands, otherwise
   from the UI.
5. Check each feature: Modbus values with the existing verifiers, a PC client reading the PLC's Modbus
   server, MQTT messages at the broker (the `examples/mqtt_large_payload/` verifiers), the clock after
   sync, the PERSISTENT value after a runtime restart.
6. If ModbusFB and SysCom resolved in Phase 1, run ModbusFB RTU on a spare USB-RS485 adapter against an
   RTU simulator (reserve the adapter; never a COM port the simulator manager owns).

Done when: a project written entirely by a script compiles, downloads and runs, and each feature in step 5
has a pass or fail, or the first step that needs the UI is identified.

## Phase 4: bench PLC (the go/no-go gate)

Only if Phase 1 loaded the P2CDS-622 device and found a supported runtime version.

1. Retarget the Phase 3 project to the P2CDS-622, with the bench's real I/O modules if any are fitted.
2. Compile it.
3. Reserve the PLC. Record which CODESYS 3 project is loaded (`GET /api/v1/bench`) so it can be
   restored.
4. Download and run the bench topology over Modbus TCP: the gateways' 11 servers, per-unit error flags.
   Check with `verify_modbus_bench.py` and the bus measurement tools; compare request rates with the
   ModbusFB/native numbers in `docs/modbus-bench.md`.
5. Run MQTT publishing and clock sync as in Phase 3. Read any fitted I/O module's inputs and drive one
   output.
6. Try ModbusFB on the RJ12 serial port, if it worked in Phase 3.
7. Re-download the recorded CODESYS 3 project with the API, confirm it runs, release the reservation.

Done when: the bench PLC runs a CODESYS 4 build and the topology checks pass, or the blocking step is
recorded (device description, compiler/runtime mismatch, gateway login). Then the CODESYS 3 application
is running again.

## Phase 5: online access without an IDE

CODESYS 4 can't write or force, and has no scripting. Test runtime-side access that needs no IDE:

- OPC UA server on the runtime with a symbol configuration (find out whether CODESYS 4 can author one),
  read and written with `asyncua` from Python 3.
- Failing that, a Modbus TCP server device in the project exposing command and status registers. This
  matches the architecture's command path: commands are values with ids, checked in `PRG_Control`.

Done when: read, write and a 100 ms watch of 50 tags work from Python against the local soft PLC (and the
bench PLC if Phase 4 passed), with measured latency.

## Phase 6: decision

Two inputs. First, the requirements matrix with every "Tested" cell filled in. Second, how easy CODESYS 4
is for agents compared with the CODESYS 3 path:

| Agent ergonomics | CODESYS 3 today | CODESYS 4 |
|---|---|---|
| Edit project as files, reviewable diffs | no (binary `.project`) | |
| Headless compile, no IDE session | via IronPython in a GUI process | |
| Parallel builds | no | |
| Compiler messages with file and line | | |
| Download / start / stop headless | yes (API) | |
| Online read/write/watch headless | yes (API) | |

Compare also with the CODESYS 3 MCP Server (Professional Developer Edition, needs 3.5.22.1+, 30-day
demo): it reads, writes and compiles ST in CODESYS 3 projects for an LLM, without changing the target.

Outcomes:

- **Hybrid** (likely if Phase 2 passes and the matrix has a blocker): CODESYS 4 compiles generator output
  into libraries headless; CODESYS 3 and this API keep device projects, field I/O, RTU, download and
  online access.
- **Full move** (no blockers left in the matrix, Phases 2–5 pass): add a `c4` backend to the API that
  wraps `c4-cli` in Python 3 with one workspace per job, and retire the file queue and IronPython for
  those projects.
- **Wait** (Phase 2 fails): record why and re-run Phases 0–2 on the next release, 1.1 in particular
  (third-party devices as Content Extensions).

Done when: the table is filled in and a person has picked an outcome.

## Results

### Phase 0 (2026-10-21): blocked on the installer

.NET 8.0.32 (NETCore, AspNetCore, WindowsDesktop) is already installed. CODESYS 4 isn't in the CODESYS
Installer, and codesys.com and store.codesys.com answer scripted requests with 429/503, so the installer
has to be downloaded through a browser with a CODESYS account.

### Phase 1, desk checks done without CODESYS 4 (2026-10-21)

- **P2CDS-622 package.** `C:\ProgramData\CODESYS\Devices` holds 62 AutomationDirect (vendor 1767)
  descriptions: the CPU (`4096/1767 0001`, 1.1.11.0 and 1.1.13.0), `P2CDS622_NetConfig`,
  `P2CDS622_SystemTags`, and 57 P2 I/O modules (discrete, relay, analog, RTD, thermocouple, PWM). All
  are plain unsigned `device.xml`, one file per device. Inventory: `examples/codesys4/inventory_p2_devices.py`, output `p2_devices.txt`.
- **The I/O driver runs in the PLC firmware.** The CPU's `DriverInfo` needs only `IoStandard` and
  `3SLicense`; the bases declare `needsBusCycle` with backplane connectors; the I/O modules reference no
  libraries. The IDE side of field I/O is XML plus two system libraries. That is the best case for
  loading it as a project-local device. NetConfig and SystemTags each need an AutomationDirect library
  (`IoDrvP2cds622NetConfig`, `IoDrvP2cds622SystemTags` 1.0.0.0, in Managed Libraries).
- **Runtime version.** The 1.1.13.0 description declares `runtime_identification/version` 3.5.19.0,
  exactly the CODESYS 4 minimum. It advertises `encrypted_download_supported`; whether the bench PLC
  enforces encrypted communication needs an online check (the bench API wasn't running).
- **Libraries are all present locally** (`C:\ProgramData\CODESYS\Managed Libraries`): MQTT 1.2.0.7
  (Stefan Dreyer, source), PRO JSON 1.0.0.16, ModbusFB 4.5.0.0 (compiled), SysCom, SysComAsync and
  SysTimeCore 3.5.17.0, SysTimeRtc 3.5.17.0/3.5.22.0, SNTP Service SL 1.9.0.0, IoStandard 3.5.17.0/3.5.22.0,
  Net Base Services, 3SLicense.

## Sources

- [CODESYS 4 product page](https://www.codesys.com/products/engineering/codesys-4/)
- [CODESYS 4 online help: start page](https://content.helpme-codesys.com/en/CODESYS%204/_c4_start_page.html)
  and [switching from CODESYS 3](https://content.helpme-codesys.com/en/CODESYS%204/_c4_start_page-2083130.html)
- [Release announcement](https://us.codesys.com/company/news-center/latest-news/codesys-4-version-1000-is-available/)
- [soup01 walkthrough (supported runtimes, Linux server install)](http://soup01.com/en/2026/09/28/codesyscodesys4-version-1-0-0-0-has-been-released/)
- [disorder.dk hands-on review](https://disorder.dk/wonderware/2026/09/30/codesys-4-is-released/)
- [ControlByte overview (CLI commands, limits)](https://controlbyte.tech/blog/codesys-4-web-based-iec-61131-3-ide/)
- [codesys4-headless-automation (library CLI pipeline)](https://github.com/angleyanalbedo/codesys4-headless-automation)
- [CODESYS Development System MCP Server](https://www.codesys.com/ecosystem/release-lifecycle/releases-updates/development-system-mcp-server/)
