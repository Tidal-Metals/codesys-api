"""Online changes while the reworked TLS client is connected or connecting (CODESYS-MQTT docs/tls-design.md).

    python examples/mqtt_large_payload/tls_online_change_test.py --out results/exp/tls/tls_online_change.json

Needs what tls_client_test.py needs (bench broker, CA trusted, demo with patch_demo_tls.py). Each step makes an
online change in the session project (OnlineChangeOption.Force: online change or nothing, never a full download):
  layout   a variable added to PLC_PRG, which holds the client: its instance is copied, so IP_CONTROL.FB_Reinit runs
           and must close the TLS connection (CmpTls keeps the verifier's old address), and the client reconnects
  code     only an assignment changed: nothing is copied, the TLS connection stays
  shift    256 bytes inserted at the top of PLC_PRG's variables, so MqttLink certainly moves
  pending  a layout change while TLS connects to an address that never answers (a context mid-connect); afterwards
           the trusted broker must connect and verify normally
For each: the change applied, the application runs and scans, connect attempts and peer closes before and after,
IsTlsVerified, and the socket layer's state. The session project keeps the edits; redeploy.sh rebuilds the copy.
"""
import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import mqtt5_test as m5  # noqa: E402
import tls_client_test as tc  # noqa: E402  (its import also gives every IDE call 300 s)

C = m5.C
CHANGE = """
import time
from scriptengine import OnlineChangeOption
p = scriptengine.projects.primary
assert p.path.replace('\\\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
kind, n = @@KIND@@, @@N@@
prg = p.find('PLC_PRG', True)[0]
decl = prg.textual_declaration.text
impl = prg.textual_implementation.text
if kind in ('layout', 'pending'):
    at = decl.find(u'END_VAR')
    prg.textual_declaration.replace(decl[:at] + u'\\tTlsOcExtra%d : UDINT := %d;\\n' % (n, n) + decl[at:])
elif kind == 'shift':
    # before everything else in the first VAR block, so every variable after it (MqttLink included) moves
    at = decl.find(u'VAR')
    at = decl.find(u'\\n', at) + 1
    prg.textual_declaration.replace(decl[:at] + u'\\tTlsOcShift%d : ARRAY[0..63] OF UDINT;\\n' % n + decl[at:])
marker = u'// tls_online_change_test'
lines = [l for l in impl.split(u'\\n') if marker not in l]
prg.textual_implementation.replace(u'\\n'.join(lines).rstrip() + u'\\nTlsOcValue := %d; %s\\n' % (n, marker))
if u'TlsOcValue' not in prg.textual_declaration.text:
    decl = prg.textual_declaration.text
    at = decl.find(u'END_VAR')
    prg.textual_declaration.replace(decl[:at] + u'\\tTlsOcValue : UDINT;\\n' + decl[at:])
on = session.ensure_online_application('', False)
try:
    logged = bool(on.is_logged_in)
except Exception:
    logged = False
if logged:
    on.logout()
started = time.time()
error = None
try:
    on.login(OnlineChangeOption.Force, False)
except Exception as exc:
    error = str(exc)
out = {'success': True, 'loginSeconds': round(time.time() - started, 1), 'error': error,
       'state': str(on.application_state)}
session.dispose_online_application(session.find_application('')[1]['path'], True)
result = out
"""
STATE = [C + ".counts.CountConnectAttempt", C + ".counts.CountPeerCloses", "PLC_PRG.IsBrokerConnected",
         C + ".MQTT_INFO.IsTlsVerified", C + ".MQTT_CONTROL.IPC.state", C + ".MQTT_CONTROL.IPC.TLS",
         "PLC_PRG.CycleStartUs", C + ".ERROR_T", C + ".ERROR_C", C + ".MQTT_CONTROL.IPC.VerifierAddress",
         C + ".MQTT_CONTROL.IPC.VerifierAddressAtContext", C + ".MQTT_CONTROL.IPC.TlsRelocationCloses"]


def snapshot(label: str) -> dict:
    values = m5.short(m5.read(STATE))
    values["at"] = label
    return values


def connect(case: str) -> None:
    name, make_url, is_tls, config, _ = tc.CASES[case]
    m5.write([("PLC_PRG.TlsConfig." + k, v) for k, v in dict(tc.DEFAULTS, **config).items()]
             + [("PLC_PRG.IsTlsEnabled", "TRUE" if is_tls else "FALSE"), ("PLC_PRG.BrokerUrl", "'%s'" % make_url()),
                ("PLC_PRG.MqttLink.ProtocolVersion", "5"), (C + ".DoDisconnect", "TRUE")])


def wait_connected(seconds: float) -> bool:
    return m5.wait_for(["PLC_PRG.IsBrokerConnected", C + ".MQTT_INFO.IsTlsVerified"],
                       lambda v: v["PLC_PRG.IsBrokerConnected"] == "TRUE" and v[C + ".MQTT_INFO.IsTlsVerified"] == "TRUE",
                       seconds) is not None


def online_change(kind: str, n: int) -> dict:
    result = m5.execute(CHANGE.replace("@@KIND@@", repr(kind)).replace("@@N@@", str(n)), 600)
    return {k: result.get(k) for k in ("success", "loginSeconds", "error", "state")}


def run_step(kind: str, n: int) -> dict:
    out = {"step": kind}
    if kind == "pending":
        connect("unanswered")
        time.sleep(6)                       # the first attempt is mid-connect or resting 1 s
    else:
        connect("trusted_ip")
        out["connected_before"] = wait_connected(60)
        time.sleep(5)
    out["before"] = snapshot("before")
    out["change"] = online_change(kind, n)
    time.sleep(3)
    out["just_after"] = snapshot("just after")
    if kind == "pending":
        connect("trusted_ip")
    out["reconnected_verified"] = wait_connected(90)
    time.sleep(5)
    out["after"] = snapshot("after")
    scans = [int(out["before"]["CycleStartUs"]), int(out["after"]["CycleStartUs"])]
    out["scanning"] = scans[1] != scans[0]
    out["reconnects"] = int(out["after"]["client.counts.CountConnectAttempt"]) - int(
        out["before"]["client.counts.CountConnectAttempt"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--steps", default="layout,code,pending")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = {"started": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": []}
    base = int(time.time()) % 100000
    try:
        for index, kind in enumerate(args.steps.split(",")):
            step = run_step(kind, base + index)
            brief = {k: step.get(k) for k in ("step", "change", "connected_before", "reconnected_verified", "scanning",
                                              "reconnects")}
            brief["peer_closes"] = [step["before"]["client.counts.CountPeerCloses"],
                                    step["after"]["client.counts.CountPeerCloses"]]
            brief["ipc_state_before_after"] = [step["before"]["client.MQTT_CONTROL.IPC.state"],
                                               step["just_after"]["client.MQTT_CONTROL.IPC.state"]]
            brief["verifier_address_before_after"] = [step["before"]["client.MQTT_CONTROL.IPC.VerifierAddress"],
                                                      step["just_after"]["client.MQTT_CONTROL.IPC.VerifierAddress"]]
            brief["relocation_closes"] = step["after"]["client.MQTT_CONTROL.IPC.TlsRelocationCloses"]
            print(json.dumps(brief), flush=True)
            result["steps"].append(step)
    finally:
        m5.write([("PLC_PRG.IsTlsEnabled", "FALSE")] + [("PLC_PRG.TlsConfig." + k, v) for k, v in tc.DEFAULTS.items()])
        result["restored"] = m5.reconnect(m5.HQ_URL, "4") is not None
        print("restored to HQ 3.1.1:", result["restored"], flush=True)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
