from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
from collections import deque
import math
import threading
import time
from typing import Callable

from .motion import MotionCalculator, MotionMode, MotionParameters, SegmentState
from .variety import speed_linked_depth
from .modifier import ModifierValues, interpolate, transform_segment


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
        self.dynamic_volume = True
        self.volume_rest_level = 0.4
        self.volume_ramp_speed_ratio = 20.0
        self.volume_ramp_up_seconds = 1.0
        self.volume_idle_seconds = 0.25
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
        self.spatial_curve = "Linear"
        self.spatial_blend = 0.0
        self._variation_depth = 0.0
        self._variation_updated_at = now
        self._input_count = 0
        self._output_count = 0
        self._sequence = 0
        self._queue: list[tuple[float, int, OutputSample]] = []
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
                  spatial_blend: float = 0.0) -> None:
        with self._lock:
            mode_changed = mode != self.mode
            self.rate_hz = max(1, min(200, int(rate_hz)))
            self.lookahead_seconds = max(0.05, min(10.0, float(lookahead_seconds)))
            self.volume = min(1.0, max(0.0, float(volume)))
            self.mode = mode
            self.params = params
            self.dynamic_volume = bool(dynamic_volume)
            self.volume_rest_level = min(1.0, max(0.0, float(volume_rest_level)))
            self.volume_ramp_speed_ratio = min(40.0, max(10.0, float(volume_ramp_speed_ratio)))
            self.volume_ramp_up_seconds = min(10.0, max(0.0, float(volume_ramp_up_seconds)))
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
                self._state = "Buffering"


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
                   stroke_bounds: tuple[float, float] | None = None) -> None:
        now = self.clock() if received_at is None else received_at
        value = min(1.0, max(0.0, value))
        with self._lock:
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
            self._segment = SegmentState(
                self._input_count, start_time, end_time, start_position, value,
                normalized_speed,
            )
            self._last_input_time = now
            self._last_input_position = value
            if completed_stroke is not None:
                self._rewrite_completed_stroke(completed_stroke)

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
                    stroke_progress=self._stroke_progress(stroke, sample.calculated_at))
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
            self._queue.clear()
            self._output_enabled = True
            self._state = "Buffering"
            self._diag = replace(self._diag, state=self._state, buffer_fill=0)

    def neutral(self) -> None:
        with self._lock:
            self._queue.clear()
            self._output_enabled = True
            self._state = "Neutral"
            self._diag = replace(self._diag, state=self._state, buffer_fill=0)

    def stop(self) -> None:
        with self._lock:
            # Stop is a latched output gate.  Incoming MFP samples continue to be
            # observed for diagnostics/Director visibility, but they cannot restart
            # output until an explicit resume().
            self._queue.clear()
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
            )
            heapq.heappush(self._queue, (sample.due_at, sample.sequence, sample))

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

    def _release_due(self, now: float) -> None:
        due: list[OutputSample] = []
        with self._lock:
            while self._queue and self._queue[0][0] <= now:
                due.append(heapq.heappop(self._queue)[2])
            if due and self._output_enabled and self._state == "Buffering":
                self._state = "Running"
        for sample in due:
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

    def _calculate_volume(self, at_time: float, speed_percent: float) -> float:
        if not self.dynamic_volume:
            return self.volume
        active = ((at_time - self._last_input_time) <= self.volume_idle_seconds
                  and speed_percent > 0.5)
        ratio = self.volume_ramp_speed_ratio
        generated = ((ratio - 1.0) + min(1.0, max(0.0, speed_percent / 100.0))) / ratio
        if not active:
            self._volume_was_active = False
            return self.volume * generated * self.volume_rest_level
        if not self._volume_was_active:
            self._volume_active_since = at_time
            self._volume_was_active = True
        if self.volume_ramp_up_seconds <= 0:
            attack = 1.0
        else:
            progress = min(1.0, max(0.0, (at_time - self._volume_active_since) /
                                        self.volume_ramp_up_seconds))
            attack = self.volume_rest_level + (1.0 - self.volume_rest_level) * progress
        return self.volume * generated * attack

    def _calculate_frequency(self, at_time: float, speed_percent: float) -> float:
        speed = (speed_percent / 100.0
                 if (at_time - self._last_input_time) <= self.volume_idle_seconds else 0.0)
        ratio = self.frequency_ramp_speed_ratio
        return min(1.0, max(0.0,
            (self.frequency_ramp_level * (ratio - 1.0) + speed) / ratio))

    def _calculate_pulse_frequency(self, at_time: float, speed_percent: float,
                                   alpha: float) -> float:
        active = ((at_time - self._last_input_time) <= self.volume_idle_seconds
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
        return self.pulse_frequency_min + combined * (
            self.pulse_frequency_max - self.pulse_frequency_min)

    def _calculate_pulse_rise_time(self, speed_percent: float) -> float:
        inverted_ramp = 1.0 - self.frequency_ramp_level
        inverted_speed = 1.0 - min(1.0, max(0.0, speed_percent / 100.0))
        ratio = self.pulse_rise_ratio
        combined = (inverted_ramp * (ratio - 1.0) + inverted_speed) / ratio
        return self.pulse_rise_min + combined * (
            self.pulse_rise_max - self.pulse_rise_min)

    def _calculate_pulse_width(self, at_time: float, speed_percent: float,
                               output_l0: float) -> float:
        active = ((at_time - self._last_input_time) <= self.volume_idle_seconds
                  and speed_percent > 0.5)
        speed = min(1.0, max(0.0, speed_percent / 100.0))
        inverted_l0 = 1.0 - min(1.0, max(0.0, output_l0))
        limited = min(self.pulse_width_max, max(self.pulse_width_min, inverted_l0))
        ratio = self.pulse_width_ratio
        combined = (speed * (ratio - 1.0) + limited) / ratio
        if not active:
            self._width_was_active = False
            combined *= self.volume_rest_level
            return min(self.pulse_width_max, max(self.pulse_width_min, combined))
        if not self._width_was_active:
            self._width_active_since = at_time
            self._width_was_active = True
        if self.volume_ramp_up_seconds > 0:
            progress = min(1.0, max(0.0,
                (at_time - self._width_active_since) / self.volume_ramp_up_seconds))
            combined *= self.volume_rest_level + (1.0 - self.volume_rest_level) * progress
        # Unlike upstream's intermediate input limit, Vector exposes Min/Max as
        # a live controller-adjustable output range. Enforce it after blending
        # so the actual P1 command always remains inside the displayed range.
        return min(self.pulse_width_max, max(self.pulse_width_min, combined))

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
        active = ((at_time - self._last_input_time) <= self.volume_idle_seconds
                  and speed_percent > 0.5)
        if not active:
            generated *= self.prostate_rest_level
        return min(self.volume, max(0.0, self.volume * generated))

    def _loop(self) -> None:
        next_tick = self.clock()
        while self._run.is_set():
            with self._lock:
                period = 1.0 / self.rate_hz
                state = self._state
                volume = self.volume
            now = self.clock()
            if state in ("Neutral", "Stopped"):
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
            self.step(next_tick, now)
            next_tick += period
