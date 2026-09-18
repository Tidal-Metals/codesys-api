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

4. **Start the server** from the same repo folder in PowerShell:

   ```powershell
   py -3 field_api_server.py
   ```

   If Windows shows a firewall prompt for **Python**, click **Allow access** for the network profile used by your LAN. Administrator rights are required.

Leave the IDE script and server running. Send us the printed LAN URL and the API key privately. We'll verify the connection from here.

If no prompt appears and we cannot connect, we'll check the firewall rules.
