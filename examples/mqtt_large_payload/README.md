# Large MQTT payloads from CODESYS

Bench demo showing that the Stefan Dreyer MQTT library (1.2.0.7, unmodified) publishes one 17.6 KB
message without trouble. The 255-character cap seen on the BCNF PLC comes from `CONCAT` and
`STRING(255)` copies, not from the library. Write-up with results and performance:
[Doc Shelf report](https://docs.local.tidalmetals.org/documents/projects/codesys/mqtt-large-payload/latest/).

## Files

| Path | Purpose |
|---|---|
| `st/` | ST sources: `AppendText` (append without the 255 cap), `PLC_PRG`, its `BuildLine` action, `NowUs` |
| `build_demo_project.py` | Headless build: turns a copy of `modbus_tcp_bench.project` into the demo project |
| `apply_session.py` | Applies the sources to the demo project open in the API session and rebuilds |
| `deploy_demo.py` | Full download to the bench PLC, start, boot application |
| `measure_performance.py` | Sweeps `ValueCount` online and reads the PLC's timing counters |
| `verify_payloads.py` | Subscribes on the HQ broker and checks every value of every message |
| `results/` | JSON from the runs on 2026-10-19 (`performance_real_*`, `performance_int_qos0` and `verify_production_sweep` are the production benchmarks) |
| `report/` | Generator and template for the Doc Shelf report |

## Run it

The demo project lives at `../codesys_projects/mqtt_large_payload_demo/`. To rebuild it from the
bench project (headless, separate IDE):

```powershell
Copy-Item ..\codesys_projects\modbus_tcp_bench\modbus_tcp_bench.project ..\codesys_projects\mqtt_large_payload_demo\mqtt_large_payload_demo.project
$env:DEMO_PROJECT = "<abs path to the copy>"; $env:DEMO_REPORT = "<abs path>\build_report.json"
$env:DEMO_SOURCE_DIR = "<abs path to this folder>"
& "C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe" --Profile="CODESYS V3.5 SP22 Patch 1" --noUI --runscript="$env:DEMO_SOURCE_DIR\build_demo_project.py"
```

Then, with the API on 8081 and the demo project open in the session (reserve `plc` first; see
`docs/modbus-bench.md`):

```powershell
python examples/mqtt_large_payload/deploy_demo.py
python examples/mqtt_large_payload/verify_payloads.py --seconds 60
python examples/mqtt_large_payload/measure_performance.py --sizes 50 500 1100 --format real --qos 0
```

`PLC_PRG` defaults match BCNF in production: two-decimal REALs formatted with BCNF's conversion
expression, one publish a second, QoS 0, no CONCAT control copy. `IsRealFormat`, `IsQos1`,
`PublishPeriod`, `ValueCount` and `IsConcatControlEnabled` can be written online.
`IsConcatControlEnabled` turns on the copy built with `CONCAT` into a `STRING(8000)` on
`raw_data_demo/concat`, which shows the 255-character cap; it is demonstration work and distorts
timings. `results/performance_with_concat_control.json` is the first sweep, measured with it on.

Deploying replaces the Modbus bench application on the PLC. The demo publishes on
`raw_data_demo` and `raw_data_demo/concat` at `192.168.50.240:1883`, never on the bridge's `raw_data`.

Edits to the project need a logged-out session; `apply_session.py` fails with "affects a device you
are currently logged into" otherwise (`POST /api/v1/plc/logout`).
