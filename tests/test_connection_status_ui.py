import queue
import threading
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch
import tkinter as tk

from vector1a.app import VectorApp
from vector1a.network import MFPListener


class ListenerStatusTests(unittest.TestCase):
    def test_recovered_banner_replaces_old_error(self):
        listener = MFPListener(lambda *_: None, lambda _: None)
        listener._run.set()
        listener._handle("L05000\n", "websocket")
        app = object.__new__(VectorApp)
        app.listener = listener
        app.mfp_status = Mock()
        app.mfp_status.get.return_value = "MFP stream recovered: OSError: WinError 10038"
        app._refresh_mfp_status()
        app.mfp_status.set.assert_called_once_with("Receiving (WEBSOCKET)")

    def test_transport_failure_remains_visible_while_other_transport_receives(self):
        listener = MFPListener(lambda *_: None, lambda _: None)
        listener._run.set()
        listener._transport_errors["udp"] = "port in use"
        listener._handle("L05000\n", "tcp")
        self.assertIn("Receiving (TCP)", listener.connection_label())
        self.assertIn("UDP recovering", listener.connection_label())
        listener._run.clear()
        self.assertEqual(listener.connection_label(), "Disconnected")

    def test_replaced_socket_close_does_not_report_an_error(self):
        messages = []
        listener = MFPListener(lambda *_: None, messages.append)
        listener._run.set()
        old = Mock()
        listener._active_client = Mock()
        listener._stream_client = Mock(side_effect=OSError("not a socket"))
        listener._serve_client(old)
        self.assertEqual(messages, [])
        old.close.assert_called_once()

    def test_actual_active_stream_error_is_still_logged(self):
        messages = []
        listener = MFPListener(lambda *_: None, messages.append)
        listener._run.set()
        client = Mock()
        listener._active_client = client
        listener._stream_client = Mock(side_effect=OSError("peer reset"))
        listener._serve_client(client)
        self.assertTrue(any("peer reset" in message for message in messages))


class ConnectionLayoutTests(unittest.TestCase):
    def test_status_changes_do_not_move_panels_or_endpoint_controls(self):
        root = tk.Tk()
        app = None
        with ExitStack() as stack:
            # Build the actual interface without timers, network connections,
            # controllers, output or user-profile access.
            stack.enter_context(patch.object(root, "after", return_value="disabled"))
            stack.enter_context(patch("vector1a.app.load_settings", return_value={}))
            stack.enter_context(patch("vector1a.app.save_settings"))
            stack.enter_context(patch("vector1a.app.XInputController.start"))
            stack.enter_context(patch("vector1a.app.VectorEngine.start"))
            stack.enter_context(patch("vector1a.app.FunscriptTimeline.request_media_poll"))
            try:
                app = VectorApp(root)
                for width in (980, 1360, 1920):
                    root.geometry(f"{width}x1000")
                    root.update_idletasks()
                    sections = [app.sections[name] for name in ("MultiFunPlayer input", "ReStim output")]
                    widgets = sections + [child for section in sections for child in section.body.winfo_children()]
                    def geometry():
                        return [(w.winfo_x(), w.winfo_y(), w.winfo_width(), w.winfo_height()) for w in widgets]
                    for var in (app.mfp_status, app.restim_status, app.prostate_status):
                        var.set("Disconnected")
                    for section in sections:
                        section.summary.set("Idle")
                    root.update_idletasks()
                    before = geometry()
                    for message in ("MFP stream disconnected: " + "very long error " * 30,
                                    "Receiving (WEBSOCKET)", "Listening; no L0 for 1234.5 s"):
                        for var in (app.mfp_status, app.restim_status, app.prostate_status):
                            var.set(message)
                        for section in sections:
                            section.summary.set(message)
                        root.update_idletasks()
                        self.assertEqual(geometry(), before, (width, message))
            finally:
                if app is not None:
                    app.close()
                else:
                    root.destroy()
