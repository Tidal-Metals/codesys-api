# CODESYS LAN setup

On the PC running CODESYS. Requires Git, Python 3.11+, scripting support in the IDE, and access to the repository. For workstation prerequisites and project preparation, start with the [README](README.md#installation).

1. **Clone** in PowerShell:

   ```powershell
   git clone https://github.com/Tidal-Metals/codesys-api.git
   cd codesys-api
   py -3 -m venv venv
   .\venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   Already cloned? Run `git pull --ff-only` inside that folder when its working tree is clean, then install the requirements with your chosen Python environment.

2. **Create an API key** (replaces existing keys). Save the printed key:

   ```powershell
   .\venv\Scripts\python.exe -c "import json,secrets; from pathlib import Path; k=secrets.token_urlsafe(32); Path('api_keys.json').write_text(json.dumps({k:{'name':'Diagnostics'}})); print(k)"
   ```

3. **In the existing CODESYS IDE**, keep the field project open and online. Select **Tools → Scripting → Execute Script File**, then run `PERSISTENT_SESSION.py` from this repo folder.

4. **Start the server** from the same repo folder in PowerShell:

   ```powershell
   .\venv\Scripts\python.exe field_api_server.py
   ```

   If Windows shows a firewall prompt for **Python**, click **Allow access** for the network profile used by your LAN. Administrator rights are required.

Leave the IDE script and server running. Send us the printed LAN URL and the API key privately. We'll verify the connection from here.

If no prompt appears and we cannot connect, we'll check the firewall rules.
