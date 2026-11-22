import math
from types import SimpleNamespace
import unittest

from vector1a.engine import VectorEngine
from vector1a.output_composer import OutputComposer


class PrimaryPulseDampingTests(unittest.TestCase):
    def setUp(self):
        self.engine = VectorEngine(lambda sample: None)
        self.composer = OutputComposer(self.engine, None, None, None, None, None)
        self.config = SimpleNamespace(frequency_damping=0.0, pulse_frequency_damping=1.0,
                                      pulse_rise_damping=0.0, pulse_width_damping=0.0)

    def test_only_selected_axis_follows_time_constant(self):
        start = (.2, .4, .2, .2)
        target = (.7, .9, .6, .35)
        self.assertEqual(self.composer._damp_primary_pulse(start, 10, self.config, False), start)
        for tick in range(1, 11):
            result = self.composer._damp_primary_pulse(target, 10 + tick / 10, self.config, False)
        self.assertEqual((result[0], *result[2:]), (target[0], *target[2:]))
        self.assertAlmostEqual(result[1], .4 + .5 * (1 - math.exp(-1)))

    def test_tightening_range_and_reset_take_effect_immediately(self):
        self.composer._damp_primary_pulse((.2, .9, .2, .2), 10, self.config, False)
        self.engine.pulse_frequency_max = .7
        target = (.7, .5, .6, .35)
        result = self.composer._damp_primary_pulse(target, 10.02, self.config, False)
        self.assertEqual(result[1], .7)
        self.composer.reset_pulse_damping()
        self.assertEqual(self.composer._damp_primary_pulse(target, 11, self.config, False), target)

    def test_zero_damping_bypasses_and_tracks_latest_command(self):
        start = (.2, .4, .2, .2)
        target = (.7, .9, .6, .35)
        self.composer._damp_primary_pulse(start, 10, self.config, False)
        self.config.pulse_frequency_damping = 0
        self.assertEqual(self.composer._damp_primary_pulse(target, 10.02, self.config, False), target)
        self.config.pulse_frequency_damping = 1
        self.assertEqual(self.composer._damp_primary_pulse(target, 10.04, self.config, False), target)

    def test_smoothing_uses_existing_queue_and_does_not_stack_damping(self):
        sent = []
        engine = VectorEngine(sent.append, rate_hz=50, lookahead_seconds=3.0)
        engine.pulse_smoothing_seconds = 5.0
        engine._calculate_pulse_frequency = (
            lambda when, *_: .5 + .1 * sum(when >= edge for edge in (4.0, 5.0, 6.0)))
        engine.resume()
        for tick in range(601):
            engine.step(tick / 50)

        ramp = [sample for sample in sent if 3.9 <= sample.calculated_at <= 6.1]
        values = [sample.shifted_primary_pulse[1] for sample in ramp]
        self.assertTrue(all(left < right for left, right in zip(values, values[1:])))
        midpoint = next(sample for sample in ramp if sample.calculated_at == 5.0)
        self.assertEqual(midpoint.due_at, 8.0)
        self.assertAlmostEqual(midpoint.shifted_primary_pulse[1], .65, places=2)
        self.assertEqual(midpoint.primary_pulse_smoothed, (True,) * 4)

        start = (.2, .5, .2, .2)
        self.composer._damp_primary_pulse(start, 7.98, self.config, False)
        target = midpoint.shifted_primary_pulse
        self.assertEqual(self.composer._damp_primary_pulse(
            target, 8.0, self.config, False, midpoint.primary_pulse_smoothed), target)
        howl = self.composer._damp_primary_pulse(
            start, 8.02, self.config, True, midpoint.primary_pulse_smoothed)
        self.assertGreater(howl[1], start[1])

        engine.pulse_smoothing_seconds = 0.0
        engine.step(12.02)
        self.assertIsNone(sent[-1].shifted_primary_pulse)
