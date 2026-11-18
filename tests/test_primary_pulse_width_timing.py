import unittest
from dataclasses import replace

from vector1a.engine import OutputSample, VectorEngine
from vector1a.motion import MotionMode, SegmentState


class PrimaryPulseTimingTests(unittest.TestCase):
    def setUp(self):
        self.engine = VectorEngine(lambda sample: None)
        self.engine._primary_pulse_history.extend(
            (10 + i / 4, (i / 4,) * 4) for i in range(5))
        for axis in ("frequency", "pulse_frequency", "pulse_rise", "pulse_width"):
            setattr(self.engine, f"{axis}_min", 0.)
            setattr(self.engine, f"{axis}_max", 1.)
        self.sample = OutputSample(
            1, 10.5, 11.0, .5, .5, 50., .3, .6, .2, MotionMode.CIRCULAR,
            .7, .6, .4, .5, .2, .5, .1)

    def shifted(self, milliseconds, degrees=0, sample=None, axis=3):
        settings = [(0., 0.)] * 4
        settings[axis] = (milliseconds, degrees)
        self.engine.configure_primary_pulse_timing(settings)
        return self.engine._shift_primary_pulse(sample or self.sample, self.sample.primary_pulse)

    def test_offset_interpolates_and_keeps_the_original_sample(self):
        self.assertIs(self.shifted(0), self.sample)
        for axis in range(4):
            for offset, expected in ((-125, .625), (125, .375)):
                result = self.shifted(offset, axis=axis)
                values = list(self.sample.primary_pulse)
                values[axis] = expected
                self.assertEqual(result.shifted_primary_pulse, tuple(values))
                self.assertEqual(replace(result, shifted_primary_pulse=None), self.sample)

    def test_phase_scales_to_the_completed_stroke_and_adds_to_offset(self):
        for duration, expected in ((.5, .375), (1., .25)):
            stroke = SegmentState(2, 10., 10. + duration, .1, .9)
            sample = replace(self.sample, timing_stroke=stroke)
            self.assertAlmostEqual(self.shifted(0, 90, sample).shifted_primary_pulse[3], expected)
        self.assertAlmostEqual(self.shifted(-125, 90, sample).shifted_primary_pulse[3], .375)

    def test_missing_stroke_and_buffer_boundaries(self):
        self.assertAlmostEqual(self.shifted(125, 180).shifted_primary_pulse[3], .375)
        self.assertIn("waiting for stroke end", self.engine.primary_pulse_timing_status()[3])
        sample = replace(self.sample, calculated_at=10.8)
        self.assertAlmostEqual(self.shifted(-500, sample=sample).shifted_primary_pulse[3], 1.)
        self.assertIn("buffer limited", self.engine.primary_pulse_timing_status()[3])
        self.engine.rebase_input(.5, 11.)
        self.assertIs(self.shifted(-500), self.sample)
