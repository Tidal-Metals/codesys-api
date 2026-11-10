"""Reproduce one refused publish on the bench and print the edge publisher's outputs as they change.

    python examples/mqtt_large_payload/mqtt5_history.py [qos] [topic]
Diagnostics for mqtt5_test.py (the online API cannot read the client's ErrorHistory pointer).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

WRITE = """
on = session.ensure_online_application('', True)
for path, value in @@VALUES@@:
    on.set_prepared_value(path, value)
on.write_prepared_values()
result = {'success': True}
"""
READ = """
on = session.ensure_online_application('', True)
C = 'PLC_PRG.MqttLink.clientFB'
def text(path):
    return str(on.read_value(path)).split('#')[-1]
values = dict((name, text('EdgeTest.Publisher.' + name)) for name in ('done', 'Rejected', 'ReasonCode', 'sendActive'))
values.update(dict((name, text('EdgeTest.' + name)) for name in ('SendSequence', 'DoneSequence', 'RejectedCount', 'IsRequested')))
values['connects'] = text(C + '.counts.CountConnectAttempt')
values['pending'] = text(C + '.IsSendPending')
values['outWorking'] = text(C + '.counts.OutSlotsWorking')
values['pubackUnknown'] = text(C + '.counts.CountReceivePubackUnknown')
values['unack'] = text(C + '.counts.PublishsUnacknowledged')
result = {'success': True, 'values': values}
"""


def write(values):
    assert execute(WRITE.replace("@@VALUES@@", repr(values)), 60).get("success")


def read():
    return execute(READ, 60)["values"]


qos = int(sys.argv[1]) if len(sys.argv) > 1 else 1
topic = sys.argv[2] if len(sys.argv) > 2 else "denied/edge"
write([("EdgeTest.IsEnabled", "TRUE"), ("EdgeTest.TopicOut", "'%s'" % topic), ("EdgeTest.SendSize", "64"),
       ("EdgeTest.IsQos1", "TRUE" if qos == 1 else "FALSE"), ("EdgeTest.IsQos2", "TRUE" if qos == 2 else "FALSE")])
time.sleep(0.5)
print("before", json.dumps(read()))
sequence = int(read()["SendSequence"]) + 1
write([("EdgeTest.SendSequence", str(sequence))])
last = None
end = time.time() + 12
while time.time() < end:
    current = read()
    if current != last:
        print("%5.1f" % (12 - (end - time.time())), json.dumps(current), flush=True)
        last = current
    time.sleep(0.2)
write([("EdgeTest.TopicOut", "'raw_data_demo/edge'")])
