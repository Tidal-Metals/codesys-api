"""Install the roots that patch_demo_trust_roots.py compiled into the demo, with the library's MqttTrustCa, and report.

    python examples/mqtt_large_payload/tls_trust_roots.py IsrgRootX1 RootXa RootYb [IsrgRootX1 ...]

Each name pulses PLC_PRG.DoTrust<Name> and reads Trust<Name>.Done / Error / IsAlreadyTrusted / Result. A name given
twice shows the second install (expected: Done with IsAlreadyTrusted, result 18 = ERR_DUPLICATE).
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import tls_client_test  # noqa: E402,F401  (its import gives every IDE call 300 s)

for name in sys.argv[1:]:
    m5.write([("PLC_PRG.DoTrust" + name, "TRUE")])
    time.sleep(2)
    fields = ["Done", "Error", "IsAlreadyTrusted", "Result"]
    values = m5.read(["PLC_PRG.Trust%s.%s" % (name, f) for f in fields])
    print(json.dumps({"root": name, **{f: values["PLC_PRG.Trust%s.%s" % (name, f)] for f in fields}}), flush=True)
    m5.write([("PLC_PRG.DoTrust" + name, "FALSE")])
    time.sleep(1)
