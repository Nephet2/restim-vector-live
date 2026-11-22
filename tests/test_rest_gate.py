"""Rest gate: stroke-reversal requirement and S-curve fall time."""
import math
import unittest

from vector1a.engine import VectorEngine
from vector1a.motion import MotionMode, MotionParameters

DT = 0.02


def run(seconds, *, pause_at=None, glide_at=None, resume_at=None, nudge=0.0,
        repeat_while_paused=False, **settings):
    """1 Hz strokes; optional pause, auto-home-style glide and resumed strokes.

    The glide moves one way only, from the paused position to 0.5 over 2.5 s,
    fast at first and easing in, like a player parking the axis.
    """
    now, released = [0.0], []
    engine = VectorEngine(released.append, lookahead_seconds=0.1, clock=lambda: now[0])
    engine.configure(rate_hz=50, lookahead_seconds=0.1, volume=0.7,
                     mode=MotionMode.CIRCULAR, params=MotionParameters(), **settings)
    engine.resume()
    phase, position, glide_from = 0.0, 0.1, None
    for index in range(int(round(seconds / DT))):
        t = index * DT
        now[0] = t
        stroking = (pause_at is None or t < pause_at
                    or (resume_at is not None and t >= resume_at))
        send = stroking
        if stroking:
            position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(phase))
        elif glide_at is not None and glide_at <= t < glide_at + 2.5:
            if glide_from is None:
                glide_from = position
            progress = (t - glide_at) / 2.5
            position = glide_from + (0.5 - glide_from) * (1 - (1 - progress) ** 3)
            if progress == 0.0:
                position += nudge       # Optional tiny step before the glide.
            send = True
        elif repeat_while_paused:
            send = True                 # Player keeps sending the paused position.
        if index == 0:
            engine.rebase_input(position, t)
        if send:
            engine.receive_l0(position, 0, t)
        if stroking:
            phase += 2 * math.pi * DT
        engine.step(t, t)
    return engine, {round(s.calculated_at, 4): s for s in released}


def values(samples, start, end, field="volume"):
    return [getattr(s, field) for t, s in sorted(samples.items()) if start <= t < end]


class ReversalWindowTests(unittest.TestCase):
    def test_default_is_off_and_glide_after_pause_raises_volume(self):
        engine, samples = run(13.0, pause_at=6.0, glide_at=9.0)
        self.assertEqual(engine.stroke_reversal_window, 0.0)
        active = min(values(samples, 5.0, 6.0))
        # Today's behaviour: the one-way glide counts as activity.
        self.assertGreater(max(values(samples, 9.5, 11.5)), 0.95 * active)

    def test_one_way_glide_after_pause_stays_at_rest(self):
        _, reference = run(13.0, pause_at=6.0)                # Pause, no glide.
        _, samples = run(13.0, pause_at=6.0, glide_at=9.0, stroke_reversal_window=2.0)
        # Rest levels still follow the speed reading, which the glide changes,
        # so V0 and Prostate V0 are checked against their rest ceilings
        # (Base volume 0.7 x rest level 0.4 / 0.7).  Active is about 0.67 / 0.69.
        self.assertLessEqual(max(values(samples, 9.0, 11.5)), 0.7 * 0.4 + 1e-9)
        self.assertLessEqual(max(values(samples, 9.0, 11.5, "volume_prostate")),
                             0.7 * 0.7 + 1e-9)
        # C0 ignores speed at rest, so it matches a pause without the glide.
        self.assertEqual(values(samples, 9.0, 11.5, "frequency"),
                         values(reference, 9.0, 11.5, "frequency"))

    def test_tiny_step_before_glide_does_not_count_as_a_fresh_turn(self):
        # Paused near the bottom on a downstroke; the parking move first steps
        # 0.2% further down, then glides up.  Without a deadband the turning
        # point is dated at that step, so V0 wakes for the window's length.
        _, samples = run(13.0, pause_at=6.0, glide_at=9.0, nudge=-0.002,
                         stroke_reversal_window=1.0)
        self.assertLessEqual(max(values(samples, 9.0, 11.5)), 0.7 * 0.4 + 1e-9)
        self.assertLessEqual(max(values(samples, 9.0, 11.5, "volume_prostate")),
                             0.7 * 0.7 + 1e-9)

    def test_larger_step_and_repeated_paused_position_still_stay_at_rest(self):
        for kwargs in ({"nudge": -0.03},
                       {"nudge": -0.002, "repeat_while_paused": True},
                       {"nudge": -0.03, "repeat_while_paused": True}):
            with self.subTest(**kwargs):
                _, samples = run(13.0, pause_at=6.0, glide_at=9.0,
                                 stroke_reversal_window=1.0, **kwargs)
                self.assertLessEqual(max(values(samples, 9.0, 11.5)), 0.7 * 0.4 + 1e-9)

    def test_slow_strokes_stay_active_with_window_on(self):
        # 0.3 Hz: a turn every 1.67 s, inside a 2 s window even with the
        # deadband dating each turn slightly before the true extreme.
        now, released = [0.0], []
        engine = VectorEngine(released.append, lookahead_seconds=0.1, clock=lambda: now[0])
        engine.configure(rate_hz=50, lookahead_seconds=0.1, volume=0.7,
                         mode=MotionMode.CIRCULAR, params=MotionParameters(),
                         stroke_reversal_window=2.0)
        engine.resume()
        for index in range(int(round(20.0 / DT))):
            t = index * DT
            now[0] = t
            position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(2 * math.pi * 0.3 * t))
            if index == 0:
                engine.rebase_input(position, t)
            engine.receive_l0(position, 0, t)
            engine.step(t, t)
        late = [s.volume for s in released if 12.0 <= s.calculated_at < 20.0]
        self.assertGreater(min(late), 0.6)

    def test_strokes_stay_active_with_window_on(self):
        _, reference = run(6.0)
        _, samples = run(6.0, stroke_reversal_window=2.0)
        self.assertEqual(values(samples, 3.0, 6.0), values(reference, 3.0, 6.0))

    def test_resumed_strokes_become_active_after_first_reversal(self):
        _, samples = run(16.0, pause_at=6.0, glide_at=8.0, resume_at=12.0,
                         stroke_reversal_window=2.0)
        active = min(values(samples, 5.0, 6.0))
        rest = max(values(samples, 8.5, 10.5))
        self.assertLess(rest, 0.6 * active)
        self.assertGreaterEqual(min(values(samples, 14.0, 16.0)), 0.95 * active)

    def test_script_hold_keeps_volume_with_rest_after_and_window(self):
        # A 1 s hold (no packets) then strokes resume from the same point.
        _, samples = run(10.0, pause_at=6.0, resume_at=7.0,
                         volume_idle_seconds=1.5, stroke_reversal_window=3.0)
        active = min(values(samples, 5.0, 6.0))
        self.assertGreaterEqual(min(values(samples, 5.0, 10.0)), 0.95 * active)

    def test_window_is_bounded(self):
        for value, expected in ((-1.0, 0.0), (99.0, 10.0), (2.5, 2.5)):
            engine, _ = run(0.1, stroke_reversal_window=value)
            self.assertEqual(engine.stroke_reversal_window, expected)


class FallTimeTests(unittest.TestCase):
    # Pause at 6.0: last packet 5.98, so with Rest after 0.25 s the gate
    # first reads idle at 6.24 and a 1 s fall lands at 7.24.
    FALL_START, FALL_END = 6.24, 7.24

    def test_default_is_an_instant_step(self):
        engine, samples = run(9.0, pause_at=6.0)
        self.assertEqual(engine.volume_fall_seconds, 0.0)
        v = values(samples, 5.9, 6.5)
        self.assertGreater(max(a - b for a, b in zip(v, v[1:])), 0.3)

    def check_s_curve_fall(self, field):
        _, step = run(9.0, pause_at=6.0)
        _, samples = run(9.0, pause_at=6.0, volume_fall_seconds=1.0)
        v = values(samples, 6.0, 9.0, field)                     # From the pause.
        start = samples[round(self.FALL_START - DT, 4)].__getattribute__(field)
        rest = step[8.0].__getattribute__(field)
        span = start - rest
        self.assertGreater(span, 0.15)
        # Never rises while falling; lands exactly on the instant-step rest level.
        rises = [(round(6.0 + i * DT, 2), a, b) for i, (a, b) in enumerate(zip(v, v[1:]))
                 if b > a + 1e-12]
        self.assertEqual(rises, [])
        self.assertEqual(values(samples, self.FALL_END + DT, 9.0, field),
                         values(step, self.FALL_END + DT, 9.0, field))
        # S-curve: gentle start, half way at half time, steepest at pi/2 x span / s.
        drops = [a - b for a, b in zip(v, v[1:])]
        self.assertLessEqual(max(drops), span * math.pi / 2 * DT + 1e-9)
        first = start - samples[self.FALL_START].__getattribute__(field)
        self.assertLess(first, 0.01 * span)
        middle = samples[round(self.FALL_START + 0.5, 4)].__getattribute__(field)
        self.assertAlmostEqual(middle, rest + span / 2, delta=0.02 * span)

    def test_v0_falls_on_an_s_curve(self):
        self.check_s_curve_fall("volume")

    def test_prostate_v0_falls_on_an_s_curve(self):
        self.check_s_curve_fall("volume_prostate")

    def test_resuming_mid_fall_rises_from_the_current_level(self):
        _, samples = run(10.0, pause_at=6.0, resume_at=6.6, volume_fall_seconds=1.0)
        reached = samples[6.58].volume
        active = min(values(samples, 5.0, 6.0))
        self.assertLess(reached, active - 0.02)                 # It had started falling.
        self.assertGreaterEqual(min(values(samples, 6.58, 10.0)), reached - 1e-12)
        v = values(samples, 6.0, 8.0)
        self.assertLess(max(abs(b - a) for a, b in zip(v, v[1:])), 0.02)
        self.assertGreaterEqual(min(values(samples, 8.5, 10.0)), 0.95 * active)

    def test_fall_time_is_bounded(self):
        for value, expected in ((-1.0, 0.0), (99.0, 5.0), (1.5, 1.5)):
            engine, _ = run(0.1, volume_fall_seconds=value)
            self.assertEqual(engine.volume_fall_seconds, expected)


class RestGateSettingsTests(unittest.TestCase):
    FIELDS = (("stroke_reversal_window", "Reversal window (s)"),
              ("volume_fall_seconds", "Fall time (s)"))

    def setUp(self):
        import tkinter as tk
        from contextlib import ExitStack
        from unittest.mock import patch
        from vector1a.app import VectorApp
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
        self.fields = VectorApp.SETTINGS_FIELDS

    def test_settings_default_off_are_saved_and_reach_engine(self):
        for name, _ in self.FIELDS:
            with self.subTest(name=name):
                self.assertEqual(self.fields.count(name), 1)
                self.assertEqual(getattr(self.app, name).get(), 0.0)
        self.app.stroke_reversal_window.set(3.0)
        self.app.volume_fall_seconds.set(1.5)
        self.assertTrue(self.app.apply_config())
        self.assertEqual(self.app.engine.stroke_reversal_window, 3.0)
        self.assertEqual(self.app.engine.volume_fall_seconds, 1.5)

    def test_controls_sit_in_volume_response_panel(self):
        panel = self.app.volume_response_bar.master
        labels = [str(w.cget("text")) for w in panel.winfo_children()
                  if w.winfo_class() == "TLabel"]
        for name, label in self.FIELDS:
            with self.subTest(name=name):
                self.assertIn(label, labels)
                spins = [w for w in panel.winfo_children() if w.winfo_class() == "TSpinbox"
                         and str(w.cget("textvariable")) == str(getattr(self.app, name))]
                self.assertEqual(len(spins), 1)


if __name__ == "__main__":
    unittest.main()
