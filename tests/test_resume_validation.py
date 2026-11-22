import tkinter as tk
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from vector1a.app import VectorApp


class ResumeValidationTests(unittest.TestCase):
    def test_resume_does_not_enable_output_when_settings_are_invalid(self):
        root = tk.Tk()
        app = None
        with ExitStack() as guards:
            guards.enter_context(patch.object(root, "after", return_value="disabled"))
            guards.enter_context(patch("vector1a.app.load_settings", return_value={}))
            guards.enter_context(patch("vector1a.app.save_settings"))
            guards.enter_context(patch("vector1a.app.XInputController.start"))
            guards.enter_context(patch("vector1a.app.VectorEngine.start"))
            guards.enter_context(patch("vector1a.app.FunscriptTimeline.request_media_poll"))
            try:
                app = VectorApp(root)
                for sender in (app.restim_sender, app.prostate_sender):
                    guards.enter_context(patch.object(sender, "submit"))
                error = guards.enter_context(patch("vector1a.app.messagebox.showerror"))
                self.assertFalse(app.engine.control_state()["output_enabled"])
                # An incomplete spinbox entry makes the Tk variable unreadable.
                with patch.object(app.rate, "get",
                                  side_effect=tk.TclError("expected integer")):
                    app.resume()
                error.assert_called_once()
                state = app.engine.control_state()
                self.assertFalse(state["output_enabled"])
                self.assertEqual(state["engine_state"], "Stopped")
            finally:
                if app is not None:
                    app.close()
                else:
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
