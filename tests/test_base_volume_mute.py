"""Base volume zero must mute composed Primary V0, envelope on or off."""
import math
import time
import tkinter as tk
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from vector1a.app import VectorApp

DT = 0.02


class BaseVolumeMuteTests(unittest.TestCase):
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
        self.primary = self.guards.enter_context(patch.object(self.app.restim, "send_primary"))
        self.prostate = self.guards.enter_context(
            patch.object(self.app.prostate_restim, "send_prostate"))
        for sender in (self.app.restim_sender, self.app.prostate_sender):
            self.guards.enter_context(patch.object(sender, "submit",
                                                   side_effect=lambda fn, **kw: fn()))
        self.t = time.monotonic()
        self.phase = 0.0

    def drive(self, seconds):
        engine = self.app.engine
        for _ in range(int(round(seconds / DT))):
            # The first packet repeats the rebase position at the rebase time,
            # as live input does, so speed normalisation is not pinned.
            position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(self.phase))
            engine.receive_l0(position, 0, self.t)
            engine.step(self.t, self.t)
            self.phase += 2 * math.pi * DT
            self.t += DT

    def composed_v0_after_base_volume_zero(self, apply=True):
        return self.composed_v0_after_base_volume(0.0, apply)

    def composed_v0_after_base_volume(self, new_volume, apply=True):
        app = self.app
        app.lookahead.set(0.5)
        app.resume()
        app.engine.rebase_input(0.1, self.t)
        self.drive(6.0)
        before = [call.args[3] for call in self.primary.call_args_list]
        # Output is active, not sitting at the rest level (0.85 x 0.38 = 0.323).
        self.assertGreater(min(before[-100:]), 0.5)
        prostate_before = [call.args[2] for call in self.prostate.call_args_list]
        self.assertGreater(max(prostate_before), 0.3)
        # Last 2 s before the change: steady strokes, steady levels.
        self.primary_before = before[-100:]
        self.prostate_before = prostate_before[-100:]
        mark = len(self.primary.call_args_list)
        prostate_mark = len(self.prostate.call_args_list)
        app.volume.set(new_volume)
        if apply:
            self.assertTrue(app.apply_config())
        self.drive(1.5)
        self.prostate_after = [call.args[2]
                               for call in self.prostate.call_args_list[prostate_mark:]]
        return [call.args[3] for call in self.primary.call_args_list[mark:]]

    def check_reduction(self, after):
        # Primary is response x ceiling: Base volume does not scale it.  The
        # first full 1 Hz stroke after the change must keep the same range;
        # dividing queued samples by the new Base volume used to saturate it.
        self.assertGreaterEqual(len(after), 50)
        stroke = after[:50]
        low, high = min(self.primary_before), max(self.primary_before)
        self.assertAlmostEqual(min(stroke), low, delta=2e-3,
                               msg=f"first stroke {min(stroke):.4f}..{max(stroke):.4f}, "
                                   f"before {low:.4f}..{high:.4f}")
        self.assertAlmostEqual(max(stroke), high, delta=2e-3,
                               msg=f"first stroke {min(stroke):.4f}..{max(stroke):.4f}, "
                                   f"before {low:.4f}..{high:.4f}")
        # Prostate is its response x Base volume: halving Base volume halves it
        # at once, including samples already queued at the old Base volume.
        limit = 0.5 * max(self.prostate_before) + 1e-6
        prostate = self.prostate_after
        self.assertTrue(prostate)
        self.assertLessEqual(max(prostate), limit,
                             f"Prostate: {sum(v > limit for v in prostate)} commands above "
                             f"half the earlier level ({limit:.4f}); first {prostate[:4]}")

    def test_halving_base_volume(self):
        self.check_reduction(self.composed_v0_after_base_volume(0.35))

    def test_halving_base_volume_without_apply(self):
        self.check_reduction(self.composed_v0_after_base_volume(0.35, apply=False))

    def test_halving_base_volume_with_v0_envelope(self):
        # The envelope must smooth the 0-1 response, not volume already scaled
        # by Base volume, or its older values are divided by the new scale.
        self.app.volume_envelope_enabled.set(True)   # Defaults: 0.1 / 0.5 s, J 100.
        self.check_reduction(self.composed_v0_after_base_volume(0.35))

    def test_halving_base_volume_with_v0_envelope_without_apply(self):
        self.app.volume_envelope_enabled.set(True)
        self.check_reduction(self.composed_v0_after_base_volume(0.35, apply=False))

    def check_muted(self, after):
        self.assertTrue(after)
        live = [v for v in after if v > 0]
        self.assertEqual(max(after), 0.0,
                         f"{len(live)} non-zero commands ({len(live) * DT:.2f} s), "
                         f"{sum(v >= 0.999 for v in after)} at 100%; first {after[:4]}")
        prostate = self.prostate_after
        self.assertTrue(prostate)
        self.assertEqual(max(prostate), 0.0,
                         f"Prostate: {sum(v > 0 for v in prostate)} non-zero commands; "
                         f"first {prostate[:4]}")

    def test_envelope_off(self):
        self.check_muted(self.composed_v0_after_base_volume_zero())

    def test_envelope_off_value_changed_without_apply(self):
        # Typing into the Base volume spinbox updates the variable (and the
        # composer's config via its trace) without calling apply_config().
        self.check_muted(self.composed_v0_after_base_volume_zero(apply=False))

    def test_v0_envelope_on(self):
        self.app.volume_envelope_enabled.set(True)   # Defaults: 0.1 / 0.5 s, J 100.
        self.check_muted(self.composed_v0_after_base_volume_zero())


class SampleVolumeScaleTests(unittest.TestCase):
    def test_samples_record_the_base_volume_they_were_calculated_with(self):
        from vector1a.engine import VectorEngine
        from vector1a.motion import MotionMode, MotionParameters
        released = []
        engine = VectorEngine(released.append, lookahead_seconds=0.1, volume=0.7,
                              clock=lambda: 0.0)
        engine.resume()
        engine.step(0.0, 0.0)
        engine.configure(rate_hz=50, lookahead_seconds=0.1, volume=0.35,
                         mode=MotionMode.CIRCULAR, params=MotionParameters())
        for i in range(1, 12):
            engine.step(i * DT, i * DT)
        self.assertEqual(released[0].volume_scale, 0.7)    # Queued before the change.
        self.assertEqual(released[-1].volume_scale, 0.35)


if __name__ == "__main__":
    unittest.main()
