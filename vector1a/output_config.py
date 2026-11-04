"""Immutable configuration read by one output-composition sample."""
from dataclasses import dataclass
from types import MappingProxyType

@dataclass(frozen=True)
class OutputConfig:
    authored_routing_mode: str
    bottom_focus_strength: float
    bottom_spatial_gain_max_percent: float
    bottom_spatial_gain_min_percent: float
    bottom_spatial_gain_step_percent: float
    director_events_enabled: bool
    director_top_focus: str
    electrode_order: str
    four_phase_acceleration_width_scale: float
    four_phase_adaptive_crossover: bool
    four_phase_crossover_curve: str
    four_phase_crossover_sharpness: float
    four_phase_crossover_width: float
    four_phase_deceleration_width_scale: float
    four_phase_directional_trajectory: bool
    four_phase_fast_crossover_width: float
    four_phase_full_depth_capture: float
    four_phase_group_delay: bool
    four_phase_group_delay_ms: float
    four_phase_group_delay_transition: float
    four_phase_invert: bool
    four_phase_moving_sequence: bool
    four_phase_moving_sequence_depth: float
    four_phase_moving_sequence_width: float
    four_phase_return_depth: float
    four_phase_reversal_emphasis: bool
    four_phase_reversal_strength: float
    four_phase_reversal_window: float
    four_phase_reverse_curve: str
    four_phase_reverse_sharpness: float
    four_phase_reverse_width_scale: float
    four_phase_slow_crossover_width: float
    four_phase_spatial_model: str
    four_phase_spread_softness: float
    four_phase_stroke_phase_texture: bool
    four_phase_tip_retention: float
    four_phase_volume_ceiling: float
    four_phase_volume_cycle: float
    four_phase_volume_headroom: float
    four_phase_volume_modulation: bool
    howl_balance_a: float
    howl_balance_b: float
    howl_boost: float
    howl_freq_max: float
    howl_freq_min: float
    howl_pan: float
    howl_position_strength: float
    howl_pulse: bool
    howl_scaling: float
    howl_sigma: float
    howl_thump: float
    howl_width: float
    match_spatial_intensity: bool
    motion_falling_volume_multiplier: float
    motion_rising_volume_multiplier: float
    spatial_gain_ramp_percent_per_second: float
    speed_linked_variation: bool
    top_focus_nominal_ceiling: float
    top_focus_strength: float
    top_spatial_gain_max_percent: float
    top_spatial_gain_min_percent: float
    top_spatial_gain_step_percent: float
    variety_electrode_morph: bool
    variety_electrode_morph_cycle: float
    variety_electrode_morph_transition_seconds: float
    variety_enabled: bool
    volume: float
    custom_curves: tuple
    variety_started: float


def freeze_curves(curves):
    return tuple(MappingProxyType({'interpolation': c['interpolation'],
                                  'points': tuple(tuple(p) for p in c['points'])})
                 for c in curves)
