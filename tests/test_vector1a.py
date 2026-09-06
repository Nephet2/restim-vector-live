import math
import unittest

from vector1a.engine import VectorEngine
from vector1a.motion import MotionCalculator, MotionMode, MotionParameters, SegmentState
from vector1a.tcode import format_command, parse_command, parse_message


class TCodeTests(unittest.TestCase):
    def test_restim_compatible_parse_and_format(self):
        cmd = parse_command("L07500I200")
        self.assertEqual((cmd.axis, cmd.value, cmd.interval_ms), ("L0", 0.75, 200))
        self.assertEqual(format_command("V0", 0.2), "V02000")
        self.assertEqual(len(parse_message("L05000 L17500\nV02000")), 3)


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.segment = SegmentState(1, 10.0, 11.0, 0.0, 1.0)
        self.params = MotionParameters(0.1, 50.0, 0.0)
        self.calc = MotionCalculator(seed=1)

    def test_circular_matches_upstream_geometry(self):
        alpha, beta, position, speed = self.calc.calculate(
            MotionMode.CIRCULAR, self.segment, 10.5, self.params
        )
        self.assertAlmostEqual(position, 0.5)
        self.assertAlmostEqual(speed, 50.0)
        self.assertAlmostEqual(alpha, 0.5, places=6)
        self.assertAlmostEqual(beta, 1.0, places=6)

    def test_four_modes_have_distinct_trajectories(self):
        points = {}
        for mode in MotionMode:
            samples = [self.calc.calculate(mode, self.segment, 10.0 + p, self.params)[:2]
                       for p in (0.2, 0.5, 0.8)]
            points[mode] = tuple(round(v, 5) for sample in samples for v in sample)
        self.assertEqual(len(set(points.values())), 4)

    def test_diagonal_modes_use_opposite_restim_alignment(self):
        left = self.calc.calculate(MotionMode.TOP_LEFT_BOTTOM_RIGHT, self.segment, 10.25, self.params)
        right = self.calc.calculate(MotionMode.TOP_RIGHT_BOTTOM_LEFT, self.segment, 10.25, self.params)
        self.assertAlmostEqual(left[0], right[0])
        self.assertAlmostEqual(left[1], 1.0 - right[1])

    def test_diagonal_modes_follow_smooth_rfp_arc(self):
        mode = MotionMode.TOP_LEFT_BOTTOM_RIGHT
        actual = [self.calc.calculate(mode, self.segment, 10.0 + p, self.params)[:2]
                  for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
        expected = []
        for p in (0.0, 0.25, 0.5, 0.75, 1.0):
            theta = 3.0 * math.pi / 2.0 - p * 4.0 * math.pi / 3.0
            alpha = 0.5 + 0.5 * math.cos(theta)
            beta = 0.5 + 0.5 * math.sin(theta)
            radians = math.radians(-30.0)
            x = alpha - 0.5
            y = beta - 0.5
            expected.append((0.5 + x * math.cos(radians) - y * math.sin(radians),
                             0.5 + x * math.sin(radians) + y * math.cos(radians)))
        for point, target in zip(actual, expected):
            self.assertAlmostEqual(point[0], target[0])
            self.assertAlmostEqual(point[1], target[1])

    def test_restim_original_ends_at_target(self):
        alpha, beta, *_ = self.calc.calculate(
            MotionMode.RESTIM_ORIGINAL, self.segment, 11.0, self.params
        )
        self.assertAlmostEqual(alpha, 1.0)
        self.assertAlmostEqual(beta, 0.5)

    def test_spatial_response_changes_three_phase_geometry_and_output_l0(self):
        linear = self.calc.calculate(
            MotionMode.CIRCULAR, self.segment, 10.25, self.params)
        shaped = self.calc.calculate(
            MotionMode.CIRCULAR, self.segment, 10.25, self.params,
            "S-curve", 1.0)
        self.assertAlmostEqual(linear[2], .25)
        self.assertAlmostEqual(shaped[2], .15625)
        self.assertNotAlmostEqual(linear[0], shaped[0])
        self.assertNotAlmostEqual(linear[1], shaped[1])

    def test_spatial_response_preserves_motion_endpoints(self):
        for at_time, expected in ((10.0, 0.0), (11.0, 1.0)):
            alpha, beta, position, _ = self.calc.calculate(
                MotionMode.CIRCULAR, self.segment, at_time, self.params,
                "Endpoint emphasis", 1.0)
            self.assertAlmostEqual(position, expected)
            self.assertTrue(0.0 <= alpha <= 1.0)
            self.assertTrue(0.0 <= beta <= 1.0)


class QueueTests(unittest.TestCase):
    def test_variation_depth_fades_with_speed_and_can_be_disabled(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.variation_fade_seconds = .1
        self.assertEqual(engine._update_variation_depth(0.0, 0.0), 0.0)
        active = engine._update_variation_depth(1.0, 100.0)
        self.assertGreater(active, .99)
        fading = engine._update_variation_depth(1.1, 0.0)
        self.assertGreater(fading, 0.0)
        self.assertLess(fading, active)
        engine.speed_linked_variation = False
        self.assertGreater(engine._update_variation_depth(2.0, 0.0), .99)

    def test_jitter_is_optional_bounded_and_does_not_change_raw_l0(self):
        sent = []
        engine = VectorEngine(sent.append, rate_hz=50, lookahead_seconds=.1,
                              clock=lambda: 0.0)
        engine.configure(rate_hz=50, lookahead_seconds=.1, volume=.7,
                         mode=MotionMode.CIRCULAR, params=MotionParameters(),
                         jitter_enabled=True, jitter_amplitude=.03,
                         jitter_cycle_seconds=1.0)
        engine.resume()
        engine.receive_l0(.5, received_at=0.0)
        engine.step(0.0, .1)
        self.assertEqual(len(sent), 1)
        self.assertAlmostEqual(sent[0].raw_l0, .5)
        self.assertLessEqual(abs(sent[0].output_l0 - .5), .03)

    def test_reversal_rewrites_buffered_restim_original_as_one_stroke(self):
        engine = VectorEngine(lambda sample: None, lookahead_seconds=1.0, clock=lambda: 0.0)
        engine.mode = MotionMode.RESTIM_ORIGINAL
        engine.resume()
        # Establish upward motion and queue samples across it.
        engine.receive_l0(0.0, 0, 0.00)
        engine.receive_l0(0.5, 0, 0.10)
        engine.step(0.05, 0.05)
        engine.step(0.10, 0.10)
        # The downward sample reveals that 1.0 at t=.20 was the endpoint.
        engine.receive_l0(1.0, 0, 0.20)
        engine.step(0.20, 0.20)
        engine.receive_l0(0.9, 0, 0.30)
        queued = {round(item[2].calculated_at, 2): item[2] for item in engine._queue}
        # Mid-stroke beta must bow away from 0.5; it is no longer a tiny arc per sample.
        self.assertNotAlmostEqual(queued[0.10].beta, 0.5)
        self.assertAlmostEqual(queued[0.20].alpha, 1.0)

    def test_reversal_never_rewrites_diagonal_samples_as_restim_arcs(self):
        engine = VectorEngine(lambda sample: None, lookahead_seconds=1.0, clock=lambda: 0.0)
        engine.mode = MotionMode.TOP_LEFT_BOTTOM_RIGHT
        engine.resume()
        engine.receive_l0(0.0, 0, 0.00)
        engine.receive_l0(0.5, 0, 0.10)
        engine.step(0.10, 0.10)
        before = engine._queue[0][2]
        engine.receive_l0(1.0, 0, 0.20)
        engine.receive_l0(0.9, 0, 0.30)  # reversal
        after = engine._queue[0][2]
        self.assertEqual(after.mode, MotionMode.TOP_LEFT_BOTTOM_RIGHT)
        self.assertEqual((after.alpha, after.beta), (before.alpha, before.beta))
        self.assertEqual(after.mode, MotionMode.TOP_LEFT_BOTTOM_RIGHT)

    def test_reversal_marks_buffered_samples_without_changing_due_times(self):
        engine = VectorEngine(lambda sample: None, lookahead_seconds=1.0,
                              clock=lambda: 0.0)
        engine.resume()
        engine.receive_l0(0.0, 0, 0.00)
        engine.receive_l0(0.5, 0, 0.10)
        engine.step(0.10, 0.10)
        engine.receive_l0(1.0, 0, 0.20)
        engine.step(0.20, 0.20)
        due_before = [item[2].due_at for item in engine._queue]
        engine.receive_l0(0.9, 0, 0.30)
        queued = {round(item[2].calculated_at, 2): item[2]
                  for item in engine._queue}
        self.assertAlmostEqual(queued[0.20].reversal_distance_seconds, 0.0)
        self.assertAlmostEqual(queued[0.10].reversal_distance_seconds, 0.1)
        self.assertAlmostEqual(queued[0.10].stroke_progress, 0.5)
        self.assertAlmostEqual(queued[0.20].stroke_progress, 1.0)
        self.assertEqual([item[2].due_at for item in engine._queue], due_before)

    def test_later_reversal_does_not_overwrite_earlier_stroke_progress(self):
        engine = VectorEngine(lambda sample: None, lookahead_seconds=2.0,
                              clock=lambda: 0.0)
        engine.resume()
        engine.receive_l0(0.0, 0, 0.00)
        engine.receive_l0(0.5, 0, 0.10)
        engine.step(0.10, 0.10)
        engine.receive_l0(1.0, 0, 0.20)
        engine.step(0.20, 0.20)
        engine.receive_l0(0.5, 0, 0.30)  # completes the first stroke
        first_progress = {round(item[2].calculated_at, 2): item[2].stroke_progress
                          for item in engine._queue}
        engine.step(0.30, 0.30)
        engine.receive_l0(0.0, 0, 0.40)
        engine.receive_l0(0.5, 0, 0.50)  # completes the second stroke
        queued = {round(item[2].calculated_at, 2): item[2]
                  for item in engine._queue}
        self.assertAlmostEqual(queued[0.10].stroke_progress, first_progress[0.10])
        self.assertAlmostEqual(queued[0.20].stroke_progress, first_progress[0.20])
        self.assertAlmostEqual(queued[0.30].stroke_progress, 0.5)

    def test_interval_free_mfp_samples_produce_normalized_stream_speed(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.receive_l0(0.6, 0, 0.02)
        engine.receive_l0(0.7, 0, 0.04)
        self.assertGreater(engine._segment.speed_percent, 90.0)
        self.assertEqual(engine._segment.start_position, 0.6)
        self.assertEqual(engine._segment.end_position, 0.7)

    def test_fifo_preserves_timing_and_order(self):
        now = [0.0]
        sent = []
        engine = VectorEngine(sent.append, rate_hz=50, lookahead_seconds=1.0,
                              clock=lambda: now[0])
        engine.resume()
        engine.receive_l0(1.0, 1000, 0.0)
        for tick in (0.00, 0.02, 0.04):
            engine.step(tick, tick)
        self.assertEqual(sent, [])
        now[0] = 1.04
        engine._release_due(now[0])
        self.assertEqual([sample.sequence for sample in sent], [1, 2, 3])
        self.assertEqual([round(sample.due_at, 2) for sample in sent], [1.0, 1.02, 1.04])
        self.assertTrue(all(math.isclose(sample.due_at - sample.calculated_at, 1.0) for sample in sent))

    def test_mode_switch_does_not_reset_sequence_or_due_times(self):
        sent = []
        engine = VectorEngine(sent.append, lookahead_seconds=1.0, clock=lambda: 0.0)
        engine.resume()
        engine.step(0.0, 0.0)
        engine.mode = MotionMode.TOP_RIGHT_BOTTOM_LEFT
        engine.step(0.02, 0.02)
        self.assertEqual([item[2].sequence for item in engine._queue], [1, 2])
        self.assertEqual([round(item[2].due_at, 2) for item in engine._queue], [1.0, 1.02])

    def test_configured_mode_switch_discards_old_geometry(self):
        engine = VectorEngine(lambda sample: None, lookahead_seconds=1.0, clock=lambda: 0.0)
        engine.resume()
        engine.step(0.0, 0.0)
        self.assertEqual(len(engine._queue), 1)
        engine.configure(rate_hz=50, lookahead_seconds=1.0, volume=0.7,
                         mode=MotionMode.TOP_LEFT_BOTTOM_RIGHT,
                         params=MotionParameters())
        self.assertEqual(len(engine._queue), 0)
        self.assertEqual(engine.diagnostics().state, "Buffering")

    def test_dynamic_volume_reduces_at_rest_and_ramps_on_motion(self):
        engine = VectorEngine(lambda sample: None, volume=0.7, clock=lambda: 0.0)
        engine._last_input_time = 0.0
        rest = engine._calculate_volume(1.0, 0.0)
        engine._last_input_time = 1.0
        attack = engine._calculate_volume(1.0, 100.0)
        engine._last_input_time = 2.0
        active = engine._calculate_volume(2.0, 100.0)
        self.assertAlmostEqual(rest, 0.7 * (19.0 / 20.0) * 0.4)
        self.assertAlmostEqual(attack, 0.7 * 0.4)
        self.assertAlmostEqual(active, 0.7)

    def test_frequency_uses_rfp_ramp_speed_combine(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.frequency_ramp_level = 0.8
        engine.frequency_ramp_speed_ratio = 2.0
        engine._last_input_time = 1.0
        self.assertAlmostEqual(engine._calculate_frequency(1.0, 40.0), 0.6)
        self.assertAlmostEqual(engine._calculate_frequency(2.0, 40.0), 0.4)

    def test_pulse_frequency_blends_speed_alpha_and_maps_limits(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.pulse_frequency_ratio = 3.0
        engine.pulse_frequency_min = 0.4
        engine.pulse_frequency_max = 0.95
        engine.volume_ramp_up_seconds = 0.0
        engine._last_input_time = 1.0
        value = engine._calculate_pulse_frequency(1.0, 75.0, 0.6)
        combined = (0.75 * 2.0 + 0.6) / 3.0
        self.assertAlmostEqual(value, 0.4 + combined * 0.55)

    def test_pulse_rise_uses_inverted_ramp_and_speed(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.frequency_ramp_level = 0.6
        engine.pulse_rise_ratio = 2.0
        engine.pulse_rise_min = 0.0
        engine.pulse_rise_max = 0.8
        combined = ((1.0 - 0.6) + (1.0 - 0.75)) / 2.0
        self.assertAlmostEqual(engine._calculate_pulse_rise_time(75.0), combined * 0.8)

    def test_pulse_width_limits_inverted_l0_then_blends_speed(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.pulse_width_ratio = 3.0
        engine.pulse_width_min = 0.1
        engine.pulse_width_max = 0.45
        engine.volume_ramp_up_seconds = 0.0
        engine._last_input_time = 1.0
        # inverted L0=.8, limited to .45
        expected = 0.45  # raw blend is .55, hard-clamped to configured maximum
        self.assertAlmostEqual(engine._calculate_pulse_width(1.0, 60.0, 0.2), expected)

    def test_pulse_width_never_leaves_controller_range(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.pulse_width_min, engine.pulse_width_max = 0.05, 0.40
        engine.volume_ramp_up_seconds = 0.0
        engine._last_input_time = 1.0
        self.assertEqual(engine._calculate_pulse_width(1.0, 100.0, 0.0), 0.40)
        engine._last_input_time = 0.0
        self.assertGreaterEqual(engine._calculate_pulse_width(1.0, 0.0, 1.0), 0.05)

    def test_prostate_path_uses_opposite_beta_sides_for_teardrop(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_arc_depth = 1.0
        down_l0 = SegmentState(1, 0.0, 1.0, 1.0, 0.0, 100.0)
        up_l0 = SegmentState(2, 0.0, 1.0, 0.0, 1.0, 100.0)
        wide = engine._calculate_prostate(down_l0, 0.5)
        narrow = engine._calculate_prostate(up_l0, 0.5)
        self.assertAlmostEqual(wide[0], 0.5)
        self.assertAlmostEqual(wide[1], 1.0)
        self.assertAlmostEqual(narrow[0], 0.5)
        self.assertAlmostEqual(narrow[1], 0.0)

    def test_prostate_return_scale_controls_negative_side(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_arc_depth = 1.0
        engine.prostate_narrow_ratio = 0.2
        returning = SegmentState(2, 0.0, 1.0, 0.0, 1.0, 100.0)
        _, beta = engine._calculate_prostate(returning, 0.5)
        self.assertAlmostEqual(beta, 0.4)
        self.assertLessEqual(beta, 0.5)

    def test_prostate_arc_depth_scales_opposite_teardrop_halves(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_arc_depth = 0.25
        outward = SegmentState(1, 0.0, 1.0, 1.0, 0.0, 100.0)
        returning = SegmentState(2, 0.0, 1.0, 0.0, 1.0, 100.0)
        self.assertAlmostEqual(engine._calculate_prostate(outward, 0.5)[1], 0.625)
        self.assertAlmostEqual(engine._calculate_prostate(returning, 0.5)[1], 0.375)

    def test_prostate_phase_shifts_timing_without_rotating_geometry(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_arc_depth = 1.0
        outward = SegmentState(1, 0.0, 1.0, 1.0, 0.0, 100.0)
        engine.prostate_phase_degrees = 0.0
        neutral_phase = engine._calculate_prostate(outward, 0.5)
        engine.prostate_phase_degrees = 90.0
        ahead = engine._calculate_prostate(outward, 0.5)
        engine.prostate_phase_degrees = -90.0
        behind = engine._calculate_prostate(outward, 0.5)
        self.assertAlmostEqual(neutral_phase[0], 0.5)
        self.assertAlmostEqual(ahead[0], 1.0)
        self.assertAlmostEqual(behind[0], 0.0)
        self.assertAlmostEqual(ahead[1], 0.5)
        self.assertAlmostEqual(behind[1], 0.5)

    def test_prostate_phase_continues_smoothly_through_reversal(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_phase_degrees = 90.0
        outward = SegmentState(1, 0.0, 1.0, 1.0, 0.0, 100.0)
        before = engine._calculate_prostate(outward, 0.49)[0]
        at_endpoint = engine._calculate_prostate(outward, 0.50)[0]
        after = engine._calculate_prostate(outward, 0.51)[0]
        self.assertLess(before, at_endpoint)
        self.assertGreater(at_endpoint, after)
        self.assertAlmostEqual(before, after, places=6)

    def test_phase_shift_preserves_full_prostate_path_extents(self):
        engine = VectorEngine(lambda sample: None, clock=lambda: 0.0)
        engine.prostate_arc_depth = 1.0
        outward = SegmentState(1, 0.0, 1.0, 1.0, 0.0, 100.0)
        returning = SegmentState(2, 1.0, 2.0, 0.0, 1.0, 100.0)
        for phase in (-90.0, -45.0, 0.0, 45.0, 90.0):
            engine.prostate_phase_degrees = phase
            points = [engine._calculate_prostate(outward, index / 200.0)
                      for index in range(201)]
            points += [engine._calculate_prostate(returning, 1.0 + index / 200.0)
                       for index in range(201)]
            alpha = [point[0] for point in points]
            self.assertAlmostEqual(min(alpha), 0.0)
            self.assertAlmostEqual(max(alpha), 1.0)

    def test_prostate_volume_uses_rfp_multiplier_and_rest_level(self):
        engine = VectorEngine(lambda sample: None, volume=0.7, clock=lambda: 0.0)
        engine._last_input_time = 0.0
        expected = 0.7 * (29.0 / 30.0) * 0.7
        self.assertAlmostEqual(engine._calculate_prostate_volume(1.0, 0.0), expected)


if __name__ == "__main__":
    unittest.main()


def test_director_forecast_summarizes_queued_future():
    from vector1a.engine import VectorEngine
    sent = []
    now = [100.0]
    engine = VectorEngine(sent.append, rate_hz=10, lookahead_seconds=2.0, clock=lambda: now[0])
    # Use deterministic step() without starting the background scheduler.
    engine.resume()
    engine.receive_l0(0.2, received_at=99.9)
    engine.receive_l0(0.8, received_at=100.0)
    for i in range(6):
        engine.step(100.0 + i * 0.1, release_at=100.0)
    forecast = engine.director_forecast(100.0)
    assert forecast["queue_samples"] >= 1
    assert forecast["horizon_seconds"] > 0
    assert forecast["direction"] in ("rising", "falling", "steady")
    assert forecast["speed_trend"] in ("increasing", "decreasing", "steady")


def test_director_signal_snapshot_reports_activity_and_lull():
    from vector1a.engine import VectorEngine
    now = [100.0]
    engine = VectorEngine(lambda sample: None, clock=lambda: now[0])
    engine.receive_l0(0.2, received_at=99.8)
    engine.receive_l0(0.8, received_at=100.0)
    snap = engine.director_signal_snapshot(100.0)
    assert snap["activity"] in ("active", "hold")
    assert snap["direction"] == "rising"
    assert snap["local_amplitude"] > 0.5
    assert snap["energy_band"] in ("relaxing", "moderate", "challenging", "testing")
    now[0] = 101.0
    lull = engine.director_signal_snapshot(101.0)
    assert lull["activity"] == "lull"
    assert lull["energy_score"] == 0.0


def test_stop_state_is_immediate_and_latched_against_input():
    from vector1a.engine import VectorEngine
    now = [100.0]
    sent = []
    engine = VectorEngine(sent.append, rate_hz=10, lookahead_seconds=0.2, clock=lambda: now[0])
    engine.resume()
    assert engine.diagnostics().state == "Buffering"
    assert engine.control_state()["output_enabled"] is True

    engine.stop()
    assert engine.diagnostics().state == "Stopped"
    assert engine.control_state()["engine_state"] == "Stopped"
    assert engine.control_state()["output_enabled"] is False

    # Input remains visible to the observer but must not reopen the output gate.
    engine.receive_l0(0.2, received_at=99.9)
    engine.receive_l0(0.8, received_at=100.0)
    engine.step(100.0, release_at=100.5)
    assert engine.director_signal_snapshot(100.0)["direction"] == "rising"
    assert engine.control_state()["engine_state"] == "Stopped"
    assert engine.control_state()["output_enabled"] is False
    assert sent == []


def test_resume_reopens_output_gate_in_buffering_state():
    from vector1a.engine import VectorEngine
    engine = VectorEngine(lambda sample: None, clock=lambda: 100.0)
    engine.stop()
    engine.receive_l0(0.7, received_at=100.0)
    engine.resume()
    state = engine.control_state()
    assert state["engine_state"] == "Buffering"
    assert state["output_enabled"] is True
    assert engine.diagnostics().state == "Buffering"
