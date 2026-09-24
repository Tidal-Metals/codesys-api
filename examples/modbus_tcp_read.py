"""Read holding registers from an explicit Modbus TCP bench target (FC03 only)."""
import argparse
import ipaddress
import json
import socket
import struct
import time


def receive_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part:
            raise ConnectionError('Server closed the TCP connection')
        data.extend(part)
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, type=ipaddress.IPv4Address)
    parser.add_argument('--source', required=True, type=ipaddress.IPv4Address,
                        help='Local adapter IPv4 address; also controls the local bind')
    parser.add_argument('--port', type=int, default=502)
    parser.add_argument('--unit', type=int, default=1)
    parser.add_argument('--address', type=int, default=0, help='Zero-based register offset')
    parser.add_argument('--count', type=int, default=2)
    parser.add_argument('--timeout', type=float, default=3)
    args = parser.parse_args()
    if not (1 <= args.port <= 65535 and 0 <= args.unit <= 255
            and 1 <= args.count <= 125 and 0 <= args.address
            and args.address + args.count <= 65536 and args.timeout > 0):
        parser.error('Invalid port, unit, register range or timeout')
    try:
        with socket.create_connection((str(args.host), args.port), args.timeout,
                                      source_address=(str(args.source), 0)) as connection:
            request = struct.pack('>HHHBBHH', 1, 0, 6, args.unit, 3,
                                  args.address, args.count)
            started = time.perf_counter()
            connection.sendall(request)
            transaction, protocol, length, unit = struct.unpack(
                '>HHHB', receive_exact(connection, 7))
            if (transaction, protocol, unit) != (1, 0, args.unit) or not 2 <= length <= 254:
                raise ValueError('Invalid or mismatched Modbus TCP header')
            reply = receive_exact(connection, length - 1)
            if reply[0] == 0x83:
                raise ValueError('Modbus exception code %d' % reply[1])
            if len(reply) != 2 + 2 * args.count or reply[:2] != bytes([3, 2 * args.count]):
                raise ValueError('Unexpected function, byte count or response length')
            print(json.dumps({'success': True, 'source': connection.getsockname(),
                              'target': connection.getpeername(), 'unit': args.unit,
                              'address': args.address,
                              'registers': struct.unpack('>' + 'H' * args.count, reply[2:]),
                              'reply_ms': round((time.perf_counter() - started) * 1000, 2)}, indent=2))
    except (OSError, ValueError) as error:
        print(json.dumps({'success': False, 'error': str(error)}))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
