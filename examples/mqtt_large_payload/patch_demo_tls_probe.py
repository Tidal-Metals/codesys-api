# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_tls_probe.py): add the TLS
# connect probe to the MQTT 5 demo copy only (mqtt_large_payload_demo_mqtt5), then save. Idempotent.
#   - library references the probe calls directly: placeholders SysSocket2, CmpTls, CmpX509Cert (resolutions as in
#     CODESYS-MQTT/build.json) and SysTypes2 Interfaces, CmpErrors2 Interfaces
#   - DUT TlsProbeByteString and PROGRAM TlsProbe from st/tls/, with CaDer filled from tmp/mqtt5_bench/tls/ca.der
#     (make_bench_certs.sh)
#   - task ProbeTask: cyclic 20 ms, priority 20 (MainTask is 1), calling TlsProbe, so a blocking call there shows
#     as ProbeTask stalls while MainTask keeps its 50 ms
import io
import os

from scriptengine import DutType, KindOfTask, PouType

MARKER = u"// ---- implementation ----"
HOME = os.path.expanduser("~")
SOURCE_DIR = os.path.join(HOME, "projects", "codesys-api", "examples", "mqtt_large_payload", "st", "tls")
CA_DER = os.path.join(HOME, "projects", "codesys-api", "tmp", "mqtt5_bench", "tls", "ca.der")
PLACEHOLDERS = [("SysSocket2", "SysSocket2, 3.5.19.0 (System)"), ("CmpTls", "CmpTls, 3.5.17.0 (System)"),
                ("CmpX509Cert", "CmpX509Cert, 3.5.17.0 (System)")]
LIBRARIES = [("SysTypes2 Interfaces, 3.5.4.0 (System)", "SysTypes"),
             ("CmpErrors2 Interfaces, 3.5.15.0 (System)", "CmpErrors")]

p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
changed = []


def read(name):
    with io.open(os.path.join(SOURCE_DIR, name + ".st"), encoding="utf-8") as handle:
        return handle.read()


def update_text(document, text, label):
    if document.text.rstrip() != text.rstrip():
        document.replace(text)
        changed.append(label)


# ---- library references
libman = [o for o in p.get_children(True) if getattr(o, 'is_libman', False)][0]
present = set(unicode(ref.name) for ref in libman.references)
for name, resolution in PLACEHOLDERS:
    if u"#" + name not in present:
        libman.add_placeholder(name, resolution)
        changed.append('placeholder ' + name)
for name, namespace in LIBRARIES:
    if name not in present:
        libman.add_library(name)
        changed.append('library ' + name)
namespaces = dict([(u"#" + n, n) for n, _ in PLACEHOLDERS] + [(n, ns) for n, ns in LIBRARIES])
for ref in libman.references:
    wanted = namespaces.get(unicode(ref.name))
    if wanted and unicode(ref.namespace) != wanted:
        ref.namespace = wanted
        changed.append('namespace ' + wanted)

# ---- DUT and program
prg = p.find('PLC_PRG', True)[0]
app = prg.parent
found = p.find('TlsProbeByteString', True)
dut = found[0] if found else app.create_dut('TlsProbeByteString', DutType.Structure)
update_text(dut.textual_declaration, read('TlsProbeByteString'), 'TlsProbeByteString')

def source_parts(name):
    declaration, implementation = read(name).split(MARKER + u"\n", 1)
    return declaration.rstrip() + u"\n", implementation


def textual(name):
    found = [o for o in p.find(name, True) if getattr(o, 'has_textual_declaration', False)]
    return found[0] if found else None


verifier = textual('TlsProbeVerifier') or app.create_pou(name='TlsProbeVerifier', type=PouType.FunctionBlock)
declaration, implementation = source_parts('TlsProbeVerifier')
update_text(verifier.textual_declaration, declaration, 'TlsProbeVerifier declaration')
update_text(verifier.textual_implementation, implementation, 'TlsProbeVerifier implementation')
methods = [o for o in verifier.get_children(False) if o.get_name() == 'VerifyCertCallback']
method = methods[0] if methods else verifier.create_method('VerifyCertCallback', 'SysTypes.RTS_IEC_RESULT')
declaration, implementation = source_parts('TlsProbeVerifier.VerifyCertCallback')
update_text(method.textual_declaration, declaration, 'VerifyCertCallback declaration')
update_text(method.textual_implementation, implementation, 'VerifyCertCallback implementation')

with open(CA_DER, 'rb') as handle:
    ca = bytearray(handle.read())
items = [u"16#%02X" % b for b in ca]
lines = [u", ".join(items[i:i + 16]) for i in range(0, len(items), 16)]  # whole literals per line
source = read('TlsProbe').replace(u'{CA_LAST}', unicode(len(ca) - 1)).replace(u'{CA_BYTES}', u",\n\t\t".join(lines))
declaration, implementation = source.split(MARKER + u"\n", 1)
found = [o for o in p.find('TlsProbe', True) if getattr(o, 'has_textual_declaration', False)]  # not the task call
probe = found[0] if found else app.create_pou(name='TlsProbe', type=PouType.Program)
update_text(probe.textual_declaration, declaration.rstrip() + u"\n", 'TlsProbe declaration')
update_text(probe.textual_implementation, implementation, 'TlsProbe implementation')

# ---- task
taskconfig = [o for o in app.get_children(True) if getattr(o, 'is_task_configuration', False)][0]
tasks = [o for o in taskconfig.get_children(False) if o.get_name() == 'ProbeTask']
if tasks:
    task = tasks[0]
else:
    task = taskconfig.create_task('ProbeTask')
    task.kind_of_task = KindOfTask.Cyclic
    task.interval = 't#20ms'
    task.priority = '20'
    changed.append('task ProbeTask')
if not [pou for pou in task.pous if 'TlsProbe' in unicode(getattr(pou, 'name', pou))]:
    task.pous.add('TlsProbe')
    changed.append('ProbeTask calls TlsProbe')
p.save()
result = {'success': True, 'changed': changed, 'caBytes': len(ca),
          'task': {'interval': str(task.interval), 'priority': str(task.priority)}}
