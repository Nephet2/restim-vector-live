import math
import unittest
from vector1a.passage import PassagePlan, PassageController
from vector1a.generated_motion import MotionPlan


class Clock:
    def __init__(self): self.now = 0.0
    def __call__(self): return self.now
    def advance(self, controller, seconds):
        for _ in range(round(seconds * 50)):
            self.now += .02
            controller.factors_now()


class PassageTests(unittest.TestCase):
    def test_invalid_values_never_become_output(self):
        for values in ({'floor': float('nan')}, {'peak': float('inf')}, {'floor': -.1},
                       {'peak': 1.01}, {'floor': .8, 'peak': .4}, {'hold_seconds': True},
                       {'build_seconds': 1}, {'clock': 'preview'}, {'target': 'secondary'},
                       {'build_seconds': 0, 'hold_seconds': 0, 'release_seconds': 0}, {'unknown': 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                PassagePlan.validated(values)

    def test_preview_phase_boundaries(self):
        p = PassagePlan.validated(dict(build_seconds=20, hold_seconds=10, release_seconds=20, floor=.3, peak=.8))
        self.assertEqual(p.at(0), ('build', .3))
        self.assertEqual(p.at(20), ('hold', .8))
        self.assertEqual(p.at(30), ('release', .8))
        self.assertEqual(p.at(50), ('complete', .3))
        self.assertTrue(all(.3 <= v['factor'] <= .8 for v in p.preview()))

    def test_hold_resume_completion_latch_and_restore_are_continuous(self):
        clock = Clock(); c = PassageController(clock)
        c.apply(PassagePlan(build_seconds=10, hold_seconds=5, release_seconds=10, floor=.4))
        self.assertEqual(c.factors_now(), (1, 1))
        clock.advance(c, 5)
        c.hold(); factors = c.factors_now(); elapsed = c.elapsed
        clock.advance(c, 30)
        self.assertEqual(factors, c.factors_now()); self.assertEqual(c.elapsed, elapsed)
        c.resume(); clock.advance(c, 40)
        self.assertAlmostEqual(c.factors_now()[0], .4)
        self.assertEqual(c.phase, 'complete')
        self.assertEqual(c.factors_now()[1], 1)
        c.restore(2); self.assertAlmostEqual(c.factors_now()[0], .4)
        clock.advance(c, 3)
        self.assertEqual(c.factors_now(), (1, 1)); self.assertFalse(c.snapshot()['active'])

    def test_replacement_and_lane_change_never_jump(self):
        clock = Clock(); c = PassageController(clock)
        c.apply(PassagePlan(build_seconds=0, hold_seconds=30, release_seconds=0, floor=.2, peak=.2, target='both'))
        clock.advance(c, 8)
        old = c.factors_now()
        c.apply(PassagePlan(target='primary'))
        self.assertEqual(c.factors_now(), old)
        clock.advance(c, .02)
        new = c.factors_now()
        self.assertLessEqual(abs(new[0]-old[0]), .02/5 + 1e-9)
        self.assertLessEqual(abs(new[1]-old[1]), .02/5 + 1e-9)

    def test_reset_discards_plan(self):
        c = PassageController(); c.apply(PassagePlan()); c.hold(); c.reset()
        self.assertEqual(c.factors_now(), (1, 1)); self.assertFalse(c.snapshot()['active'])

    def test_media_pause_loss_seek_and_explicit_reanchor(self):
        clock = Clock()
        t = dict(valid=True, playing=True, position_seconds=10, source='film-a')
        c = PassageController(clock, lambda: dict(t))
        c.apply(PassagePlan(clock='media'))
        for _ in range(100):
            clock.now += .02; t['position_seconds'] += .02; c.factors_now()
        before = c.elapsed
        t['playing'] = False; clock.advance(c, 8)
        self.assertAlmostEqual(c.elapsed, before)
        t['valid'] = False; clock.advance(c, 8)
        self.assertAlmostEqual(c.elapsed, before)
        t.update(valid=True, playing=True)
        c.factors_now()
        t['position_seconds'] += 30; clock.advance(c, .02)
        self.assertTrue(c.held); self.assertIn('seek', c.reason)
        c.resume(); clock.advance(c, .02)
        t['position_seconds'] += .02; clock.advance(c, .02)
        self.assertFalse(c.held); self.assertGreater(c.elapsed, before)
        t['source'] = 'film-b'; clock.advance(c, .02)
        self.assertTrue(c.held)

    def test_media_requires_real_transport_not_manual_preview(self):
        c = PassageController(transport=lambda: {'valid': False})
        with self.assertRaises(ValueError): c.apply(PassagePlan(clock='media'))

    def test_generated_variation_retains_limits_and_changes_depth_and_pace(self):
        p = MotionPlan(variation=1)
        spans = []
        for i in range(10000):
            t = i*.02; lo, hi = p.bounds_at(t)
            self.assertGreaterEqual(lo, p.minimum-1e-9); self.assertLessEqual(hi, p.maximum+1e-9)
            value = lo + (hi-lo)*(1+math.sin(p.phase_at(t)*2*math.pi))/2
            self.assertTrue(lo <= value <= hi)
            spans.append(hi-lo)
        self.assertGreater(max(spans)-min(spans), .2)
        for base in (125, 750, 3000):
            p = MotionPlan(stroke_duration_ms=base, variation=1)
            for i in range(1000):
                t = i*.02
                frequency = (p.phase_at(t+.001)-p.phase_at(t))/.001
                stroke_ms = 1000/(2*frequency)
                self.assertTrue(124.999 <= stroke_ms <= 3000.001)
        p = MotionPlan()
        for t in (0, 1, 7.5, 90):
            self.assertEqual(p.bounds_at(t), (.2, .8))
            self.assertAlmostEqual(p.phase_at(t), t/1.5)


if __name__ == '__main__': unittest.main()
