# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_trust_roots.py): add CA
# certificates to the MQTT 5 demo copy (mqtt_large_payload_demo_mqtt5), each with a MQTT.MqttTrustCa that installs it
# into the PLC's Trusted store on PLC_PRG.DoTrust<Name> (online write). Then save. Idempotent.
#   IsrgRootX1   Let's Encrypt's root (from the Windows trust store, SHA-256 96BCEC06...08C6)
#   RootXa       hierarchy A's old root (make_lechain_certs.sh)
#   RootYb       hierarchy B's new self-signed root
# Outputs per root: PLC_PRG.Trust<Name>.Done, .Error, .IsAlreadyTrusted, .Result.
import io
import os

p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
TLS = os.path.join(os.path.expanduser("~"), "projects", "codesys-api", "tmp", "mqtt5_bench", "tls")
ROOTS = [("IsrgRootX1", os.path.join(TLS, "ISRGRootX1.der")), ("RootXa", os.path.join(TLS, "le", "rootXa.der")),
         ("RootYb", os.path.join(TLS, "le", "rootYb.der"))]
MARKER = u"// patch_demo_trust_roots"
prg = p.find('PLC_PRG', True)[0]
decl = prg.textual_declaration.text
impl = prg.textual_implementation.text
changed = []


def array_literal(data):
    items = [u"16#%02X" % b for b in bytearray(data)]
    return u",\n\t\t".join(u", ".join(items[i:i + 16]) for i in range(0, len(items), 16))


for name, path in ROOTS:
    with open(path, 'rb') as handle:
        der = handle.read()
    if u'Der%s :' % name not in decl:
        at = decl.find(u'END_VAR')
        block = (u'\tDer%s : ARRAY[0..%d] OF BYTE := [%s];  %s\n\tTrust%s : MQTT.MqttTrustCa;\n\tDoTrust%s : BOOL;\n'
                 % (name, len(der) - 1, array_literal(der), MARKER, name, name))
        decl = decl[:at] + block + decl[at:]
        changed.append('declare ' + name)
    call = u'Trust%s(Execute := DoTrust%s, pCertificate := ADR(Der%s), Size := SIZEOF(Der%s));  %s' % (
        name, name, name, name, MARKER)
    if call not in impl:
        impl = impl.rstrip() + u'\n' + call + u'\n'
        changed.append('call ' + name)
# and the library's bundled Let's Encrypt roots (MqttTrustLetsEncrypt, 1.4.0.0)
if u'TrustLetsEncrypt :' not in decl:
    at = decl.find(u'END_VAR')
    decl = decl[:at] + (u'\tTrustLetsEncrypt : MQTT.MqttTrustLetsEncrypt;  %s\n\tDoTrustLetsEncrypt : BOOL;\n' % MARKER) + decl[at:]
    changed.append('declare TrustLetsEncrypt')
call = u'TrustLetsEncrypt(Execute := DoTrustLetsEncrypt);  %s' % MARKER
if call not in impl:
    impl = impl.rstrip() + u'\n' + call + u'\n'
    changed.append('call TrustLetsEncrypt')
prg.textual_declaration.replace(decl)
prg.textual_implementation.replace(impl)
p.save()
result = {'success': True, 'changed': changed}
