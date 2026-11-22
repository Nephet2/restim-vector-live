import time
import tkinter as tk
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from vector1a.app import VectorApp
from vector1a.engine import OutputSample
from vector1a.motion import MotionMode


class NeutralRaceTests(unittest.TestCase):
    def test_live_frame_popped_before_neutral_cannot_supersede_it(self):
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
                submit_live = guards.enter_context(patch.object(app, "_submit_sample"))
                # Calculated before Neutral, released by the engine thread after
                # Neutral drops _input_lock (engine.py _release_due sends unlocked).
                stale = OutputSample(1, time.monotonic() - 0.05, time.monotonic(),
                                     .2, .2, 50., .9, .1, .6, MotionMode.CIRCULAR,
                                     .5, .5, .5, .5, .5, .5, .6)
                app.neutral()
                app._send_sample(stale)
                submit_live.assert_not_called()
            finally:
                if app is not None:
                    app.close()
                else:
                    root.destroy()


if __name__ == "__main__":
    unittest.main()
