import json
import struct
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock, patch

from vector1a.direct_player import DEOVR, HERESPHERE, DirectPlayerInput, vr_snapshot


class DeoVRInputTests(TestCase):
    def setUp(self):
        self.now = 10.0
        self.player = DirectPlayerInput(DEOVR, "192.0.2.7", 23554, clock=lambda: self.now)
        self.message = {
            "path": "https://example.invalid/first.m3u8",
            "currentTime": 2.0,
            "duration": 10.0,
            "playbackSpeed": 1.25,
            "playerState": 0,
        }

    def test_fragmented_remote_packet_and_heartbeat(self):
        payload = json.dumps(self.message).encode()
        packet = struct.pack("<i", len(payload)) + payload
        transport = MagicMock()
        transport.__enter__.return_value = transport
        transport.recv.side_effect = [packet[:3], packet[3:17], packet[17:], b""]
        with patch("vector1a.direct_player.socket.create_connection", return_value=transport) as connect:
            self.player._read_vr_player()
        connect.assert_called_once_with(("192.0.2.7", 23554), timeout=.75)
        transport.sendall.assert_called_once_with(bytes(4))
        snapshot = self.player.frame.snapshot
        self.assertEqual(snapshot.player, DEOVR)
        self.assertEqual(snapshot.duration_seconds, 10.0)
        self.assertEqual(snapshot.rate, 1.25)
        self.assertEqual(self.player.session_status(self.now), ("Playing", "Online video; load a local funscript"))

        transport.recv.side_effect = [bytes(4), b""]
        with patch("vector1a.direct_player.socket.create_connection", return_value=transport):
            self.player._read_vr_player()
        self.assertIsNone(self.player.frame)

    def test_local_script_tracks_online_clock_and_clears_on_media_change(self):
        def accept(**changes):
            self.player._accept(vr_snapshot(DEOVR, self.message | changes))

        accept()
        self.now += 1.0
        self.assertEqual(self.player.session_status(self.now)[0], "Playing")
        self.assertIsNone(self.player.sample(self.now, "Linear")[0])
        with TemporaryDirectory() as folder:
            script = Path(folder) / "local.funscript"
            script.write_text('{"actions":[{"at":0,"pos":0},{"at":10000,"pos":100}]}', encoding="utf-8")
            self.player.load_manual(script, self.message["path"])
            self.assertAlmostEqual(self.player.sample(self.now, "Linear", lead=1.0)[0], .45)
            self.assertAlmostEqual(self.player.follow_transport(self.now, "Linear")["l0"], .325)
            self.assertAlmostEqual(self.player.handy_transport(self.now, "Linear")["position"], 3.25)
            self.now += .2
            accept(currentTime=4.0, playerState=1)
            self.assertEqual(self.player.session_status(self.now), ("Paused", script.name))
            self.assertIsNone(self.player.sample(self.now, "Linear")[0])
            self.now += .2
            accept(currentTime=4.0)
            self.assertIsNotNone(self.player.sample(self.now, "Linear")[0])
            self.now += 2.0
            self.assertEqual(self.player.session_status(self.now)[0], "Stale player clock")
            self.assertIsNone(self.player.handy_transport(self.now, "Linear"))
            accept(path="https://example.invalid/second.m3u8")
            self.assertIsNone(self.player.sample(self.now, "Linear")[0])

    def test_invalid_state_and_here_sphere_resource(self):
        self.assertFalse(vr_snapshot(DEOVR, self.message | {"playerState": 2}).connected)
        here = vr_snapshot(HERESPHERE, self.message | {"resource": "D:/some/file.mp4"})
        self.assertEqual(here.media_path, "D:/some/file.mp4")
