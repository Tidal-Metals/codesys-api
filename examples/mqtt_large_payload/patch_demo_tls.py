# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_tls.py): add an online TLS
# switch to the MQTT 5 demo copy only (mqtt_large_payload_demo_mqtt5), then save.
# PLC_PRG.IsTlsEnabled (default FALSE) replaces TLS := FALSE in both client calls, and PLC_PRG.TlsConfig
# (MQTT.TLS_CONFIG, the library defaults) is wired to MqttLink.TLS_CONFIG before each call: TLS with a null
# TLS_CONFIG would dereference a null pointer. Used by tls_test.py. Idempotent.
p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
prg = p.find('PLC_PRG', True)[0]
call = p.find('CallClient', True)[0]
changed = []
decl = prg.textual_declaration.text
if u'IsTlsEnabled' not in decl:
    anchor = u'IsSendInFlight : BOOL;'
    assert decl.count(anchor) == 1, 'IsSendInFlight declaration not found once'
    decl = decl.replace(anchor, anchor + u'\n\tIsTlsEnabled : BOOL := FALSE;  // tls_test.py: TRUE connects over TLS'
                        u'\n\tTlsConfig : MQTT.TLS_CONFIG;  // tls_test.py: library defaults, editable online')
    prg.textual_declaration.replace(decl)
    changed.append('declaration')
CALL = u'MqttLink.clientFB(MQTT_IN_OUT := MqttLink,'
WIRE = u'MqttLink.TLS_CONFIG := ADR(TlsConfig); '
OLD, NEW = u'TIMEOUT := T#10S, TLS := FALSE);', u'TIMEOUT := T#10S, TLS := IsTlsEnabled);'
for obj, label in ((prg, 'PLC_PRG call'), (call, 'CallClient call')):
    impl = obj.textual_implementation.text
    if NEW not in impl:
        assert impl.count(CALL) == 1, label + ': client call not found once'
        assert impl.count(OLD) == 1, label + ': TLS := FALSE not found once'
        impl = impl.replace(OLD, NEW).replace(CALL, WIRE + CALL)  # CallClient is a PLC_PRG method: same TlsConfig
        obj.textual_implementation.replace(impl)
        changed.append(label)
p.save()
result = {'success': True, 'changed': changed}
