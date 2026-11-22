"""'Rest after (s)': how long input may pause before outputs drop to rest."""
import math
import tkinter as tk
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from vector1a.app import VectorApp
from vector1a.engine import VectorEngine
from vector1a.motion import MotionMode, MotionParameters

DT = 0.02


def drive(rest_after=None, gap=(6.0, 6.75), seconds=9.0):
    """1 Hz strokes with one input gap; returns {calculated_at: sample}."""
    now, released = [0.0], []
    engine = VectorEngine(released.append, lookahead_seconds=0.1, clock=lambda: now[0])
    if rest_after is not None:
        engine.configure(rate_hz=50, lookahead_seconds=0.1, volume=0.7,
                         mode=MotionMode.CIRCULAR, params=MotionParameters(),
                         volume_idle_seconds=rest_after)
    engine.resume()
    phase = 0.0
    for index in range(int(round(seconds / DT))):
        t = index * DT
        now[0] = t
        position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(phase))
        if index == 0:
            engine.rebase_input(position, t)
        if not gap[0] <= t < gap[1]:
            engine.receive_l0(position, 0, t)
            phase += 2 * math.pi * DT
        engine.step(t, t)
    return engine, {round(s.calculated_at, 4): s for s in released}


def window(samples, start, end):
    return [s for t, s in samples.items() if start <= t < end]


class EngineRestAfterTests(unittest.TestCase):
    def test_default_keeps_the_existing_quarter_second(self):
        engine, _ = drive()
        self.assertEqual(engine.volume_idle_seconds, 0.25)

    def test_short_hold_drops_to_rest_with_default(self):
        _, samples = drive(gap=(6.0, 6.75))
        active = min(s.volume for s in window(samples, 5.0, 6.0))
        held = min(s.volume for s in window(samples, 6.0, 6.75))
        self.assertLess(held, 0.6 * active)

    def test_longer_rest_after_keeps_volume_through_short_hold(self):
        _, samples = drive(rest_after=1.0, gap=(6.0, 6.75))
        active = min(s.volume for s in window(samples, 5.0, 6.0))
        held = window(samples, 6.0, 6.75)
        self.assertGreaterEqual(min(s.volume for s in held), 0.95 * active)
        # Pulse width and the prostate volume use the same rest gate.
        self.assertGreaterEqual(min(s.volume_prostate for s in held),
                                0.95 * min(s.volume_prostate
                                           for s in window(samples, 5.0, 6.0)))

    def test_longer_pause_still_reaches_rest_after_the_setting(self):
        _, reference = drive(gap=(6.0, 9.0))
        _, samples = drive(rest_after=1.0, gap=(6.0, 9.0))
        rest = reference[round(8.5, 4)].volume
        before = [s.volume for s in window(samples, 6.0, 6.98)]
        after = [s.volume for s in window(samples, 7.04, 9.0)]
        self.assertTrue(all(v > 1.5 * rest for v in before))
        self.assertTrue(after and all(abs(v - rest) < 1e-12 for v in after))

    def test_value_is_bounded(self):
        for value, expected in ((0.0, 0.05), (99.0, 5.0), (1.5, 1.5)):
            engine, _ = drive(rest_after=value, seconds=0.1)
            self.assertEqual(engine.volume_idle_seconds, expected)


class AppRestAfterTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for target in ("vector1a.app.XInputController.start",
                       "vector1a.app.VectorEngine.start",
                       "vector1a.app.FunscriptTimeline.request_media_poll",
                       "vector1a.app.save_settings"):
            self.guards.enter_context(patch(target))
        self.guards.enter_context(patch.object(self.root, "after", return_value="disabled"))
        self.guards.enter_context(patch("vector1a.app.load_settings", return_value={}))
        self.guards.enter_context(patch("vector1a.app.messagebox.showerror"))
        self.app = VectorApp(self.root)
        self.addCleanup(self.app.close)

    def test_setting_is_saved_and_reaches_engine(self):
        self.assertEqual(VectorApp.SETTINGS_FIELDS.count("volume_idle_seconds"), 1)
        self.assertEqual(self.app.volume_idle_seconds.get(), 0.25)
        self.app.volume_idle_seconds.set(1.2)
        self.assertTrue(self.app.apply_config())
        self.assertEqual(self.app.engine.volume_idle_seconds, 1.2)

    def test_control_sits_in_volume_response_panel(self):
        panel = self.app.volume_response_bar.master
        spins = [w for w in panel.winfo_children() if w.winfo_class() == "TSpinbox"
                 and str(w.cget("textvariable")) == str(self.app.volume_idle_seconds)]
        self.assertEqual(len(spins), 1)
        labels = [str(w.cget("text")) for w in panel.winfo_children()
                  if w.winfo_class() == "TLabel"]
        self.assertIn("Rest after (s)", labels)


if __name__ == "__main__":
    unittest.main()
