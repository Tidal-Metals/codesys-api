# rtu-sim — Go Modbus RTU bench simulator

One `rtu-sim.exe` process serves several simulated slave IDs on one RS485 adapter.
It replaces the PyModbus multidrop transport, which failed above 38,400 baud.
The design is in the [Doc Shelf plan](https://docs.local.tidalmetals.org/documents/projects/codesys/go-rtu-simulator-plan/latest/).

## Build

```powershell
tools\modbus-rtu-sim\build.ps1     # vet, test, build to build\rtu-sim.exe
```

`build\` is Git-ignored. Stop running workers before rebuilding, because Windows locks a running executable.

## Run through the API (normal path)

```json
POST /api/v1/modbus/simulator/apply
{"buses": [{"backend": "go", "pcPort": "COM11", "usbSerial": "BG00XX03",
            "baudrate": 115200, "multidrop": true,
            "devices": [{"unit": 11, "holdingMap": {"0": 1101, "1": 1102}}]}]}
```

`modbus_simulator_control.py` checks the whole request before it changes any worker.
It writes `templates/modbus_simulator_<port>.json`, then starts
`rtu-sim.exe --config <file>`. For a Go bus, it waits up to 3 s for the port to open.
`success` is false if the port does not open in that time. The worker keeps
retrying, so check `lastError` in the status. Before stopping a worker, the manager
checks the PID's create time and command line, so it never kills a reused PID.
A USB serial number can belong to only one port.

Optional bus fields: `usbSerial` (FTDI serial, with or without the `A` suffix),
`bytesize`, `parity`, `stopbits`, `idleGapMs` (default 50), and
`traceFrames` (log every frame to the stderr log). Device fields match the
Python manifest (`unit`, `name`, `holdingMap`, `inputRegistersMap`), plus `silent`.

`GET /api/v1/modbus/simulator/status` reports these separately for each Go bus:
`running` (whether the process is ours), `portOpen`, and `heartbeatAgeSeconds`/`heartbeatStale`.
`worker` carries the full status file (`logs/rtu_sim_<port>_status.json`): RX/TX
counters, per-unit requests/replies/exceptions/skips, framer discards, reopen
count, and host-side reply latency. A quiet bus does not trigger a port reset.

## Behaviour

- **Framing.** A USB read is not a frame. Bytes are buffered, and frames are cut by
  function-code length rules plus CRC. Split reads and reads that combine several
  frames are both handled. Foreign requests and replies are consumed silently.
  Garbage is dropped one byte at a time until a frame validates.
- **When it replies.** The simulator answers only CRC-valid requests for its own IDs that
  begin on a known boundary: after `idleGapMs` of silence or directly after another
  valid frame. It does not answer a request found by resynchronizing, or one followed
  by more bytes already buffered (the master has moved on). Broadcasts get no reply.
  Local echo of the simulator's own reply is removed if the adapter produces one.
- **Functions.** FC03 (holding) and FC04 (input) reads. A missing register
  returns exception 02, and a quantity outside 1–125 returns 03. Other standard
  functions addressed to a served ID return exception 01.
- **USB recovery.** An I/O error, or the port disappearing during silence,
  closes the port. The worker reopens it with 250 ms–5 s backoff. With `usbSerial`
  it finds the adapter again even if Windows assigns a new COM number.
- `idleGapMs` must be longer than the FTDI latency timer (16 ms by default), not just
  3.5 character times.

## Layout

| Path | Responsibility |
| --- | --- |
| `cmd/rtu-sim` | Config, shutdown, JSON-line events on stdout, status file publisher |
| `internal/rtu` | CRC, framer and resynchronization, echo filter |
| `internal/device` | Unit IDs, register maps, FC03/FC04 replies and exceptions |
| `internal/serialrun` | Serial bus loop, reply decisions, port reopen, status snapshot |

## Bench verification

`temp/go_rtu_gateway_test.py` sends FC03 reads from the PC's USB-Ethernet adapter
(`192.168.50.155`) through the NE2-D11P gateway (`192.168.50.151:502`). The PLC must
already be paused. The script sets the gateway baud and reboots it if that is needed to
free a socket. It checks every reply and records worker counter deltas in
`temp/field_live/go_rtu/`. `temp/go_rtu_buses.py` holds the bench bus definitions:
COM18/BG01GGR2 serves IDs 1–10 and COM11/BG00XX03 serves ID 11.
