"""Scripted MQTT 3.1.1 broker for one PLC client: plays a QoS scenario mosquitto never produces, logs every packet.

Runs on the Claude VM (python3, standard library only); qos_broker_test.py copies it to /tmp and starts it:
    python3 /tmp/qos_fake_broker.py --scenario dup_publish --port 1885 --log /tmp/qos_dup_publish.jsonl
It answers CONNECT, SUBSCRIBE, PINGREQ and QoS 1/2 publishes like a broker, except where the scenario says
otherwise. Each line of the log is one JSON record: a packet ("dir": "in" from the PLC, "out" to it), a scenario
note, or the final {"event": "done"} with the scenario's findings. Scenarios (topic raw_data_demo/edge_in,
payloads start with an 8-digit sequence that EdgeTest.Receiver checks):
  dup_publish     QoS 2 PUBLISH, then the same PUBLISH again (DUP) before PUBREL; expects PUBREC with the same
                  id twice, one PUBCOMP, nothing else (upstream answered the duplicate with a stale id)
  pubrel_unknown  PUBREL for ids the client no longer holds; expects a PUBCOMP for each
  burst_qos1      40 QoS 1 PUBLISH in one write; expects 40 PUBACK and no reconnect (upstream disconnected)
  burst_qos2      40 QoS 2 PUBLISH in one write, PUBREL for each PUBREC; expects 40 PUBCOMP, no reconnect
  burst_large     as burst_qos2, but number 31 is a 20 kB QoS 1 message (split while earlier ones wait); with
                  fewer in slots than messages in flight this can only end in a disconnect (see OPTIMIZATION.md)
  burst_large_window  burst_large with a 20-message inflight window, as mosquitto sends by default
  suback_reject   SUBACK 0x80 for edge_in, then a PUBLISH on it (the PLC should not deliver it)
  no_pubcomp      the PLC's QoS 2 PUBLISH gets PUBREC, its PUBRELs go unanswered for --hold seconds; expects
                  no second PUBLISH (upstream resent it after 10 PUBRELs)
  cut_publish     reads only the start of the PLC's first large PUBLISH and closes the link; records what the
                  PLC sends after reconnecting (upstream could resume the half-built packet)
"""
import argparse
import json
import os
import queue
import socket
import struct
import threading
import time

TOPIC_IN = "raw_data_demo/edge_in"
TOPIC_OUT = "raw_data_demo/edge"
NAMES = {1: "CONNECT", 2: "CONNACK", 3: "PUBLISH", 4: "PUBACK", 5: "PUBREC", 6: "PUBREL", 7: "PUBCOMP",
         8: "SUBSCRIBE", 9: "SUBACK", 10: "UNSUBSCRIBE", 11: "UNSUBACK", 12: "PINGREQ", 13: "PINGRESP",
         14: "DISCONNECT"}


class Log:
    def __init__(self, path):
        self.file = open(path, "w", buffering=1)
        self.start = time.time()
        self.lock = threading.Lock()

    def write(self, **record):
        record["t"] = round(time.time() - self.start, 3)
        with self.lock:
            self.file.write(json.dumps(record) + "\n")


def encode_length(n):
    out = bytearray()
    while True:
        digit, n = n % 128, n // 128
        out.append(digit | (0x80 if n else 0))
        if not n:
            return bytes(out)


def publish_packet(packet_id, qos, payload, dup=False, topic=TOPIC_IN):
    body = struct.pack(">H", len(topic)) + topic.encode()
    if qos:
        body += struct.pack(">H", packet_id)
    body += payload
    return bytes([0x30 | (0x08 if dup else 0) | (qos << 1)]) + encode_length(len(body)) + body


def ack_packet(kind, packet_id):
    first = {4: 0x40, 5: 0x50, 6: 0x62, 7: 0x70, 11: 0xB0}[kind]
    return bytes([first, 2]) + struct.pack(">H", packet_id)


class Connection:
    """One accepted PLC connection: a reader thread parses packets into a queue and answers the routine ones."""

    def __init__(self, sock, log, number, policy):
        self.sock, self.log, self.number, self.policy = sock, log, number, policy
        self.packets = queue.Queue()
        self.closed = threading.Event()
        self.send_lock = threading.Lock()
        self.subscribed = threading.Event()
        threading.Thread(target=self.read_loop, daemon=True).start()

    def send(self, data, note=None):
        with self.send_lock:
            self.sock.sendall(data)
        index = 0
        while index < len(data):
            kind = data[index] >> 4
            length, size = 0, 0
            multiplier = 1
            while True:
                byte = data[index + 1 + size]
                length += (byte & 0x7F) * multiplier
                multiplier *= 128
                size += 1
                if not byte & 0x80:
                    break
            packet = data[index:index + 1 + size + length]
            self.log.write(dir="out", conn=self.number, **describe(packet, kind, size), **({"note": note} if note else {}))
            index += 1 + size + length

    def read_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
        return data

    def read_packet(self):
        first = self.read_exact(1)
        length, multiplier, raw = 0, 1, b""
        while True:
            byte = self.read_exact(1)
            raw += byte
            length += (byte[0] & 0x7F) * multiplier
            multiplier *= 128
            if not byte[0] & 0x80:
                break
        if first[0] >> 4 == 3 and length > 10000 and self.policy.get("cut_after"):
            # cut_publish: read the start of the large PUBLISH, then drop the link mid-packet
            time.sleep(0.5)  # let the PLC fill its socket buffer with the rest of the packet
            data = self.read_exact(self.policy["cut_after"])
            self.log.write(event="cut", conn=self.number, remainingLength=length, bytesRead=len(data),
                           firstBytes=(first + raw + data[:40]).hex())
            self.policy["cut_after"] = None
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
            raise ConnectionError("cut by scenario")
        return first + raw + self.read_exact(length), len(raw)

    def read_loop(self):
        try:
            while True:
                packet, size = self.read_packet()
                kind = packet[0] >> 4
                info = describe(packet, kind, size)
                self.log.write(dir="in", conn=self.number, **info)
                self.answer(kind, info, packet)
                self.packets.put(info)
        except (ConnectionError, OSError) as error:
            self.log.write(event="closed", conn=self.number, reason=str(error))
        finally:
            self.closed.set()

    def send_split(self, data, split_at, label):
        """Send one packet in two TCP writes 0.3 s apart (TCP_NODELAY is on, so they go out as two segments)."""
        with self.send_lock:
            self.sock.sendall(data[:split_at])
            time.sleep(0.3)
            self.sock.sendall(data[split_at:])
        self.log.write(dir="out", conn=self.number, type=label, length=len(data), split=split_at)

    def answer(self, kind, info, packet):
        if kind == 1:
            if self.policy.get("split_connack"):
                self.send_split(bytes([0x20, 2, 0, 0]), 1, "CONNACK")
            else:
                self.send(bytes([0x20, 2, 0, 0]))
        elif kind == 12:
            if self.policy.get("split_pingresp"):
                self.send_split(bytes([0xD0, 0]), 1, "PINGRESP")
            else:
                self.send(bytes([0xD0, 0]))
        elif kind == 8:
            code = self.policy.get("suback_code", {}).get(info["topic"], info["qos"])
            self.send(bytes([0x90, 3]) + struct.pack(">H", info["id"]) + bytes([code]))
            if info["topic"] == TOPIC_IN:
                self.subscribed.set()
        elif kind == 10:
            self.send(ack_packet(11, info["id"]))
        elif kind == 3 and info["qos"] == 1:
            self.send(ack_packet(4, info["id"]))
        elif kind == 3 and info["qos"] == 2 and not self.policy.get("hold_pubrec_topic") == info["topic"]:
            self.send(ack_packet(5, info["id"]))
        elif kind == 6 and not self.policy.get("ignore_pubrel"):
            self.send(ack_packet(7, info["id"]))

    def expect(self, kind, timeout):
        """The next packet of this kind within timeout seconds (others are kept in the log only), or None."""
        end = time.time() + timeout
        while time.time() < end:
            try:
                info = self.packets.get(timeout=max(0.01, end - time.time()))
            except queue.Empty:
                return None
            if info["type"] == NAMES[kind]:
                return info
        return None

    def collect(self, seconds):
        end, got = time.time() + seconds, []
        while time.time() < end:
            try:
                got.append(self.packets.get(timeout=max(0.01, end - time.time())))
            except queue.Empty:
                break
        return got


def describe(packet, kind, size):
    info = {"type": NAMES.get(kind, str(kind)), "flags": packet[0] & 0x0F, "length": len(packet)}
    body = packet[1 + size:]
    if kind == 3:
        qos = (packet[0] >> 1) & 3
        topic_length = struct.unpack(">H", body[:2])[0]
        info.update(topic=body[2:2 + topic_length].decode(errors="replace"), qos=qos, dup=bool(packet[0] & 8))
        rest = body[2 + topic_length:]
        if qos:
            info["id"] = struct.unpack(">H", rest[:2])[0]
            rest = rest[2:]
        info["payloadLength"] = len(rest)
        info["payloadHead"] = rest[:12].hex()
    elif kind in (4, 5, 6, 7, 11):
        info["id"] = struct.unpack(">H", body[:2])[0]
    elif kind == 8:
        info["id"] = struct.unpack(">H", body[:2])[0]
        topic_length = struct.unpack(">H", body[2:4])[0]
        info["topic"] = body[4:4 + topic_length].decode(errors="replace")
        info["qos"] = body[4 + topic_length]
    return info


def seq(n):
    return b"%08d" % n


def ids_of(packets, kind):
    return [p.get("id") for p in packets if p["type"] == NAMES[kind]]


def scenario_dup_publish(conn, args):
    conn.subscribed.wait(30)
    time.sleep(1)
    conn.collect(0.5)
    conn.send(publish_packet(7, 2, seq(1)), "first")
    first = conn.expect(5, 3)
    conn.send(publish_packet(7, 2, seq(1), dup=True), "duplicate before PUBREL")
    after_dup = conn.collect(1.5)
    conn.send(ack_packet(6, 7), "release")
    after_rel = conn.collect(1.5)
    conn.send(publish_packet(8, 2, seq(2)), "next message")
    next_rec = conn.expect(5, 3)
    conn.send(ack_packet(6, 8))
    tail = conn.collect(args.hold)
    return {"firstPubrec": first and first["id"], "afterDuplicate": ids_of(after_dup, 5),
            "pubcompAfterRelease": ids_of(after_rel, 7), "nextPubrec": next_rec and next_rec["id"],
            "laterPubrec": ids_of(tail, 5), "laterPubcomp": ids_of(tail, 7),
            "ok": first is not None and ids_of(after_dup, 5) == [7] and ids_of(after_rel, 7) == [7]
            and next_rec is not None and next_rec["id"] == 8 and ids_of(tail, 5) == [] and ids_of(tail, 7) == [8]}


def scenario_pubrel_unknown(conn, args):
    conn.subscribed.wait(30)
    time.sleep(1)
    conn.collect(0.5)
    conn.send(ack_packet(6, 300), "never used")
    never = conn.collect(1.5)
    # complete id 9, then id 10 (reuses the slot), then repeat PUBREL 9
    for packet_id, number in ((9, 1), (10, 2)):
        conn.send(publish_packet(packet_id, 2, seq(number)))
        conn.expect(5, 3)
        conn.send(ack_packet(6, packet_id))
        conn.expect(7, 3)
    conn.send(ack_packet(6, 9), "repeat after completion and slot reuse")
    repeat = conn.collect(1.5)
    return {"pubcompForNeverUsed": ids_of(never, 7), "pubcompForRepeat": ids_of(repeat, 7),
            "ok": ids_of(never, 7) == [300] and ids_of(repeat, 7) == [9]}


def scenario_burst(conn, args, qos, large_at=None, inflight=0):
    """args.burst publishes back to back; large_at: that one (1-based) is QoS 1 with a 20 kB payload, which the
    client must split (it does not fit the 16 kB receive buffer). inflight: like mosquitto's max_inflight_messages,
    at most that many unfinished (no PUBACK / PUBCOMP yet) at a time; 0 sends them all in one write."""
    conn.subscribed.wait(30)
    time.sleep(1)
    conn.collect(0.5)
    count = args.burst
    packets, expected_qos2 = [], 0
    for n in range(count):
        if n + 1 == large_at:
            packets.append(publish_packet(100 + n, 1, seq(n + 1) + bytes(i % 251 for i in range(20000))))
        else:
            packets.append(publish_packet(100 + n, qos, seq(n + 1)))
            expected_qos2 += qos == 2
    window = inflight or count
    conn.send(b"".join(packets[:window]), "burst" if not inflight else "first %d (inflight window)" % window)
    next_index = window
    pubacks, pubrecs, completes = set(), set(), set()
    expected_pubacks = count - expected_qos2
    end = time.time() + 20
    while (time.time() < end and (len(pubacks) < expected_pubacks or len(completes) < expected_qos2)
           and not conn.closed.is_set()):
        for info in conn.collect(0.2):
            finished = False
            if info["type"] == "PUBACK":
                finished = info["id"] not in pubacks
                pubacks.add(info["id"])
            elif info["type"] == "PUBREC":
                pubrecs.add(info["id"])
                conn.send(ack_packet(6, info["id"]))
            elif info["type"] == "PUBCOMP":
                finished = info["id"] not in completes
                completes.add(info["id"])
            if finished and next_index < count:
                conn.send(packets[next_index])
                next_index += 1
    return {"sent": count, "inflightWindow": inflight, "pubacks": len(pubacks), "pubrecs": len(pubrecs),
            "completed": len(completes), "closed": conn.closed.is_set(),
            "ok": len(pubacks) == expected_pubacks and len(completes) == expected_qos2 and not conn.closed.is_set()}


def scenario_suback_reject(conn, args):
    conn.subscribed.wait(30)
    time.sleep(1)
    conn.send(publish_packet(0, 0, seq(1)), "publish on the rejected subscription")
    time.sleep(2)
    return {"ok": None, "note": "the PLC side decides: Receiver.ReceivedCount must not change"}


def scenario_no_pubcomp(conn, args):
    publish = None
    end = time.time() + 60
    while time.time() < end and publish is None:
        info = conn.expect(3, 1)
        if info and info.get("topic") == TOPIC_OUT and info["qos"] == 2:
            publish = info
    if publish is None:
        return {"ok": False, "error": "no QoS 2 PUBLISH on %s" % TOPIC_OUT}
    held = conn.collect(args.hold)
    conn.policy["ignore_pubrel"] = False
    republished = [p for p in held if p["type"] == "PUBLISH" and p.get("topic") == TOPIC_OUT]
    pubrels = ids_of(held, 6)
    # answer the next PUBREL so the PLC finishes
    final = conn.expect(6, 5)
    if final:
        conn.send(ack_packet(7, final["id"]))
    else:
        conn.send(ack_packet(7, publish["id"]), "PUBCOMP without a fresh PUBREL")
    return {"publishId": publish["id"], "pubrelsWhileHeld": len(pubrels), "publishesWhileHeld": len(republished),
            "ok": len(republished) == 0 and len(pubrels) > 0}


def scenario_cut_publish(conn, args, server):
    conn.policy["cut_after"] = 4000
    if not conn.closed.wait(90):
        return {"ok": False, "error": "no large PUBLISH to cut"}
    second = server.wait_newer_than(conn.number, 30)
    if second is None:
        return {"ok": False, "error": "the PLC did not reconnect"}
    got = second.collect(args.hold)
    publishes = [p for p in got if p["type"] == "PUBLISH" and p.get("topic") == TOPIC_OUT]
    first_type = got[0]["type"] if got else None
    return {"firstPacketAfterReconnect": first_type, "publishesAfterReconnect": len(publishes),
            "lengths": [p["payloadLength"] for p in publishes],
            "ok": first_type == "CONNECT" and len(publishes) == 1 and publishes[0]["payloadLength"] == args.large}


def scenario_split(conn, args, label):
    """The connection survives packets that arrive in two pieces (CONNACK already did, at connect)."""
    conn.subscribed.wait(30)
    got = conn.collect(args.hold)
    pings = ids_of(got, 12)
    return {"split": label, "pingsAnswered": len(pings), "closed": conn.closed.is_set(),
            "ok": not conn.closed.is_set() and (label == "CONNACK" or len(pings) >= 2)}


def scenario_bad_topic_length(conn, args, server):
    """A PUBLISH whose topic length points past the packet: the client must drop the connection and come back."""
    conn.subscribed.wait(30)
    time.sleep(1)
    with conn.send_lock:
        conn.sock.sendall(bytes([0x32, 0x04, 0x4E, 0x20, 0x00, 0x01]))  # QoS 1, remaining 4, topic length 20000
    conn.log.write(dir="out", conn=conn.number, type="PUBLISH (malformed)", length=6)
    closed = conn.closed.wait(15)
    again = server.wait_newer_than(conn.number, 30) if closed else None
    if again is not None:
        again.subscribed.wait(15)
    return {"closedByClient": closed, "reconnected": again is not None,
            "resubscribed": again is not None and again.subscribed.is_set(),
            "ok": closed and again is not None and again.subscribed.is_set()}


class Server:
    """Accepts every connection on a thread (a reconnect is never left in the backlog); latest is the newest."""

    def __init__(self, port, log, policy, small_receive_buffer):
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if small_receive_buffer:
            self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        self.listener.bind(("0.0.0.0", port))
        self.listener.listen(4)
        self.log, self.policy, self.count, self.latest = log, policy, 0, None
        self.changed = threading.Condition()
        threading.Thread(target=self.accept_loop, daemon=True).start()

    def accept_loop(self):
        while True:
            sock, address = self.listener.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.changed:
                self.count += 1
                self.log.write(event="accepted", conn=self.count, peer=address[0])
                self.latest = Connection(sock, self.log, self.count, self.policy)
                self.changed.notify_all()

    def wait_newer_than(self, number, timeout):
        with self.changed:
            self.changed.wait_for(lambda: self.latest is not None and self.latest.number > number, timeout)
            return self.latest if self.latest is not None and self.latest.number > number else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--port", type=int, default=1885)
    parser.add_argument("--log", required=True)
    parser.add_argument("--hold", type=float, default=6, help="seconds to watch after the scenario's last step")
    parser.add_argument("--burst", type=int, default=40)
    parser.add_argument("--large", type=int, default=30000, help="cut_publish: the PLC's payload size")
    parser.add_argument("--wait", type=float, default=120, help="seconds to wait for the go file")
    parser.add_argument("--go", help="start the scenario on the newest connection once this file exists "
                                     "(default: on the first connection)")
    args = parser.parse_args()
    log = Log(args.log)
    policy = {}
    if args.scenario == "suback_reject":
        policy["suback_code"] = {TOPIC_IN: 0x80}
    if args.scenario == "split_connack":
        policy["split_connack"] = True
    if args.scenario == "split_pingresp":
        policy["split_pingresp"] = True
    if args.scenario == "no_pubcomp":
        policy["ignore_pubrel"] = True
    server = Server(args.port, log, policy, small_receive_buffer=args.scenario == "cut_publish")
    log.write(event="listening", scenario=args.scenario, port=args.port)
    end = time.time() + args.wait
    while time.time() < end and (server.latest is None or (args.go and not os.path.exists(args.go))):
        time.sleep(0.1)
    conn = server.latest
    if conn is None or (args.go and not os.path.exists(args.go)):
        log.write(event="done", result={"ok": False, "error": "no connection or no go"})
        return
    log.write(event="go", conn=conn.number)
    runners = {"dup_publish": scenario_dup_publish, "pubrel_unknown": scenario_pubrel_unknown,
               "burst_qos1": lambda c, a: scenario_burst(c, a, 1), "burst_qos2": lambda c, a: scenario_burst(c, a, 2),
               "burst_large": lambda c, a: scenario_burst(c, a, 2, large_at=31),
               "burst_large_window": lambda c, a: scenario_burst(c, a, 2, large_at=31, inflight=20),
               "suback_reject": scenario_suback_reject, "no_pubcomp": scenario_no_pubcomp,
               "cut_publish": lambda c, a: scenario_cut_publish(c, a, server),
               "split_connack": lambda c, a: scenario_split(c, a, "CONNACK"),
               "split_pingresp": lambda c, a: scenario_split(c, a, "PINGRESP"),
               "bad_topic_length": lambda c, a: scenario_bad_topic_length(c, a, server)}
    try:
        result = runners[args.scenario](conn, args)
    except Exception as error:  # the log must always end with a done record
        result = {"ok": False, "error": repr(error)}
    log.write(event="done", result=result, connections=server.count)
    # keep serving so the PLC stays connected until the driver moves it back
    time.sleep(3600)


if __name__ == "__main__":
    main()
