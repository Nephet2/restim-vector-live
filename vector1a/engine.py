from __future__ import annotations

from dataclasses import dataclass, replace
from bisect import bisect_left
import heapq
from collections import deque
import math
import threading
import time
from typing import Callable

from .motion import MotionCalculator, MotionMode, MotionParameters, SegmentState
from .variety import speed_linked_depth
from .modifier import ModifierValues, interpolate, transform_segment
from .output_ranges import scale_response, unit_range
from .parameter_curves import default_curves, validate_parameter_curves, shape_output
from .timing_variation import TimingVariation
from .envelope import EnvelopeChain, advance_lookup


PRIMARY_PULSE_AXES = ("frequency", "pulse_frequency", "pulse_rise", "pulse_width")
# Output envelope axes: primary V0 then the primary pulse commands in
# PRIMARY_PULSE_AXES order.  Off unless configure_envelopes() enables an axis.
ENVELOPE_AXES = ("V0", "C0", "P0", "P3", "P1")
ENVELOPE_OPTIONS = frozenset(("tau_attack", "tau_release", "jerk_limit", "compensation"))
# Reversal window: L0 moves smaller than this (1% of travel) are ignored when
# dating turning points, so jitter or a nudge cannot count as a fresh turn.
REVERSAL_DEADBAND = 0.01
# A slow V0 release keeps intensity up after input stops, so it has a tight cap.
ENVELOPE_MAX_TAU = {"V0": 2.0, "C0": 30.0, "P0": 30.0, "P3": 30.0, "P1": 30.0}


@dataclass(frozen=True)
class OutputSample:
    sequence: int
    calculated_at: float
    due_at: float
    raw_l0: float
    output_l0: float
    speed_percent: float
    alpha: float
    beta: float
    volume: float
    mode: MotionMode
    frequency: float
    pulse_frequency: float
    pulse_rise_time: float
    pulse_width: float
    alpha_prostate: float
    beta_prostate: float
    volume_prostate: float
    reversal_distance_seconds: float = math.inf
    stroke_progress: float = 0.5
    variation_depth: float = 0.0
    prostate_bounds_known: bool = False
    source_stroke_span: float | None = None
    timing_stroke: SegmentState | None = None
    secondary_pulse_frequency: float | None = None
    secondary_pulse_width: float | None = None
    keyframe_arc: tuple[float, float] | None = None
    shifted_primary_pulse: tuple[float, ...] | None = None
    primary_pulse_smoothed: tuple[bool, ...] = ()
    # Base volume that volume and volume_prostate were scaled by.  A sample can
    # be released after Base volume changes; the composer uses this to undo
    # the old scale instead of dividing by the new one.  None: unknown.
    volume_scale: float | None = None

    @property
    def primary_pulse(self) -> tuple[float, ...]:
        return self.frequency, self.pulse_frequency, self.pulse_rise_time, self.pulse_width


@dataclass(frozen=True)
class Diagnostics:
    raw_l0: float = 0.5
    output_l0: float = 0.5
    speed_percent: float = 0.0
    alpha: float = 0.5
    beta: float = 0.5
    buffer_fill: int = 0
    lookahead_seconds: float = 2.0
    actual_queue_delay: float = 0.0
    input_samples: int = 0
    output_samples: int = 0
    state: str = "Stopped"
    output_mode: str = "--"
    output_volume: float = 0.0
    frequency: float = 0.0
    pulse_frequency: float = 0.0
    pulse_rise_time: float = 0.0
    pulse_width: float = 0.0
    alpha_prostate: float = 0.5
    beta_prostate: float = 0.5
    volume_prostate: float = 0.0
    reversal_distance_seconds: float = math.inf
    stroke_progress: float = 0.5
    variation_depth: float = 0.0


class VectorEngine:
    """Fixed-cadence calculator and deterministic due-time FIFO."""

    def __init__(self, send_sample: Callable[[OutputSample], None], rate_hz: int = 50,
                 lookahead_seconds: float = 2.0, volume: float = 0.7,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.send_sample = send_sample
        self.input_tick = None
        self.rate_hz = rate_hz
        self.lookahead_seconds = lookahead_seconds
        self.volume = volume
        self.clock = clock
        self.mode = MotionMode.CIRCULAR
        self.params = MotionParameters()
        self.calculator = MotionCalculator()
        self._lock = threading.RLock()
        now = clock()
        self._segment = SegmentState(0, now, now, 0.5, 0.5)
        self._raw_l0 = 0.5
        self._keyframe_arc: tuple[float, float] | None = None
        self._last_input_time = now
        self._last_input_position = 0.5
        self._velocity_history: deque[tuple[float, float]] = deque()
        self._signal_history: deque[tuple[float, float, float]] = deque()
        self._speed_peak_history: deque[tuple[float, float]] = deque()
        self._stroke_start_time = now
        self._stroke_start_position = 0.5
        self._stroke_direction = 0
        self._stroke_sequence = 0
        self._completed_strokes: deque[SegmentState] = deque(maxlen=256)
        self._known_stroke_bounds: tuple[float, float] | None = None
        self._preserve_stroke_range = False
        self._range_scale = 1.0
        self._range_scale_time = None
        self._range_source = 'waiting for a complete stroke'
        self.timing_variation = TimingVariation()
        self.volume_response_min, self.volume_response_max = 0.0, 1.0
        self.frequency_min, self.frequency_max = 0.0, 1.0
        self.dynamic_volume = True
        self.volume_rest_level = 0.4
        self.volume_ramp_speed_ratio = 20.0
        self.volume_ramp_up_seconds = 1.0
        self.volume_idle_seconds = 0.25
        # 0 = off.  Otherwise input only counts as active if L0 changed direction
        # within this many seconds, so a one-way parking move stays at rest.
        self.stroke_reversal_window = 0.0
        self._reset_reversal_tracking()
        # 0 = instant step.  Otherwise V0 and Prostate V0 ease to rest on an
        # S-curve over this many seconds once the rest gate turns off.
        self.volume_fall_seconds = 0.0
        self._reset_rest_fall()
        self._volume_was_active = False
        self._volume_active_since = now
        self.frequency_ramp_level = 1.0
        self.frequency_ramp_speed_ratio = 2.0
        self.pulse_frequency_ratio = 3.0
        self.pulse_frequency_min = 0.40
        self.pulse_frequency_max = 0.95
        self._pulse_was_active = False
        self._pulse_active_since = now
        self.pulse_rise_ratio = 2.0
        self.pulse_rise_min = 0.0
        self.pulse_rise_max = 0.80
        self.pulse_width_ratio = 3.0
        self.pulse_width_min = 0.10
        self.pulse_width_max = 0.45
        self._width_was_active = False
        self._width_active_since = now
        self.prostate_narrow_ratio = 1.0
        self.prostate_arc_depth = 0.25
        self.prostate_stroke_threshold = 0.25
        self.prostate_volume_multiplier = 1.5
        self.prostate_rest_level = 0.7
        self.prostate_phase_degrees = 0.0
        self.jitter_enabled = False
        self.jitter_amplitude = 0.02
        self.jitter_cycle_seconds = 1.0
        self.speed_linked_variation = True
        self.variation_full_speed_percent = 35.0
        self.variation_fade_seconds = 0.75
        self.parameter_curves = default_curves()
        self._parameter_curve_live = {}
        self.spatial_curve = "Linear"
        self.spatial_blend = 0.0
        self._variation_depth = 0.0
        self._variation_updated_at = now
        self._input_count = 0
        self._output_count = 0
        self._sequence = 0
        self._queue: list[tuple[float, int, OutputSample]] = []
        self._primary_pulse_history: deque[tuple[float, tuple[float, ...]]] = deque()
        self.pulse_smoothing_seconds = 0.0
        self._primary_pulse_timing = ((0.0, 0.0),) * len(PRIMARY_PULSE_AXES)
        self._primary_pulse_timing_status = ("Off",) * len(PRIMARY_PULSE_AXES)
        self._envelope_settings: dict[str, dict] = {}
        self._envelope_chains: dict[str, EnvelopeChain] = {}
        self._envelope_key = None
        self._envelope_history: dict[str, deque[tuple[float, float]]] = {}
        self._envelope_limited: dict[str, bool] = {}
        self._envelope_soft_start = False
        self._state = "Stopped"
        self._output_enabled = False
        self._diag = Diagnostics()
        self._run = threading.Event()
        self._thread: threading.Thread | None = None
        # Alpha68: manual deterministic funscript modifier layer.  Neutral by default.
        self._modifier_start = ModifierValues()
        self._modifier_target = ModifierValues()
        self._modifier_transition_started_at = now
        self._modifier_transition_seconds = 0.2

    def configure(self, *, rate_hz: int, lookahead_seconds: float, volume: float,
                  mode: MotionMode, params: MotionParameters,
                  dynamic_volume: bool = True, volume_rest_level: float = 0.4,
                  volume_response_min: float = 0.0, volume_response_max: float = 1.0,
                  frequency_min: float = 0.0, frequency_max: float = 1.0,
                  volume_ramp_speed_ratio: float = 20.0,
                  volume_ramp_up_seconds: float = 1.0,
                  frequency_ramp_level: float = 1.0,
                  frequency_ramp_speed_ratio: float = 2.0,
                  pulse_frequency_ratio: float = 3.0,
                  pulse_frequency_min: float = 0.40,
                  pulse_frequency_max: float = 0.95,
                  pulse_rise_ratio: float = 2.0,
                  pulse_rise_min: float = 0.0,
                  pulse_rise_max: float = 0.80,
                  pulse_width_ratio: float = 3.0,
                  pulse_width_min: float = 0.10,
                  pulse_width_max: float = 0.45,
                  prostate_narrow_ratio: float = 1.0,
                  prostate_arc_depth: float = 0.25,
                  prostate_stroke_threshold: float = 0.25,
                  prostate_volume_multiplier: float = 1.5,
                  prostate_rest_level: float = 0.7,
                  prostate_phase_degrees: float = 0.0,
                  jitter_enabled: bool = False, jitter_amplitude: float = 0.02,
                  jitter_cycle_seconds: float = 1.0,
                  speed_linked_variation: bool = True,
                  variation_full_speed_percent: float = 35.0,
                  variation_fade_seconds: float = .75,
                  spatial_curve: str = "Linear",
                  spatial_blend: float = 0.0,
                  parameter_curves: dict | None = None,
                  pulse_smoothing_seconds: float = 0.0,
                  volume_idle_seconds: float = 0.25,
                  stroke_reversal_window: float = 0.0,
                  volume_fall_seconds: float = 0.0) -> None:
        with self._lock:
            if parameter_curves is not None:
                self.parameter_curves = validate_parameter_curves(parameter_curves)
            mode_changed = mode != self.mode
            self.rate_hz = max(1, min(200, int(rate_hz)))
            self.lookahead_seconds = max(0.05, min(10.0, float(lookahead_seconds)))
            self.pulse_smoothing_seconds = max(0.0, min(20.0, float(pulse_smoothing_seconds)))
            self.volume = min(1.0, max(0.0, float(volume)))
            self.mode = mode
            self.params = params
            self.volume_response_min, self.volume_response_max = unit_range(volume_response_min, volume_response_max)
            self.frequency_min, self.frequency_max = unit_range(frequency_min, frequency_max)
            self.dynamic_volume = bool(dynamic_volume)
            self.volume_rest_level = min(1.0, max(0.0, float(volume_rest_level)))
            self.volume_ramp_speed_ratio = min(40.0, max(10.0, float(volume_ramp_speed_ratio)))
            self.volume_ramp_up_seconds = min(10.0, max(0.0, float(volume_ramp_up_seconds)))
            # "Rest after": input silence before V0, C0, P0, P1 and Prostate V0
            # drop to their rest levels.  Scripts with holds need more than 0.25 s.
            self.volume_idle_seconds = min(5.0, max(0.05, float(volume_idle_seconds)))
            self.stroke_reversal_window = min(10.0, max(0.0, float(stroke_reversal_window)))
            self.volume_fall_seconds = min(5.0, max(0.0, float(volume_fall_seconds)))
            self.frequency_ramp_level = min(1.0, max(0.0, float(frequency_ramp_level)))
            self.frequency_ramp_speed_ratio = min(10.0, max(1.0, float(frequency_ramp_speed_ratio)))
            self.pulse_frequency_ratio = min(10.0, max(1.0, float(pulse_frequency_ratio)))
            low = min(1.0, max(0.0, float(pulse_frequency_min)))
            high = min(1.0, max(0.0, float(pulse_frequency_max)))
            self.pulse_frequency_min, self.pulse_frequency_max = sorted((low, high))
            self.pulse_rise_ratio = min(10.0, max(1.0, float(pulse_rise_ratio)))
            rise_low = min(1.0, max(0.0, float(pulse_rise_min)))
            rise_high = min(1.0, max(0.0, float(pulse_rise_max)))
            self.pulse_rise_min, self.pulse_rise_max = sorted((rise_low, rise_high))
            self.pulse_width_ratio = min(10.0, max(1.0, float(pulse_width_ratio)))
            width_low = min(1.0, max(0.0, float(pulse_width_min)))
            width_high = min(1.0, max(0.0, float(pulse_width_max)))
            self.pulse_width_min, self.pulse_width_max = sorted((width_low, width_high))
            self.prostate_narrow_ratio = min(1.0, max(0.0, float(prostate_narrow_ratio)))
            self.prostate_arc_depth = min(1.0, max(0.0, float(prostate_arc_depth)))
            self.prostate_stroke_threshold = min(1.0, max(0.0, float(prostate_stroke_threshold)))
            self.prostate_volume_multiplier = min(3.0, max(1.0, float(prostate_volume_multiplier)))
            self.prostate_rest_level = min(1.0, max(0.0, float(prostate_rest_level)))
            self.prostate_phase_degrees = min(90.0, max(-90.0, float(prostate_phase_degrees)))
            self.jitter_enabled = bool(jitter_enabled)
            self.jitter_amplitude = min(.20, max(0.0, float(jitter_amplitude)))
            self.jitter_cycle_seconds = min(30.0, max(.05, float(jitter_cycle_seconds)))
            self.speed_linked_variation = bool(speed_linked_variation)
            self.variation_full_speed_percent = min(
                100.0, max(1.0, float(variation_full_speed_percent)))
            self.variation_fade_seconds = min(10.0, max(.05, float(variation_fade_seconds)))
            self.spatial_curve = str(spatial_curve)
            self.spatial_blend = min(1.0, max(0.0, float(spatial_blend)))
            if mode_changed and self._state in ("Buffering", "Running"):
                # Never release samples calculated by a previously selected
                # geometry under a newly-labelled UI state.
                self._queue.clear()
                self._reset_primary_pulse_timing()
                self._state = "Buffering"


    def set_motion_mode(self, mode):
        # Preserve the output FIFO and all response settings.
        with self._lock:
            self.mode = MotionMode(mode)

    def configure_modifier(self, *, enabled: bool, stroke_range: float = 1.0,
                           position_bias: float = 0.0, smoothing: float = 0.0,
                           transition_seconds: float = 0.2) -> None:
        """Set a bounded modifier target; transitions preserve output continuity."""
        with self._lock:
            now = self.clock()
            current = self._modifier_values(now)
            target = (ModifierValues(stroke_range, position_bias, smoothing).bounded()
                      if enabled else ModifierValues())
            self._modifier_start = current
            self._modifier_target = target
            self._modifier_transition_started_at = now
            self._modifier_transition_seconds = min(5.0, max(0.0, float(transition_seconds)))

    def modifier_state(self, now: float | None = None) -> dict:
        with self._lock:
            at = self.clock() if now is None else float(now)
            values = self._modifier_values(at)
            target = self._modifier_target
            return {
                "active": not values.is_neutral(),
                "target_active": not target.is_neutral(),
                "stroke_range": round(values.stroke_range, 4),
                "position_bias": round(values.position_bias, 4),
                "smoothing": round(values.smoothing, 4),
                "transition_seconds": round(self._modifier_transition_seconds, 3),
            }

    def _modifier_values(self, at_time: float) -> ModifierValues:
        duration = self._modifier_transition_seconds
        if duration <= 1e-9:
            return self._modifier_target
        amount = (float(at_time) - self._modifier_transition_started_at) / duration
        if amount <= 0.0:
            return self._modifier_start
        if amount >= 1.0:
            return self._modifier_target
        return interpolate(self._modifier_start, self._modifier_target, amount)

    def _modified_segment(self, segment: SegmentState, at_time: float) -> SegmentState:
        return transform_segment(segment, self._modifier_values(at_time))

    def receive_l0(self, value: float, interval_ms: int = 0,
                   received_at: float | None = None,
                   stroke_bounds: tuple[float, float] | None = None, *,
                   keyframe_arc: tuple[float, float] | None = None) -> None:
        now = self.clock() if received_at is None else received_at
        value = min(1.0, max(0.0, value))
        with self._lock:
            self._keyframe_arc = keyframe_arc
            if stroke_bounds is None:
                self._known_stroke_bounds = None
            else:
                low, high = sorted((min(1.0, max(0.0, float(stroke_bounds[0]))),
                                    min(1.0, max(0.0, float(stroke_bounds[1])))))
                self._known_stroke_bounds = (low, high)
            current = self._segment.position(now)
            if interval_ms > 0:
                duration = interval_ms / 1000.0
                velocity = abs(value - current) / max(duration, 1e-6)
                start_time, end_time = now, now + duration
                start_position = current
            else:
                # MFP's fixed-update outputs normally send sampled positions without
                # T-code interval fields. Reconstruct the just-observed segment from
                # consecutive arrival timestamps instead of treating every sample as
                # a zero-duration stroke.
                duration = max(1e-6, now - self._last_input_time)
                velocity = abs(value - self._last_input_position) / duration
                start_time, end_time = self._last_input_time, now
                start_position = self._last_input_position

            self._velocity_history.append((now, velocity))
            while self._velocity_history and self._velocity_history[0][0] < now - 5.0:
                self._velocity_history.popleft()
            self._signal_history.append((now, value, velocity))
            while self._signal_history and self._signal_history[0][0] < now - 10.0:
                self._signal_history.popleft()
            rolling_velocity = sum(item[1] for item in self._velocity_history) / len(self._velocity_history)
            self._speed_peak_history.append((now, rolling_velocity))
            while self._speed_peak_history and self._speed_peak_history[0][0] < now - 30.0:
                self._speed_peak_history.popleft()
            rolling_peak = max((item[1] for item in self._speed_peak_history), default=0.0)
            normalized_speed = 100.0 * rolling_velocity / rolling_peak if rolling_peak > 1e-9 else 0.0
            self._input_count += 1
            self._raw_l0 = value
            delta = value - self._last_input_position
            new_direction = 1 if delta > 0.00005 else (-1 if delta < -0.00005 else 0)
            completed_stroke = None
            if new_direction and self._stroke_direction and new_direction != self._stroke_direction:
                self._stroke_sequence += 1
                completed_stroke = SegmentState(
                    self._stroke_sequence, self._stroke_start_time, self._last_input_time,
                    self._stroke_start_position, self._last_input_position, normalized_speed,
                )
                self._completed_strokes.append(completed_stroke)
                self._stroke_start_time = self._last_input_time
                self._stroke_start_position = self._last_input_position
            if new_direction:
                self._stroke_direction = new_direction
            self._track_reversal(value, now)
            self._segment = SegmentState(
                self._input_count, start_time, end_time, start_position, value,
                normalized_speed,
            )
            self._last_input_time = now
            self._last_input_position = value
            if completed_stroke is not None:
                self._rewrite_completed_stroke(completed_stroke)

    def rebase_input(self, value: float, now: float) -> None:
        """Discard queued and historical motion at a source change or seek."""
        with self._lock:
            self._queue.clear()
            self._reset_primary_pulse_timing()
            self._velocity_history.clear()
            self._signal_history.clear()
            self._speed_peak_history.clear()
            self._completed_strokes.clear()
            self._keyframe_arc = None
            self._known_stroke_bounds = None
            self.timing_variation.reset()
            self._range_scale, self._range_scale_time = 1.0, None
            self._volume_was_active = self._pulse_was_active = self._width_was_active = False
            self._reset_rest_fall()
            self._stroke_start_time = self._last_input_time = now
            self._stroke_start_position = self._last_input_position = self._raw_l0 = value
            self._stroke_direction = 0
            self._reset_reversal_tracking()
            self._segment = SegmentState(self._input_count, now, now, value, value)
            if self._state == "Running":
                self._state = "Buffering"

    def _rewrite_completed_stroke(self, stroke: SegmentState) -> None:
        """Apply a discovered reversal endpoint to samples still in look-ahead.

        MFP sends interpolated positions, not original funscript keyframes. The
        reversal identifies the equivalent RFP stroke endpoint. Since calculated
        samples are held for one second, ordinary strokes can be corrected before
        they are released to ReStim.
        """
        rewritten: list[tuple[float, int, OutputSample]] = []
        for due_at, sequence, sample in self._queue:
            sample = replace(
                sample,
                reversal_distance_seconds=min(
                    sample.reversal_distance_seconds,
                    abs(sample.calculated_at - stroke.end_time)))
            # A reversal timestamp is both the end of one stroke and the start
            # of the next. Keep that shared sample owned by the stroke that
            # ended there; the first later sample starts the new stroke.
            if stroke.start_time < sample.calculated_at <= stroke.end_time:
                sample = replace(
                    sample,
                    stroke_progress=self._stroke_progress(stroke, sample.calculated_at),
                    timing_stroke=stroke,
                    source_stroke_span=(sample.source_stroke_span if sample.prostate_bounds_known else
                                        abs(stroke.end_position-stroke.start_position)))
            if (sample.mode == MotionMode.RESTIM_ORIGINAL
                    and stroke.start_time <= sample.calculated_at <= stroke.end_time):
                alpha, beta, position, speed = self.calculator.calculate(
                    MotionMode.RESTIM_ORIGINAL,
                    self._jitter_segment(
                        self._modified_segment(stroke, sample.calculated_at), sample.variation_depth),
                    sample.calculated_at, self.params
                )
                sample = replace(sample, output_l0=position, speed_percent=speed,
                                 alpha=alpha, beta=beta)
            if (not sample.prostate_bounds_known
                    and stroke.start_time <= sample.calculated_at <= stroke.end_time):
                pa, pb = self._calculate_prostate(
                    self._jitter_segment(
                        self._modified_segment(stroke, sample.calculated_at), sample.variation_depth),
                    sample.calculated_at)
                sample = replace(sample, alpha_prostate=pa, beta_prostate=pb)
            rewritten.append((due_at, sequence, sample))
        self._queue = rewritten
        heapq.heapify(self._queue)

    def _nearest_reversal_distance(self, at_time: float) -> float:
        return min((abs(at_time - stroke.end_time)
                    for stroke in self._completed_strokes), default=math.inf)

    @staticmethod
    def _stroke_progress(stroke: SegmentState, at_time: float) -> float:
        duration = stroke.end_time - stroke.start_time
        if duration <= 1e-9:
            return 0.5
        return min(1.0, max(0.0, (at_time - stroke.start_time) / duration))

    def _stroke_for_time(self, scheduled_at: float) -> SegmentState:
        for stroke in reversed(self._completed_strokes):
            if stroke.start_time <= scheduled_at <= stroke.end_time:
                return stroke
        # Provisional current stroke. It will be rewritten on the next reversal.
        return SegmentState(
            1_000_000_000 + self._stroke_sequence + 1, self._stroke_start_time,
            max(scheduled_at, self._last_input_time), self._stroke_start_position,
            self._last_input_position, self._segment.speed_percent,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._run.set()
        self._thread = threading.Thread(target=self._loop, name="vector-engine", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._run.clear()
        if self._thread:
            self._thread.join(timeout=2.0)

    def resume(self) -> None:
        with self._lock:
            self.timing_variation.reset()
            self._queue.clear()
            self._envelope_soft_start = True   # An enabled V0 envelope rises from zero.
            self._reset_primary_pulse_timing()
            self._range_scale_time = None
            self._range_scale = 1.0
            self._output_enabled = True
            self._state = "Buffering"
            self._diag = replace(self._diag, state=self._state, buffer_fill=0)

    def neutral(self) -> None:
        with self._lock:
            self.timing_variation.reset()
            self._queue.clear()
            self._reset_primary_pulse_timing()
            self._range_scale_time = None
            self._range_scale = 1.0
            self._output_enabled = True
            self._state = "Neutral"
            self._diag = replace(self._diag, state=self._state, buffer_fill=0)

    def stop(self) -> None:
        with self._lock:
            # Stop is a latched output gate.  Incoming MFP samples continue to be
            # observed for diagnostics/Director visibility, but they cannot restart
            # output until an explicit resume().
            self._queue.clear()
            self._reset_primary_pulse_timing()
            self._output_enabled = False
            self._state = "Stopped"
            self._diag = replace(self._diag, state=self._state, buffer_fill=0)

    def control_state(self) -> dict:
        with self._lock:
            return {
                "engine_state": self._state,
                "output_enabled": bool(self._output_enabled),
                "buffer_fill": len(self._queue),
            }

    def diagnostics(self) -> Diagnostics:
        with self._lock:
            # Keep control state authoritative even between scheduler ticks.
            return replace(self._diag, state=self._state, buffer_fill=len(self._queue))

    def loop_alive(self) -> bool:
        return bool(self._run.is_set() and self._thread and self._thread.is_alive())

    def director_signal_snapshot(self, now: float | None = None) -> dict:
        """Read-only semantic summary of the recently received L0 signal.

        The observer deliberately reports coarse, deterministic descriptors rather
        than exposing raw T-code history to an AI client.  Energy bands are relative
        to Vector's recent-session speed normalisation; they are useful Director
        semantics, not a claim about absolute physical intensity.
        """
        now = self.clock() if now is None else float(now)
        with self._lock:
            diag = replace(self._diag)
            age = max(0.0, now - self._last_input_time)
            history = list(self._signal_history)
            strokes = list(self._completed_strokes)

        recent = [x for x in history if x[0] >= now - 2.0]
        if not recent:
            recent = history[-1:]
        positions = [x[1] for x in recent]
        local_min = min(positions) if positions else float(diag.raw_l0)
        local_max = max(positions) if positions else float(diag.raw_l0)
        amplitude = max(0.0, local_max - local_min)

        direction = "steady"
        if len(recent) >= 2:
            delta = recent[-1][1] - recent[-2][1]
            if delta > 0.0005:
                direction = "rising"
            elif delta < -0.0005:
                direction = "falling"

        recent_strokes = [st for st in strokes if st.end_time >= now - 5.0]
        reversal_rate = len(recent_strokes) / 5.0
        stroke_amplitudes = [abs(st.end_position - st.start_position) for st in recent_strokes]
        mean_stroke_amplitude = (sum(stroke_amplitudes) / len(stroke_amplitudes)
                                 if stroke_amplitudes else amplitude)

        active = age <= 0.75
        speed = float(diag.speed_percent) if active else 0.0
        # Blend relative speed with recent excursion so small, fast tremors and broad
        # slow sweeps do not collapse to the same semantic label.
        energy_score = min(100.0, max(0.0, speed * 0.70 + mean_stroke_amplitude * 100.0 * 0.30))
        if not active:
            activity = "lull"
            energy_band = "relaxing"
            energy_score = 0.0
        else:
            activity = "active" if (speed >= 2.0 or amplitude >= 0.01) else "hold"
            if energy_score < 25.0:
                energy_band = "relaxing"
            elif energy_score < 50.0:
                energy_band = "moderate"
            elif energy_score < 75.0:
                energy_band = "challenging"
            else:
                energy_band = "testing"

        center = (local_min + local_max) / 2.0
        if center < 0.34:
            focus_region = "lower"
        elif center > 0.66:
            focus_region = "upper"
        else:
            focus_region = "middle"

        return {
            "source": "live_l0",
            "activity": activity,
            "input_age_seconds": round(age, 3),
            "position": round(float(diag.raw_l0), 4),
            "direction": direction,
            "speed_percent": round(speed, 2),
            "local_range": [round(local_min, 4), round(local_max, 4)],
            "local_amplitude": round(amplitude, 4),
            "mean_stroke_amplitude": round(mean_stroke_amplitude, 4),
            "reversals_per_second": round(reversal_rate, 3),
            "focus_region": focus_region,
            "energy_score": round(energy_score, 1),
            "energy_band": energy_band,
            "energy_note": "relative live-script energy; not absolute physical output intensity",
        }

    def director_forecast(self, now: float | None = None) -> dict:
        """Compact read-only forecast from samples already in the deterministic queue.

        This does not calculate new motion or mutate engine state.  It only summarizes
        samples Vector has already calculated and scheduled for future release.
        """
        now = self.clock() if now is None else float(now)
        with self._lock:
            samples = [item[2] for item in sorted(self._queue) if item[0] > now]
            lookahead = float(self.lookahead_seconds)

        if not samples:
            return {
                "horizon_seconds": round(lookahead, 3),
                "queue_samples": 0,
                "direction": "unknown",
                "speed_trend": "unknown",
                "projected_speed_percent": 0.0,
                "next_reversal_seconds": None,
                "endpoint_approach": None,
            }

        # Use due-time order: this is what the user will actually experience next.
        positions = [float(x.output_l0) for x in samples]
        speeds = [float(x.speed_percent) for x in samples]
        deltas = [b - a for a, b in zip(positions, positions[1:])]

        def sign(v: float, eps: float = 1e-4) -> int:
            return 1 if v > eps else (-1 if v < -eps else 0)

        first_dir = 0
        for d in deltas:
            first_dir = sign(d)
            if first_dir:
                break
        direction = "rising" if first_dir > 0 else ("falling" if first_dir < 0 else "steady")

        next_reversal = None
        active_dir = first_dir
        if active_dir:
            for idx, d in enumerate(deltas, start=1):
                sd = sign(d)
                if sd and sd != active_dir:
                    next_reversal = max(0.0, samples[idx].due_at - now)
                    break

        n = max(1, min(12, len(speeds) // 3 or 1))
        early = sum(speeds[:n]) / len(speeds[:n])
        late = sum(speeds[-n:]) / len(speeds[-n:])
        if late > early + 5.0:
            speed_trend = "increasing"
        elif late < early - 5.0:
            speed_trend = "decreasing"
        else:
            speed_trend = "steady"

        endpoint = None
        # Only claim an approach when the queued path actually reaches near an endpoint.
        if direction == "rising" and max(positions) >= 0.90:
            endpoint = "top"
        elif direction == "falling" and min(positions) <= 0.10:
            endpoint = "bottom"

        horizon = max(0.0, samples[-1].due_at - now)
        return {
            "horizon_seconds": round(min(lookahead, horizon), 3),
            "queue_samples": len(samples),
            "direction": direction,
            "speed_trend": speed_trend,
            "projected_speed_percent": round(sum(speeds) / len(speeds), 2),
            "next_reversal_seconds": (None if next_reversal is None else round(next_reversal, 3)),
            "endpoint_approach": endpoint,
        }

    def _calculate_and_queue(self, scheduled_at: float) -> None:
        with self._lock:
            if not self._output_enabled or self._state not in ("Buffering", "Running"):
                return
            calculation_segment = (self._stroke_for_time(scheduled_at)
                                   if self.mode == MotionMode.RESTIM_ORIGINAL
                                   else self._segment)
            variation_depth = self._update_variation_depth(
                scheduled_at, calculation_segment.speed_percent)
            calculation_segment = self._modified_segment(calculation_segment, scheduled_at)
            calculation_segment = self._jitter_segment(calculation_segment, variation_depth)
            alpha, beta, output_l0, speed = self.calculator.calculate(
                self.mode, calculation_segment, scheduled_at, self.params,
                self.spatial_curve, self.spatial_blend * variation_depth)
            output_volume = self._calculate_volume(scheduled_at, speed)
            frequency = self._calculate_frequency(scheduled_at, speed)
            pulse_frequency = self._calculate_pulse_frequency(scheduled_at, speed, alpha)
            pulse_rise_time = self._calculate_pulse_rise_time(speed)
            pulse_width = self._calculate_pulse_width(scheduled_at, speed, output_l0)
            prostate_segment = self._jitter_segment(
                self._modified_segment(self._stroke_for_time(scheduled_at), scheduled_at), variation_depth)
            known_bounds = self._known_stroke_bounds
            if known_bounds is None:
                alpha_prostate, beta_prostate = self._calculate_prostate(
                    prostate_segment, scheduled_at)
            else:
                alpha_prostate, beta_prostate = self._calculate_known_prostate(
                    scheduled_at, variation_depth, known_bounds)
            volume_prostate = self._calculate_prostate_volume(scheduled_at, speed)
            self._sequence += 1
            sample = OutputSample(
                self._sequence, scheduled_at, scheduled_at + self.lookahead_seconds,
                self._raw_l0, output_l0, speed, alpha, beta, output_volume, self.mode,
                frequency,
                pulse_frequency,
                pulse_rise_time,
                pulse_width,
                alpha_prostate, beta_prostate, volume_prostate,
                self._nearest_reversal_distance(scheduled_at),
                self._stroke_progress(prostate_segment, scheduled_at),
                variation_depth,
                known_bounds is not None,
                (abs(known_bounds[1]-known_bounds[0]) if known_bounds is not None else
                 abs(self._completed_strokes[-1].end_position-self._completed_strokes[-1].start_position)
                 if self._completed_strokes else None),
                keyframe_arc=self._keyframe_arc,
                volume_scale=self.volume,
            )
            heapq.heappush(self._queue, (sample.due_at, sample.sequence, sample))
            self._feed_envelopes(scheduled_at, sample)
            history = self._primary_pulse_history
            if history and scheduled_at < history[-1][0]:
                self._reset_primary_pulse_timing()
            history.append((scheduled_at, sample.primary_pulse))
            while len(history) > 1 and history[1][0] < scheduled_at - 22.0:
                history.popleft()

    def _update_variation_depth(self, at_time: float, speed_percent: float) -> float:
        target = (speed_linked_depth(speed_percent, self.variation_full_speed_percent)
                  if self.speed_linked_variation else 1.0)
        elapsed = max(0.0, at_time - self._variation_updated_at)
        self._variation_updated_at = at_time
        blend = 1.0 - math.exp(-elapsed / self.variation_fade_seconds)
        self._variation_depth += (target - self._variation_depth) * blend
        if target <= 1e-9 and self._variation_depth < 1e-4:
            self._variation_depth = 0.0
        return min(1.0, max(0.0, self._variation_depth))

    def _jitter_offset(self, at_time: float, depth: float = 1.0) -> float:
        """Deterministic band-limited texture; never alters input stroke detection."""
        if not self.jitter_enabled or self.jitter_amplitude <= 0.0:
            return 0.0
        phase = 2.0 * math.pi * at_time / self.jitter_cycle_seconds
        wave = .65 * math.sin(phase) + .35 * math.sin(phase / .57 + 1.7)
        return self.jitter_amplitude * min(1.0, max(0.0, depth)) * wave

    def _jitter_segment(self, segment: SegmentState, depth: float | None = None) -> SegmentState:
        if not self.jitter_enabled or self.jitter_amplitude <= 0.0:
            return segment
        if depth is None:
            depth = (speed_linked_depth(segment.speed_percent,
                                        self.variation_full_speed_percent)
                     if self.speed_linked_variation else 1.0)
        start = min(1.0, max(0.0, segment.start_position
                             + self._jitter_offset(segment.start_time, depth)))
        end = min(1.0, max(0.0, segment.end_position
                           + self._jitter_offset(segment.end_time, depth)))
        return replace(segment, start_position=start, end_position=end)

    def set_range_preservation(self, enabled: bool) -> None:
        with self._lock:
            self._preserve_stroke_range = bool(enabled)

    def configure_timing_variation(self, enabled, style, amount, group_multiplier=1):
        with self._lock:self.timing_variation.configure(enabled,style,amount,group_multiplier)

    def timing_variation_snapshot(self):
        with self._lock:return self.timing_variation.snapshot()

    def range_preservation_snapshot(self) -> dict:
        with self._lock:
            return {'enabled':self._preserve_stroke_range,'scale':self._range_scale,
                    'source':self._range_source,'modes':[1,2,3],
                    'transition_seconds':2.0,'minimum_scale':.1}

    def _range_preserved_sample(self, sample: OutputSample) -> OutputSample:
        """Spatial-only A/B control, evaluated in output order after reversal repair.

        Sample span comes from known bounds, a queued completed stroke, or the
        last completed stroke. Never treat one UDP update as a whole stroke.
        Volume, pulse channels, L0 and the secondary path remain untouched.
        """
        with self._lock:
            span=sample.source_stroke_span
            applicable=sample.mode != MotionMode.RESTIM_ORIGINAL
            target=max(.1,min(1.0,span)) if self._preserve_stroke_range and applicable and span is not None else 1.0
            self._range_source=('Mode 4 already follows stroke range' if not applicable else
                                'detected stroke range' if span is not None else 'waiting for a complete stroke')
            dt=max(0.0,min(.1,sample.due_at-self._range_scale_time)) if self._range_scale_time is not None else 0.0
            self._range_scale_time=sample.due_at
            # Bounded scale slew: toggling either way takes up to two seconds.
            self._range_scale+=max(-dt/2,min(dt/2,target-self._range_scale))
            if not applicable or abs(self._range_scale-1)<1e-12:return sample
            return replace(sample,alpha=.5+(sample.alpha-.5)*self._range_scale,
                           beta=.5+(sample.beta-.5)*self._range_scale)

    def configure_primary_pulse_timing(self, settings) -> None:
        with self._lock:
            timing = tuple((max(-500., min(500., ms)) / 1000.,
                            max(-180., min(180., degrees)) / 360.)
                           for ms, degrees in settings)
            if timing != self._primary_pulse_timing:
                self._primary_pulse_timing_status = tuple(
                    status if new == old else ("Pending" if any(new) else "Off")
                    for new, old, status in zip(timing, self._primary_pulse_timing,
                                                self._primary_pulse_timing_status))
                self._primary_pulse_timing = timing

    def primary_pulse_timing_status(self) -> tuple[str, ...]:
        with self._lock:
            return self._primary_pulse_timing_status

    def _reset_primary_pulse_timing(self) -> None:
        self._primary_pulse_history.clear()
        self._primary_pulse_timing_status = tuple(
            "Buffering" if any(timing) else "Off" for timing in self._primary_pulse_timing)
        self._reset_envelopes()

    # -- Output envelopes (attack/release, jerk limit, delay compensation) --

    def configure_envelopes(self, settings) -> None:
        """Enable per-axis envelopes: {axis: options or None}; None/absent = off.

        Options: tau_attack, tau_release (s), jerk_limit (normalized units/s^3,
        None or 0 = off) and compensation ("none", "ma", "ma+attack").
        Invalid settings raise ValueError and leave the current ones in place.
        """
        cleaned = {}
        for axis, options in (settings or {}).items():
            if axis not in ENVELOPE_AXES:
                raise ValueError(f"unknown envelope axis {axis!r}")
            if options is None:
                continue
            options = dict(options)
            unknown = set(options) - ENVELOPE_OPTIONS
            if unknown:
                raise ValueError(f"unknown envelope option(s) {sorted(unknown)}")
            cap = ENVELOPE_MAX_TAU[axis]
            for name in ("tau_attack", "tau_release"):
                if float(options.get(name, 0.0)) > cap:
                    raise ValueError(f"{axis} {name} must be at most {cap:g} s")
            EnvelopeChain(1.0 / self.rate_hz, axis_range=1.0, **options)  # Validates.
            cleaned[axis] = options
        with self._lock:
            if cleaned != self._envelope_settings:
                self._envelope_settings = cleaned
                self._envelope_key = None

    def envelope_status(self) -> dict:
        with self._lock:
            self._ensure_envelope_chains()
            return {axis: {"advance_seconds": chain.advance_seconds,
                           "window_samples": chain.window_samples,
                           "buffer_limited": self._envelope_limited.get(axis, False)}
                    for axis, chain in self._envelope_chains.items()}

    def _envelope_ranges(self) -> dict[str, float]:
        ranges = {"V0": 1.0}
        for axis, (low, high) in zip(ENVELOPE_AXES[1:], self.pulse_command_ranges()):
            ranges[axis] = max(1e-6, high - low)
        return ranges

    def _ensure_envelope_chains(self) -> None:
        ranges = self._envelope_ranges()
        settings_key = tuple(sorted((axis, tuple(sorted(options.items())))
                                    for axis, options in self._envelope_settings.items()))
        key = (self.rate_hz, tuple(sorted(ranges.items())), settings_key)
        if key == self._envelope_key:
            return
        chains = {}
        for axis, options in self._envelope_settings.items():
            chain = EnvelopeChain(1.0 / self.rate_hz, axis_range=ranges[axis], **options)
            history = self._envelope_history.setdefault(axis, deque())
            if history:
                chain.reset(history[-1][1])      # A settings change continues smoothly.
            elif axis == "V0" and self._envelope_soft_start:
                chain.reset(0.0)
            chains[axis] = chain
        for axis in list(self._envelope_history):
            if axis not in chains:
                del self._envelope_history[axis]
        self._envelope_chains = chains
        self._envelope_key = key
        self._envelope_soft_start = False

    def _reset_envelopes(self) -> None:
        for history in self._envelope_history.values():
            history.clear()
        self._envelope_limited = {}
        if self._envelope_chains:
            for axis, chain in self._envelope_chains.items():
                chain.reset(0.0 if axis == "V0" and self._envelope_soft_start else None)
            self._envelope_soft_start = False

    def _feed_envelopes(self, at_time: float, sample: OutputSample) -> None:
        """Run enabled envelopes in calculation order (caller holds the lock)."""
        if not self._envelope_settings:
            return
        self._ensure_envelope_chains()
        # V0 is smoothed as its 0-1 response, so a Base volume change never meets
        # older values scaled by the previous Base volume.
        response = sample.volume / sample.volume_scale if sample.volume_scale else 0.0
        inputs = dict(zip(ENVELOPE_AXES, (response,) + sample.primary_pulse))
        horizon = at_time - (self.lookahead_seconds + 1.0)
        for axis, chain in self._envelope_chains.items():
            history = self._envelope_history[axis]
            history.append((at_time, chain.step(inputs[axis])))
            while len(history) > 1 and history[0][0] < horizon:
                history.popleft()

    def _apply_envelopes(self, sample: OutputSample, baseline: tuple[float, ...],
                         calculated_volume: float) -> OutputSample:
        """Replace enabled axes with the advanced envelope (caller holds the lock).

        Release-time changes (timing variation) are kept as an offset, as
        _shift_primary_pulse does.  Envelope axes are marked smoothed so the
        composer's symmetric damping does not filter them twice.
        """
        if not self._envelope_chains:
            return sample
        values = list(sample.shifted_primary_pulse or sample.primary_pulse)
        smoothed = list(sample.primary_pulse_smoothed or (False,) * len(PRIMARY_PULSE_AXES))
        volume = sample.volume
        pulse_changed = False
        bounds = self.pulse_command_ranges()
        for axis, chain in self._envelope_chains.items():
            value, limited = advance_lookup(self._envelope_history[axis],
                                            sample.calculated_at, chain.advance_seconds)
            self._envelope_limited[axis] = limited
            if value is None:
                continue
            if axis == "V0":
                # Back to this sample's own Base volume, which the composer undoes.
                scale = sample.volume_scale or 0.0
                volume = min(scale, max(0.0, value * scale + sample.volume
                                        - calculated_volume))
                continue
            index = ENVELOPE_AXES.index(axis) - 1
            low, high = bounds[index]
            values[index] = max(low, min(high, value + sample.primary_pulse[index]
                                         - baseline[index]))
            smoothed[index] = True
            pulse_changed = True
        changes = {"volume": volume}
        if pulse_changed:
            changes.update(shifted_primary_pulse=tuple(values),
                           primary_pulse_smoothed=tuple(smoothed))
        return replace(sample, **changes)

    def _smooth_primary_pulse(self, center: float) -> tuple[float, ...] | None:
        history = self._primary_pulse_history
        if not self.pulse_smoothing_seconds or not history:
            return None
        # Keep the window centered even when the available buffer is shorter.
        # The raised-cosine weights taper to zero at both ends.
        radius = min(self.pulse_smoothing_seconds / 2, self.lookahead_seconds,
                     center - history[0][0], history[-1][0] - center)
        if radius < 2 / self.rate_hz:
            return None
        start = bisect_left(history, (center - radius, ()))
        totals = [0.0] * len(PRIMARY_PULSE_AXES)
        weight_total = 0.0
        for index in range(start, len(history)):
            at_time, pulse = history[index]
            if at_time >= center + radius:
                break
            weight = 1 + math.cos(math.pi * (at_time - center) / radius)
            for axis, value in enumerate(pulse):
                totals[axis] += weight * value
            weight_total += weight
        return tuple(total / weight_total for total in totals) if weight_total else None

    def _shift_primary_pulse(self, sample: OutputSample, baseline: tuple[float, ...]) -> OutputSample:
        history = self._primary_pulse_history
        smoothed = self._smooth_primary_pulse(sample.calculated_at)
        if not history or (smoothed is None and not any(map(any, self._primary_pulse_timing))):
            return sample
        stroke = sample.timing_stroke
        duration = stroke.duration if stroke else 0.
        values = list(sample.primary_pulse)
        smoothed_axes = [False] * len(PRIMARY_PULSE_AXES)
        statuses = ["Off"] * len(PRIMARY_PULSE_AXES)
        bounds = self.pulse_command_ranges()
        for axis, (offset, phase) in enumerate(self._primary_pulse_timing):
            if not (offset or phase):
                if smoothed is not None:
                    value = smoothed[axis] + values[axis] - baseline[axis]
                    low, high = bounds[axis]
                    values[axis] = max(low, min(high, value))
                    smoothed_axes[axis] = True
                continue
            target = sample.calculated_at - offset - phase * duration
            when = max(history[0][0], min(history[-1][0], target))
            applied = (sample.calculated_at - when) * 1000
            status = f"Applied {applied:+.0f} ms"
            if abs(when - target) > 1e-6:
                status += " (buffer limited)"
            if phase and duration <= 0:
                status += " (waiting for stroke end)"
            statuses[axis] = status
            window = smoothed if when == sample.calculated_at else self._smooth_primary_pulse(when)
            if window is not None:
                value = window[axis]
                smoothed_axes[axis] = True
            else:
                if abs(when - sample.calculated_at) <= 1e-9:
                    continue
                index = bisect_left(history, (when, ()))
                right_time, right_values = history[index]
                value = right_values[axis]
                if index and right_time > when:
                    left_time, left_values = history[index - 1]
                    fraction = (when - left_time) / (right_time - left_time)
                    value = left_values[axis] + (value - left_values[axis]) * fraction
            # Retain the current contribution from stroke timing variation.
            value += values[axis] - baseline[axis]
            low, high = bounds[axis]
            values[axis] = max(low, min(high, value))
        self._primary_pulse_timing_status = tuple(statuses)
        return replace(sample, shifted_primary_pulse=tuple(values),
                       primary_pulse_smoothed=tuple(smoothed_axes) if any(smoothed_axes) else ())

    def _release_due(self, now: float) -> None:
        due: list[OutputSample] = []
        with self._lock:
            while self._queue and self._queue[0][0] <= now:
                due.append(heapq.heappop(self._queue)[2])
            if due and self._output_enabled and self._state == "Buffering":
                self._state = "Running"
        for sample in due:
            with self._lock:
                baseline = sample.primary_pulse
                calculated_volume = sample.volume
                sample = self.timing_variation.apply(self, sample)
                sample = self._shift_primary_pulse(sample, baseline)
                sample = self._apply_envelopes(sample, baseline, calculated_volume)
            sample = self._range_preserved_sample(sample)
            self.send_sample(sample)
            actual = self.clock() - sample.calculated_at
            with self._lock:
                self._output_count += 1
                self._diag = Diagnostics(
                    sample.raw_l0, sample.output_l0, sample.speed_percent,
                    sample.alpha, sample.beta, len(self._queue),
                    self.lookahead_seconds, actual, self._input_count,
                    self._output_count, self._state, sample.mode.value, sample.volume,
                    sample.frequency,
                    sample.pulse_frequency,
                    sample.pulse_rise_time,
                    sample.pulse_width,
                    sample.alpha_prostate, sample.beta_prostate, sample.volume_prostate,
                    sample.reversal_distance_seconds,
                    sample.stroke_progress,
                    sample.variation_depth,
                )
        with self._lock:
            if not due:
                self._diag = replace(
                    self._diag, raw_l0=self._raw_l0,
                    buffer_fill=len(self._queue), lookahead_seconds=self.lookahead_seconds,
                    input_samples=self._input_count, state=self._state,
                )

    def step(self, scheduled_at: float, release_at: float | None = None) -> None:
        """One deterministic scheduler step, also used by tests."""
        self._calculate_and_queue(scheduled_at)
        self._release_due(scheduled_at if release_at is None else release_at)

    def _volume_response(self, value: float, parameter: str = 'primary_volume') -> float:
        response = scale_response(value, self.volume_response_min, self.volume_response_max)
        shaped = self._shape_parameter(parameter, response, self.volume_response_min, self.volume_response_max)
        return self.volume * shaped

    def volume_rest_response(self) -> float:
        """Normalized idle floor for primary spatial intensity matching."""
        generated = (((self.volume_ramp_speed_ratio - 1.0) / self.volume_ramp_speed_ratio)
                     * self.volume_rest_level if self.dynamic_volume else 0.0)
        response = scale_response(generated, self.volume_response_min, self.volume_response_max)
        # Reading the idle bound must not replace the live current-volume marker.
        return shape_output(self.parameter_curves['primary_volume'], response,
                            self.volume_response_min, self.volume_response_max)[0]

    def _reset_reversal_tracking(self) -> None:
        self._last_reversal_time: float | None = None
        self._turn_direction = 0                      # +1 rising, -1 falling, 0 unknown.
        self._turn_extreme: float | None = None       # Furthest position this way.
        self._turn_anchor: float | None = None        # Last position that dated the extreme.
        self._turn_anchor_time: float | None = None
        self._turn_last_value: float | None = None
        self._turn_last_move_time: float | None = None

    def _track_reversal(self, value: float, now: float) -> None:
        """Turning points for the reversal window, with a movement deadband.

        Moves smaller than REVERSAL_DEADBAND neither reverse the direction nor
        re-date the extreme, and movement that starts after L0 has stood still
        for longer than Rest after cannot re-date the old stroke either.  So a
        tiny nudge after a pause cannot make a later parking move look like a
        fresh turn.  Separate from the stroke detection that shapes the
        output, which is unchanged.
        """
        band = REVERSAL_DEADBAND
        continuous = (self._turn_last_move_time is not None
                      and now - self._turn_last_move_time <= self.volume_idle_seconds)
        if self._turn_last_value is None or abs(value - self._turn_last_value) > 0.00005:
            self._turn_last_move_time = now
        self._turn_last_value = value
        if self._turn_extreme is None:
            self._turn_extreme = self._turn_anchor = value
            self._turn_anchor_time = now
            return
        direction = self._turn_direction
        if direction >= 0 and value > self._turn_extreme:
            self._turn_extreme = value
        elif direction <= 0 and value < self._turn_extreme:
            self._turn_extreme = value
        if direction == 0:
            if abs(value - self._turn_anchor) > band:
                self._turn_direction = 1 if value > self._turn_anchor else -1
                self._turn_extreme = self._turn_anchor = value
                self._turn_anchor_time = now
            return
        if direction * (value - self._turn_anchor) > band:
            # Clearly further the same way: the extreme is dated now, unless
            # this move only began after L0 had stopped.
            self._turn_anchor = value
            if continuous:
                self._turn_anchor_time = now
        elif direction * (self._turn_extreme - value) > band:
            # Clearly back the other way: the turn happened at the anchor time.
            self._last_reversal_time = self._turn_anchor_time
            self._turn_direction = -direction
            self._turn_extreme = self._turn_anchor = value
            self._turn_anchor_time = now

    def _recently_driven(self, at_time: float) -> bool:
        """Shared rest gate: recent input and, if required, a recent reversal."""
        if (at_time - self._last_input_time) > self.volume_idle_seconds:
            return False
        if self.stroke_reversal_window > 0.0:
            return (self._last_reversal_time is not None
                    and at_time - self._last_reversal_time <= self.stroke_reversal_window)
        return True

    def _reset_rest_fall(self) -> None:
        # Level factors (rest level .. 1) last applied, and where a fall began.
        self._volume_factor: float | None = None
        self._volume_fall_from = self._volume_fall_since = None
        self._volume_rise_from: float | None = None
        self._prostate_factor = 1.0
        self._prostate_was_active = False
        self._prostate_fall_from = self._prostate_fall_since = None

    def _falling_factor(self, at_time: float, since: float | None,
                        start: float | None, rest: float) -> float:
        """S-curve (half cosine) from start to rest over volume_fall_seconds."""
        if self.volume_fall_seconds <= 0.0 or since is None or start is None:
            return rest
        progress = (at_time - since) / self.volume_fall_seconds
        if progress >= 1.0:
            return rest
        progress = max(0.0, progress)
        return rest + (start - rest) * (0.5 + 0.5 * math.cos(math.pi * progress))

    def _calculate_volume(self, at_time: float, speed_percent: float) -> float:
        if not self.dynamic_volume:
            return self._volume_response(1.0)
        active = self._recently_driven(at_time) and speed_percent > 0.5
        ratio = self.volume_ramp_speed_ratio
        generated = ((ratio - 1.0) + min(1.0, max(0.0, speed_percent / 100.0))) / ratio
        rest = self.volume_rest_level
        if not active:
            if self._volume_was_active:
                self._volume_fall_since = at_time
                self._volume_fall_from = self._volume_factor
            self._volume_was_active = False
            factor = self._falling_factor(at_time, self._volume_fall_since,
                                          self._volume_fall_from, rest)
            self._volume_factor = factor
            return self._volume_response(generated * factor)
        if not self._volume_was_active:
            self._volume_active_since = at_time
            self._volume_was_active = True
            # The return ramp starts wherever a fall had reached (rest if none).
            self._volume_rise_from = (rest if self._volume_factor is None
                                      else self._volume_factor)
        if self.volume_ramp_up_seconds <= 0:
            attack = 1.0
        else:
            progress = min(1.0, max(0.0, (at_time - self._volume_active_since) /
                                        self.volume_ramp_up_seconds))
            start = rest if self._volume_rise_from is None else self._volume_rise_from
            attack = start + (1.0 - start) * progress
        self._volume_factor = attack
        return self._volume_response(generated * attack)

    def set_parameter_curves(self, curves):
        curves = validate_parameter_curves(curves)
        with self._lock:
            self.parameter_curves = curves

    def parameter_curve_snapshot(self):
        with self._lock:
            return dict(self._parameter_curve_live)

    def pulse_command_ranges(self):
        with self._lock:
            return ((self.frequency_min, self.frequency_max),
                    (self.pulse_frequency_min, self.pulse_frequency_max),
                    (self.pulse_rise_min, self.pulse_rise_max),
                    (self.pulse_width_min, self.pulse_width_max))

    def _shape_parameter(self, name, value, low, high):
        output, drive = shape_output(self.parameter_curves[name], value, low, high)
        self._parameter_curve_live[name] = (drive, output, low, high)
        return output

    def _calculate_frequency(self, at_time: float, speed_percent: float) -> float:
        speed = (speed_percent / 100.0
                 if self._recently_driven(at_time) else 0.0)
        ratio = self.frequency_ramp_speed_ratio
        value = min(1.0, max(0.0,
            (self.frequency_ramp_level * (ratio - 1.0) + speed) / ratio))
        return self._shape_parameter('frequency',
            scale_response(value, self.frequency_min, self.frequency_max), self.frequency_min, self.frequency_max)

    def _calculate_pulse_frequency(self, at_time: float, speed_percent: float,
                                   alpha: float) -> float:
        active = (self._recently_driven(at_time)
                  and speed_percent > 0.5 and alpha > 1e-6)
        speed = min(1.0, max(0.0, speed_percent / 100.0))
        ratio = self.pulse_frequency_ratio
        combined = (speed * (ratio - 1.0) + min(1.0, max(0.0, alpha))) / ratio
        if not active:
            self._pulse_was_active = False
            combined *= self.volume_rest_level
        else:
            if not self._pulse_was_active:
                self._pulse_active_since = at_time
                self._pulse_was_active = True
            if self.volume_ramp_up_seconds > 0:
                progress = min(1.0, max(0.0,
                    (at_time - self._pulse_active_since) / self.volume_ramp_up_seconds))
                combined *= self.volume_rest_level + (1.0 - self.volume_rest_level) * progress
        return self._shape_parameter('pulse_frequency',
            self.pulse_frequency_min + combined * (self.pulse_frequency_max - self.pulse_frequency_min),
            self.pulse_frequency_min, self.pulse_frequency_max)

    def _calculate_pulse_rise_time(self, speed_percent: float) -> float:
        inverted_ramp = 1.0 - self.frequency_ramp_level
        inverted_speed = 1.0 - min(1.0, max(0.0, speed_percent / 100.0))
        ratio = self.pulse_rise_ratio
        combined = (inverted_ramp * (ratio - 1.0) + inverted_speed) / ratio
        return self._shape_parameter('pulse_rise_time',
            self.pulse_rise_min + combined * (self.pulse_rise_max - self.pulse_rise_min),
            self.pulse_rise_min, self.pulse_rise_max)

    def _calculate_pulse_width(self, at_time: float, speed_percent: float,
                               output_l0: float) -> float:
        active = self._recently_driven(at_time) and speed_percent > 0.5
        speed = min(1.0, max(0.0, speed_percent / 100.0))
        inverted_l0 = 1.0 - min(1.0, max(0.0, output_l0))
        ratio = self.pulse_width_ratio
        combined = (speed * (ratio - 1.0) + inverted_l0) / ratio
        if not active:
            self._width_was_active = False
            combined *= self.volume_rest_level
        else:
            if not self._width_was_active:
                self._width_active_since = at_time
                self._width_was_active = True
            if self.volume_ramp_up_seconds > 0:
                progress = min(1.0, max(0.0,
                    (at_time - self._width_active_since) / self.volume_ramp_up_seconds))
                combined *= self.volume_rest_level + (1.0 - self.volume_rest_level) * progress
        return self._shape_parameter('pulse_width',
            scale_response(combined, self.pulse_width_min, self.pulse_width_max),
            self.pulse_width_min, self.pulse_width_max)

    def _calculate_prostate(self, stroke: SegmentState, at_time: float) -> tuple[float, float]:
        # RFP tear-shaped prostate path is generated from inverted L0.
        start = 1.0 - stroke.start_position
        end = 1.0 - stroke.end_position
        progress = stroke.progress(at_time) + self.prostate_phase_degrees / 180.0
        # One source stroke is half of a reciprocating 360-degree cycle. Crossing
        # either endpoint therefore continues into the mirrored neighbouring
        # stroke instead of clamping and dwelling at the endpoint.
        if progress > 1.0:
            start, end = end, start
            progress -= 1.0
        elif progress < 0.0:
            start, end = end, start
            progress += 1.0
        progress = min(1.0, max(0.0, progress))
        alpha = start + progress * (end - start)
        stroke_range = abs(end - start)
        beta = 0.5
        if stroke_range >= self.prostate_stroke_threshold:
            going_up = end > start
            bulge = min(stroke_range / 2.0, 0.5) * self.prostate_arc_depth
            # A true tear occupies opposite sides of beta=0.5. Because the
            # working position is inverted L0, going_up here is the source
            # downstroke: beta is positive on the way down and negative on the
            # way up. Side arc depth keeps both deviations deliberately small.
            beta_direction = bulge if going_up else -(bulge * self.prostate_narrow_ratio)
            beta = 0.5 + beta_direction * math.sin(progress * math.pi)
        return min(1.0, max(0.0, alpha)), min(1.0, max(0.0, beta))

    def _calculate_known_prostate(self, at_time: float, variation_depth: float,
                                  bounds: tuple[float, float]) -> tuple[float, float]:
        """Calculate the prostate path from a generated plan's known bounds."""
        low, high = bounds

        def transformed(value: float) -> float:
            point = SegmentState(0, at_time, at_time, value, value)
            point = self._modified_segment(point, at_time)
            point = self._jitter_segment(point, variation_depth)
            return point.end_position

        value = transformed(self._raw_l0)
        low, high = sorted((transformed(low), transformed(high)))
        if high - low <= 1e-9 or self._stroke_direction == 0:
            return 1.0 - value, 0.5
        if self._stroke_direction > 0:
            start, end = low, high
            progress = (value - low) / (high - low)
        else:
            start, end = high, low
            progress = (high - value) / (high - low)
        synthetic = SegmentState(0, 0.0, 1.0, start, end,
                                 self._segment.speed_percent)
        return self._calculate_prostate(
            synthetic, min(1.0, max(0.0, progress)))

    def _calculate_prostate_volume(self, at_time: float, speed_percent: float) -> float:
        ratio = min(40.0, self.volume_ramp_speed_ratio * self.prostate_volume_multiplier)
        speed = min(1.0, max(0.0, speed_percent / 100.0))
        generated = ((ratio - 1.0) + speed) / ratio
        active = self._recently_driven(at_time) and speed_percent > 0.5
        if active:
            # Prostate V0 has no return ramp: it is back to full at once.
            self._prostate_was_active = True
            self._prostate_factor = 1.0
            return self._volume_response(generated, 'prostate_volume')
        if self._prostate_was_active:
            self._prostate_fall_since = at_time
            self._prostate_fall_from = self._prostate_factor
            self._prostate_was_active = False
        self._prostate_factor = self._falling_factor(
            at_time, self._prostate_fall_since, self._prostate_fall_from,
            self.prostate_rest_level)
        return self._volume_response(generated * self._prostate_factor, 'prostate_volume')

    def _loop(self) -> None:
        next_tick = self.clock()
        while self._run.is_set():
            with self._lock:
                period = 1.0 / self.rate_hz
                state = self._state
                volume = self.volume
            now = self.clock()
            if state in ("Neutral", "Stopped"):
                if self.input_tick is not None:
                    self.input_tick(now)
                # Networking layer emits transition commands; scheduler stays idle.
                time.sleep(0.01)
                next_tick = self.clock()
                continue
            if now < next_tick:
                time.sleep(min(next_tick - now, 0.01))
                continue
            # If the OS stalls, skip stale calculations instead of burst-sending them.
            if now - next_tick > period * 2:
                next_tick = now
            if self.input_tick is not None:
                self.input_tick(now)
            self.step(next_tick, now)
            next_tick += period
