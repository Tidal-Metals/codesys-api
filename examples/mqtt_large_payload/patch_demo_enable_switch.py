# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_enable_switch.py): add an online
# switch for the client's ENABLE to the MQTT 5 demo copy only (mqtt_large_payload_demo_mqtt5), then save.
# PLC_PRG.IsClientEnabled (default TRUE) replaces ENABLE := TRUE in both client calls (PLC_PRG's end-of-scan call and
# CallClient), so will_enable_test.py can close the client deliberately. Idempotent.
p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
prg = p.find('PLC_PRG', True)[0]
call = p.find('CallClient', True)[0]
changed = []
decl = prg.textual_declaration.text
if u'IsClientEnabled' not in decl:
    anchor = u'IsSendInFlight : BOOL;'
    assert decl.count(anchor) == 1, 'IsSendInFlight declaration not found once'
    decl = decl.replace(anchor, anchor + u'\n\tIsClientEnabled : BOOL := TRUE;  // will_enable_test.py: FALSE closes the client (ENABLE)')
    prg.textual_declaration.replace(decl)
    changed.append('declaration')
OLD, NEW = u'ENABLE := TRUE,', u'ENABLE := IsClientEnabled,'
for obj, label in ((prg, 'PLC_PRG call'), (call, 'CallClient call')):
    impl = obj.textual_implementation.text
    if NEW not in impl:
        assert impl.count(u'MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ' + OLD) == 1, label + ': client call not found once'
        obj.textual_implementation.replace(impl.replace(u'MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ' + OLD,
                                                        u'MqttLink.clientFB(MQTT_IN_OUT := MqttLink, ' + NEW))
        changed.append(label)
p.save()
result = {'success': True, 'changed': changed}
