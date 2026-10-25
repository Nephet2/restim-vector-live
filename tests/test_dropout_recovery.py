import socket
import time
import unittest
from vector1a.network import MFPListener, ReStimClient, ReStimWebSocketClient

def wait_for(predicate, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(.01)
    return False

class DropoutTests(unittest.TestCase):
    def test_replacement_stream_works_while_previous_client_stays_open(self):
        values = []
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        listener = MFPListener(lambda value, *_: values.append(value), lambda _: None)
        listener.start("127.0.0.1", port)
        old = new = None
        try:
            self.assertTrue(wait_for(lambda: listener.health()["tcp"]))
            old = socket.create_connection(("127.0.0.1", port), timeout=1)
            old.sendall(b"L01000\n")
            self.assertTrue(wait_for(lambda: values == [.1]))
            new = socket.create_connection(("127.0.0.1", port), timeout=1)
            new.sendall(b"L09000\n")
            self.assertTrue(wait_for(lambda: values == [.1, .9]))
            new.sendall(b"L05000\n")
            self.assertTrue(wait_for(lambda: values == [.1, .9, .5]))
        finally:
            if old: old.close()
            if new: new.close()
            listener.stop()

    def test_fragmented_ping_is_answered_and_close_is_detected(self):
        client = ReStimWebSocketClient(lambda _: None)
        left, peer = socket.socketpair()
        peer.settimeout(1)
        client._socket = left
        client._incoming = bytearray()
        try:
            peer.sendall(b"\x89\x03a")
            client._receive_available()
            peer.sendall(b"bc")
            client._receive_available()
            pong = peer.recv(100)
            self.assertEqual(pong[:2], b"\x8a\x83")
            mask, payload = pong[2:6], pong[6:]
            self.assertEqual(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)), b"abc")
            peer.sendall(b"\x88\x00")
            with self.assertRaises(ConnectionResetError):
                client._receive_available()
        finally:
            client.close()
            peer.close()

    def test_tcp_output_sends_and_updates_health(self):
        client = ReStimClient(lambda _: None)
        left, peer = socket.socketpair()
        peer.settimeout(1)
        client._socket = left
        try:
            client.send(.1, .2, .3, .4, .5, .6, .7)
            self.assertIn(b"L01000", peer.recv(1024))
            self.assertEqual(client.health()["send_count"], 1)
        finally:
            client.close()
            peer.close()
