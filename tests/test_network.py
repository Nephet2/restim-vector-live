import base64
import hashlib
import socket
import threading
import time
import unittest

from vector1a.engine import VectorEngine
from vector1a.network import LatestFrameDispatcher, MFPListener, ReStimWebSocketClient


class NetworkTests(unittest.TestCase):
    def test_blocked_restim_lane_cannot_starve_vector_engine(self):
        entered = threading.Event()
        release = threading.Event()
        statuses = []
        lane = LatestFrameDispatcher("Primary", statuses.append)
        output_count = []

        def blocked_send():
            entered.set()
            release.wait(1.0)
            return True

        def dispatch(sample):
            output_count.append(sample.sequence)
            lane.submit(blocked_send)

        engine = VectorEngine(dispatch, rate_hz=50, lookahead_seconds=.02)
        engine.resume()
        engine.receive_l0(.2)
        engine.start()
        try:
            self.assertTrue(entered.wait(.5))
            before = len(output_count)
            time.sleep(.12)
            self.assertTrue(engine.loop_alive())
            self.assertGreater(len(output_count), before + 2)
            self.assertGreater(lane.health()["dropped"], 0)
        finally:
            release.set()
            engine.close()
            lane.close()

    def test_dual_lanes_are_independent_and_latest_frame_wins(self):
        blocked = threading.Event()
        release = threading.Event()
        primary_seen = []
        prostate_seen = []
        primary = LatestFrameDispatcher("Primary", lambda _: None)
        prostate = LatestFrameDispatcher("Prostate", lambda _: None)
        try:
            primary.submit(lambda: (blocked.set(), release.wait(.5), primary_seen.append(1), True)[-1])
            self.assertTrue(blocked.wait(.3))
            primary.submit(lambda: (primary_seen.append(2), True)[-1])
            primary.submit(lambda: (primary_seen.append(3), True)[-1])
            prostate.submit(lambda: (prostate_seen.append(1), True)[-1])
            deadline = time.monotonic() + .5
            while not prostate_seen and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(prostate_seen, [1])
            release.set()
            deadline = time.monotonic() + .5
            while primary.health()["completed"] < 2 and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(primary_seen, [1, 3])
            self.assertGreaterEqual(primary.health()["dropped"], 1)
        finally:
            release.set()
            primary.close()
            prostate.close()

    def test_stale_frame_is_discarded_instead_of_replayed(self):
        ran = []
        lane = LatestFrameDispatcher("Primary", lambda _: None, max_age_seconds=.02)
        blocker = threading.Event()
        lane.submit(lambda: blocker.wait(.1) or True)
        time.sleep(.01)
        lane.submit(lambda: (ran.append("stale"), True)[-1], max_age_seconds=.02)
        time.sleep(.04)
        blocker.set()
        deadline = time.monotonic() + .3
        while lane.health()["pending"] and time.monotonic() < deadline:
            time.sleep(.005)
        try:
            self.assertEqual(ran, [])
            self.assertGreaterEqual(lane.health()["stale"], 1)
        finally:
            lane.close()

    def test_dependency_free_websocket_handshake_and_masked_text(self):
        server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(1)
        port = server.getsockname()[1]; received = []

        def serve():
            conn, _ = server.accept(); request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(4096)
            key = next(line.split(b":", 1)[1].strip() for line in request.split(b"\r\n")
                       if line.lower().startswith(b"sec-websocket-key:"))
            accept = base64.b64encode(hashlib.sha1(
                key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
            frame = conn.recv(4096); size = frame[1] & 0x7f; index = 2
            if size == 126: size = int.from_bytes(frame[2:4], "big"); index = 4
            mask, payload = frame[index:index+4], frame[index+4:index+4+size]
            received.append(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)).decode())
            conn.close(); server.close()

        threading.Thread(target=serve, daemon=True).start()
        client = ReStimWebSocketClient(lambda _: None); client.connect("127.0.0.1", port)
        client.send_prostate(.1, .2, .3, .4, .5, .6, .7)
        time.sleep(.05); client.disconnect()
        self.assertIn("L01000 L12000 V03000 F04000 P05000 P16000 P37000", received)

    def test_listener_accepts_a_new_tcp_client_after_disconnect(self):
        values = []
        probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
        listener = MFPListener(lambda value, *_: values.append(value), lambda _: None)
        listener.start("127.0.0.1", port)
        try:
            for command in (b"L01000\n", b"L09000\n"):
                with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
                    client.sendall(command)
                time.sleep(.05)
            self.assertEqual(values, [.1, .9])
        finally:
            listener.stop()

    def test_four_phase_uses_restim_e_axes(self):
        client = ReStimWebSocketClient(lambda _: None)
        messages = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: messages.append(value)})()
        client.send_four_phase((1.0, 0.0, .25, .5))
        frame = messages[0]; size = frame[1] & 0x7f; index = 2
        mask, payload = frame[index:index+4], frame[index+4:index+4+size]
        text = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
        self.assertEqual(text, "E19999 E20000 E32500 E45000")

    def test_four_phase_can_include_volume(self):
        client = ReStimWebSocketClient(lambda _: None)
        messages = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: messages.append(value)})()
        client.send_four_phase((1.0, 0.0, .25, .5), .4)
        frame = messages[0]; size = frame[1] & 0x7f; index = 2
        mask, payload = frame[index:index+4], frame[index+4:index+4+size]
        text = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
        self.assertEqual(text, "E19999 E20000 E32500 E45000 V04000")

    def test_primary_websocket_sends_three_and_four_phase_axes_together(self):
        client = ReStimWebSocketClient(lambda _: None)
        messages = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: messages.append(value)})()
        client.send_primary(.1, .2, (1.0, 0.0, .25, .5), .6, .7, .8, .9, .4)
        frame = messages[0]; size = frame[1] & 0x7f; index = 2
        if size == 126: size = int.from_bytes(frame[2:4], "big"); index = 4
        mask, payload = frame[index:index+4], frame[index+4:index+4+size]
        text = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
        self.assertEqual(
            text, "L01000 L12000 E19999 E20000 E32500 E45000 V06000 "
                  "C07000 P08000 P39000 P14000")

    def test_recovered_websocket_sends_safe_neutral_before_live_sample(self):
        client = ReStimWebSocketClient(lambda _: None)
        frames = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: frames.append(value)})()
        client._needs_neutral = True
        client.send_primary(.1, .2, (1.0, 0.0, .25, .5), .6, .7, .8, .9, .4)
        self.assertEqual(len(frames), 2)

        def decode(frame):
            size = frame[1] & 0x7f; index = 2
            if size == 126: size = int.from_bytes(frame[2:4], "big"); index = 4
            mask, payload = frame[index:index+4], frame[index+4:index+4+size]
            return bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()

        self.assertEqual(decode(frames[0]),
                         "L05000 L15000 E15000 E25000 E35000 E45000 V00000")
        self.assertIn("L01000 L12000 E19999 E20000", decode(frames[1]))


    def test_primary_authored_override_can_replace_generated_l0(self):
        client = ReStimWebSocketClient(lambda _: None)
        messages = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: messages.append(value)})()
        client.send_primary(.1, .2, (1.0, 0.0, .25, .5), .6, .7, .8, .9, .4,
                            overrides={"L0": .77, "V0": .45})
        frame = messages[0]; size = frame[1] & 0x7f; index = 2
        if size == 126: size = int.from_bytes(frame[2:4], "big"); index = 4
        mask, payload = frame[index:index+4], frame[index+4:index+4+size]
        text = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
        self.assertIn("L07700", text)
        self.assertIn("V04500", text)
        self.assertNotIn("L01000", text)
        self.assertNotIn("V06000", text)

    def test_primary_authored_overrides_replace_generated_and_append_extra_axes(self):
        client = ReStimWebSocketClient(lambda _: None)
        messages = []
        client._socket = type("Socket", (), {"sendall": lambda _, value: messages.append(value)})()
        client.send_primary(.1, .2, (1.0, 0.0, .25, .5), .6, .7, .8, .9, .4,
                            overrides={"L1": .91, "R0": .33})
        frame = messages[0]; size = frame[1] & 0x7f; index = 2
        if size == 126: size = int.from_bytes(frame[2:4], "big"); index = 4
        mask, payload = frame[index:index+4], frame[index+4:index+4+size]
        text = bytes(value ^ mask[i % 4] for i, value in enumerate(payload)).decode()
        self.assertIn("L19100", text)
        self.assertIn("R03300", text)
        self.assertNotIn("L12000", text)

    def test_listener_reports_all_axes_without_changing_l0_callback_contract(self):
        l0 = []
        commands = []
        listener = MFPListener(lambda value, *_: l0.append(value), lambda _: None,
                               lambda command, _: commands.append((command.axis, command.value)))
        listener._handle("L02500 L17500 R05000")
        self.assertEqual(l0, [.25])
        self.assertEqual(commands, [("L0", .25), ("L1", .75), ("R0", .5)])

    def test_quiet_listener_is_not_reported_as_failed(self):
        listener = MFPListener(lambda *_: None, lambda _: None)
        listener._run.set()
        listener._last_received = time.monotonic() - 3.25
        self.assertTrue(listener.connection_label().startswith("Listening; no L0 for"))
        self.assertTrue(listener.health()["running"])
        listener._run.clear()

    def test_websocket_reconnects_in_background_while_no_samples_are_sent(self):
        server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen(2)
        port = server.getsockname()[1]
        reconnected = threading.Event()

        def handshake(conn):
            request = b""
            while b"\r\n\r\n" not in request:
                request += conn.recv(4096)
            key = next(line.split(b":", 1)[1].strip() for line in request.split(b"\r\n")
                       if line.lower().startswith(b"sec-websocket-key:"))
            accept = base64.b64encode(hashlib.sha1(
                key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest())
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")

        def serve():
            first, _ = server.accept(); handshake(first); first.close()
            second, _ = server.accept(); handshake(second); reconnected.set()
            reconnected.wait(1.0); second.close(); server.close()

        threading.Thread(target=serve, daemon=True).start()
        client = ReStimWebSocketClient(lambda _: None)
        try:
            client.connect("127.0.0.1", port)
            self.assertTrue(reconnected.wait(3.0))
            health = client.health()
            self.assertGreaterEqual(health["reconnect_attempts"], 1)
            self.assertGreaterEqual(health["reconnect_successes"], 1)
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()


def test_mfp_listener_records_raw_packet_and_all_axes():
    seen = []
    listener = MFPListener(lambda value, interval, when: None, lambda text: None,
                           lambda command, when: seen.append(command.axis))
    listener._handle("L05000L17500V02500 C09000", "udp")
    assert seen == ["L0", "L1", "V0", "C0"]
    packet = listener.recent_packets(1)[0]
    assert packet["transport"] == "UDP"
    assert packet["axes"] == ["L0", "L1", "V0", "C0"]
    assert packet["raw"] == "L05000L17500V02500 C09000"
