"""Exercise the real PyModbus framer against traffic from another RTU device."""
import asyncio
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import modbus_rtu_slave_sim as sim
from pymodbus.server import ModbusSerialServer
from pymodbus.framer.rtu import FramerRTU


def rtu_frame(payload):
    return payload + FramerRTU.compute_CRC(payload).to_bytes(2, 'big')

class MultidropTest(unittest.TestCase):
    def test_real_cli_over_socket_transport(self):
        # PyModbus's socket:// serial-server mode carries RTU frames over a
        # loopback TCP connection, exercising StartSerialServer without a COM port.
        for args in ((), ('--multidrop', '--baudrate', '38400')):
            with self.subTest(args=args), tempfile.TemporaryFile(mode='w+t') as log:
                with socket.socket() as reserved:
                    reserved.bind(('127.0.0.1', 0))
                    port = reserved.getsockname()[1]
                process = subprocess.Popen(
                    [sys.executable, str(Path(sim.__file__).resolve()), '--port',
                     f'socket://127.0.0.1:{port}', '--unit', '11',
                     '--holding', '1101,1102', *args],
                    stdout=log, stderr=log,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                try:
                    deadline = time.monotonic() + 5
                    while True:
                        try:
                            connection = socket.create_connection(('127.0.0.1', port), timeout=0.1)
                            break
                        except OSError:
                            if process.poll() is not None or time.monotonic() >= deadline:
                                log.seek(0)
                                self.fail('Simulator did not listen: ' + log.read())
                            time.sleep(0.02)
                    with connection:
                        connection.settimeout(0.15)
                        connection.sendall(rtu_frame(bytes.fromhex('010300000002')))
                        with self.assertRaises(socket.timeout):
                            connection.recv(256)
                        connection.settimeout(2)
                        connection.sendall(rtu_frame(bytes.fromhex('0b0300000002')))
                        expected = rtu_frame(bytes.fromhex('0b0304044d044e'))
                        received = b''
                        while len(received) < len(expected):
                            chunk = connection.recv(256)
                            self.assertTrue(chunk, 'Simulator disconnected')
                            received += chunk
                        self.assertEqual(received, expected)
                finally:
                    process.terminate()
                    process.wait(timeout=5)

    def exercise_cli(self, exercise, *extra_args):
        async def run(**kwargs):
            # Real PyModbus constructor, transport buffering, framer and datastore;
            # no listen() call, so this never opens the placeholder serial port.
            server = ModbusSerialServer(**kwargs)
            handler = server.callback_new_connection()
            sent = []
            handler.server_send = lambda pdu, addr: sent.append(pdu)

            async def feed(packet):
                handler.data_received(packet)
                await asyncio.sleep(0.01)

            await exercise(feed, sent)

        def start(**kwargs):
            asyncio.run(run(**kwargs))

        argv = ['sim', '--port', 'UNOPENED_TEST_PORT', '--unit', '11',
                '--holding', '1101,1102', *extra_args]
        with patch.object(sim, 'StartSerialServer', start), patch('sys.argv', argv), \
                patch.object(sim.signal, 'signal'):
            self.assertEqual(sim.main(), 0)

    def test_single_device_starts_and_ignores_foreign_requests(self):
        async def exercise(feed, sent):
            await feed(rtu_frame(bytes.fromhex('010300000002')))
            self.assertEqual(sent, [])
            await feed(rtu_frame(bytes.fromhex('0b0300000002')))
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].dev_id, 11)
            self.assertEqual(sent[0].registers, [1101, 1102])

        self.exercise_cli(exercise)

    def test_foreign_exception_writes_and_broadcasts_are_silent(self):
        async def exercise(feed, sent):
            for payload in ('018302', '010600004321', '000600004321'):
                await feed(rtu_frame(bytes.fromhex(payload)))
                self.assertEqual(sent, [])
            await feed(rtu_frame(bytes.fromhex('0b0300000002')))
            self.assertEqual(sent[0].registers, [1101, 1102])

        self.exercise_cli(exercise, '--multidrop', '--baudrate', '38400')

    def test_fragmented_own_request_and_valid_write_readback(self):
        async def exercise(feed, sent):
            request = rtu_frame(bytes.fromhex('0b0300000002'))
            await feed(request[:3])
            self.assertEqual(sent, [])
            await feed(request[3:6])
            self.assertEqual(sent, [])
            await feed(request[6:])
            self.assertEqual(sent[0].registers, [1101, 1102])
            await feed(rtu_frame(bytes.fromhex('0b0600004321')))
            await feed(request)
            self.assertEqual(len(sent), 3)
            self.assertEqual(sent[1].function_code, 6)
            self.assertEqual(sent[2].registers, [0x4321, 1102])

        for args in ((), ('--multidrop', '--baudrate', '38400')):
            with self.subTest(args=args):
                self.exercise_cli(exercise, *args)

    def test_manifest_serves_each_configured_unit_and_rejects_bad_crc(self):
        async def exercise(feed, sent):
            request = rtu_frame(bytes.fromhex('0b0300000002'))
            await feed(request[:-1] + bytes([request[-1] ^ 1]))
            self.assertEqual(sent, [])
            await feed(request)
            await feed(rtu_frame(bytes.fromhex('0c0300000002')))
            self.assertEqual([(pdu.dev_id, pdu.registers) for pdu in sent],
                             [(11, [1101, 1102]), (12, [1201, 1202])])

        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'devices.json'
            manifest.write_text(json.dumps({'devices': [
                {'unit': 11, 'holding': [1101, 1102]},
                {'unit': 12, 'holding': [1201, 1202]},
            ]}), encoding='utf-8')
            self.exercise_cli(exercise, '--manifest', str(manifest),
                              '--multidrop', '--baudrate', '38400')

    def test_foreign_requests_and_replies_are_silent_but_own_unit_responds(self):
        async def exercise(**kwargs):
            server = ModbusSerialServer(**kwargs)
            handler = server.callback_new_connection()
            sent = []
            handler.server_send = lambda pdu, addr: sent.append(pdu)
            # Actual captured request AND response from unit 1.
            for packet in ('010300000002c40b', '01030404d2162ed546'):
                handler.callback_data(bytes.fromhex(packet))
                await asyncio.sleep(0.01)
                self.assertEqual(sent, [], 'Responder transmitted for a foreign unit')
            # Unit 11, holding registers 0..1.
            from pymodbus.framer.rtu import FramerRTU
            payload = bytes.fromhex('0b0300000002')
            packet = payload + FramerRTU.compute_CRC(payload).to_bytes(2, 'big')
            handler.callback_data(packet)
            await asyncio.sleep(0.01)
            self.assertEqual(len(sent), 1)
            self.assertEqual(sent[0].dev_id, 11)
            self.assertEqual(sent[0].registers, [1101, 1102])

        def run_server(**kwargs):
            asyncio.run(exercise(**kwargs))

        with patch.object(sim, 'StartSerialServer', run_server), patch('sys.argv', [
            'sim', '--port', 'UNOPENED_TEST_PORT', '--unit', '11',
            '--baudrate', '38400', '--holding', '1101,1102', '--multidrop'
        ]):
            self.assertEqual(sim.main(), 0)

if __name__ == '__main__':
    unittest.main()
