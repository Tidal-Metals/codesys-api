# Connect to an existing CODESYS IDE over LAN

Use this setup to inspect a field project that is already open in CODESYS. The HTTP server and IDE script must run on the same Windows computer and use the same repository folder.

## 1. Clone the repository

Install Git and Python 3.11 or newer if needed. In PowerShell, using a GitHub account with access to Tidal-Metals:

```powershell
New-Item -ItemType Directory -Force "$env:USERPROFILE\projects" | Out-Null
Set-Location "$env:USERPROFILE\projects"
git clone https://github.com/Tidal-Metals/codesys-api.git
Set-Location codesys-api
```

For an existing clean clone, use `git pull --ff-only` in that folder. The manual server uses Python's standard library; no service installation is needed.

## 2. Create a local API key

Run this once in the repository folder, before starting the server. It replaces any keys in this clone and prints the new key:

```powershell
py -3 -c "import json,secrets,time; from pathlib import Path; k=secrets.token_urlsafe(32); Path('api_keys.json').write_text(json.dumps({k:{'name':'Field diagnostics','created':time.time()}}),encoding='utf-8'); print(k)"
```

Keep the key for the connection test and give it to the person performing diagnostics through your usual private channel. The API supports script execution and PLC/project changes; this launcher is not a read-only access control.

## 3. Run the script inside CODESYS

Keep the field project open in the existing IDE, preferably already online and showing the fault. Save any intended project edits first.

Select **Tools → Scripting → Execute Script File**, then select `PERSISTENT_SESSION.py` from this clone. Run it once in that IDE. Leave the script running; it waits for requests. Running it does not itself download or start a PLC application.

This is the [documented CODESYS script menu](https://content.helpme-codesys.com/en/CODESYS%20Scripting/_cds_python_first_steps.html). If the menu is unavailable, that IDE installation needs CODESYS Scripting support.

## 4. Start the HTTP server

In ordinary PowerShell, from the same repository folder:

```powershell
py -3 field_api_server.py
```

The server listens on all IPv4 interfaces at port `8081` by default and prints the available LAN/VPN URLs, such as `http://192.168.50.108:8081`. Choose the address reachable from the diagnostic computer. Use `--port 8082` to change the port, or `--host 127.0.0.1` for access only from this PC. Windows Firewall must also allow the connection as described below.

Leave this window open. This launcher attaches through the script's request files. It does not use the configured CODESYS executable path, launch another IDE, terminate duplicate IDEs, or stop the IDE when the HTTP server exits. `Ctrl+C` stops only this HTTP server. Session stop/restart endpoints cannot manage the IDE through this launcher.

## 5. Allow the diagnostic computer through Windows Firewall

In **PowerShell as Administrator**, replace the example address with the diagnostic computer's reachable LAN/VPN IPv4 address:

```powershell
$diagnosticPC = '192.168.50.108'
New-NetFirewallRule -DisplayName 'CODESYS field diagnostics 8081' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8081 -RemoteAddress $diagnosticPC -Profile Any
```

Use the reachable LAN/VPN connection; this is plain HTTP and should not be forwarded from the public internet.

## 6. Check the IDE connection

In a second ordinary PowerShell window:

```powershell
$apiKey = Read-Host 'API key'
$headers = @{ Authorization = "ApiKey $apiKey" }
$body = @{ script = "result = {'success': True, 'project_open': scriptengine.projects.primary is not None}" } | ConvertTo-Json
Invoke-RestMethod -Uri 'http://127.0.0.1:8081/api/v1/script/execute' -Method Post -Headers $headers -ContentType 'application/json' -Body $body
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object InterfaceAlias,IPAddress
```

The probe should return `success: True` and `project_open: True`. It reads project presence only. A timeout usually means the script is not running or it was started from a different repository folder.

Send the diagnostic operator the computer's reachable IP address, port `8081`, and API key. On the diagnostic computer, `Test-NetConnection <field-PC-IP> -Port 8081` checks reachability; repeating the HTTP probe with that IP checks the complete path.

Start with observations of the current fault. Opening a project, logging in, downloading, starting/stopping the PLC, or changing parameters are separate actions from this connection test.
