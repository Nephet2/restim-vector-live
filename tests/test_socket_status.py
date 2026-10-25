import threading
import unittest

from vector1a.network import ReStimClient, ReStimWebSocketClient


class SocketStatusTests(unittest.TestCase):
    def run_without_deadlock(self, client, action):
        errors = []
        def run():
            try:
                action()
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join(1)
        self.assertFalse(thread.is_alive(), "status callback deadlocked reading client health")
        if errors:
            raise errors[0]

    def test_reconnect_status_can_read_health(self):
        reports = []
        client = ReStimClient(lambda text: reports.append((text, client.health())))
        try:
            client._target = ("test", 1)
            client._manual_disconnect = False
            def fail():
                raise OSError("offline")
            client._connect_now = fail
            self.run_without_deadlock(client, lambda: self.reconnect(client))
            self.assertTrue(any("Reconnecting:" in text for text, _ in reports))
            self.assertEqual(client.health()["reconnect_attempts"], 1)
        finally:
            client.close()

    @staticmethod
    def reconnect(client):
        with client._locked():
            client._ensure_connected()

    def test_recovery_status_can_read_health_and_preserves_neutral(self):
        reports, frames = [], []
        client = ReStimWebSocketClient(lambda text: reports.append((text, client.health())))
        class Socket:
            def sendall(self, frame):
                frames.append(frame)
            def close(self):
                pass
        try:
            client._socket = Socket()
            client._needs_neutral = True
            self.run_without_deadlock(client, lambda: client.send_primary(
                .1, .2, (.1, .2, .3, .4), .2, .3, .4, .5, .6))
            self.assertEqual(len(frames), 2)
            self.assertIn("Recovered safely; output resumed", [text for text, _ in reports])
            self.assertEqual(reports[-1][1]["send_count"], 1)
        finally:
            client.close()

    def test_failure_status_is_delivered_after_lock_release(self):
        reports = []
        client = ReStimClient(lambda text: reports.append((text, client.health())))
        class Socket:
            def sendall(self, frame):
                raise OSError("peer disappeared")
            def close(self):
                pass
        try:
            client._socket = Socket()
            self.run_without_deadlock(client, lambda: client.send(.1, .2, .3))
            self.assertFalse(client.connected)
            self.assertEqual(reports[-1][1]["send_failures"], 1)
        finally:
            client.close()
