# PLC program architecture: skeleton

The compiled reference skeleton for the redesigned PLC program structure: a control task and a comms task
joined by queues and a snapshot, a seven-step control scan, a generated tag table, per-tag quality, request
AND permit outputs, and commands with ids and acknowledgements. Four example tags; it compiles without errors
or warnings on CODESYS V3.5 SP22 with the MQTT 1.2.0.7 library. Scaled to 2,000 tags, it has run on the bench
PLC as two tasks (`bench/`).

- Design and reasoning, with diagrams:
  [architecture redesign on Doc Shelf](https://docs.local.tidalmetals.org/documents/projects/codesys/bcnf-architecture-redesign/latest/)
- Rules and generator workflow for agents: [`docs/plc-architecture-for-agents.md`](../../docs/plc-architecture-for-agents.md)

| Path | Purpose |
|---|---|
| `st/` | One file per object: `Object.st` (declaration and implementation split by `// ---- implementation ----`), `Object.Method.st`, `Program.Action.st` |
| `manifest.json` | Object kinds and creation order for the compile check |
| `check_compile.py` | Headless compile check: adds every object into a copy of a project with the MQTT library and rebuilds |
| `report/` | Generator and template for the Doc Shelf document; code snippets come from `st/` |
| `bench/` | Two-task bench on the PLC: `make_bench_sources.py` scales the skeleton to N tags with bench topics and client id; `apply_bench.py` writes it and the tasks (MainTask 50 ms priority 1 = control, CommsTask 50 ms priority 10 = MQTT) into `~/projects/codesys_projects/arch_bench/arch_bench.project`; `deploy_bench.py`, `measure_bench.py`, `verify_arch.py` and `run_series.ps1` measure control timing while comms publishes. Results in `bench/results/` |

Compile check (uses a copy of the MQTT demo project, which already has the library, dynamic memory and `AppendZ`):

```powershell
Copy-Item ~\projects\codesys_projects\mqtt_large_payload_demo\mqtt_large_payload_demo.project tmp\skeleton_check.project
$env:SKELETON_DIR = "<abs path to this folder>"; $env:SKELETON_PROJECT = "<abs path>\tmp\skeleton_check.project"
$env:SKELETON_REPORT = "<abs path>\tmp\skeleton_check.json"
& "C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe" --Profile="CODESYS V3.5 SP22 Patch 1" --noUI --runscript="$env:SKELETON_DIR\check_compile.py"
```
