# PLC Modbus TCP/RTU bench — agent guide

How the CODESYS PLC, the Ebyte TCP-to-RTU gateways, the PC's RS485 simulators and this API fit
together, and how to test or change them without breaking another agent's run. Updated
2026-10-20. The state below comes from recorded tests; verify it live before relying on it.

**What is physically wired is data, not prose:** `GET /api/v1/bench` returns a `plc` section (each PLC
port: wired or not, to what, polarity, what has been verified) and the adapters by USB serial. It comes
from `templates/bench_inventory.default.json`. When wiring changes, or a port is proven, update that file in
the same session; a fact left only in chat is lost by the next session.

Gateway internals (web API, enums, save sequence, client limits) live in the device profiles and
are not repeated here:

- [NE2-D11P profile](https://github.com/Tidal-Metals/devices/blob/master/gateways/ebyte-ne2-d11p/README.md): two server sockets, 5 + 5 clients
- [NA111-E profile](https://github.com/Tidal-Metals/devices/blob/master/gateways/ebyte-na111-e/README.md): one server socket, 6 clients

Other references: [Go RTU simulator](../tools/modbus-rtu-sim/README.md),
[ten-unit ModbusFB example](../examples/modbusfb_single_connection/README.md),
[native generation handoff](https://docs.local.tidalmetals.org/documents/projects/scada-greenfield-rewrite/modbus-tcp-generator-handoff/latest/),
[remote IDE access](../FIELD_ACCESS.md). The README's "P2CDS-622 Modbus bench" section is history;
its addresses and baud rates are out of date.

## Topology (last verified 2026-10-20)

```
PLC P2CDS-622-DEV  ETH1 .123 carries all traffic. ETH2 (.125) is unplugged. COM1 (RJ12) is not connected.
 ├─ Modbus TCP → NA111-E            192.168.50.67:502
 │                  └─ RS485 115200 8N1 → COM11 (FTDI BG00XX03) Go worker, units 11–40 (bench/bus_sim.py)
 ├─ COM2 terminal block, 2-wire RS485 9600 8N1 → COM12 (FTDI BG041BD0) Go worker, units 1–10, or a listener
 └─ (2026-09-28 setup, NE2 not on the network on 2026-10-20) Modbus TCP → NE2-D11P 192.168.50.153
                    └─ RS485 115200 8N1 → COM18 (FTDI BG01GGR2) Go worker, units 1–10
```

| Item | Value |
|---|---|
| PC LAN (API server, TCP sim `.108`) | Realtek, `192.168.50.108` |
| PC USB Ethernet (bench test source) | ASIX, `192.168.50.155` DHCP |
| API | `serve_on_port.py --port 8081`; `Authorization: ApiKey <key from api_keys.json>` |
| PLC project | `../codesys_projects/modbus_tcp_bench/modbus_tcp_bench.project` |
| Unit values | COM18: `examples/modbusfb_single_connection/rtu_devices.json` (unit 1 = `[1234,5678]`, unit 2 = `[2222,3333]`, unit *n* = `[n01,n02]`); COM11 unit 11 = `[1101,1102]`. Units 2 and 11 also serve coils 0–9 = `1,0,1,1,0,0,0,1,0,1` (FC01 bytes `16#8D 16#02`), coils 10–47 = 0 and discrete inputs 0–9 = `0,1,1,0,1,0,0,0,1,1` (`16#16 16#03`); `temp/coil_proof/apply_buses.py` applies them |

Until 2026-09-25, COM11 shared the NE2's bus as a second multidrop responder.

**On 2026-09-28 the NE2's DHCP lease had moved from `.151` to `192.168.50.153`** (MAC
`B0-CB-D8-4E-88-BB`), and the PLC application was found stopped. The ten gateway modules were
re-pointed to `.153` (project backup `modbus_tcp_bench.project.before-ip-153-20260928-141217`),
downloaded, started and saved as the boot application. A 60 s check afterwards: 11/11 slaves
connected, all ten units at 1 Hz, 0 new error or bad-value cycles. **The lease is still not
reserved**, so if it moves again the PLC path breaks; `/bench` warns when the gateway's address
differs from `expectedIp`. Always find a gateway by MAC before using an address. A download resets
`PLC_PRG.TenMonitorEnable` to FALSE, which makes the error counters read 0 regardless; set it
TRUE before judging them.

## The PLC's own serial ports (RJ12 = COM1, terminal block = COM2)

- **Port facts:** COM2 in CODESYS is the terminal block, device parameter `8001`, `16#0003` = RS485; COM1
  is the RJ12 jack (parameter `8000`), unused here. The terminal block is 2-wire. On the COM12 adapter the
  PLC's + line is TX+; on an Ebyte device + is A. Reversed polarity shows as bytes at the right times but
  wrong values (`fd f7 fd df` for `01 04 01 90 00 06 71 d9`).
- **Answer (2026-10-20): this bench unit's terminal-block port (COM2) has a faulty receive path. Use the RJ12
  port (COM1) instead.** With the same native configuration, devices and cable moved to the RJ12 jack (RS485:
  pin 3 TXRX+, pin 4 TXRX-, pins 1/6 GND; device parameter 8000 = 16#0003; Modbus_COM ComPort 1), the master polls
  the ME31 every ~140 ms with RESPONSE_SUCCESS. The investigation below is kept for the evidence.
- **COM2 investigation (2026-10-20):**
  The same configuration works in the field (BCNF, `PLC_DEH_10_19_2026`) on other P2CDS-622 units, with
  native Modbus_COM masters. Nothing in the repo shows this bench unit's serial port ever receiving.
  - **Proven working:** the PLC's requests reach the bus intact (adapter sniff); a simulator and a real Ebyte
    ME31 both put correct replies on the bus within 3–50 ms (captured by the adapter).
  - **Proven failing, identically, in every receive path:** native Modbus_COM master (auto-restart on, fresh
    power cycle, no SysCom code in the application): RESPONSE_TIMEOUT every request; ModbusFB ClientSerial
    (every RTS mode); a raw SysCom listener opened both with `SysComOpen2` and with AutomationDirect's own
    `SysComOpen` + `SysComSetSettings` sequence: 0 bytes from 800 sent. The port's **RXD LED never lights**
    while TXD does, so the receiver sees nothing at the hardware level.
  - **Ruled out:** IDE configuration (8001 = `16#0003` RS485 and `SYS_COMPORT2`, identical to
    AutomationDirect's Modbus RTU guide, their `Demo_SerialPassthrough` example, BCNF and PLC_DEH; device
    description 1.1.11.0 and 1.1.13.0 are identical); A/B polarity (both ways); ground (connected); RTS
    mode; baud and parity; COM numbering (vendor docs: COM1 = RJ12, COM2 = 4-pin terminal block); port
    state left over from SysCom use (power-cycled with a native-only application); reply timing (the
    ME31 answers after 30–50 ms).
  - **Measured:** pin 3 (TXRX-) to pin 4 (GND) at idle = +1.08 V, an RS485 level, so the RS485 setting is
    applied (RS232 would sit near -5 V). Pin 2 (TXRX+) = +1.18 V: idle differential +0.1 V, a weak bias,
    but replies are driven at volts and decode cleanly on the adapter, so bias does not explain a dark RXD.
    The receive path inside this unit is the prime suspect.
  - **Not yet tested:** the RJ12 port in RS485 mode (pins 3 +, 4 -, 1/6 GND); this project on another P2CDS-622; the
    bench unit's firmware against the field units'. Record the answer here and in the inventory seed.
- **Check order for a serial problem (would have found this in 20 minutes, not a day):**
  1. Sniff the bus (`sniff_serial.py`, below): are the PLC's requests intact?
  2. Is a known-good device answering on the wire? Put one on the bus and sniff its reply.
  3. Watch the port's RXD LED while the device answers. If the reply is on the wire and RXD stays dark,
     stop debugging software: it is the port, its wiring or its mode.
  4. Only then compare configuration, starting from AutomationDirect's procedure:
     https://docs.codesys-p2cds622.com/en/latest/Example%20Projects/modbus_rtu.html
- **Terminal block pinout (P2CDS-622 insert):** 1 TERMINATE (120 ohm to pin 3; jumper 1-2 to terminate),
  2 TXRX+, 3 TXRX-, 4 GND. 2-wire, automatic direction, echo cancelled while transmitting.
- **Receive-only test without Modbus:** the bench app has `PRG_SerialProbe` (bus task): turn the bus line off
  (`PRG_Bus.Lines[2].IsEnabled := FALSE`), set `PRG_SerialProbe.IsEnabled`, and send a pattern from the PC with
  `bench/serial_pattern.py COM12`; `PRG_SerialProbe.BytesReceived` counts what the port got.
- **Look at the wire first:** `examples/plc_architecture/bench/sniff_serial.py COM12` listens read-only.
  Only when no simulator owns COM12 (`GET /api/v1/bench` → adapters → owner); stop or move the
  simulator first. `bench/scan_serial.py` cycles port, baud, parity and RTS mode on the running bench app.
- **Native master:** `bench/add_native_serial.py` adds Modbus_COM + Modbus_Client_COM_Port (BCNF's device
  types; parity as the quoted literal `'NONE'`, auto-restart on). Then `modbus_device_driver_runner.py
  <manifest> --skip-simulator` adds servers and channels and fails if a channel is missing; a server with no
  channel shows an orange triangle and is never polled. A channel nobody reads also needs
  `PATCH /api/v1/modbus/devices/<server>` `{"alwaysUpdateVariables": "AlwaysInBusCycle"}`.
  `bench/native_serial_check.json` is a one-device example.

## Architecture bench (two or three tasks, 2,000 tags)

`examples/plc_architecture/bench/`: the redesign skeleton with a generated 2,000-tag table, a 50 ms control
task, a 5 ms bus task (Modbus lines from generated tables, ModbusFB) and a 50 ms MQTT task, in
`~/projects/codesys_projects/arch_bench/arch_bench.project`. `bus_sim.py apply` starts both simulated
buses (COM11 behind the NA111-E, COM12 on the terminal block); `apply_bench.py` writes the sources and tasks
(logged out); `deploy_bench.py [project]` downloads; `measure_bench.py` and `verify_arch.py --expected
tmp/arch_bench/src/expected_bus_values.json` measure and check every value at the broker. Results go in
`bench/results/`. ModbusFB reads coils as one byte per coil, not packed bits.

## Bench API for agents

Start every session with `GET /api/v1/bench`. It returns the IDE session heartbeat, active
reservations, running jobs, simulators, adapters by USB serial, gateways by MAC, and warnings
(for example a gateway whose address no longer matches what the PLC is configured for). The
schema is at `/openapi.json` and `/docs`.

| Need | Endpoint |
|---|---|
| Claim equipment | `POST /api/v1/bench/reservations` `{holder, purpose, scope:["plc","adapter:BG01GGR2","gateway:B0-CB-D8-4E-88-BB"], ttlSeconds}`; send the returned token as `X-Bench-Reservation` on changes; renew with `PUT`, release with `DELETE` |
| Anything over a few seconds | `POST /api/v1/jobs` `{script, timeoutSeconds ≤ 3600}` → 202; poll `GET /api/v1/jobs/{id}` |
| Find adapters and gateways | `GET /api/v1/inventory/adapters`, `GET /api/v1/inventory/gateways?refresh=true`; label with `PUT` |
| Read PLC values | `POST /api/v1/plc/online/read` `{names:[...]}` |
| Write PLC values | `POST /api/v1/plc/online/write` `{values:{"Modbus_TCP_Client.xStop":"TRUE"}, restoreAfterSeconds?}` (returns previous values) |
| Watch counters | `POST /api/v1/plc/online/watch` `{names, intervalMs, durationSeconds}` → job with samples and per-name `delta` |
| Stop one simulator bus (frees its COM port; others keep running) | `POST /api/v1/modbus/simulator/stop` `{"port": "COM12"}` |
| Modbus health | `GET /api/v1/plc/online/diagnostics` (every Modbus master/slave's `xError`, `uiConnectedSlaves`) |
| Start/stop the app | `POST /api/v1/plc/app/start` or `/stop` |

Reservations are advisory for unclaimed equipment: an unreserved scope is open to everyone. A
reserved one returns 423 to anyone without its token on simulator apply, PLC login/logout/
deploy/bind-ip, online write and app start/stop, including the holder's own calls: keep the token
(e.g. in `tmp/<task>/reservation.json`) and send it every time. Session scripts (`run_ide_script.execute`)
bypass reservations. Reads never need a token. `/script/execute`
honors `timeout` (up to 300 s) and runs scripts in one namespace, so their functions can call
each other.

## Ownership rules

- **One process per COM port.** A second opener fails or, worse, steals the port. Before touching
  COM11/COM18, check `GET /api/v1/modbus/simulator/status` or
  `logs/rtu_sim_<port>_status.json`. Other agents may be mid-test; the status row's
  `pausedFor`/`stoppedAt` fields and a recent heartbeat show that.
- Start and replace simulators only through the manager (`POST /api/v1/modbus/simulator/apply`
  or `modbus_simulator_control.apply_simulator`). It records PID plus create time and command
  line, and it never kills a process it didn't start.
- Health is three separate facts: `running` (our process), `portOpen`, and **counters moving**
  (`framer.requests`, per-unit `replies`). A live PID is not serial health.
- The PLC holds gateway sockets even while paused. Count every client (PLC, PC scripts, other
  agents) against the gateway limit.

## Procedures

### Start the bench simulators

```json
POST /api/v1/modbus/simulator/apply
{"buses": [
  {"backend": "go", "pcPort": "COM18", "usbSerial": "BG01GGR2", "baudrate": 115200, "multidrop": true,
   "devices": [{"unit": 1, "holdingMap": {"0": 1234, "1": 5678}}, "... units 2-10 from rtu_devices.json"]},
  {"backend": "go", "pcPort": "COM11", "usbSerial": "BG00XX03", "baudrate": 115200, "multidrop": true,
   "devices": [{"unit": 11, "holdingMap": {"0": 1101, "1": 1102}}]}
]}
```

Use `backend: "go"`. The PyModbus backend rejects multidrop above 38,400 baud and does not
recover from USB unplugs. `"silent": true` on a device makes it ignore requests, for timeout tests.
The Go worker answers FC01/02/03/04 and writes FC05/06/15/16; `coilsMap`/`discreteInputsMap`
are `{"offset": 0|1}`, and the status file shows each unit's `writes`, `lastWrite` and current `coils`.
A device given both `holding` and `holdingMap` uses `holdingMap`, even when it is empty.
The simulator baud must equal the gateway's serial setting.

### Read through a gateway from the PC

```powershell
python examples/modbus_tcp_read.py --host 192.168.50.153 --source 192.168.50.155 --port 502 --unit 1 --address 0 --count 2
```

Bind to `.155` explicitly, and confirm the NE2's current address by MAC first. The expected values are above; confirm the worker's counters rose by
the same amount. If the gateway's sockets are full, pause PLC polling. If the slots stay held
(native clients keep their sockets open), reboot the NE2 while the PLC is paused; see the profile.
For sustained tests, `temp/go_rtu_gateway_test.py` cycles units, verifies every reply, and
records latency plus worker counter deltas. It lives in `temp/` and is not in git.

### Pause, resume and check the PLC

Online calls need the IDE session with `modbus_tcp_bench.project` open and **logged in**. A fresh
IDE session has neither and returns 409 with `code` `no_project` or `not_logged_in`. Open the
project, then `POST /api/v1/plc/login` (OnlineChangeOption.Keep, no download) or pass
`login: true`.

- **Login is not free.** On 2026-09-28 a `/plc/login` (Keep, reported as no download) was
  followed by the IDE stalling at "Sending download info … 91%", leaving CODESYS Not
  Responding. The login response now includes `online.beforeLogin`, the application state
  before you logged in. `/bench` shows `ide.notResponding`, and while that is true, online
  and PLC-changing calls return 503 `ide_not_responding`. Log in only when you need online
  access, and check the IDE afterwards.
- Pause and resume: `POST /api/v1/plc/online/write` `{"values": {"Modbus_TCP_Client.xStop": "TRUE"}}`.
  The response's `previous` is the value you found; restore it, or pass `restoreAfterSeconds`.
  Another agent may have paused polling on purpose.
- Health: `PLC_PRG.AllTenRTUHealthy`, `AllTenRTUValuesMatch`, `BothPathsPass` (PC TCP plus
  gateway), `Modbus_TCP_Client.uiConnectedSlaves` (11 when healthy), per-unit
  `Gateway_RTU_Unit<n>.xError`; `GET /api/v1/plc/online/diagnostics` reads the device flags.
- Counters: `TenErrorCycles[1..10]` and `TenBadValueCycles[1..10]` count scans while
  `TenMonitorEnable` is TRUE. Watch them with `POST /api/v1/plc/online/watch` and judge by the
  summary's **delta**, over a window that starts after polling has settled (about 15 s after
  resume). A just-reconnected unit briefly counts bad values.
- `uiConnectedSlaves` = 10 with the gateway healthy usually means the PC TCP simulator on `.155`
  is not running. That path is unrelated to RTU.

### Change the NE2 baud

Change the simulators first, then the gateway: complete save sequence, reboot, readback. The
`uart_baud` values are enums (6 = 38400, 8 = 115200); the profile has the sequence. A reboot drops
every client, and the PLC reconnects on its own.

### Restart the API server without killing CODESYS

Terminate the `serve_on_port.py` process hard (psutil `terminate()`), never with Ctrl+C: its
`finally` block stops the CODESYS session. Relaunch with `CREATE_NO_WINDOW` only. A
`DETACHED_PROCESS` server opens a visible console window for every helper subprocess. Startup's
`ensure_singleton` leaves one existing IDE session alone. Afterwards confirm the CODESYS PID is
unchanged and `GET /api/v1/session/status` still shows the session attached.

A restarted IDE picks up the current `PERSISTENT_SESSION.py`. Since 2026-09-28 the session
writes a `busy` heartbeat while a script runs, so `session/status` answers without queuing, and
`session.report_progress({...})` shows as a job's progress. An older loaded session lacks both. The PLC keeps polling without the
IDE, but online reads need the project reopened and logged in.

## Native PLC configuration rules

- Native device tree: Ethernet → Modbus TCP Client → one Modbus TCP Server child per unit ID. Each
  child opens its own TCP connection, so connection limits cap the child count: 10 on the NE2
  (5 on A, 5 on B), 6 on the NA111-E, minus any other clients.
- Past that limit, use one `ModbusFB.ClientTCP` and change the unit per request (the example
  polls ten units over one connection). It needs application code for scheduling, validity and
  reconnection.
- Channels: FC03, zero-based offset, map the input words to typed ST storage. ST alone creates no
  communication.
- Generated native exports (`modbus_native_export_generator.py`) follow CODESYS's own canonical
  export: config ID `0xSS100000` and IO ID `0xSSFFOOOO` (slot, family byte, register offset),
  with array words numbered in the second field (`38010881_1_0_0`). The canonical templates in
  `templates/modbus_serial_slave_canonical*.export` are required at run time.

### Coil and discrete-input channels (proven 2026-09-30)

CODESYS builds these channels itself in `DeviceEditorModbus.plugin` (`ChannelData.CreateSlaveChannel`,
the code behind the editor's Add Channel button). The proof called that code from the IDE session,
exported the result (`templates/modbus_tcp_server_canonical_coils.export`) and ran it on the PLC
against NE2 unit 2.

- **IO type:** FC1, FC2, FC5 and FC15 get `std:ARRAY[0..ceil(n/8)-1] OF BYTE`: one BYTE per
  eight coils, each byte holding eight `BIT`s. Coil *k* of the channel is bit *k* mod 8 of byte *k* div 8
  (Modbus LSB-first). Bits past the channel length carry `OfflineAccess None` and never reach the wire:
  `16#FE` in byte 1 of a 10-coil FC15 channel wrote only coils 8–9.
- **Version gate:** the packed form requires the slave's ConfigVersion (param `1879052288`) to be
  at least `16#03050300`. The TCP Server here is `16#03050B00`, the RTU slave (type 91) `16#03050300`.
  Older versions give one parameter per coil.
- **IDs:** read `0xSS4F0000 + offset`, write `0xSS8F0000 + offset`, where F is `1` for discrete inputs,
  `2` for coils, `3` for input registers and `4` for holding registers. So FC2 is `0x41`, FC1 `0x42`,
  FC5/15 `0x82`. Bytes are `<id>_<byte>_0_0` and bits are `<id>_<byte>_0_0_<bit>`.
- **Mapping, all proven on the wire:** a whole channel to an `ARRAY[0..m] OF BYTE` variable (read and
  write); a single bit to a `BOOL` (read FC1/FC2, write FC5); ten bits to `ARRAY[0..9] OF BOOL`
  elements. CODESYS also compiles a `BOOL` mapped to a whole 1-coil channel, and FC05 then drives the
  coil, but only its FALSE read was observed. Map BOOL storage to bit 0 instead.
- **Unused I/O is not updated.** CODESYS copies a channel's IO only when IEC code uses the mapped
  variable or the device's connector has `io_always_mapping = True`. Mapped GVL variables that no
  program reads stayed at 0 until that flag was set.
- Evidence: `temp/coil_proof/` (exports, `write_check_unit2.json`, `watch_60s_unit2_coils.json`, the
  proven project copy, and the decompiled plugin, which is local only).

## Verified results

| Test | Result | Evidence (local, not in git) |
|---|---|---|
| PC → NE2 → COM18 + COM11 multidrop, 115200, 15 min | 52,249/52,249 reads; median 16.5 ms, p95 26.7 ms; zero discards or stale replies | `temp/field_live/go_rtu/soak_115200.json` |
| Unplug and replug both adapters under load | Detected in about 1 s, reopened by USB serial; failures only while unplugged | `temp/field_live/go_rtu/replug_115200.json` |
| One silent unit (5) | Only unit 5 timed out; the other 10 stayed at 100% | `temp/field_live/go_rtu/silent5_115200.json` |
| PLC polling units 1–10 through the NE2, 2 min | 0 new error or bad-value cycles, 11 connections | `temp/field_live/go_rtu/plc_end_to_end_115200.json` |
| NE2 native modules, 5 A + 5 B | 612/612 in 60.8 s | `temp/native_repair_20260924/recovered/summary.json` |
| NA111-E, 6 concurrent clients → COM11 | 600/600, median about 11.8 ms; a 7th client is accepted then closed | `temp/na111_setup/client_limit_results.json` |
| ModbusFB, one connection, ten units | 0.696 s round at a 5 ms task vs 4.04 s at 50 ms (115200) | `examples/modbusfb_single_connection/test_results.json` |
| Go sim FC1/2/5/6/15/16 from pymodbus via NA111-E → COM11 unit 11 | All reads, writes and read-backs match | `temp/coil_proof/pc_client_check_na111_unit11.json` |
| PLC coil channels on NE2 unit 2 (FC1 ×3, FC2, FC5, FC15) | Reads `16#8D 16#02`, BOOL bits and 10 DI bits exact; three write patterns exact on the wire and in FC1 read-back; 60 s with 0 new error cycles | `temp/coil_proof/write_check_unit2.json`, `watch_60s_unit2_coils.json` |

## Pitfalls

- A CODESYS certificate-expiry dialog can block a login or download until someone clicks it.
  On 2026-09-30 a "login with download" waited about 3 minutes on one. Earlier the same day, an
  online read hung the IDE's script thread for 10 minutes and needed a session restart and a kill
  of the old IDE, with no dialog visible to UI automation. `/plc/login` reports
  `certificateTrustError: "This functionality is no longer supported!"`, so the API cannot
  pre-trust certificates on SP22. If a login stalls, ask someone at the desktop.
- After an online change or a download, cached online reads can fail with "Invalid variable
  reference" for most names. `POST /plc/logout` then `/plc/login` fixes it. Until the IDE session is
  restarted with the fixed `PERSISTENT_SESSION.py`, `session.dispose_online_application('')` disposes
  nothing; dispose by application path (`session.find_application('')[1]['path']`), as the deploy
  scripts do.
- A modal IDE dialog ("no connection to device", a certificate prompt) blocks the API's script thread:
  `session/status` stays `busy` on one request. Ask someone at the desktop to close it.
- After a PLC power cycle, wait until ETH1 answers ping and port 11740 accepts, then log out and in.
- The PLC's clock runs on UTC from the NTP server at 192.168.50.240 since 2026-10-20. Before, it
  held local time and was 84 s off. It drifts about 30 ms an hour. Stepping the clock 4 hours
  while the application ran stopped the application on an exception (operating state 4129) and
  dropped the IDE's connection; the IDE's "no connection to device" dialog then blocked the API's
  script thread until someone closed it. A warm reset and start recovered it. Set the clock with
  the application stopped, or correct it only in small steps.
- The NA111-E does not forward Modbus exception replies. The simulator answered exception 02
  four times, and the PC client timed out.
- The PLC task interval, not baud, dominated the round time. Raising baud from 38,400 to
  115,200 barely changed a 50 ms-task round.
- A cached gateway polling mode can report stale data as valid while a unit is silent (keep time
  10 s and 2 s hid failures; 1 s exposed them). Multi Host mode, used on this bench, forwards
  requests live.
- A TCP handshake does not prove a usable slot; excess clients connect and are then dropped.
- FTDI serials appear with an `A` suffix in Windows (`BG01GGR2A`). The Go worker accepts either
  form.
- The USB adapters here do not echo their own transmissions, and foreign replies arrive combined
  with the next request in one read. The Go framer handles both.
- Scripts under `temp/` (`multihost_bench.py` gateway helper, `go_rtu_*.py`) are local tools, not
  versioned; read them before reuse.
