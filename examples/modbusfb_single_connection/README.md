# Ten RTU devices over one TCP connection

`FB_ModbusTenUnits` shares one `ModbusFB.ClientTCP` across unit IDs 1-10. One reusable FC03 request reads two holding registers, then advances to the next unit. There are no Modbus TCP server nodes.

## Run

Open `codesys_projects/modbus_fb_single_connection/modbus_fb_single_connection.project`, or add **ModbusFB 4.5.0.0 (CODESYS)** and **Standard**, import `ModbusTenUnits.export`, and call `PLC_PRG` from a **5 ms cyclic task**. The `.st` files contain the same source.

Bench settings: gateway `192.168.50.151:502`, **115200 baud, 8N1, Multi Host**; units 1-10; holding-register offsets 0-1. Socket A only. `tRequestGap=T#0ms`. Reply/total timeouts are 2/3 seconds; library inputs use microseconds. Change gateway IP/port with `xEnable=FALSE`, then re-enable.

PC simulator, from the repository root:

```powershell
python modbus_rtu_slave_sim.py --port COM18 --baudrate 115200 --manifest examples/modbusfb_single_connection/rtu_devices.json
```

## Watch

`PLC_PRG.Poller.aRegisters[device,register]` holds data. `aValid`, `aReadCount`, and `aErrorCount` report each device's result. `PLC_PRG.AllTenValuesMatch` checks the simulator's values. `Poller.udiConnectionCount` counts TCP connection establishments.

Failed requests invalidate that device and polling advances; old values remain with `aValid=FALSE`. Request errors keep TCP open. TCP client errors trigger a delayed reconnect.

## Measured results

Zero added gap; median time between polls of the same device:

| Baud | PLC task | Ten-device polling round |
|---:|---:|---:|
| 9600 | 50 ms | 4.201 s |
| 38400 | 50 ms | 4.048 s |
| 115200 | 50 ms | 4.038 s |
| 115200 | 5 ms | **0.696 s** |

Each healthy test ran about one minute with correct values, no new request errors, and one stable TCP connection. Missing-device tests also kept TCP connected while the other nine responded. All ten recovered after restoring unit 5. Runtime timeout counters include these deliberate fault tests.

The task interval was the main bottleneck: several application/library state transitions occur per request. A 100 ms request gap added approximately one second per ten-device round.

Details: `test_results.json`. CODESYS references: [ClientTCP](https://content.helpme-codesys.com/en/libs/ModbusFB/4.5.0.0/ModbusFB/Function-Blocks/Client/ClientTCP.html), [ClientRequest](https://content.helpme-codesys.com/en/libs/ModbusFB/4.5.0.0/ModbusFB/Function-Blocks/Client/ClientRequest.html).

## Gateway polling and cached reads

The same PLC code also works with the NE2-D11P's **Configurable gateway** mode (4). Configure one six-byte command per unit: `01 03 00 00 00 02` through `0A 03 00 00 00 02`. Keep TCP→RTU enabled, socket A on port 502, and both serial endpoints at 115200/8N1.

With a 0 ms gateway polling interval and **1 s Modbus keep time**, the bench measured a **0.543 s PLC round** and **0.280 s RTU refresh interval**, versus 0.676/0.671 s in a fresh Multi Host baseline. No PLC code changes were required. Gateway refresh and PLC cached-read timing are separate measurements.

Keep time affects failure reporting. At 10 s, a silent unit produced no RTU replies for 41 seconds while CODESYS continued successful cached reads and reported it valid. A 2 s setting also hid the silent unit throughout an 18 s test. At 1 s, the same fault produced request errors and `aValid=FALSE`, with TCP still connected. A repeat that silenced only unit 5 produced ten request errors for that unit, zero errors for the other nine, and full recovery. This is evidence for this firmware and workload, not a guaranteed one-second detection deadline or a universal freshness bound. Keep time 0 exposed the fault but slowed the healthy PLC round to about 0.87 s.

Detailed timing, settings and fault observations are in `cache_test_results.json` and the [Doc Shelf bench report](https://docs.local.tidalmetals.org/documents/projects/codesys/modbus-gateway-bench-2026-09-21/latest/).
