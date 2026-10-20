"""Find the serial settings a device answers on: for each port, baud and parity, reconnect bench line 2 and watch
its serial client's reply counter for a few seconds. Stops at the first combination with replies. Uses the
running bench application (deploy_bench.py).

Usage: python examples/plc_architecture/bench/scan_serial.py [--ports 1,2] [--bauds 9600,...] [--parities 0,2] [--rts 0,3]
"""
import argparse
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from run_ide_script import execute  # noqa: E402

CODE = """
import time
on = session.ensure_online_application('', True)

def number(path):
    text = str(on.read_value(path)).split('#')[-1]
    return int(text) if text.isdigit() else text

def write(values):
    for path, text in values:
        on.set_prepared_value(path, text)
    on.write_prepared_values()

client = 'PRG_Bus.Lines[2].ClientRtu.'
rows = []
found = None
for port, baud, parity, rts in @@COMBOS@@:
    write([('GVL_Bus.Lines[2].ComPort', str(port)), ('GVL_Bus.Lines[2].Baudrate', str(baud)),
           ('GVL_Bus.Lines[2].Parity', str(parity)), ('GVL_Bus.Lines[2].RtsControl', str(rts)),
           ('PRG_Bus.Reconnect[2]', 'TRUE')])
    time.sleep(1.5)
    sent, replies = number(client + 'udiNumMsgSent'), number(client + 'udiNumMsgReply')
    time.sleep(@@SECONDS@@)
    row = {'port': port, 'baud': baud, 'parity': parity, 'rts': rts, 'sent': number(client + 'udiNumMsgSent') - sent,
           'replies': number(client + 'udiNumMsgReply') - replies, 'connected': str(on.read_value(client + 'xConnected'))}
    rows.append(row)
    if row['replies'] > 0:
        found = row
        break
result = {'success': True, 'found': found, 'rows': rows}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ports", default="1,2")
    parser.add_argument("--bauds", default="9600,19200,38400,115200")
    parser.add_argument("--parities", default="0,2")
    parser.add_argument("--rts", default="0", help="0 disabled, 1 on, 2 handshake, 3 toggle")
    parser.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    numbers = lambda text: [int(x) for x in text.split(",")]  # noqa: E731
    combos = list(itertools.product(numbers(args.ports), numbers(args.bauds), numbers(args.parities), numbers(args.rts)))
    code = CODE.replace("@@COMBOS@@", repr(combos)).replace("@@SECONDS@@", repr(args.seconds))
    print(json.dumps(execute(code, int(len(combos) * (args.seconds + 3)) + 60), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
