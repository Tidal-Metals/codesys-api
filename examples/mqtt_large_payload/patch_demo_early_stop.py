# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_early_stop.py): add an online switch for the client loop's early stop on
# MqttClient.IsSendPending to the MQTT 5 demo copy only (mqtt_large_payload_demo_mqtt5), then save.
# IsEarlyStopEnabled FALSE (the default) leaves the loop exactly as the shared sources have it.
p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
prg = p.find('PLC_PRG', True)[0]
decl = prg.textual_declaration.text
added = []
if u'IsEarlyStopEnabled' not in decl:
    anchor = u'IsSendInFlight : BOOL;'
    assert decl.count(anchor) == 1, 'IsSendInFlight declaration not found once'
    decl = decl.replace(anchor, anchor + u'\n\tIsEarlyStopEnabled : BOOL;     // MQTT 5 tests: the loop also stops once the client has nothing left (IsSendPending)')
    prg.textual_declaration.replace(decl)
    added.append('declaration')
call = p.find('CallClient', True)[0]
impl = call.textual_implementation.text
if u'IsEarlyStopEnabled' not in impl:
    anchor = u'\tOR_ELSE (IsClientLoopGated AND NOT IsSendInFlight)'
    assert impl.count(anchor) == 1, 'loop condition not found once'
    impl = impl.replace(anchor, anchor + u'\n\tOR_ELSE (IsEarlyStopEnabled AND NOT MqttLink.clientFB.IsSendPending)')
    call.textual_implementation.replace(impl)
    added.append('loop')
p.save()
result = {'success': True, 'added': added, 'loop': call.textual_implementation.text}
