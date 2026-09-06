import base64
import hashlib
import os
import socket
import struct
import threading
import time
import unittest

from vector1a.engine import VectorEngine
from vector1a.network import MFPListener


def frame(payload, opcode=1, final=True, masked=True):
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    size = len(payload)
    header = bytes(((0x80 if final else 0) | opcode,))
    flag = 0x80 if masked else 0
    if size < 126:
        header += bytes((flag | size,))
    elif size < 65536:
        header += bytes((flag | 126,)) + struct.pack("!H", size)
    else:
        header += bytes((flag | 127,)) + struct.pack("!Q", size)
    if not masked:
        return header + payload
    mask = os.urandom(4)
    return header + mask + bytes(value ^ mask[i % 4] for i, value in enumerate(payload))


def read_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError
        data += chunk
    return data


class WebSocketInputTests(unittest.TestCase):
    def setUp(self):
        self.values = []
        self.commands = []
        self.statuses = []
        self.listener = MFPListener(lambda *args: self.values.append(args), self.statuses.append,
                                    lambda command, when: self.commands.append((command, when)))
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            self.port = reserve.getsockname()[1]
        self.listener.start("127.0.0.1", self.port)
        self.wait_for(lambda: self.listener.health()["tcp"] and self.listener.health()["udp"])
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.listener.stop()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while not predicate() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertTrue(predicate())

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
        self.clients.append(sock)
        return sock

    def request(self, path="/ws", key=None):
        key = key or base64.b64encode(os.urandom(16)).decode()
        return (f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                f"Upgrade: websocket\r\nConnection: keep-alive, Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode(), key

    def headers(self, sock):
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            header += read_exact(sock, 1)
        return header

    def websocket(self, path="/ws", first_frame=b""):
        sock = self.connect()
        request, key = self.request(path)
        sock.sendall(request + first_frame)
        header = self.headers(sock)
        self.assertIn(b"101 Switching Protocols", header)
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        self.assertIn(b"Sec-WebSocket-Accept: " + accept, header)
        return sock

    def control(self, sock):
        first, size = read_exact(sock, 2)
        self.assertFalse(size & 0x80, "Server frames must not be masked")
        return first & 0x0f, read_exact(sock, size)

    def test_upgrade_with_coalesced_first_message_all_axes_and_no_newline(self):
        self.websocket(first_frame=frame("L02500I125 L17500 V03000"))
        self.wait_for(lambda: len(self.commands) == 3)
        self.assertEqual([(c.axis, c.value) for c, _ in self.commands],
                         [("L0", .25), ("L1", .75), ("V0", .3)])
        self.assertEqual(self.values[0][:2], (.25, 125))
        self.assertEqual(len({when for _, when in self.commands}), 1)
        self.assertEqual(self.listener.recent_packets(1)[0]["transport"], "WEBSOCKET")
        self.assertIn("WEBSOCKET", self.listener.connection_label())

    def test_tcp_udp_and_websocket_deliver_identical_commands(self):
        text = "L02500I125 L17500 V03000\n"
        with self.connect() as sock:
            sock.sendall(text.encode())
            self.wait_for(lambda: len(self.commands) == 3)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(text.encode(), ("127.0.0.1", self.port))
            self.wait_for(lambda: len(self.commands) == 6)
        self.websocket(first_frame=frame(text))
        self.wait_for(lambda: len(self.commands) == 9)
        groups = [[(c.axis, c.value, c.interval_ms) for c, _ in self.commands[i:i+3]]
                  for i in (0, 3, 6)]
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(groups[1], groups[2])

    def test_fragmented_message_ping_pong_and_multiple_frames(self):
        sock = self.websocket()
        data = frame("L0", final=False) + frame(b"alive", opcode=9) + frame("7500", opcode=0)
        for byte in data:
            sock.sendall(bytes((byte,)))
        self.assertEqual(self.control(sock), (10, b"alive"))
        self.wait_for(lambda: len(self.values) == 1)
        sock.sendall(frame("L02500") + frame("L05000"))
        self.wait_for(lambda: len(self.values) == 3)
        self.assertEqual([v[0] for v in self.values], [.75, .25, .5])

    def test_extended_lengths_and_maximum_message(self):
        sock = self.websocket()
        sock.sendall(frame("L05000" + " " * 200))
        self.wait_for(lambda: len(self.values) == 1)
        sock.sendall(frame("L07500" + " " * (65536 - 6)))
        self.wait_for(lambda: len(self.values) == 2)
        self.assertEqual(self.values[-1][0], .75)

    def test_close_reconnect_and_endpoint_aliases(self):
        for path in ("/ws", "/tcode", "/"):
            with self.websocket(path) as sock:
                sock.sendall(frame("L02500") + frame(struct.pack("!H", 1000), opcode=8))
                self.assertEqual(self.control(sock), (8, struct.pack("!H", 1000)))
        self.assertEqual(len(self.values), 3)
        self.assertTrue(self.listener.health()["websocket"])

    def test_abrupt_disconnect_and_restart_with_partial_frame(self):
        sock = self.websocket()
        sock.sendall(frame("L05000")[:3])
        workers = list(self.listener._threads)
        self.listener.stop()
        self.assertFalse(any(t.is_alive() for t in workers))
        self.listener.start("127.0.0.1", self.port)
        self.wait_for(lambda: self.listener.health()["tcp"])
        with self.websocket(first_frame=frame("L07500")):
            self.wait_for(lambda: len(self.values) == 1)
        with self.websocket(first_frame=frame("L02500")):
            self.wait_for(lambda: len(self.values) == 2)
        self.assertEqual([v[0] for v in self.values], [.75, .25])

    def test_invalid_frames_are_closed_without_reaching_engine(self):
        cases = [
            (frame("L05000", masked=False), 1002),
            (frame("L05000", opcode=0), 1002),
            (frame("L05000", opcode=2), 1003),
            (frame(b"\xff"), 1007),
            (frame("L0", final=False) + frame("5000"), 1002),
            (frame("x", opcode=9, final=False), 1002),
            (frame(b"x", opcode=8), 1002),
            (frame(struct.pack("!H", 1005), opcode=8), 1002),
            (frame(struct.pack("!H", 1000) + b"\xff", opcode=8), 1007),
            (b"\xc1\x80", 1002),
            (b"\x81\xff" + struct.pack("!Q", 65537), 1009),
            (frame(" " * 40000, final=False) + frame(" " * 30000, opcode=0), 1009),
        ]
        for data, code in cases:
            with self.subTest(code=code, prefix=data[:8]):
                with self.websocket() as sock:
                    sock.sendall(data)
                    self.assertEqual(self.control(sock), (8, struct.pack("!H", code)))
        self.assertEqual(self.values, [])
        self.assertTrue(self.listener.health()["tcp"])

    def test_invalid_handshake_does_not_poison_next_connection(self):
        for path, key in (("/wrong", None), ("/ws", "bad")):
            with self.connect() as sock:
                request, _ = self.request(path, key)
                sock.sendall(request)
                self.assertIn(b"400 Bad Request", self.headers(sock))
        self.websocket(first_frame=frame("L05000"))
        self.wait_for(lambda: len(self.values) == 1)

    def test_split_handshake_and_quiet_connection_remain_usable(self):
        sock = self.connect()
        request, _ = self.request()
        sock.sendall(request[:1])
        sock.sendall(request[1:])
        self.assertIn(b"101 Switching Protocols", self.headers(sock))
        # Cross the socket read timeout while retaining the incomplete frame.
        data = frame("L05000")
        sock.sendall(data[:3])
        time.sleep(.6)
        sock.sendall(data[3:])
        self.wait_for(lambda: len(self.values) == 1)
        self.assertTrue(self.listener.health()["websocket"])

    def test_websocket_preserves_queue_delay_and_stop_latch(self):
        clock = [10.0]
        samples = []
        engine = VectorEngine(samples.append, lookahead_seconds=.1, clock=lambda: clock[0])
        received = threading.Event()
        def deliver(value, interval, _received_at):
            engine.receive_l0(value, interval, clock[0])
            received.set()
        self.listener.on_l0 = deliver
        engine.resume()
        sock = self.websocket(first_frame=frame("L02500I100"))
        self.assertTrue(received.wait(2))
        engine.step(clock[0])
        self.assertEqual(samples, [])
        clock[0] = 10.11
        engine.step(clock[0])
        self.assertGreater(len(samples), 0)
        self.assertAlmostEqual(samples[0].due_at - samples[0].calculated_at, .1)
        engine.stop()
        count = len(samples)
        received.clear()
        sock.sendall(frame("L07500I100"))
        self.assertTrue(received.wait(2))
        clock[0] = 10.5
        engine.step(clock[0])
        self.assertEqual(len(samples), count)
        self.assertEqual(engine.diagnostics().state, "Stopped")
