"""Exercise the real PyModbus framer against traffic from another RTU device."""
import asyncio
import unittest
from unittest.mock import patch
import modbus_rtu_slave_sim as sim
from pymodbus.server import ModbusSerialServer

class MultidropTest(unittest.TestCase):
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
