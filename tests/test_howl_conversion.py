import math
import unittest
from vector1a.howl_conversion import LiveConversion, positional, dynamic


class HowlConversionTests(unittest.TestCase):
    def test_profiles_satisfy_foc_domain(self):
        for i in range(101):
            for width in (0, .35, 1):
                profiles = (positional(i/100, width),
                            dynamic(.7, .4, i/100, 1-i/100, width))
                for values in profiles:
                    self.assertTrue(all(math.isfinite(x) and 0 <= x <= 1 for x in values))
                    self.assertAlmostEqual(max(values), 1)
                    self.assertGreaterEqual(sum(values), 2-1e-12)

    def test_idle_decays_to_silence_and_time_jump_resets(self):
        for mode in ('Howl Positional', 'Howl Dynamic'):
            converter = LiveConversion()
            converter.sample(0, 0, mode)
            frame = converter.sample(.02, .1, mode)
            self.assertGreater(frame.volume, 0)
            for i in range(1, 60):
                frame = converter.sample(.02+i*.02, .1, mode)
            self.assertEqual(frame.volume, 0)
            self.assertEqual(converter.sample(5, 1, mode).volume, 0)

    def test_frequency_direction_and_dynamic_panning(self):
        left = dynamic(.7, .4, 0, 0, 1)
        right = dynamic(.7, .4, 1, 1, 1)
        self.assertGreater(left[0], left[1])
        self.assertGreater(right[1], right[0])
        self.assertEqual(dynamic(.7, .4, 0, 1, 0)[0],
                         dynamic(.7, .4, 0, 1, 0)[1])

    def test_bad_inputs_are_bounded(self):
        converter = LiveConversion()
        for i, pos in enumerate((float('nan'), float('inf'), -5, 9)):
            frame = converter.sample(i*.02, pos, 'Howl Dynamic')
            self.assertTrue(0 <= frame.volume <= 1)
            self.assertTrue(0 <= frame.frequency <= 1)

    def test_amplitude_scaling_and_neutral_defaults(self):
        def frame(**kwargs):
            converter = LiveConversion()
            converter.sample(0, .3, 'Howl Dynamic', **kwargs)
            return converter.sample(.02, .4, 'Howl Dynamic', **kwargs)
        default = frame()
        self.assertEqual(default, frame(balance_a=.5, balance_b=.5, scaling=1, strength=1))
        self.assertEqual(frame(scaling=0).volume, 0)
        self.assertLess(frame(scaling=.5).volume, default.volume)
        self.assertNotEqual(frame(balance_a=0, balance_b=1).electrodes, default.electrodes)

    def test_zero_positional_strength_centres_positional_mode(self):
        converter = LiveConversion()
        converter.sample(0, .7, 'Howl Positional', strength=0)
        frame = converter.sample(.02, .8, 'Howl Positional', strength=0)
        for actual, expected in zip(frame.electrodes, positional(.5)):
            self.assertAlmostEqual(actual, expected)

    def test_matched_volume_is_independent_of_spatial_mode(self):
        baseline, switching = LiveConversion(), LiveConversion()
        for i in range(100):
            position = .5 + .4*math.sin(i*.08)
            expected = baseline.sample(i*.02, position, 'Howl Positional')
            mode = ('Howl Positional', 'Howl Dynamic', 'Moving focus', 'Depth spread')[i//25]
            actual = switching.sample(i*.02, position, mode)
            self.assertAlmostEqual(actual.matched_volume, expected.matched_volume)
            self.assertTrue(0 <= actual.matched_volume <= 1)


if __name__ == '__main__':
    unittest.main()
