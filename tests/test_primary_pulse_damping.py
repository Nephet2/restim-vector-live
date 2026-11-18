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
