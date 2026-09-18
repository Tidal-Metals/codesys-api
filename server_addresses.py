"""Print usable connection addresses for an IPv4 HTTP listener."""

import ipaddress
import socket


def print_connection_addresses(server_address):
    host, port = server_address[:2]
    print("CODESYS API listening on %s:%s" % (host, port))
    if host == "0.0.0.0":
        try:
            addresses = {
                ipaddress.IPv4Address(entry[4][0])
                for entry in socket.getaddrinfo(
                    socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
                )
            }
        except OSError:
            addresses = set()
        addresses = sorted(
            address for address in addresses
            if not (address.is_loopback or address.is_link_local
                    or address.is_unspecified or address.is_multicast)
        )
        if addresses:
            print("Connect using the address on your LAN/VPN:")
            for address in addresses:
                print("  http://%s:%s" % (address, port))
        else:
            print("No LAN IPv4 address detected; use ipconfig to find this PC's address.")
        print("On this PC: http://127.0.0.1:%s" % port, flush=True)
    else:
        print("Connect at: http://%s:%s" % (host, port), flush=True)
