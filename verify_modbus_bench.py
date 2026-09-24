#!/usr/bin/env python
"""Check both ETH2 Modbus paths using values read from the running bench PLC."""

import argparse
import json
import logging

from run_ide_script import execute


SCRIPT = r'''
project = scriptengine.projects.primary
assert project is not None and project.path.replace('\\', '/').endswith('/modbus_tcp_bench.project'), 'Open modbus_tcp_bench.project first'
online_app = getattr(session, 'bench_online', None)
if online_app is None:
    online_app = scriptengine.online.create_online_application(project.active_application)
    session.bench_online = online_app
if not online_app.is_logged_in:
    online_app.login(scriptengine.OnlineChangeOption.Keep, False)
names = [
    'PLC_PRG.BenchRegisters[0]', 'PLC_PRG.BenchRegisters[1]',
    'PLC_PRG.GatewayRegisters[0]', 'PLC_PRG.GatewayRegisters[1]',
    'PLC_PRG.BothPathsPass', 'PC_TCP_Server.xError',
    'Gateway_RTU_Server.xError', 'PLC_PRG.ScanCount',
]
samples = []
deadline = time.time() + duration
while True:
    samples.append(dict((name, str(online_app.read_value(name))) for name in names))
    if time.time() >= deadline:
        break
    time.sleep(0.25)
passed = str(online_app.application_state) == 'run'
for sample in samples:
    passed = passed and sample['PLC_PRG.BothPathsPass'] == 'TRUE'
    passed = passed and sample['PC_TCP_Server.xError'] == 'FALSE'
    passed = passed and sample['Gateway_RTU_Server.xError'] == 'FALSE'
    for source in ['BenchRegisters', 'GatewayRegisters']:
        passed = passed and sample['PLC_PRG.' + source + '[0]'] == 'WORD#1234'
        passed = passed and sample['PLC_PRG.' + source + '[1]'] == 'WORD#5678'
passed = passed and samples[0]['PLC_PRG.ScanCount'] != samples[-1]['PLC_PRG.ScanCount']
result = {'success': passed, 'state': str(online_app.application_state),
          'sample_count': len(samples), 'duration_seconds': duration,
          'first': samples[0], 'last': samples[-1],
          'failures': [s for s in samples if s['PLC_PRG.BothPathsPass'] != 'TRUE'
                       or s['PC_TCP_Server.xError'] != 'FALSE'
                       or s['Gateway_RTU_Server.xError'] != 'FALSE']}
'''


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=3,
                        help='Observation seconds (1 to 45); reuses the online session')
    args = parser.parse_args()
    if not 1 <= args.duration <= 45:
        parser.error('--duration must be between 1 and 45')
    logging.disable(logging.CRITICAL)
    result = execute('duration = %r\n' % args.duration + SCRIPT, timeout=args.duration + 15)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result.get('success') else 1)
