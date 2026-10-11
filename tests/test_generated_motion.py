import time
import unittest

from vector1a.generated_motion import GeneratedMotionSource, MotionPlan


class GeneratedMotionTests(unittest.TestCase):
    def test_plan_validation_rejects_unbounded_or_tiny_travel(self):
        with self.assertRaises(ValueError):
            MotionPlan.validated({"pattern": "sine", "minimum": 0.2, "maximum": 0.25,
                                  "stroke_duration_ms": 500, "transition_seconds": 5,
                                  "duration_seconds": 60})
        with self.assertRaises(ValueError):
            MotionPlan.validated({"pattern": "random", "minimum": 0.2, "maximum": 0.8,
                                  "stroke_duration_ms": 500, "transition_seconds": 5,
                                  "duration_seconds": 60})

    def test_fixed_cadence_source_stays_inside_plan_and_can_hold(self):
        samples = []
        source = GeneratedMotionSource(lambda value, _interval, _now: samples.append(value), cadence_hz=50)
        try:
            plan = MotionPlan.validated({"pattern": "triangle", "minimum": 0.0, "maximum": 1.0,
                                         "stroke_duration_ms": 125, "transition_seconds": 1,
                                         "duration_seconds": 30})
            source.apply(plan, 0.5)
            time.sleep(0.09)
            self.assertGreaterEqual(len(samples), 2)
            self.assertTrue(all(0.0 <= sample <= 1.0 for sample in samples))
            source.hold()
            held_start = len(samples)
            deadline = time.monotonic() + 1.0
            while len(samples) < held_start + 3 and time.monotonic() < deadline:
                time.sleep(0.005)
            held = samples[held_start:]
            self.assertGreaterEqual(len(held), 3)
            self.assertTrue(held and max(held) - min(held) < 1e-9)
            self.assertEqual(source.authored()["source"], "authored_tcode")
        finally:
            source.close()

    def test_review_horizon_does_not_hold_or_flatten_motion(self):
        samples = []
        source = GeneratedMotionSource(lambda value, _interval, _now: samples.append(value), cadence_hz=50)
        try:
            # Construct directly to make the horizon short enough for a focused test;
            # the public validator still enforces its 30-second minimum.
            plan = MotionPlan(pattern="triangle", minimum=0.1, maximum=0.9,
                              stroke_duration_ms=125, transition_seconds=0.01,
                              duration_seconds=0.04, reason="test horizon")
            source.apply(plan, 0.5)
            time.sleep(0.13)
            state = source.snapshot()
            self.assertTrue(state["review_due"])
            self.assertFalse(state["held"])
            tail = samples[-4:]
            self.assertGreater(len(tail), 2)
            self.assertGreater(max(tail) - min(tail), 0.05)
        finally:
            source.close()

    def test_transition_bounds_expand_smoothly_from_starting_position(self):
        source = GeneratedMotionSource(lambda *_args: None, cadence_hz=50)
        try:
            plan = MotionPlan("breathing", 0.35, 0.85, 2400, 8.0, 120, "test")
            source.apply(plan, 0.50)
            started = source._plan_started_at
            self.assertEqual(source.stroke_bounds(started), (0.5, 0.5))
            low, high = source.stroke_bounds(started + 4.0)
            self.assertAlmostEqual(low, 0.425)
            self.assertAlmostEqual(high, 0.675)
            self.assertEqual(source.stroke_bounds(started + 8.0), (0.35, 0.85))
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
