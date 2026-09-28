# CODESYS REST API

For LAN diagnostics using an already-open IDE, follow [Connect to an existing CODESYS IDE](FIELD_ACCESS.md). This uses `field_api_server.py`, which leaves IDE process management with the operator.

![CODESYS API Logo](https://via.placeholder.com/1200x300/0073CF/FFFFFF?text=CODESYS+REST+API)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.x-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)]()

A persistent RESTful API wrapper for CODESYS automation software, allowing for seamless integration with other systems and automation of CODESYS operations.

## 📋 Features

- **Persistent CODESYS Session**: Maintains a single running instance of CODESYS for improved performance
- **RESTful API**: Provides standard HTTP endpoints for all CODESYS operations
- **Session Management**: Start, stop, and monitor CODESYS sessions
- **Project Operations**: Create, open, save, close, and compile projects
- **POU Management**: Create and modify Program Organization Units
- **Script Execution**: Execute arbitrary CODESYS scripts
- **Authentication**: Secure access with API keys
- **Windows Service**: Run as a background service with auto-recovery
- **Comprehensive Logging**: Detailed activity and error logging

## 🚀 Quick Start

### Prerequisites

- Windows OS with CODESYS 3.5 or later installed
- Python 3.x installed
  - Note: Only the PERSISTENT_SESSION.py script maintains compatibility with CODESYS IronPython environment
- Administrator privileges (for service installation)

### Installation

1. Clone this repository:
   ```
   git clone https://github.com/johannesPettersson80/codesys-api.git
   ```

2. Navigate to the project directory:
   ```
   cd codesys-api
   ```

3. Install required packages:
   ```
   pip install requests pywin32
   ```

4. Run the installation script:
   ```
   install.bat
   ```

   If you prefer not to install as a Windows service, use:
   ```
   start_server.bat
   ```

5. Verify the installation:
   ```
   python example_client.py
   ```

For detailed installation instructions, see the [Installation Guide](INSTALLATION_GUIDE.md) and [CODESYS Script Compatibility Guide](CODESYS_SCRIPT_COMPATIBILITY.md).

### Verified Manual Invocation

The working invocation path for the real server is:

1. Review [`server_config.py`](server_config.py) and confirm:
   - `CODESYS_PATH`
   - `CODESYS_PROFILE`
   - `SERVER_HOST`
   - `SERVER_PORT`
2. Start the HTTP API server:
   ```
   python HTTP_SERVER.py
   ```
   Or:
   ```
   run_server.bat
   ```
3. Start the persistent CODESYS session through the API:
   ```
   curl -X POST -H "Authorization: ApiKey admin" -H "Content-Type: application/json" -d "{}" http://localhost:8080/api/v1/session/start
   ```
4. Verify the session:
   ```
   curl -H "Authorization: ApiKey admin" http://localhost:8080/api/v1/session/status
   ```

Replace `8080` with the port you actually started the server on.

Important:

- Starting `HTTP_SERVER.py` only starts the HTTP listener. It does **not** launch CODESYS until `POST /api/v1/session/start` is called.
- CODESYS is started with the persistent script `PERSISTENT_SESSION.py` using the configured profile and executable path from `server_config.py`.
- If port `8080` is already in use, either change `SERVER_PORT` in `server_config.py` or launch with an override:
  ```
  python -c "import server_config; import HTTP_SERVER; server_config.SERVER_PORT = 8081; HTTP_SERVER.SERVER_PORT = 8081; HTTP_SERVER.run_server()"
  ```
- For a repeatable startup path that handles stale bridge processes and starts the persistent session for you:
  ```
  python launch_session.py --project "C:\Users\KevinTritz\OneDrive - Tidal Metals\Documents\Codesys\test.project"
  ```

## 📖 API Documentation

### P2CDS-622 Modbus bench (verified 2026-09-18)

Current bench topology, procedures and verified limits: [`docs/modbus-bench.md`](docs/modbus-bench.md). Gateway driver profiles and current setup requirements: [NE2-D11P](docs/gateways/ebyte-ne2-d11p.md) and [NA111-E](docs/gateways/ebyte-na111-e.md). The bench narrative below records earlier configurations; consult the profiles before using its historical IP addresses, baud rates or simulator commands.

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
[`tools/modbus-rtu-sim/README.md`](tools/modbus-rtu-sim/README.md).

### Authentication

All API requests require an API key in the header:

```
Authorization: ApiKey YOUR_API_KEY
```

### Endpoints

#### Session Management

- `POST /api/v1/session/start`: Start CODESYS session
- `POST /api/v1/session/stop`: Stop CODESYS session
- `GET /api/v1/session/status`: Get session status
- `POST /api/v1/session/restart`: Restart CODESYS session

#### Project Operations

- `POST /api/v1/project/create`: Create new project
- `POST /api/v1/project/open`: Open existing project
- `POST /api/v1/project/save`: Save current project
- `POST /api/v1/project/close`: Close current project
- `POST /api/v1/project/compile`: Compile project
- `GET /api/v1/project/list`: List recent projects

#### POU Management

- `POST /api/v1/pou/create`: Create new POU
- `POST /api/v1/pou/code`: Set POU code
- `GET /api/v1/pou/list`: List POUs in project

#### Script Execution

- `POST /api/v1/script/execute`: Execute arbitrary script

#### System Operations

- `GET /api/v1/system/info`: Get system information
- `GET /api/v1/system/logs`: Get system logs

## 📝 Example Usage

### Example Client

The repository includes an example client (`example_client.py`) demonstrating basic operations:

```python
import requests

# API configuration
API_BASE_URL = "http://localhost:8080/api/v1"
API_KEY = "admin"  # Default API key

# Call API with authentication
def call_api(method, endpoint, data=None):
    headers = {"Authorization": f"ApiKey {API_KEY}"}
    url = f"{API_BASE_URL}/{endpoint}"
    
    if method.upper() == "GET":
        response = requests.get(url, headers=headers)
    elif method.upper() == "POST":
        response = requests.post(url, json=data, headers=headers)
        
    return response.json()

# Start a session
result = call_api("POST", "session/start")
print(f"Session started: {result}")

# Create a project
project_data = {"path": "C:/Temp/TestProject.project"}
result = call_api("POST", "project/create", project_data)
print(f"Project created: {result}")
```

For a complete example workflow, see the [example_client.py](example_client.py) file.

## 🧰 Architecture

The CODESYS REST API consists of several key components:

1. **HTTP REST API Server**: Processes incoming requests and routes them to handlers
2. **CODESYS Session Manager**: Maintains and monitors the persistent CODESYS instance
3. **Script Execution Engine**: Generates and executes scripts in the CODESYS environment
4. **Authentication System**: Validates API keys and controls access

For more information about the architecture, see the [Project Summary](PROJECT_SUMMARY.md).

## 🔧 Configuration

### Server Configuration

Server settings are configured in `server_config.py`:

```python
SERVER_HOST = '0.0.0.0'  # Listen on all interfaces
SERVER_PORT = 8080       # HTTP port
CODESYS_PATH = r"C:\Program Files\CODESYS 3.5.22.10\CODESYS\Common\CODESYS.exe"
CODESYS_PROFILE = "CODESYS V3.5 SP22 Patch 1"
```

### API Keys

API keys are stored in `api_keys.json`:

```json
{
  "admin": {"name": "Admin", "created": 1620000000.0}
}
```

## 📚 Documentation

- [Installation Guide](INSTALLATION_GUIDE.md): Detailed installation instructions
- [Implementation Checklist](IMPLEMENTATION_CHECKLIST.md): Development progress and status
- [Python 2.7 Compatibility](PY27_COMPATIBILITY.md): Notes on Python 2.7 compatibility
- [Project Summary](PROJECT_SUMMARY.md): Overview of implementation details

## 🚨 Troubleshooting

### Common Issues

- **API returns "Unauthorized"**: Check that you're using the correct API key
- **Service fails to start**: Verify CODESYS path is correct and CODESYS is installed
- **Connection refused**: Ensure the service is running and the port is not blocked
- **`[WinError 10013]` on startup**: Another process is already listening on `SERVER_PORT`; pick a different port
- **`/system/info` works but CODESYS is not running**: Call `POST /api/v1/session/start` to launch the persistent CODESYS session

### Logs

Check the following log files for error messages:

- `codesys_api_server.log`: Main API server log
- `session.log`: CODESYS session log
- `codesys_api_service.log`: Windows service log (if running as a service)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgements

- CODESYS Group for the CODESYS automation software and scripting API
- Python community for excellent libraries and tools
- All contributors to this project
