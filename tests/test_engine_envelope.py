import math
import unittest

from vector1a.engine import VectorEngine
from vector1a.envelope import EnvelopeChain, advance_lookup

DT = 0.02
V0_SETTINGS = {"tau_attack": 0.1, "tau_release": 0.5, "jerk_limit": 100.0,
               "compensation": "ma+attack"}


def drive(configure=None, seconds=14.0, gap=(8.0, 10.0), lookahead=1.0):
    """1 Hz strokes with an input gap; returns (engine, released samples)."""
    now, released = [0.0], []
    engine = VectorEngine(released.append, rate_hz=50, lookahead_seconds=lookahead,
                          clock=lambda: now[0])
    if configure is not None:
        configure(engine)
    engine.resume()
    phase = 0.0
    for index in range(int(round(seconds / DT))):
        t = index * DT
        now[0] = t
        silent = gap[0] <= t < gap[1]
        if not silent:
            phase += 2.0 * math.pi * DT
        position = 0.1 + 0.8 * (0.5 - 0.5 * math.cos(phase))
        if index == 0:
            engine.rebase_input(position, t)
        if not silent:
            engine.receive_l0(position, 0, t)
        engine.step(t, t)
    return engine, released


def largest_step(values):
    return max(abs(b - a) for a, b in zip(values, values[1:]))


class EngineEnvelopeTests(unittest.TestCase):
    def test_no_envelopes_leaves_released_samples_identical(self):
        _, reference = drive()
        for settings in ({}, {"V0": None, "C0": None}):
            with self.subTest(settings=settings):
                _, released = drive(lambda e: e.configure_envelopes(settings))
                self.assertEqual(released, reference)

    def test_v0_envelope_removes_the_stop_input_step(self):
        _, reference = drive()
        _, released = drive(lambda e: e.configure_envelopes({"V0": V0_SETTINGS}))
        self.assertGreater(largest_step([s.volume for s in reference]), 0.3)
        self.assertLess(largest_step([s.volume for s in released]), 0.02)
        # Pulse commands are untouched when only V0 is enabled.
        self.assertEqual([s.primary_pulse for s in released],
                         [s.primary_pulse for s in reference])
        self.assertTrue(all(s.shifted_primary_pulse is None for s in released))

    def test_released_v0_matches_offline_chain_with_advance(self):
        _, reference = drive()
        _, released = drive(lambda e: e.configure_envelopes({"V0": V0_SETTINGS}))
        chain = EnvelopeChain(DT, axis_range=1.0, **V0_SETTINGS)
        chain.reset(0.0)                  # Resume starts V0 from zero.
        history = [(s.calculated_at, chain.step(s.volume)) for s in reference]
        last = history[-1][0]
        compared = 0
        for sample in released:
            if sample.calculated_at + chain.advance_seconds > last:
                break
            expected, limited = advance_lookup(history, sample.calculated_at,
                                               chain.advance_seconds)
            self.assertFalse(limited)
            self.assertAlmostEqual(sample.volume, expected, places=12)
            compared += 1
        self.assertGreater(compared, 400)

    def test_resume_soft_starts_v0_from_zero(self):
        _, reference = drive()
        _, released = drive(lambda e: e.configure_envelopes(
            {"V0": {"tau_attack": 0.2, "tau_release": 0.5}}))
        self.assertLess(released[0].volume, reference[0].volume)
        self.assertLess(released[0].volume, 0.1)

    def test_pulse_axis_envelope_marks_axis_smoothed_and_keeps_others(self):
        _, reference = drive()
        _, released = drive(lambda e: e.configure_envelopes(
            {"C0": {"tau_attack": 0.05, "tau_release": 0.25, "jerk_limit": 100.0,
                    "compensation": "ma+attack"}}))
        frequencies = [s.shifted_primary_pulse[0] for s in released]
        self.assertGreater(largest_step([s.frequency for s in reference]), 0.3)
        self.assertLess(largest_step(frequencies), 0.03)
        for sample, raw in zip(released, reference):
            self.assertEqual(sample.shifted_primary_pulse[1:], raw.primary_pulse[1:])
            self.assertEqual(sample.primary_pulse_smoothed, (True, False, False, False))
            self.assertEqual(sample.volume, raw.volume)
        low, high = released[0].frequency, released[0].frequency
        self.assertTrue(all(0.0 <= f <= 1.0 for f in frequencies), (low, high))

    def test_status_reports_advance_and_buffer_limit(self):
        engine, _ = drive(lambda e: e.configure_envelopes({"V0": V0_SETTINGS}))
        status = engine.envelope_status()
        self.assertEqual(set(status), {"V0"})
        self.assertAlmostEqual(status["V0"]["advance_seconds"], 0.61)
        self.assertEqual(status["V0"]["window_samples"], 18)
        self.assertFalse(status["V0"]["buffer_limited"])
        short, _ = drive(lambda e: e.configure_envelopes({"V0": V0_SETTINGS}),
                         lookahead=0.2)
        self.assertTrue(short.envelope_status()["V0"]["buffer_limited"])

    def test_stop_and_neutral_still_release_nothing(self):
        engine, released = drive(lambda e: e.configure_envelopes({"V0": V0_SETTINGS}))
        count = len(released)
        engine.stop()
        engine.step(20.0, 20.0)
        engine.neutral()
        engine.step(20.02, 20.02)
        self.assertEqual(len(released), count)
        self.assertEqual(engine.control_state()["buffer_fill"], 0)

    def test_invalid_settings_raise_and_keep_previous(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.configure_envelopes({"V0": V0_SETTINGS})
        for settings in ({"V0": {"tau_attack": -1.0}}, {"X9": {"tau_attack": 0.1}},
                         {"V0": {"tau_release": 2.5}},          # V0 release cap: 2 s.
                         {"C0": {"tau_release": 31.0}},
                         {"P1": {"compensation": "release"}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                engine.configure_envelopes(settings)
        self.assertEqual(set(engine.envelope_status()), {"V0"})


if __name__ == "__main__":
    unittest.main()
