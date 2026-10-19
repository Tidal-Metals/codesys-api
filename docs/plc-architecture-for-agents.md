# PLC program architecture: guide for agents

For agents that write CODESYS Structured Text for our PLCs, or write generators that turn config-sheet data
into that ST. The design, its reasoning and the diagrams are in the
[architecture redesign](https://docs.local.tidalmetals.org/documents/projects/codesys/bcnf-architecture-redesign/latest/);
the reference implementation is the compiled skeleton in [`examples/plc_architecture/`](../examples/plc_architecture/).
Read the skeleton before writing anything: new code follows its shapes and names.

## Invariants

Every program, generated or hand-written, holds all of these. A change that breaks one is wrong even if it
compiles and runs.

1. **Two tasks.** `PRG_Control` (high priority, cyclic, e.g. 50 ms) owns everything that touches the plant.
   `PRG_Comms` (lower priority, e.g. 100 ms) owns everything that touches the network. Control code makes no
   network calls and builds no strings; comms code reads tags only through the snapshot.
2. **Three hand-over points, each single-producer/single-consumer:** `GVL_Tags.Commands` (comms → control),
   `GVL_Tags.Acks` (control → comms), the snapshot (`SnapshotRequest` written by comms, `SnapshotSequence` and
   `PublishSnapshot` written by control). Anything else shared between the tasks is a defect.
3. **One owner per field.** Every variable, and every field of a struct, has exactly one writer. Name the writer
   in the declaration comment, as `GVL_Tags` does. Requests are written only in step 2, outputs only in step 6.
4. **The pipeline.** `PRG_Control` runs its seven steps in order, every scan: read inputs, apply commands,
   compute values, alarms, permissives, write outputs, serve snapshot. A step reads what earlier steps produced
   and writes only its own results.
5. **The table.** Tags are rows of `GVL_Tags.TagConfig` (generated, constant) and `GVL_Tags.Tags` (state).
   Repetitive work (scaling, quality, alarms, publishing, command lookup) is a loop over the table. Hand-written
   logic refers to tags through generated index constants (`Tags[GVL_Tags.TAG_AIT_1508]`).
6. **Quality.** Every value has an `E_Quality`. Anything other than GOOD counts as an alarm in interlocks
   (fail safe), is published, and keeps the last good value instead of zero.
7. **Request AND permit.** `output := request AND permit`, written in step 6 only. A trip clears the request
   (in step 2, from last scan's permit) and records the trip time; a start sent before the permit came back
   (plus the clock-skew margin) is refused. A bypass is per actuator, time-limited, needs the local key-switch
   input, and never lifts an E-stop.
8. **Commands are values with ids.** Every command is queued, checked, applied as a value (never a toggle)
   and acknowledged by id. The bridge is the only command sender: it authorizes the user, assigns the id and
   stamps `sent_ms` from its own clock, so ids share one space and timestamps can be ordered. The checks, in
   `PRG_Control.CheckCommand`: numeric text validated (and length-limited) before conversion; a retry (same
   id, tag, value and `sent_ms`) gets its first answer from the ledger and is never applied twice; known and
   writable tag; inside the range, then 0/1 for BOOL, then whole for INT (converted only once in range);
   plausible PLC clock; not too old, not in the future, not queued too long; not older than the last command
   applied to that tag; a start only while permitted and sent after the last trip. A full Acks queue never
   holds a command back: it is applied, the answer is dropped, and the sender's retry is answered from the
   ledger. Size `LEDGER_SIZE` for every command the bridge may send within `MAX_COMMAND_AGE_MS`
   (`LedgerTooSmall` counts violations).
9. **Bounded work per scan.** Control loops over the table and handles at most `MAX_COMMANDS_PER_SCAN`
   commands. Comms spreads message builds over calls (`TAGS_PER_CALL`). Work happens on an event (a message, a
   timer tick, a change), never every scan by default.
10. **Long strings through pointers.** Build payloads with `AppendZ` into one buffer passed by `ADR()`. Standard
    string functions (`CONCAT`, `LEFT`, `MID`, `FIND`, `LEN`) and `STRING` inputs handle at most 255 characters,
    so they only ever see one short piece. The generator sizes the buffer from the table's worst-case message.
11. **Range checks are NaN-safe.** Write them as `NOT (x >= min AND x <= max)` and fail-safe signals as
    `NOT (x < 0.5)`: NaN fails every comparison, so these forms treat it as out of range or active.
12. **Publishing commits after the fact.** Report-by-exception history moves only after the publisher's
    `done`; an oversized message forces a full refresh, and so does a reconnect. A tag that isn't GOOD is
    published as `NaN`, never through an integer conversion. Each remote source
    sends a heartbeat, so a quiet source isn't mistaken for a stale one.
13. **One core, full downloads.** The two tasks run on the same CPU core (or the queues use the runtime's
    atomics). Any change to the generated table is a full download: queued commands and history refer to rows
    by index.

## Writing a generator

A generator turns one workbook's manifest into the generated ST files. Run the steps in order; each ends on its
completion criterion.

### 1. Fetch the manifest

Production config sheets: `GET http://10.2.40.142:3001/api/v1/workbooks/by-group/<GROUP>` resolves the latest
workbook, `GET /workbooks/<id>/manifest` returns everything in one response (`tagManifest`, `interlockManifest`,
`bridgeLayout`, `publishMap`, `rs485Config`, `interTags`). The API needs `Authorization: Bearer
$CONFIG_SHEETS_API_TOKEN`; the token is in `~/.env` on the Claude VM (`ssh ktritz@192.168.50.142`), so run the
request there and keep the token on the VM. API details: `~/.claude/docs/config-sheets-api.md`.

Done when: the manifest is saved with its `workbook.id`, `workbook.updatedAt` and `checksum`, which go into the
header of every generated file.

### 2. Validate

Call `POST /api/v1/validate/workbook/<id>`, then check what the PLC needs on top:

- Every tag name is unique per PLC and fits the generated `STRING(n)` (size `n` from the longest name; CONC
  RevB_3 reaches 23 characters).
- Every interlock's `alarmTag` (`<deviceTag>/<suffix>`) resolves to an alarm the workbook defines.
- Every RS485 channel's `deviceTag` resolves to a device on this PLC's `nodeId`.
- The worst-case published message (every tag, longest value text) fits the buffer the generator will emit.
- Every writable tag has a default value (alarm setpoints from `alarms[].setpoint`; requests 0).
- `objectType` values are normalized (the sheets contain both `DigitalSensor` and `Digital Sensor`).

Done when: the validator passes and every check above passes, or the generator stops with a list of every
violation (all of them, not the first).

### 3. Map the manifest to tables

Filter devices by the PLC's `nodeId` (for BCNF: `CONC-BCNF-PLC`). Then:

| Manifest | ST | Notes |
|---|---|---|
| `tagManifest.devices[]` with its `role: device` tag | one `TagConfig` row | `Name` = tag name; `Kind` from `dataType`: Bool/Boolean → `BOOL_TAG`, Integer → `INT_TAG`, Float → `REAL_TAG` |
| `engLow`, `engHigh` | `MinValue`, `MaxValue` | range for INVALID; when empty, use the type's sensible range and say so in a comment |
| `devices[].alarms[]` | one row in the alarm table per entry, plus a writable setpoint tag `<deviceTag>_<suffix>_SP` for numeric alarms | the alarm columns are the source; the manifest's `plcAlarm` and `setpoint` tag entries are expanded from them by the API, so derive from `alarms[]` and treat those entries as a cross-check |
| `alarms[].suffix` | direction and level | H, HH: value ≥ setpoint; L, LL: value ≤ setpoint |
| `alarms[].setpoint` | the setpoint tag's default value | for `isNumeric: false` (BOOL alarms), `setpoint: true` means "alarm when the input is TRUE" |
| `alarms[].deadband`, `delay`, `priority` | hysteresis, on-delay, priority in the alarm table | deadband 0 still gets a small hysteresis from config, so analog alarms don't chatter |
| `isActuator` devices and their `actuatorControl` tags | request tag (`<tag>`), per-actuator bypass request (`<tag>_Bypass`), manual/auto (`<tag>_Manual`), status (`<tag>_Interlocked` = NOT permit) | requests and bypass requests are writable tags; `_Interlocked` is computed in step 5 |
| `interlockManifest.actuators[].interlocks[]` | rows of the permissive table | `alarmTag` names the alarm; `action` OFF/FALSE: the alarm forces the target FALSE (removes the permit); ON: the alarm forces it TRUE. Review every ON with a person before generating it |
| `rs485Config.channels[]` | source and I/O mapping | `deviceId` → Modbus slave = `Source`; `registerType`, `registerAddress`, `wordCount`, `wordOrder` → the channel; `scaleFactor` → `Scale`; `invertLogic` → invert in step 1; `defaultValue` → the value before the first read; `direction: write` → output channel fed in step 6 |
| `publishMap.mappings[]` | only if the PLC still publishes positional groups | with `tag:value` publishing the PLC needs no publish map |
| `interTags.routings[]` | remote sources | each publishing PLC is a source with its own staleness timeout |

Done when: every device, alarm, interlock and RS485 channel for the `nodeId` maps to exactly one row, and the
generator reports the counts (devices, alarms, interlocks, channels) so they can be compared with the sheet.

### 4. Emit the ST

Generate data, not code: the `TagConfig` initializer, the alarm and permissive tables, the index constants
(`TAG_<NAME>` with `-` replaced by `_`), the I/O mapping export, and the table sizes. Hand-written logic
(sequences, special interlocks, derived values) lives in separate files that only reference the generated
constants.

- Order rows deterministically (sheet order), so regenerating an unchanged workbook gives identical files.
- Start each file with a header: generated by which generator, from which workbook id, `updatedAt` and
  checksum, and "regenerate instead of editing".
- One object per file, named like the skeleton (`Object.st`, `Object.Action.st`, declaration and
  implementation separated by `// ---- implementation ----`).

Done when: regenerating from the same manifest produces byte-identical files, and every generated identifier
is used by the program or listed as intentionally unused.

### 5. Compile

Compile headless with [`examples/plc_architecture/check_compile.py`](../examples/plc_architecture/check_compile.py)
(or the same approach in the target project): it adds every object from a manifest of files into a copy of a
project and rebuilds it. Never compile inside a project someone has open.

Done when: the build reports zero errors and zero warnings from our code (library warnings are listed and
left alone).

### 6. Prove it on the bench

Download to the bench PLC through the codesys-api API (reserve the PLC first; see
[`docs/modbus-bench.md`](modbus-bench.md)). Feed inputs from the Modbus RTU simulators, check every published
value with a broker-side verifier (the `verify_*.py` scripts in `examples/mqtt_large_payload/` are the
pattern), and measure each pipeline step with microsecond timers (`SysTimeCore.SysTimeGetUs`).

Done when: every alarm and interlock in the tables has been driven to trip and to clear on the bench with the
expected output change, every published value matches, and the worst scan stays inside the task interval with
margin.

## Writing hand-written ST

Hand-written code goes where the table can't express the logic: sequences, unusual interlocks, derived values.

- Put it in the step it belongs to (an interlock in step 5, a derived value in step 3) as an action of
  `PRG_Control`, and give every variable it writes a comment naming that action as the owner.
- Read tags through index constants and check their quality before using their value.
- Guard every division; a derived value takes the worst quality of its inputs.
- Name booleans `Is…`/`Has…`, use `qualified_only` GVLs, and keep functions under about 50 lines.
- Write comments for the reason behind a line; the line itself says what it does.

## CODESYS facts that bite

Each of these cost time on this bench; none is obvious from the code.

- **Names are case-insensitive.** A variable `Mqtt` hides the library namespace `MQTT` ("'QoS' is no component
  of 'MQTT_IN_OUT'"). Use distinct names (`MqttLink`).
- **`AND` evaluates both sides.** Chained appends and `Pop` in a `WHILE` condition need `AND_THEN`, or the
  right side runs (and consumes data) even when the left is FALSE.
- **`done` is a one-call pulse; `SendTimeout` is not an ending.** `MQTTPublish.done` is TRUE for one call.
  `SendTimeout` stays TRUE while a request is slow, and the library keeps that request (it resends after a
  reconnect) until `done`; nothing cancels it. Treat `SendTimeout` as a diagnostic only.
- **`MQTTPublish` starts on a rising edge of `send`.** It must see FALSE between two messages; setting `send`
  again in the call after `done` sends nothing. Track an "armed" flag as `PRG_Comms.PublishData` does.
- **The library reads payloads through the pointer over several scans.** Leave the buffer, and anything that
  records what it contains, untouched from `send` until `done`.
- **Conversions can fault.** `REAL_TO_DINT` and `TRUNC` on a value outside DINT (or NaN) may raise an
  exception on some targets, and plain `AND`/`OR` still evaluate them. Range-check first, then convert in a
  separate branch or behind `AND_THEN`.
- **A self-resetting TON** (`IN := NOT Q`) adds two task intervals per period: `T#1S` on a 50 ms task fires
  every 1.1 s.
- **`STRING_TO_REAL`** returns 0 for text it can't read; validate with `F_IsNumberText` before converting.
- **`OR_ELSE` / `AND_THEN`** are the short-circuit forms; use them whenever the right side has a side effect
  (`Pop`, `Push`, an append).
- **64-bit values are not atomic across tasks** on a 32-bit CPU. Keep `ULINT` timestamps owned and read in the
  same task, or hand them over through the queues.
- **The MQTT library needs dynamic memory** (Application properties › Build; 50–100 KB). It isn't scriptable;
  set it through the object manager as `examples/mqtt_large_payload/build_demo_project.py` does.
- **Libraries are often qualified-only:** `SysTimeCore.SysTimeGetUs`, `SysTimeRtc.SysTimeRtcHighResGet`.
- **Unused I/O isn't updated.** A mapped variable no program reads stays 0 unless the device has
  `io_always_mapping` (see `docs/modbus-bench.md`).
- **Scripting:** adding objects fails while logged in (log out first); `__file__` is undefined under
  `--runscript`; IronPython's `json` fails on non-ASCII compiler messages; `insert()` on text objects clashes
  with its overloads, so use `replace()`.

## When the sheet and the code disagree

The sheet is the source. The current BCNF code has four AIT-1508 alarms that CONC RevB_3 doesn't define; a
generated program would drop them. Report such differences to a person before regenerating a running PLC, and
never patch generated files to match old code.
