"""Output composition, independent of UI widgets and network destinations."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping
import math
import time
from .engine import OutputSample
from .motion import MotionMode
from .output_config import OutputConfig
from .output_ranges import match_volume_response
from .custom_spatial import evaluate_curves
from .howl_conversion import LiveConversion, positional as howl_positional
from .events import AXIS_AUTHORED
from .focus import apply_top_focus, apply_bottom_focus_window
from .spatial_gain import apply_gain
from .fourphase import (ELECTRODE_ORDERS, adaptive_crossover_width, apply_group_delay,
                        depth_spread, directional_crossover_profile, map_electrode_order,
                        morph_electrode_order, moving_sequence_window, sequence_cycle_stage,
                        proportional_reversal_boost, reversal_emphasis_envelope,
                        stroke_phase_crossover, restim_crossfade)

@dataclass(frozen=True)
class CompositionResult:
    primary_args: tuple
    primary_overrides: Mapping[str, float] | None
    prostate_args: tuple
    outgoing_volumes: tuple[float, float]
    spatial_output: tuple
    gain_displays: tuple[str, str]

class OutputComposer:
    def __init__(self, engine, axis_router, event_engine, top_gain, bottom_gain, bottom_focus):
        self.passage = None
        self._pulse_damping_state = None
        self.applied_motion_mode = None
        self._keyframe_arc_applied = False
        self._mode_from = None
        self._mode_changed_at = 0.0
        self._last_spatial = None
        self.engine = engine
        self.axis_router = axis_router
        self.event_engine = event_engine
        self._top_spatial_gain = top_gain
        self._bottom_spatial_gain = bottom_gain
        self._bottom_focus_transition = bottom_focus
        self._howl_converter = LiveConversion()

        self._howl_frame = None

        self._four_phase_send_last_l0 = 0.5

        self._four_phase_send_direction = 1

        self._motion_send_last_l0 = 0.5

        self._motion_send_direction = 1

        self._four_phase_history = deque(maxlen=128)

        self._four_phase_effective_group_delay = 0.0

        self._four_phase_group_delay_last_time = None


    def reset_motion_direction(self) -> None:
        self._motion_send_last_l0 = 0.5
        self._motion_send_direction = 1

    def reset_pulse_damping(self) -> None:
        self._pulse_damping_state = None

    def _damp_primary_pulse(self, values, due_at, config, howl_pulse, smoothed_axes=()):
        seconds = (config.frequency_damping, config.pulse_frequency_damping,
                   config.pulse_rise_damping, config.pulse_width_damping)
        if smoothed_axes:
            seconds = tuple(
                0.0 if smoothed and not (howl_pulse and axis in (1, 3)) else tau
                for axis, (smoothed, tau) in enumerate(zip(smoothed_axes, seconds)))
        previous = self._pulse_damping_state
        if previous is not None and any(seconds):
            last_at, last_values = previous
            elapsed = due_at - last_at
            if elapsed >= 0:
                limits = list(self.engine.pulse_command_ranges())
                if howl_pulse:
                    limits[1] = limits[3] = (0.0, 1.0)
                damped = []
                for target, prior, tau, (low, high) in zip(values, last_values, seconds, limits):
                    if tau > 0:
                        # Use the scheduled command interval, independent of the configured sample rate.
                        target = prior + (target - prior) * -math.expm1(-elapsed / tau)
                        target = max(low, min(high, target))
                    damped.append(target)
                values = tuple(damped)
        self._pulse_damping_state = (due_at, values)
        return values

    @property
    def effective_group_delay(self) -> float:
        return self._four_phase_effective_group_delay

    @property
    def last_path_position(self) -> float:
        return self._four_phase_send_last_l0

    def reset_group_delay(self) -> None:
        self._four_phase_history.clear()
        self._four_phase_effective_group_delay = 0.0
        self._four_phase_group_delay_last_time = None

    def _spatial_path(self, output_l0: float, variation_depth: float = 1.0, *, config) -> float:
        return 1.0 - output_l0 if config.four_phase_invert else output_l0


    def _four_phase_profile(
            self, path_l0: float, direction: int, speed_percent: float,
            stroke_progress: float, variation_depth: float,
            at_time: float | None = None
            , *, config) -> tuple[tuple[float, float, float, float], str, str, float, str]:
        """Build logical E1-E4 values, then apply physical sequence mapping."""
        if config.four_phase_spatial_model == "Custom":
            logical = evaluate_curves(config.custom_curves, path_l0)
            order = config.electrode_order
            return map_electrode_order(logical, order), order, order, 0.0, "custom"
        if config.four_phase_spatial_model.startswith("Howl "):
            logical = (self._howl_frame.electrodes if self._howl_frame else
                       howl_positional(path_l0, config.howl_width))
            order = config.electrode_order
            return map_electrode_order(logical, order), order, order, 0.0, "howl"
        if config.four_phase_spatial_model == "Depth spread":
            logical = depth_spread(
                path_l0, config.four_phase_tip_retention,
                config.four_phase_spread_softness,
                config.four_phase_full_depth_capture)
            order = config.electrode_order
            return map_electrode_order(logical, order), order, order, 0.0, "depth spread"

        width, curve, sharpness, _ = self._crossover_profile(
            speed_percent, direction, stroke_progress, variation_depth, config=config)
        logical = restim_crossfade(
            path_l0, direction, config.four_phase_return_depth,
            width, curve, sharpness)
        source, target, amount, kind = self._sequence_morph_state(
            direction, stroke_progress, variation_depth, at_time, config=config)
        if source == target:
            return map_electrode_order(logical, source), source, target, amount, kind
        return (morph_electrode_order(logical, source, target, amount),
                source, target, amount, kind)


    def _electrode_morph_state(self, at_time: float | None = None
                               , *, config) -> tuple[str, str, float]:
        base = config.electrode_order
        if not (config.variety_enabled and config.variety_electrode_morph):
            return base, base, 0.0
        elapsed = (time.monotonic() if at_time is None else at_time) - config.variety_started
        stage_seconds = max(1.0, config.variety_electrode_morph_cycle * 60.0)
        transition_seconds = min(stage_seconds,
            max(.1, config.variety_electrode_morph_transition_seconds))
        full_cycle = stage_seconds * len(ELECTRODE_ORDERS)
        return sequence_cycle_stage(
            base, (elapsed % full_cycle) / full_cycle,
            transition_seconds / stage_seconds)


    def _sequence_morph_state(self, direction: int, stroke_progress: float,
                              variation_depth: float, at_time: float | None = None
                              , *, config) -> tuple[str, str, float, str]:
        if config.four_phase_spatial_model == "Depth spread":
            order = config.electrode_order
            return order, order, 0.0, "depth spread"
        carousel_active = config.variety_enabled and config.variety_electrode_morph
        if config.four_phase_moving_sequence and not carousel_active:
            source, target, amount = moving_sequence_window(
                config.electrode_order, direction, stroke_progress,
                config.four_phase_moving_sequence_depth * variation_depth,
                config.four_phase_moving_sequence_width)
            return source, target, amount, "window"
        source, target, amount = self._electrode_morph_state(at_time, config=config)
        return source, target, amount, ("carousel" if carousel_active else "stable")


    def _effective_crossover_width(self, speed_percent: float, *, config) -> float:
        if not config.four_phase_adaptive_crossover:
            return min(1.0, max(.05, config.four_phase_crossover_width))
        return adaptive_crossover_width(
            speed_percent, config.four_phase_slow_crossover_width,
            config.four_phase_fast_crossover_width)


    def _crossover_profile(self, speed_percent: float, direction: int,
                           stroke_progress: float = .5, variation_depth: float = 1.0
                           , *, config) -> tuple[float, str, float, str]:
        variation_depth = min(1.0, max(0.0, variation_depth))
        base_width = min(1.0, max(.05, config.four_phase_crossover_width))
        adaptive_width = self._effective_crossover_width(speed_percent, config=config)
        adaptive_width = base_width + (adaptive_width - base_width) * variation_depth
        reverse_scale = 1.0 + (config.four_phase_reverse_width_scale - 1.0) * variation_depth
        width, curve, sharpness, direction_name = directional_crossover_profile(
            direction, adaptive_width,
            config.four_phase_crossover_curve,
            config.four_phase_crossover_sharpness,
            config.four_phase_directional_trajectory and variation_depth > .001,
            reverse_scale,
            config.four_phase_reverse_curve,
            (config.four_phase_crossover_sharpness +
             (config.four_phase_reverse_sharpness -
              config.four_phase_crossover_sharpness) * variation_depth))
        acceleration_scale = 1.0 + (
            config.four_phase_acceleration_width_scale - 1.0) * variation_depth
        deceleration_scale = 1.0 + (
            config.four_phase_deceleration_width_scale - 1.0) * variation_depth
        width, phase_name = stroke_phase_crossover(
            width, stroke_progress, config.four_phase_stroke_phase_texture,
            acceleration_scale, deceleration_scale)
        if config.four_phase_stroke_phase_texture:
            direction_name = f"{direction_name} {phase_name}"
        return width, curve, sharpness, direction_name


    def _spatial_gain_parameters(self, region: str, *, config) -> tuple[float, float, float, float]:
        if region == "top":
            return (config.top_spatial_gain_step_percent / 100.0,
                    config.top_spatial_gain_min_percent / 100.0,
                    config.top_spatial_gain_max_percent / 100.0,
                    config.spatial_gain_ramp_percent_per_second / 100.0)
        if region == "bottom":
            return (config.bottom_spatial_gain_step_percent / 100.0,
                    config.bottom_spatial_gain_min_percent / 100.0,
                    config.bottom_spatial_gain_max_percent / 100.0,
                    config.spatial_gain_ramp_percent_per_second / 100.0)
        raise ValueError("region must be top or bottom")


    def _blend_motion(self, sample, keyframe_arcs=False):
        incoming = sample.mode.value
        use_arc = (keyframe_arcs and sample.mode is MotionMode.RESTIM_ORIGINAL
                   and sample.keyframe_arc is not None)
        if use_arc:
            sample = replace(sample, alpha=sample.keyframe_arc[0], beta=sample.keyframe_arc[1])
        if self.applied_motion_mode is not None and (
                incoming != self.applied_motion_mode or use_arc != self._keyframe_arc_applied):
            self._mode_from = self._last_spatial
            self._mode_changed_at = sample.due_at
        self.applied_motion_mode = incoming
        self._keyframe_arc_applied = use_arc
        if self._mode_from is not None:
            amount = min(1.0, max(0.0, (sample.due_at-self._mode_changed_at)/2.0))
            amount = amount*amount*(3-2*amount)
            old_a, old_b = self._mode_from
            sample = replace(sample, alpha=old_a+(sample.alpha-old_a)*amount,
                             beta=old_b+(sample.beta-old_b)*amount)
            if amount >= 1: self._mode_from = None
        self._last_spatial = (sample.alpha, sample.beta)
        return sample

    def compose(self, sample: OutputSample, config: OutputConfig) -> CompositionResult:
        sample = self._blend_motion(sample, config.magik_keyframe_arcs)
        variation_depth = (sample.variation_depth
                           if config.speed_linked_variation else 1.0)
        motion_delta = sample.output_l0 - self._motion_send_last_l0
        if abs(motion_delta) > 0.0005:
            self._motion_send_direction = 1 if motion_delta > 0 else -1
        self._motion_send_last_l0 = sample.output_l0
        howl_mode = config.four_phase_spatial_model.startswith("Howl ")
        match_intensity = config.match_spatial_intensity
        if howl_mode or match_intensity:
            source_l0 = 1-sample.raw_l0 if config.four_phase_invert else sample.raw_l0
            self._howl_frame = self._howl_converter.sample(
                sample.calculated_at, source_l0,
                config.four_phase_spatial_model if howl_mode else "Howl Positional",
                config.howl_width, config.howl_pan,
                config.howl_boost, config.howl_sigma,
                config.howl_balance_a, config.howl_balance_b,
                config.howl_scaling, config.howl_position_strength)
            path_l0 = source_l0 if howl_mode else self._spatial_path(sample.output_l0, variation_depth, config=config)
        else:
            self._howl_converter = LiveConversion()
            self._howl_frame = None
            path_l0 = self._spatial_path(sample.output_l0, variation_depth, config=config)
        delta = path_l0 - self._four_phase_send_last_l0
        if abs(delta) > 0.0005:
            self._four_phase_send_direction = 1 if delta > 0 else -1
        self._four_phase_send_last_l0 = path_l0
        electrodes, morph_source, morph_target, morph_amount, profile_kind = \
            self._four_phase_profile(
            path_l0, self._four_phase_send_direction, sample.speed_percent,
            sample.stroke_progress, variation_depth, sample.due_at, config=config)
        self._four_phase_history.append((sample.due_at, electrodes))
        target_delay = 0.0
        if config.four_phase_group_delay and profile_kind not in ("depth spread", "howl", "custom"):
            target_delay = min(.300, max(-.300,
                config.four_phase_group_delay_ms / 1000.0)) * variation_depth
        previous_time = self._four_phase_group_delay_last_time
        self._four_phase_group_delay_last_time = sample.due_at
        dt = max(0.0, sample.due_at - previous_time) if previous_time is not None else 0.0
        transition = max(.1, config.four_phase_group_delay_transition)
        blend = 1.0 - math.exp(-dt / transition) if dt > 0 else 0.0
        self._four_phase_effective_group_delay += (
            target_delay - self._four_phase_effective_group_delay) * blend
        if abs(target_delay) <= 1e-9 and abs(self._four_phase_effective_group_delay) < 1e-5:
            self._four_phase_effective_group_delay = 0.0
        if profile_kind in ("depth spread", "howl", "custom"):
            self._four_phase_effective_group_delay = 0.0
        else:
            electrodes = apply_group_delay(
                electrodes, list(self._four_phase_history), sample.due_at,
                self._four_phase_effective_group_delay)
        electrodes = apply_top_focus(
            electrodes, config.director_top_focus,
            nominal_ceiling=config.top_focus_nominal_ceiling,
            strength=config.top_focus_strength, path_position=path_l0)
        spatial_output = (electrodes, morph_source, morph_target, morph_amount, profile_kind)
        ceiling = min(1.0, max(0.0, config.four_phase_volume_ceiling))
        if config.four_phase_volume_modulation:
            cycle = max(.5, config.four_phase_volume_cycle) * 60.0
            wave = (1.0 - math.cos((sample.calculated_at % cycle)
                                   * 2.0 * math.pi / cycle)) / 2.0
            ceiling = min(1.0, ceiling +
                          config.four_phase_volume_headroom * wave * variation_depth)
        # Undo the Base volume this sample was calculated with, not the current
        # one: queued samples outlive a Base volume change.
        volume_scale = (sample.volume_scale if sample.volume_scale is not None
                        else config.volume)
        primary_volume = min(1.0, max(0.0,
            ceiling * sample.volume / max(volume_scale, 1e-9)))
        if match_intensity or howl_mode:
            intensity = (self._howl_frame.matched_volume if match_intensity
                         else self._howl_frame.volume)
            response = sample.volume / max(volume_scale, 1e-9)
            rest_response = self.engine.volume_rest_response()
            primary_volume = (ceiling * match_volume_response(response, intensity, rest_response)
                              if sample.volume > 0 else 0.0)
        if config.four_phase_stroke_phase_texture:
            configured = (config.motion_rising_volume_multiplier
                          if self._motion_send_direction > 0
                          else config.motion_falling_volume_multiplier)
            multiplier = 1.0 + (min(1.0, max(.8, configured)) - 1.0) * variation_depth
            primary_volume *= multiplier
        if config.four_phase_reversal_emphasis:
            reversal = reversal_emphasis_envelope(
                sample.reversal_distance_seconds, config.four_phase_reversal_window)
            boost = min(1.0, max(0.0,
                config.four_phase_reversal_strength * variation_depth))
            primary_volume = proportional_reversal_boost(
                primary_volume, reversal, boost)
        primary_volume = min(1.0, max(0.0, primary_volume))
        now_gain = time.monotonic()
        _, _, _, gain_ramp = self._spatial_gain_parameters("top", config=config)
        top_gain = self._top_spatial_gain.update(ramp_per_second=gain_ramp, now=now_gain)
        _, _, _, bottom_gain_ramp = self._spatial_gain_parameters("bottom", config=config)
        bottom_gain = self._bottom_spatial_gain.update(ramp_per_second=bottom_gain_ramp, now=now_gain)
        gain_displays = (
            f"{self._top_spatial_gain.target * 100:.0f}% target · {top_gain * 100:.0f}% live",
            f"{self._bottom_spatial_gain.target * 100:.0f}% target · {bottom_gain * 100:.0f}% live")
        primary_volume = apply_gain(primary_volume, top_gain)
        if config.authored_routing_mode == "Auto authored ReStim set":
            authored_overrides = self.axis_router.snapshot_auto(sample.calculated_at)
        else:
            authored_overrides = self.axis_router.snapshot(sample.calculated_at)
        if authored_overrides:
            e_names = ("E1", "E2", "E3", "E4")
            source_e = tuple(authored_overrides.get(name, electrodes[i]) for i, name in enumerate(e_names))
            focused_e = apply_top_focus(
                source_e, config.director_top_focus,
                nominal_ceiling=config.top_focus_nominal_ceiling,
                strength=config.top_focus_strength, path_position=path_l0)
            authored_overrides = dict(authored_overrides)
            for name, value in zip(e_names, focused_e):
                if name in authored_overrides:
                    authored_overrides[name] = value
            if "V0" in authored_overrides:
                authored_overrides["V0"] = apply_gain(authored_overrides["V0"], top_gain)
        focused_alpha_prostate = apply_bottom_focus_window(
            sample.alpha_prostate,
            self._bottom_focus_transition.window(now=sample.due_at),
            strength=config.bottom_focus_strength)
        prostate_volume = sample.volume_prostate
        if volume_scale > 0.0 and config.volume != volume_scale:
            # Prostate is its response x Base volume: apply the current Base volume.
            prostate_volume = min(1.0, max(0.0,
                prostate_volume * config.volume / volume_scale))
        bottom_volume = apply_gain(prostate_volume, bottom_gain)
        primary_alpha = sample.alpha
        primary_beta = sample.beta
        primary_frequency, primary_pulse_frequency, primary_pulse_rise, primary_pulse_width = (
            sample.shifted_primary_pulse or sample.primary_pulse)
        howl_pulse = howl_mode and config.howl_pulse
        if howl_pulse:
            # These normalized axes require the ranges displayed in the UI.
            low = min(100.0, max(1.0, config.howl_freq_min))
            high = min(100.0, max(low, config.howl_freq_max))
            hz = low + (high-low) * self._howl_frame.frequency
            primary_pulse_frequency = (hz-1)/99
            cycles = round(5 + min(1.0, max(0.0, config.howl_thump))*15*(1-(min(50, max(1, hz))-1)/49)**1.5)
            primary_pulse_width = (cycles-3)/17
        primary_frequency, primary_pulse_frequency, primary_pulse_rise, primary_pulse_width = (
            self._damp_primary_pulse(
                (primary_frequency, primary_pulse_frequency, primary_pulse_rise, primary_pulse_width),
                sample.due_at, config, howl_pulse, sample.primary_pulse_smoothed))
        if config.director_events_enabled:
            event_base = authored_overrides or {}
            event_values = self.event_engine.apply_triggers(sample.due_at, {
                "volume": event_base.get("V0", primary_volume),
                "volume-prostate": bottom_volume,
                "frequency": event_base.get("C0", primary_frequency),
                "pulse_frequency": event_base.get("P0", primary_pulse_frequency),
                "pulse_width": event_base.get("P1", primary_pulse_width),
                "alpha": event_base.get("L0", primary_alpha),
                "beta": event_base.get("L1", primary_beta),
                "e1": event_base.get("E1", electrodes[0]),
                "e2": event_base.get("E2", electrodes[1]),
                "e3": event_base.get("E3", electrodes[2]),
                "e4": event_base.get("E4", electrodes[3]),
                "sensor_suppression": event_base.get("S1", 0.0),
            })
            primary_volume = event_values["volume"]
            bottom_volume = event_values["volume-prostate"]
            primary_frequency = event_values["frequency"]
            primary_pulse_frequency = event_values["pulse_frequency"]
            primary_pulse_width = event_values["pulse_width"]
            primary_alpha = event_values["alpha"]
            primary_beta = event_values["beta"]
            electrodes = tuple(event_values[f"e{i}"] for i in range(1, 5))
            if authored_overrides:
                authored_overrides = dict(authored_overrides)
                for event_axis, authored_axis in AXIS_AUTHORED.items():
                    if authored_axis in authored_overrides:
                        authored_overrides[authored_axis] = event_values[event_axis]
        if self.passage is not None:
            primary_factor, secondary_factor = self.passage.factors_now()
            primary_volume = min(1.0, primary_volume * primary_factor)
            bottom_volume *= secondary_factor
            if authored_overrides and "V0" in authored_overrides:
                authored_overrides = dict(authored_overrides)
                authored_overrides["V0"] = min(1.0, authored_overrides["V0"] * primary_factor)
        if config.volume <= 0.0:
            # Zero Base volume mutes both generated outputs.  Queued samples were
            # scaled by the earlier Base volume, and dividing them by zero above
            # would clamp Primary to 100%.  Authored V0 overrides keep ownership.
            primary_volume = bottom_volume = 0.0
        outgoing_volumes = (
            authored_overrides.get("V0", primary_volume) if authored_overrides else primary_volume,
            bottom_volume)
        primary_args = (
            primary_alpha, primary_beta, tuple(electrodes), primary_volume, primary_frequency,
            primary_pulse_frequency, primary_pulse_rise, primary_pulse_width)
        primary_overrides = dict(authored_overrides) if authored_overrides else None
        prostate_args = (
            focused_alpha_prostate, sample.beta_prostate, bottom_volume,
            sample.frequency,
            sample.pulse_frequency if sample.secondary_pulse_frequency is None else sample.secondary_pulse_frequency,
            sample.pulse_width if sample.secondary_pulse_width is None else sample.secondary_pulse_width,
            sample.pulse_rise_time)
        return CompositionResult(
            primary_args, MappingProxyType(primary_overrides) if primary_overrides else None,
            prostate_args, outgoing_volumes, spatial_output, gain_displays)
