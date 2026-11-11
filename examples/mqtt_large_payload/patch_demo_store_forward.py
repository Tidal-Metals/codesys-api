# IDE session script (python run_ide_script.py examples/mqtt_large_payload/patch_demo_store_forward.py): add the
# MqttStoreForward tests to the MQTT 5 demo copy only (mqtt_large_payload_demo_mqtt5), with the call pattern the
# block needs, then save. Run after patch_demo_early_stop.py. Idempotent, and upgrades a copy patched by an earlier
# version of this script (StoreForwardTest only, or StoreForwardTest and MixedPushTest).
#   StoreForwardTest (st/sfw/StoreForwardTest.st, sfw_test.py drives it), MixedPushTest (st/sfw/MixedPushTest.st
#   with FB_MixedPushStream, mixed_rate_test.py --push drives it) and RealisticSfwTest (st/sfw/RealisticSfwTest.st
#   with its BuildPayload action, sfw_test.py realistic drives it) are created or updated from their sources;
#   PLC_PRG calls StoreForwardTest(), MixedPushTest() then RealisticSfwTest() after MixedTest(), before the
#   end-of-scan client call; the end-of-scan call also runs when any test's IsLiveHandedOff, whatever the first
#   calls took; CallClient keeps calling while any test's IsSendInFlight, and with IsEarlyStopEnabled stops on
#   NOT IsUnsentPending (not IsSendPending) while any test is enabled.
# Needs library 1.4.0.0 with MqttStoreForward (or a later one with the same API). With every test's IsEnabled FALSE
# the demo behaves as before.
import io
import os

from scriptengine import PouType

MARKER = u"// ---- implementation ----"
SOURCE_DIR = os.path.join(os.path.expanduser("~"), "projects", "codesys-api", "examples", "mqtt_large_payload",
                          "st", "sfw")

p = scriptengine.projects.primary
assert p.path.replace('\\', '/').endswith('mqtt_large_payload_demo_mqtt5/mqtt_large_payload_demo.project'), p.path
changed = []


def read_source(name):
    with io.open(os.path.join(SOURCE_DIR, name + ".st"), encoding="utf-8") as handle:
        text = handle.read()
    declaration, implementation = text.split(MARKER + u"\n", 1)
    return declaration, implementation


def direct_child(parent, name):
    matches = [obj for obj in parent.get_children(False) if obj.get_name() == name]
    return matches[0] if matches else None


def update_text(document, text, label):
    if document.text.rstrip() != text.rstrip():
        document.replace(text)
        changed.append(label)


def upsert_pou(parent, name, pou_type):
    found = p.find(name, True)
    if found:
        pou = found[0]
    else:
        pou = parent.create_pou(name=name, type=pou_type)
        changed.append('created ' + name)
    declaration, implementation = read_source(name)
    update_text(pou.textual_declaration, declaration.rstrip() + u"\n", name + ' declaration')
    update_text(pou.textual_implementation, implementation, name + ' implementation')
    return pou


def upsert_action(pou, action_name):
    action = direct_child(pou, action_name)
    if action is None:
        action = pou.create_action(action_name)
        changed.append('created %s.%s' % (pou.get_name(), action_name))
    update_text(action.textual_implementation, read_source(pou.get_name() + "." + action_name)[1],
                '%s.%s implementation' % (pou.get_name(), action_name))


prg = p.find('PLC_PRG', True)[0]
upsert_pou(prg.parent, u'StoreForwardTest', PouType.Program)
push_stream = upsert_pou(prg.parent, u'FB_MixedPushStream', PouType.FunctionBlock)
upsert_action(push_stream, u'ServiceRounds')
upsert_pou(prg.parent, u'MixedPushTest', PouType.Program)
realistic = upsert_pou(prg.parent, u'RealisticSfwTest', PouType.Program)
upsert_action(realistic, u'BuildPayload')


def patch(obj, anchors, replacement, label):
    """Replace the first anchor found exactly once (most patched form first) unless replacement is already there."""
    impl = obj.textual_implementation.text
    if replacement in impl:
        return
    for anchor in anchors:
        if impl.count(anchor) == 1:
            obj.textual_implementation.replace(impl.replace(anchor, replacement))
            changed.append(label)
            return
    raise AssertionError('%s: no anchor found once: %r' % (label, anchors))


SFW_CALL = (u"MixedTest();\n// MqttStoreForward test (idle unless StoreForwardTest.IsEnabled; sfw_test.py drives it).\n"
            u"StoreForwardTest();\n")
MIXED_CALL = SFW_CALL + (u"// Mixed-rate load through MqttStoreForward (idle unless MixedPushTest.IsEnabled; "
                         u"mixed_rate_test.py --push).\nMixedPushTest();\n")
patch(prg, [MIXED_CALL, SFW_CALL, u"MixedTest();\n"],
      MIXED_CALL + u"// Two-stream outage load through MqttStoreForward (idle unless RealisticSfwTest.IsEnabled; "
      u"sfw_test.py realistic).\nRealisticSfwTest();\n", 'PLC_PRG call')
END_OF_SCAN = u"IF IsSecondClientCallEnabled AND (ClientUs < SecondCallBudgetUs OR StoreForwardTest.IsLiveHandedOff"
patch(prg, [END_OF_SCAN + u" OR MixedPushTest.IsLiveHandedOff) THEN", END_OF_SCAN + u") THEN",
            u"IF IsSecondClientCallEnabled AND ClientUs < SecondCallBudgetUs THEN"],
      END_OF_SCAN + u" OR MixedPushTest.IsLiveHandedOff OR RealisticSfwTest.IsLiveHandedOff) THEN", 'end-of-scan call')
call = p.find('CallClient', True)[0]
IN_FLIGHT = u"OR SplitTest.IsRoundActive OR MixedTest.IsSendInFlight"
patch(call, [IN_FLIGHT + u" OR StoreForwardTest.IsSendInFlight OR MixedPushTest.IsSendInFlight;",
             IN_FLIGHT + u" OR StoreForwardTest.IsSendInFlight;", IN_FLIGHT + u";"],
      IN_FLIGHT + u" OR StoreForwardTest.IsSendInFlight OR MixedPushTest.IsSendInFlight"
      u" OR RealisticSfwTest.IsSendInFlight;", 'CallClient in flight')
EARLY_STOP_TAIL = u" MqttLink.clientFB.IsSendPending, MqttLink.clientFB.IsUnsentPending))"
patch(call, [u"OR_ELSE (IsEarlyStopEnabled AND NOT SEL(StoreForwardTest.IsEnabled OR MixedPushTest.IsEnabled,"
             + EARLY_STOP_TAIL,
             u"OR_ELSE (IsEarlyStopEnabled AND NOT SEL(StoreForwardTest.IsEnabled," + EARLY_STOP_TAIL,
             u"OR_ELSE (IsEarlyStopEnabled AND NOT MqttLink.clientFB.IsSendPending)"],
      u"OR_ELSE (IsEarlyStopEnabled AND NOT SEL(StoreForwardTest.IsEnabled OR MixedPushTest.IsEnabled"
      u" OR RealisticSfwTest.IsEnabled," + EARLY_STOP_TAIL,
      'CallClient early stop')
p.save()
result = {'success': True, 'changed': changed, 'loop': call.textual_implementation.text}
