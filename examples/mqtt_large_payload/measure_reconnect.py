"""Disconnect the demo's MQTT client and time the reconnect; read the client's clock data.

Run from the repo root after deploy_demo.py (session logged in):
    python examples/mqtt_large_payload/measure_reconnect.py --out results/ab/<label>/reconnect.json
Writes PLC_PRG.MqttLink.clientFB.DoDisconnect := TRUE, the library's own hard disconnect (as after
missed pings), waits for IsBrokerConnected to drop and times the automatic reconnect. (Forcing ENABLE
to FALSE does not work: PLC_PRG passes ENABLE := TRUE in every call.) Then reads the error history if
the application allocated one, and the date/time pulse data next to the PC's UTC clock, which shows
whether the library's timestamps are UTC or local time.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from run_ide_script import execute  # noqa: E402

CODE = """
import time
on = session.ensure_online_application('', True)
assert 'run' in str(on.application_state).lower(), on.application_state
CLIENT = 'PLC_PRG.MqttLink.clientFB'

def text(path):
    return str(on.read_value(path))

def connected():
    return text('PLC_PRG.IsBrokerConnected') == 'TRUE'

def history(count):
    # The demo leaves the history unallocated (HistoryItems 0): the pointer can't be dereferenced.
    rows = []
    try:
        for i in range(count):
            base = '%s.ErrorHistory^[%d]' % (CLIENT, i)
            rows.append(dict((field, text(base + '.' + field)) for field in ('nr', 'error', 'when', 'text', 'DoesDisconnect')))
    except Exception as error:
        rows.append({'unavailable': str(error)})
    return rows

out = {'connectedBefore': connected(), 'historyBefore': history(3)}
# The library's own hard disconnect (as after missed pings); it reconnects by itself.
start = time.time()
on.set_prepared_value(CLIENT + '.DoDisconnect', 'TRUE')
on.write_prepared_values()
while connected() and time.time() - start < 10:
    time.sleep(0.02)
out['disconnectSeconds'] = round(time.time() - start, 2)
out['sawDisconnect'] = not connected()
start = time.time()
while not connected() and time.time() - start < 60:
    time.sleep(0.05)
out['reconnectSeconds'] = round(time.time() - start, 2)
out['connectedAfter'] = connected()
time.sleep(1)
out['historyAfter'] = history(6)
out['tdi'] = dict((field, text('PLC_PRG.MqttLink.TDI.' + field)) for field in ('SYSTEM_TIME', 'UDT', 'TIME_IO', 'IMP'))
out['pcUtc'] = time.strftime('%Y-%m-%d-%H:%M:%S', time.gmtime())
out['success'] = out['connectedAfter']
result = out
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out")
    args = parser.parse_args()
    result = execute(CODE, 180)
    text = json.dumps(result, indent=1)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
