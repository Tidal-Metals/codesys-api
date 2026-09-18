# CODESYS LAN setup

On the PC running CODESYS. Requires Git, Python 3.11+, and access to the repository.

1. **Clone** in PowerShell:

   ```powershell
   git clone https://github.com/Tidal-Metals/codesys-api.git
   cd codesys-api
   ```

   Already cloned? Run `git pull --ff-only` inside that folder.

2. **Create an API key** (replaces existing keys). Save the printed key:

   ```powershell
   py -3 -c "import json,secrets; from pathlib import Path; k=secrets.token_urlsafe(32); Path('api_keys.json').write_text(json.dumps({k:{'name':'Diagnostics'}})); print(k)"
   ```

3. **In the existing CODESYS IDE**, keep the field project open and online. Select **Tools → Scripting → Execute Script File**, then run `PERSISTENT_SESSION.py` from this repo folder.

4. **Allow our PC through the firewall**. Run once in Administrator PowerShell; replace `192.168.50.108` if our diagnostic PC's address differs:

   ```powershell
   New-NetFirewallRule -DisplayName 'CODESYS diagnostics' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8081 -RemoteAddress 192.168.50.108 -Profile Any
   ```

5. **Start the server** from the same repo folder in ordinary PowerShell:

   ```powershell
   py -3 field_api_server.py
   ```

Leave the IDE script and server running. Send us the printed LAN URL and the API key privately. We'll verify the connection from here.
