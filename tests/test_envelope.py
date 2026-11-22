import math
import random
import unittest

from vector1a.envelope import (AttackRelease, EnvelopeChain, JerkLimiter,
                               advance_lookup, compensation_seconds,
                               jerk_window_samples)

DT = 0.02


def run(stage, values):
    return [stage.step(value) for value in values]


class AttackReleaseTests(unittest.TestCase):
    def test_attack_covers_63_percent_in_one_time_constant(self):
        stage = AttackRelease(0.1, 0.5)
        stage.reset(0.0)
        for _ in range(5):          # 5 x 20 ms = 0.1 s
            value = stage.step(1.0, DT)
        self.assertAlmostEqual(value, 1 - math.exp(-1))

    def test_release_time_constant_is_used_when_target_is_below(self):
        stage = AttackRelease(0.1, 0.5)
        stage.reset(1.0)
        for _ in range(25):         # 0.5 s
            value = stage.step(0.0, DT)
        self.assertAlmostEqual(value, math.exp(-1))

    def test_direction_is_chosen_per_sample_against_filtered_value(self):
        stage = AttackRelease(0.02, 1.0)
        stage.reset(0.5)
        risen = stage.step(0.9, DT)                      # Attack: 63% in one tau.
        self.assertAlmostEqual(risen, 0.5 + 0.4 * (1 - math.exp(-1)))
        # 0.6 is above the input's start but below the filtered value: release.
        held = stage.step(0.6, DT)
        self.assertAlmostEqual(held, risen - (risen - 0.6) * (1 - math.exp(-DT / 1.0)))

    def test_zero_time_constant_passes_target_through(self):
        stage = AttackRelease(0.0, 0.0)
        stage.reset(0.2)
        self.assertEqual(stage.step(0.7, DT), 0.7)
        self.assertEqual(stage.step(0.1, DT), 0.1)

    def test_first_sample_without_reset_starts_at_target(self):
        stage = AttackRelease(0.5, 0.5)
        self.assertEqual(stage.step(0.4, DT), 0.4)

    def test_split_interval_matches_single_interval(self):
        a, b = AttackRelease(0.1, 0.3), AttackRelease(0.1, 0.3)
        a.reset(0.0)
        b.reset(0.0)
        b.step(1.0, DT / 2)
        self.assertAlmostEqual(a.step(1.0, DT), b.step(1.0, DT / 2))

    def test_non_positive_interval_does_not_move(self):
        stage = AttackRelease(0.1, 0.1)
        stage.reset(0.3)
        self.assertEqual(stage.step(0.9, 0.0), 0.3)
        self.assertEqual(stage.step(0.9, -0.5), 0.3)


class JerkLimiterTests(unittest.TestCase):
    def test_window_bounds_third_difference_for_axis_range(self):
        self.assertEqual(jerk_window_samples(100.0, 1.0, DT), 18)
        self.assertEqual(jerk_window_samples(500.0, 1.0, DT), 10)
        self.assertEqual(jerk_window_samples(2000.0, 1.0, DT), 7)
        self.assertLess(jerk_window_samples(100.0, 0.35, DT),
                        jerk_window_samples(100.0, 1.0, DT))
        self.assertEqual(jerk_window_samples(None, 1.0, DT), 1)
        self.assertEqual(jerk_window_samples(0.0, 1.0, DT), 1)

    def test_third_difference_never_exceeds_limit_for_inputs_in_range(self):
        rng = random.Random(85)
        for jerk, low, high in ((100.0, 0.0, 1.0), (500.0, 0.1, 0.45), (20.0, 0.4, 0.95)):
            n = jerk_window_samples(jerk, high - low, DT)
            stage = JerkLimiter(n)
            stage.reset(low)
            values = []
            for _ in range(1500):
                # Mix of hard steps, held levels and noise across the range.
                choice = rng.random()
                values.append(high if choice < .3 else low if choice < .6
                              else rng.uniform(low, high))
            out = run(stage, values)
            worst = max(abs(out[i] - 3 * out[i - 1] + 3 * out[i - 2] - out[i - 3])
                        for i in range(3, len(out))) / DT ** 3
            self.assertLessEqual(worst, jerk * (1 + 1e-9), (jerk, low, high))

    def test_delay_is_three_halves_of_window_minus_one_samples(self):
        n = 10
        stage = JerkLimiter(n)
        self.assertEqual(stage.delay_samples, 3 * (n - 1) / 2)
        stage.reset(0.0)
        ramp = [i * 0.001 for i in range(200)]
        out = run(stage, ramp)
        for i in range(100, 200):
            self.assertAlmostEqual(out[i], (i - stage.delay_samples) * 0.001)

    def test_single_sample_window_is_identity(self):
        stage = JerkLimiter(1)
        self.assertEqual(run(stage, [0.1, 0.9, 0.3]), [0.1, 0.9, 0.3])

    def test_first_sample_without_reset_fills_history(self):
        stage = JerkLimiter(5)
        self.assertEqual(stage.step(0.6), 0.6)
        self.assertAlmostEqual(stage.step(0.6), 0.6)


class AdvanceTests(unittest.TestCase):
    history = [(10.00, 0.2), (10.02, 0.4), (10.04, 0.8)]

    def test_fractional_offset_uses_linear_interpolation(self):
        value, limited = advance_lookup(self.history, 10.00, 0.03)
        self.assertAlmostEqual(value, 0.6)
        self.assertFalse(limited)

    def test_exact_sample_and_zero_advance(self):
        self.assertEqual(advance_lookup(self.history, 10.02, 0.0), (0.4, False))

    def test_beyond_newest_sample_is_clamped_and_reported(self):
        value, limited = advance_lookup(self.history, 10.02, 0.5)
        self.assertEqual(value, 0.8)
        self.assertTrue(limited)

    def test_before_oldest_sample_uses_oldest(self):
        self.assertEqual(advance_lookup(self.history, 9.0, 0.0), (0.2, True))

    def test_empty_history_has_no_value(self):
        self.assertEqual(advance_lookup([], 10.0, 0.1), (None, True))

    def test_compensation_modes(self):
        self.assertEqual(compensation_seconds("none", 10, DT, 0.1), 0.0)
        self.assertAlmostEqual(compensation_seconds("ma", 10, DT, 0.1), 0.27)
        self.assertAlmostEqual(compensation_seconds("ma+attack", 10, DT, 0.1), 0.37)
        self.assertAlmostEqual(compensation_seconds("ma+attack", 1, DT, 0.0), 0.0)
        with self.assertRaises(ValueError):
            compensation_seconds("release", 10, DT, 0.1)


class EnvelopeChainTests(unittest.TestCase):
    def test_all_stages_off_is_exact_identity(self):
        chain = EnvelopeChain(DT, axis_range=1.0)
        values = [0.0, 0.31, 1.0, 0.123456789, 0.5]
        self.assertEqual([chain.step(v) for v in values], values)
        self.assertEqual(chain.advance_seconds, 0.0)

    def test_output_never_leaves_input_range(self):
        rng = random.Random(7)
        chain = EnvelopeChain(DT, axis_range=0.35, tau_attack=0.05, tau_release=0.5,
                              jerk_limit=100.0)
        values = [rng.choice((0.10, 0.45, rng.uniform(0.10, 0.45))) for _ in range(800)]
        out = [chain.step(v) for v in values]
        self.assertGreaterEqual(min(out), 0.10 - 1e-12)
        self.assertLessEqual(max(out), 0.45 + 1e-12)

    def test_chain_matches_stages_in_order_and_reports_advance(self):
        chain = EnvelopeChain(DT, axis_range=1.0, tau_attack=0.1, tau_release=0.5,
                              jerk_limit=500.0, compensation="ma+attack")
        ar, jl = AttackRelease(0.1, 0.5), JerkLimiter(jerk_window_samples(500.0, 1.0, DT))
        for value in (0.0, 1.0, 1.0, 0.2, 0.9, 0.0):
            self.assertAlmostEqual(chain.step(value), jl.step(ar.step(value, DT)))
        self.assertAlmostEqual(chain.advance_seconds, 0.27 + 0.1)

    def test_reset_clears_every_stage(self):
        chain = EnvelopeChain(DT, axis_range=1.0, tau_attack=0.5, tau_release=0.5,
                              jerk_limit=100.0)
        for _ in range(50):
            chain.step(1.0)
        chain.reset()
        self.assertEqual(chain.step(0.25), 0.25)

    def test_invalid_settings_are_rejected(self):
        for kwargs in ({"tau_attack": -0.1}, {"tau_release": math.nan},
                       {"jerk_limit": -5.0}, {"compensation": "bogus"}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                EnvelopeChain(DT, axis_range=1.0, **kwargs)
        with self.assertRaises(ValueError):
            EnvelopeChain(0.0, axis_range=1.0)


if __name__ == "__main__":
    unittest.main()
