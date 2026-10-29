# P2CDS-622 Modbus bench history

Historical setup and verification notes formerly in the README. For current topology and procedures, use the [bench guide](modbus-bench.md). Paths in the notes below are relative to the repository root.

Clone verification on 2026-10-29 exposed an unsupported `allow_multiple_devices` argument in the Python RTU simulator and unwanted exception replies to foreign unit IDs. Both were fixed that day: startup uses the stock PyModbus 3.16.1 interface, and the receive PDU hook discards foreign units before datastore access. All 51 tests in the selected API/project/configuration suite passed in a clean Python environment, including actual CLI startup and RTU request/response over loopback in single-device and multidrop modes. Physical RS485 was not exercised. The existing Python multidrop baud limit remains; the [Go simulator](../tools/modbus-rtu-sim/README.md) is a separate backend.

## Recorded setup (2026-09-18)


Current bench topology, procedures and verified limits: [`docs/modbus-bench.md`](modbus-bench.md). Gateway driver profiles and current setup requirements: [NE2-D11P](gateways/ebyte-ne2-d11p.md) and [NA111-E](gateways/ebyte-na111-e.md). The bench narrative below records earlier configurations; consult the profiles before using its historical IP addresses, baud rates or simulator commands.

The separate CODESYS project is `../codesys_projects/modbus_tcp_bench/modbus_tcp_bench.project`.
It targets **P2CDS-622-DEV** through `Gateway-1`. Its two Modbus TCP targets read unit **1**,
function **03**, zero-based holding-register offsets **0–1**, once per second. The expected
words are **1234, 5678**. This project has no physical output mappings.

| Connection | Address / settings |
| --- | --- |
| PLC ETH1, local LAN | `192.168.50.123/24` via DHCP; gateway `192.168.50.1` |
| PLC ETH2, local LAN test | `192.168.50.125/24` via DHCP; no gateway reported |
| PC USB Ethernet | `192.168.3.100/24` |
| PC TCP simulator, isolated switch | `192.168.3.100:502`, retained but unused in current test |
| PC TCP simulator, LAN | `192.168.50.108:502`, unit 1 |
| Ebyte NE2-D11P gateway, LAN | `192.168.50.151:502` via DHCP |
| PC RTU simulator | FTDI `COM18`, 9600 baud, 8N1, unit 1 |
| PLC USB maintenance link | PLC `169.254.102.37/30`, PC `169.254.102.38/30` |

ETH1's address is a DHCP lease. Reserve it on the LAN DHCP server using MAC
`60:52:D0:08:05:83` if a fixed management address is needed. ETH2's MAC is
`60:52:D0:08:05:84`. Keep the Ethernet device's **Adjust operating system settings**
option off. The project now includes **P2CDS622_NetConfig** under the CPU:

- ETH1 DHCP is enabled. Its static address fields are unused and left zero.
- ETH2 DHCP is enabled for the dual-LAN experiment; its static fields are unused and zero.
- DNS obtains its settings from DHCP.
- The three **Adjust Ethernet Settings** flags are **FALSE** in the final project.

`ETH1_LAN` selects `et1` and has no Modbus client beneath it. The ETH1 Modbus test
branch and its unused program variables were removed at the user's request.
`ETH2_LAN` selects `et2`; its `Modbus_TCP_Client` contains `PC_TCP_Server` and
`Gateway_RTU_Server`. The PC target addresses `192.168.50.108:502`, and the gateway
target addresses `192.168.50.151:502`. Both physical PLC ports remain on the LAN.

Before removing the ETH1 Modbus branch, the user requested a test with both PLC ports physically connected to the same LAN.
The gateway reported its PLC client as `192.168.50.125`, and both PC connections
also used `.125`, including the connection configured beneath `ETH1_LAN`. Therefore,
node selection did not produce independent source addresses in this experiment.
The test establishes working Modbus reads in this arrangement; it does not establish
deterministic routing across restarts or prove that the field system's drops have the
same cause. Evidence is in `logs/dual_lan_stability_1.json`,
`logs/dual_lan_stability_2.json`, `logs/dual_lan_gateway_peer.json`, and
`logs/dual_lan_pc_peers.json`. The prior working split-network project is backed up
beside the project as `modbus_tcp_bench.project.before-dual-lan-test`; restoring it
also requires reapplying ETH2's static `192.168.3.10/24` settings through NetConfig.
The gateway's MAC is `B0-CB-D8-4E-88-BB`; reserve its DHCP lease before relying on a
fixed Modbus target address. Its former static address was `192.168.3.7`.
The first DHCP change did not survive restart. A second save, followed by a ten-second
wait before restart, produced a verified DHCP lease. Serial and Modbus settings matched
the pre-change backup in `temp/bench/gateway-before-dhcp/`.

The settings were downloaded once with the Adjust flags TRUE, checked against the
PLC's live port configuration, then downloaded again with the flags FALSE. This
follows the [vendor NetConfig procedure](https://docs.codesys-p2cds622.com/en/latest/Communications/ethernet.html).
The final application was also saved as the PLC boot application. The project backup
before this change is `modbus_tcp_bench.project.before-netconfig-20260918` beside the project.

Start these simulators in separate terminals when they are not already running:

```powershell
python modbus_tcp_slave_sim.py --host 192.168.3.100 --unit 1
python modbus_tcp_slave_sim.py --host 192.168.50.108 --unit 1
python modbus_rtu_slave_sim.py --port COM18 --baudrate 9600 --unit 1 --holding 1234,5678,9012,3456
```

With the bench project open and `PERSISTENT_SESSION.py` running in the IDE, check
actual PLC values with:

```powershell
python verify_modbus_bench.py
# Observe for longer without logging out and reconnecting:
python verify_modbus_bench.py --duration 40
```

The check requires both pairs of registers to match, both device error flags to be
false, and the PLC scan counter to advance. It does not download or start an application.
It reuses the existing online session and waits 250 ms between sample reads. After a separate
download, stale CODESYS variable references may require recreating the online handle.
`PLC_PRG.BenchRegisters` holds direct TCP results; `PLC_PRG.GatewayRegisters` holds
results from the gateway/RS485 path; `PLC_PRG.BothPathsPass` combines them.
The removed ETH1 test used `PLC_PRG.LANBenchRegisters` and `PLC_PRG.LANValuesMatch`.
The current ETH2-only Modbus check is recorded in `logs/eth2_only_modbus_check.json`.

The ETH1-to-PC test passed, with the server confirming the PLC peer address
`192.168.50.123`. After moving the gateway onto the LAN, its status page confirmed
a connection from that same PLC address, but register reads timed out and COM18
received no RTU requests. A direct PC request reproduced the missing serial traffic
with the bench application paused. The user observed gateway TX activity but no
USB adapter RX activity, then redid the adapter's RS485 wiring. Valid RTU requests
and replies returned, followed by correct PLC register values. This points to an
intermittent terminal connection; the exact faulty contact was not identified.
The adapter was also power-cycled and its simulator restarted during diagnosis.
See `logs/eth1_pc_lan_check.json`, `logs/gateway_lan_dhcp_verified.json`, and
`logs/eth1_all_paths_final.json` for the final checks. Earlier failed checks are
retained in `logs/eth1_all_paths_stability.json` and `logs/eth1_all_paths_recovered.json`.

After adding NetConfig, two 40-second online checks passed (118 samples total).
Simulator logs also showed continuous one-second requests for over two minutes,
with no direct-PC TCP disconnects. This does not reproduce or resolve the separate
field system's reported `TCP_COMMUNICATION_ERROR`. During this change, both bench
targets were found without polling channels; their tested FC03 channels were restored
and confirmed present after reopening a copy of the saved project.

The session's simulator logs and verification results are in `logs/`. The PLC's prior
boot application was copied to `../codesys_projects/modbus_tcp_bench/backup/` before
loading the bench application. These `.app` and `.crc` files are compiled backups,
not editable source or a snapshot of live retained values.

The original network settings placed ETH1 at `10.2.40.25/23` and ETH2 at
`169.254.214.199/16`. ETH2 therefore did not share the gateway's `192.168.3.0/24`
subnet. After correcting the addresses, both PLC paths returned the expected words.
The older failing application was not available as source, so this does not establish
whether it had additional configuration problems. In particular, the TCP target's
unit ID must match the RTU slave ID; this bench uses 1, whereas a new CODESYS TCP
server device defaults to 255.

`run_ide_script.py <script.py>` can submit a script through the existing IDE session.
It gives submitted scripts a shared global/local namespace, avoiding the legacy
runner's `name 'safe_text' is not defined` error during PLC discovery. Submitted
scripts must set a `result` dictionary with a `success` field.

### Managed RTU simulators

`POST /api/v1/modbus/simulator/apply` starts one simulator per PC serial port, and
`GET /api/v1/modbus/simulator/status` reports them. Add `"backend": "go"` to a bus
to use `build/rtu-sim.exe` in place of PyModbus. The Go backend supports multidrop
above 38,400 baud, can find its adapter by `usbSerial`, recovers from USB unplugs, and
supports `"silent": true` devices for timeout tests. See
[`tools/modbus-rtu-sim/README.md`](../tools/modbus-rtu-sim/README.md).
