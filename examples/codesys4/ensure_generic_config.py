"""Add an empty BaseDevice.GenericDeviceConfig entry to *.device.json files that lack one.

CODESYS 4 1.0's AddDevice RPC and ResetDeviceConfig don't always write it, and without it the device
can't take children ("ParentDeviceConfigMissing") or compile ("GenericDeviceConfig is missing").
Usage: python ensure_generic_config.py <device.json> [...]
"""
import json
import sys
from pathlib import Path

EMPTY = {"configuration": {"parameterSets": {"deviceParameterSet": [], "hostParameterSets": {}}}}

for name in sys.argv[1:]:
    path = Path(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    extensions = data.setdefault("extensions", {})
    if "BaseDevice.GenericDeviceConfig" not in extensions:
        extensions["BaseDevice.GenericDeviceConfig"] = EMPTY
        path.write_text(json.dumps(data, indent="\t") + "\n", encoding="utf-8")
        print(f"added GenericDeviceConfig: {path.name}")
