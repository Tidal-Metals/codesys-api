"""TCP proxy between the bench PLC and the MQTT broker, to break the link on purpose (link-loss tests).

Runs on the Claude VM (192.168.50.142), which the PLC can reach; this desktop's firewall blocks inbound ports.
    python3 mqtt_link_proxy.py --listen 1884 --broker 192.168.50.240:1883
Every client connection is piped to the broker. Kill the process to drop the link (both sides see the
connection close); SIGSTOP it to freeze the link silently (connections stay open, nothing flows), SIGCONT to
resume. Python 3 standard library only.
"""
import argparse
import asyncio


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        writer.close()


async def handle(client_reader, client_writer, broker_host: str, broker_port: int) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        broker_reader, broker_writer = await asyncio.open_connection(broker_host, broker_port)
    except OSError as error:
        print("broker connect failed for %s: %s" % (peer, error), flush=True)
        client_writer.close()
        return
    print("connected %s" % (peer,), flush=True)
    await asyncio.gather(pipe(client_reader, broker_writer), pipe(broker_reader, client_writer))
    print("closed %s" % (peer,), flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listen", type=int, default=1884)
    parser.add_argument("--broker", default="192.168.50.240:1883")
    args = parser.parse_args()
    host, port = args.broker.rsplit(":", 1)
    server = await asyncio.start_server(lambda r, w: handle(r, w, host, int(port)), "0.0.0.0", args.listen)
    print("listening on %d -> %s" % (args.listen, args.broker), flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
