from __future__ import annotations

import tkinter as tk
import time
import queue
import math
import threading
from collections import deque
from tkinter import filedialog, messagebox, ttk

from .engine import OutputSample, VectorEngine
from .events import AXIS_AUTHORED, EventEngine
from .motion import MotionMode, MotionParameters
from .network import LatestFrameDispatcher, MFPListener, ReStimWebSocketClient
from .routing import AuthoredAxisRouter
from .orchestration import SessionOrchestrator, port_is_open, wait_for_port
from .settings import load_settings, save_settings, settings_path
from .controller import (A, B, X, Y, START, LEFT_SHOULDER, RIGHT_SHOULDER, DPAD_UP, DPAD_DOWN,
                         DPAD_LEFT, DPAD_RIGHT, XInputController, controller_snapshot)
from .variety import fit_range_for_travel, rolling_offset, rolling_value
from .director import DirectorBridge, DirectorServer
from .generated_motion import GeneratedMotionSource, MotionPlan, PATTERNS
from .timeline import FunscriptTimeline
from .fourphase import (ELECTRODE_ORDERS, SPATIAL_MODELS, adaptive_crossover_width,
                        apply_group_delay, depth_spread, directed_signed,
                        directional_crossover_profile, map_electrode_order,
                        morph_electrode_order, moving_sequence_window, potential_roles, sequence_cycle_stage,
                        proportional_reversal_boost, reversal_emphasis_envelope,
                        stroke_phase_crossover, restim_crossfade, vertical_crossfade)
from .spatial_gain import SpatialGainController, apply_gain
from .focus import (TOP_FOCUS_LABELS, BOTTOM_FOCUS_LABELS, apply_top_focus,
                    apply_bottom_focus_window, top_focus_weights, bottom_focus_window,
                    BottomFocusTransition, FocusHistory)
from . import __version__


class RangeBar(tk.Canvas):
    def __init__(self, parent, width=520, height=24):
        super().__init__(parent, width=width, height=height, highlightthickness=1,
                         highlightbackground="#999", background="#e6e6e6")
        self._width, self._height = width, height

    def set(self, minimum: float, maximum: float, value: float) -> None:
        minimum, maximum, value = (min(1.0, max(0.0, x)) for x in (minimum, maximum, value))
        self.delete("all")
        self.create_rectangle(minimum * self._width, 1, maximum * self._width,
                              self._height - 1, fill="#08ae2a", outline="")
        x = value * self._width
        self.create_line(x, 0, x, self._height, fill="#173b8f", width=3)


class CollapsibleSection(ttk.Frame):
    def __init__(self, parent, title: str, collapsed: bool = False):
        super().__init__(parent, padding=(2, 2))
        self.title = title
        self.collapsed = collapsed
        self.summary = tk.StringVar(value="")
        self.button = ttk.Button(self, width=3, command=self.toggle)
        self.button.grid(row=0, column=0, padx=(2, 5))
        ttk.Label(self, text=title, font=("TkDefaultFont", 10, "bold")) \
            .grid(row=0, column=1, sticky="w")
        ttk.Label(self, textvariable=self.summary, foreground="#555") \
            .grid(row=0, column=2, sticky="w", padx=12)
        self.columnconfigure(2, weight=1)
        self.body = ttk.Frame(self, padding=(10, 6))
        self.body.grid(row=1, column=0, columnspan=3, sticky="nsew")
        ttk.Separator(self, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew")
        self._render()

    def toggle(self) -> None:
        self.collapsed = not self.collapsed
        self._render()

    def _render(self) -> None:
        self.button.configure(text="▶" if self.collapsed else "▼")
        if self.collapsed:
            self.body.grid_remove()
        else:
            self.body.grid()


class VectorApp:
    DIRECTOR_EVENT_CATALOG = {
        "mcb_tease": ("Tease", "Slow volume modulation with a moderate pulse rate", 12.0),
        "mcb_throb": ("Throb", "Pronounced low-rate volume modulation", 10.0),
        "mcb_calm": ("Calm", "Gentle modulation with a lower pulse rate", 15.0),
        "mcb_intensity_build": ("Intensity build", "Gradual temporary increase", 10.0),
        "mcb_release": ("Release", "Gradual temporary reduction", 8.0),
        "clutch_tranquil": ("Tranquil", "Slow, smooth volume modulation", 20.0),
        "clutch_pulse_wobble": ("Pulse wobble", "Temporary pulse-width movement", 10.0),
        "pulse_freq_shift": ("Pulse-frequency shift", "Temporary pulse-frequency offset", 5.0),
        "pulse_width_shift": ("Pulse-width shift", "Temporary pulse-width offset", 5.0),
        "volume_shift": ("Volume shift", "Small temporary volume offset", 5.0),
    }
    DIRECTOR_EVENT_MIN_SECONDS = 2.0
    DIRECTOR_EVENT_MAX_SECONDS = 30.0
    DIRECTOR_EVENT_PARAM_OVERRIDES = {
        "mcb_tease": {"tease_amplitude": 0.08},
        "mcb_throb": {"throb_amplitude": 0.10},
        "mcb_calm": {"calm_amplitude": 0.07},
        "mcb_intensity_build": {"end_boost": 0.08},
        "mcb_release": {"volume_drop": -0.10},
        "clutch_tranquil": {"calm_amplitude": 0.08},
        "volume_shift": {"shift_start": 0.05, "shift_end": 0.05},
    }
    FOUR_PHASE_PRESET_FIELDS = (
        "four_phase_return_depth", "four_phase_invert", "four_phase_volume_ceiling",
        "four_phase_volume_modulation", "four_phase_volume_headroom",
        "four_phase_volume_cycle", "four_phase_crossover_width",
        "four_phase_crossover_curve", "four_phase_crossover_sharpness",
        "four_phase_adaptive_crossover", "four_phase_slow_crossover_width",
        "four_phase_fast_crossover_width", "four_phase_directional_trajectory",
        "four_phase_reverse_width_scale", "four_phase_reverse_curve",
        "four_phase_reverse_sharpness", "four_phase_spatial_curve",
        "four_phase_spatial_blend", "four_phase_reversal_emphasis",
        "four_phase_reversal_window", "four_phase_reversal_strength",
        "four_phase_stroke_phase_texture", "four_phase_acceleration_width_scale",
        "four_phase_deceleration_width_scale", "motion_rising_volume_multiplier",
        "motion_falling_volume_multiplier", "four_phase_group_delay",
        "four_phase_group_delay_ms", "four_phase_group_delay_transition", "electrode_order",
        "four_phase_moving_sequence", "four_phase_moving_sequence_depth",
        "four_phase_moving_sequence_width",
        "four_phase_spatial_model", "four_phase_tip_retention",
        "four_phase_spread_softness", "four_phase_full_depth_capture",
    )
    TEXTURE_PROFILE_NAMES = ("Smoothest", "Smooth", "Normal", "Rough", "Roughest")
    VARIATION_PROFILE_NAMES = ("Still", "Subtle", "Normal", "Lively", "Wild")
    TOP_FOCUS_PROFILE_NAMES = TOP_FOCUS_LABELS
    BOTTOM_FOCUS_PROFILE_NAMES = BOTTOM_FOCUS_LABELS
    PRIMARY_SPATIAL_NAMES = {
        "top_moving_focus": "Top — Moving Focus",
        "top_depth_spread": "Top — Depth Spread",
    }
    SECONDARY_SPATIAL_NAMES = {
        "bottom_focus": "Bottom Focus",
    }
    TEXTURE_PROFILE_FIELDS = (
        "frequency_ramp_level",
        "pulse_frequency_min", "pulse_frequency_max",
        "pulse_rise_min", "pulse_rise_max",
        "pulse_width_min", "pulse_width_max",
        "four_phase_crossover_width", "four_phase_crossover_curve",
        "four_phase_crossover_sharpness", "four_phase_adaptive_crossover",
        "four_phase_slow_crossover_width", "four_phase_fast_crossover_width",
        "four_phase_directional_trajectory", "four_phase_reverse_width_scale",
        "four_phase_reverse_curve", "four_phase_reverse_sharpness",
        "four_phase_reversal_emphasis", "four_phase_reversal_window",
        "four_phase_reversal_strength", "four_phase_stroke_phase_texture",
        "four_phase_acceleration_width_scale", "four_phase_deceleration_width_scale",
        "four_phase_group_delay", "four_phase_group_delay_ms",
        "four_phase_group_delay_transition",
    )
    VARIATION_PROFILE_FIELDS = (
        "variety_enabled", "variety_frequency", "variety_pulse_frequency",
        "variety_pulse_rise", "variety_pulse_width", "variety_phase",
        "variety_electrode_morph",
        "variety_frequency_cycle", "variety_pulse_frequency_cycle",
        "variety_pulse_rise_cycle", "variety_pulse_width_cycle",
        "variety_phase_cycle", "variety_electrode_morph_cycle",
        "variety_electrode_morph_transition_seconds",
        "jitter_enabled", "jitter_amplitude", "jitter_cycle_seconds",
        "speed_linked_variation", "variation_full_speed_percent",
        "variation_fade_seconds", "four_phase_moving_sequence",
        "four_phase_moving_sequence_depth", "four_phase_moving_sequence_width",
    )
    TOP_FOCUS_PROFILE_FIELDS = (
        "electrode_order",
        "four_phase_crossover_width", "four_phase_slow_crossover_width",
        "four_phase_fast_crossover_width", "four_phase_spatial_curve",
        "four_phase_spatial_blend", "four_phase_directional_trajectory",
        "four_phase_moving_sequence", "four_phase_moving_sequence_depth",
        "four_phase_moving_sequence_width", "four_phase_spatial_model",
        "four_phase_tip_retention", "four_phase_spread_softness",
        "four_phase_full_depth_capture", "motion_rising_volume_multiplier",
        "motion_falling_volume_multiplier",
    )
    BOTTOM_FOCUS_PROFILE_FIELDS = (
        "prostate_narrow_ratio", "prostate_arc_depth", "prostate_threshold",
        "prostate_volume_multiplier", "prostate_rest_level", "prostate_phase_degrees",
    )

    SETTINGS_FIELDS = (
        "mfp_host", "mfp_port", "restim_host", "restim_port", "prostate_host", "prostate_port",
        "timeline_media_host", "timeline_vlc_port", "timeline_vlc_password", "timeline_mpc_port",
        "timeline_script_libraries", "timeline_auto_load_script", "timeline_clock_source",
        "four_phase_host", "four_phase_port",
        "auto_start_mfp", "auto_start_restim", "auto_start_prostate",
        "director_enabled", "director_host", "director_port", "director_events_enabled",
        "top_focus_nominal_ceiling", "top_focus_strength", "bottom_focus_strength",
        "top_spatial_gain_step_percent", "bottom_spatial_gain_step_percent",
        "top_spatial_gain_min_percent", "top_spatial_gain_max_percent",
        "bottom_spatial_gain_min_percent", "bottom_spatial_gain_max_percent",
        "spatial_gain_ramp_percent_per_second",
        "director_top_focus", "director_bottom_focus",
        "mfp_launch_target", "restim_launch_target", "prostate_launch_target",
        "rate", "lookahead", "volume", "dynamic_volume", "volume_rest_level", "volume_ratio",
        "volume_ramp_up", "frequency_ramp_level", "frequency_ratio", "send_frequency",
        "pulse_frequency_ratio", "pulse_frequency_min", "pulse_frequency_max", "send_pulse_frequency",
        "pulse_rise_ratio", "pulse_rise_min", "pulse_rise_max", "send_pulse_rise",
        "pulse_width_ratio", "pulse_width_min", "pulse_width_max", "send_pulse_width",
        "prostate_narrow_ratio", "prostate_arc_depth", "prostate_threshold",
        "prostate_volume_multiplier", "prostate_rest_level", "prostate_phase_degrees",
        "four_phase_return_depth",
        "four_phase_invert", "four_phase_volume_ceiling", "four_phase_volume_modulation",
        "four_phase_volume_headroom", "four_phase_volume_cycle",
        "four_phase_crossover_width", "four_phase_crossover_curve",
        "four_phase_crossover_sharpness", "four_phase_adaptive_crossover",
        "four_phase_slow_crossover_width", "four_phase_fast_crossover_width",
        "four_phase_directional_trajectory", "four_phase_reverse_width_scale",
        "four_phase_reverse_curve", "four_phase_reverse_sharpness",
        "four_phase_spatial_curve", "four_phase_spatial_blend",
        "four_phase_reversal_emphasis", "four_phase_reversal_window",
        "four_phase_reversal_strength",
        "four_phase_stroke_phase_texture", "four_phase_acceleration_width_scale",
        "four_phase_deceleration_width_scale", "motion_rising_volume_multiplier",
        "motion_falling_volume_multiplier", "four_phase_group_delay",
        "four_phase_group_delay_ms", "four_phase_group_delay_transition",
        "four_phase_moving_sequence", "four_phase_moving_sequence_depth",
        "four_phase_moving_sequence_width",
        "four_phase_spatial_model", "four_phase_tip_retention",
        "four_phase_spread_softness", "four_phase_full_depth_capture",
        "preset_a_name", "preset_b_name", "preset_transition_seconds",
        "electrode_order", "variety_electrode_morph", "variety_electrode_morph_cycle",
        "variety_electrode_morph_transition_seconds",
        "jitter_enabled", "jitter_amplitude", "jitter_cycle_seconds",
        "speed_linked_variation", "variation_full_speed_percent", "variation_fade_seconds",
        "prostate_phase_step", "controller_enabled", "controller_fine_step", "minimum_radius",
        "speed_threshold", "direction_probability", "mode", "direct_controller_enabled",
        "variety_enabled", "variety_frequency_cycle", "variety_pulse_frequency_cycle",
        "variety_pulse_rise_cycle", "variety_pulse_width_cycle", "variety_phase_cycle",
        "variety_frequency", "variety_pulse_frequency",
        "variety_pulse_rise", "variety_pulse_width", "variety_phase",
        "modifier_enabled", "modifier_stroke_range",
        "modifier_position_bias", "modifier_smoothing", "modifier_transition_seconds",
        "modifier_tempo_scale", "modifier_tempo_duration_seconds",
    )

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"Vector 1A {__version__} - MFP to ReStim")
        root.geometry("1360x900")
        root.minsize(980, 720)

        self.mfp_status = tk.StringVar(value="Disconnected")
        self.restim_status = tk.StringVar(value="Disconnected")
        self.prostate_status = tk.StringVar(value="Disconnected")
        self.four_phase_status = tk.StringVar(value="Disconnected")
        self.mfp_host = tk.StringVar(value="127.0.0.1")
        self.mfp_port = tk.IntVar(value=12345)
        self.restim_host = tk.StringVar(value="127.0.0.1")
        self.restim_port = tk.IntVar(value=12346)
        self.prostate_host = tk.StringVar(value="127.0.0.1")
        self.prostate_port = tk.IntVar(value=12350)
        self.four_phase_host = tk.StringVar(value="127.0.0.1")
        self.four_phase_port = tk.IntVar(value=12351)
        self.auto_start_mfp = tk.BooleanVar(value=False)
        self.auto_start_restim = tk.BooleanVar(value=False)
        self.auto_start_prostate = tk.BooleanVar(value=False)
        self.mfp_launch_target = tk.StringVar(value="")
        self.restim_launch_target = tk.StringVar(value="")
        self.prostate_launch_target = tk.StringVar(value="")
        self.startup_status = tk.StringVar(value="Manual startup")
        self.director_enabled = tk.BooleanVar(value=False)
        self.director_host = tk.StringVar(value="127.0.0.1")
        self.director_port = tk.IntVar(value=11436)
        self.director_status = tk.StringVar(value="DIRECTOR: OFF")
        self.director_events_enabled = tk.BooleanVar(value=False)
        self._director_window = None
        self.session_ready_status = tk.StringVar(value="SESSION: MANUAL")
        self._startup_in_progress = False
        self.authored_axes_status = tk.StringVar(value="No authored axes detected")
        self.authored_routing_mode = tk.StringVar(value="Manual selected axes")
        self.rate = tk.IntVar(value=50)
        self.lookahead = tk.DoubleVar(value=2.0)
        self.volume = tk.DoubleVar(value=0.70)
        self.dynamic_volume = tk.BooleanVar(value=True)
        self.volume_rest_level = tk.DoubleVar(value=0.40)
        self.volume_ratio = tk.DoubleVar(value=20.0)
        self.volume_ramp_up = tk.DoubleVar(value=1.0)
        self.frequency_ramp_level = tk.DoubleVar(value=1.0)
        self.frequency_ratio = tk.DoubleVar(value=2.0)
        self.send_frequency = tk.BooleanVar(value=True)
        self.pulse_frequency_ratio = tk.DoubleVar(value=3.0)
        self.pulse_frequency_min = tk.DoubleVar(value=0.40)
        self.pulse_frequency_max = tk.DoubleVar(value=0.95)
        self.send_pulse_frequency = tk.BooleanVar(value=True)
        self.pulse_rise_ratio = tk.DoubleVar(value=2.0)
        self.pulse_rise_min = tk.DoubleVar(value=0.0)
        self.pulse_rise_max = tk.DoubleVar(value=0.80)
        self.send_pulse_rise = tk.BooleanVar(value=True)
        self.pulse_width_ratio = tk.DoubleVar(value=3.0)
        self.pulse_width_min = tk.DoubleVar(value=0.10)
        self.pulse_width_max = tk.DoubleVar(value=0.45)
        self.send_pulse_width = tk.BooleanVar(value=True)
        self.prostate_narrow_ratio = tk.DoubleVar(value=1.0)
        self.prostate_arc_depth = tk.DoubleVar(value=0.25)
        self.prostate_threshold = tk.DoubleVar(value=0.25)
        self.prostate_volume_multiplier = tk.DoubleVar(value=1.5)
        self.prostate_rest_level = tk.DoubleVar(value=0.7)
        self.prostate_phase_degrees = tk.DoubleVar(value=0.0)
        self.prostate_phase_step = tk.DoubleVar(value=15.0)
        self.four_phase_return_depth = tk.DoubleVar(value=0.30)
        self.four_phase_invert = tk.BooleanVar(value=False)
        self.four_phase_volume_ceiling = tk.DoubleVar(value=0.85)
        self.four_phase_volume_modulation = tk.BooleanVar(value=False)
        self.four_phase_volume_headroom = tk.DoubleVar(value=0.15)
        self.four_phase_volume_cycle = tk.DoubleVar(value=4.0)
        self.four_phase_crossover_width = tk.DoubleVar(value=1.0)
        self.four_phase_crossover_curve = tk.StringVar(value="Cosine")
        self.four_phase_crossover_sharpness = tk.DoubleVar(value=1.0)
        self.four_phase_adaptive_crossover = tk.BooleanVar(value=False)
        self.four_phase_slow_crossover_width = tk.DoubleVar(value=.90)
        self.four_phase_fast_crossover_width = tk.DoubleVar(value=.35)
        self.four_phase_effective_crossover_width = tk.StringVar(value="1.000")
        self.four_phase_directional_trajectory = tk.BooleanVar(value=False)
        self.four_phase_reverse_width_scale = tk.DoubleVar(value=.75)
        self.four_phase_reverse_curve = tk.StringVar(value="Ease Out")
        self.four_phase_reverse_sharpness = tk.DoubleVar(value=.6)
        self.four_phase_spatial_curve = tk.StringVar(value="Linear")
        self.four_phase_spatial_blend = tk.DoubleVar(value=.5)
        self.four_phase_spatial_live = tk.StringVar(value="live 0.500")
        self.four_phase_reversal_emphasis = tk.BooleanVar(value=False)
        self.four_phase_reversal_window = tk.DoubleVar(value=.35)
        self.four_phase_reversal_strength = tk.DoubleVar(value=.20)
        self.four_phase_reversal_live = tk.StringVar(value="live 0.000")
        self.four_phase_stroke_phase_texture = tk.BooleanVar(value=False)
        self.four_phase_acceleration_width_scale = tk.DoubleVar(value=.70)
        self.four_phase_deceleration_width_scale = tk.DoubleVar(value=1.20)
        self.motion_rising_volume_multiplier = tk.DoubleVar(value=1.0)
        self.motion_falling_volume_multiplier = tk.DoubleVar(value=1.0)
        self.four_phase_stroke_phase_live = tk.StringVar(value="off")
        self.four_phase_group_delay = tk.BooleanVar(value=False)
        self.four_phase_group_delay_ms = tk.DoubleVar(value=0.0)
        self.four_phase_group_delay_transition = tk.DoubleVar(value=1.0)
        self.four_phase_group_delay_live = tk.StringVar(value="live 0 ms")
        self.four_phase_moving_sequence = tk.BooleanVar(value=False)
        self.four_phase_moving_sequence_depth = tk.DoubleVar(value=.50)
        self.four_phase_moving_sequence_width = tk.DoubleVar(value=1.0)
        self.four_phase_moving_sequence_live = tk.StringVar(value="off")
        self.four_phase_spatial_model = tk.StringVar(value="Moving focus")
        self.four_phase_tip_retention = tk.DoubleVar(value=.80)
        self.four_phase_spread_softness = tk.DoubleVar(value=.20)
        self.four_phase_full_depth_capture = tk.DoubleVar(value=.05)
        self.four_phase_model_live = tk.StringVar(value="Moving focus")
        self.preset_a_name = tk.StringVar(value="A")
        self.preset_b_name = tk.StringVar(value="B")
        self.preset_transition_seconds = tk.DoubleVar(value=2.5)
        self.preset_status = tk.StringVar(value="No preset active")
        self._preset_slots: dict[str, dict] = {}
        self._preset_active: str | None = None
        self._preset_transition = None
        self._preset_window = None
        self.director_texture = tk.StringVar(value="Unassigned")
        self.director_primary_spatial = tk.StringVar(value="top_moving_focus")
        self.director_secondary_spatial = tk.StringVar(value="bottom_focus")
        self.director_variation = tk.StringVar(value="Unassigned")
        self.director_top_focus = tk.StringVar(value="Top Full")
        self.director_bottom_focus = tk.StringVar(value="Bottom Full")
        self.top_focus_nominal_ceiling = tk.DoubleVar(value=0.65)
        self.top_focus_strength = tk.DoubleVar(value=1.0)
        self.bottom_focus_strength = tk.DoubleVar(value=1.0)
        self.top_spatial_gain_step_percent = tk.DoubleVar(value=10.0)
        self.bottom_spatial_gain_step_percent = tk.DoubleVar(value=10.0)
        self.top_spatial_gain_min_percent = tk.DoubleVar(value=50.0)
        self.top_spatial_gain_max_percent = tk.DoubleVar(value=150.0)
        self.bottom_spatial_gain_min_percent = tk.DoubleVar(value=50.0)
        self.bottom_spatial_gain_max_percent = tk.DoubleVar(value=150.0)
        self.spatial_gain_ramp_percent_per_second = tk.DoubleVar(value=20.0)
        self.top_spatial_gain_display = tk.StringVar(value="100%")
        self.bottom_spatial_gain_display = tk.StringVar(value="100%")
        self._director_texture_profiles: dict[str, dict] = {}
        self._director_variation_profiles: dict[str, dict] = {}
        self._director_top_focus_profiles: dict[str, dict] = {}
        self._director_bottom_focus_profiles: dict[str, dict] = {}
        self._director_texture_status_vars: dict[str, tk.StringVar] = {}
        self._director_variation_status_vars: dict[str, tk.StringVar] = {}
        self._director_top_focus_status_vars: dict[str, tk.StringVar] = {}
        self._director_bottom_focus_status_vars: dict[str, tk.StringVar] = {}
        self.director_semantic_status = tk.StringVar(value="")
        self._director_semantic_window = None
        self.electrode_order = tk.StringVar(value="ABCD")
        self.variety_electrode_morph = tk.BooleanVar(value=False)
        self.variety_electrode_morph_cycle = tk.DoubleVar(value=6.0)
        self.variety_electrode_morph_transition_seconds = tk.DoubleVar(value=3.0)
        self.jitter_enabled = tk.BooleanVar(value=False)
        self.jitter_amplitude = tk.DoubleVar(value=0.02)
        self.jitter_cycle_seconds = tk.DoubleVar(value=1.0)
        self.speed_linked_variation = tk.BooleanVar(value=True)
        self.variation_full_speed_percent = tk.DoubleVar(value=35.0)
        self.variation_fade_seconds = tk.DoubleVar(value=.75)
        self.variation_depth_live = tk.StringVar(value="Effect depth 0%")
        self.modifier_enabled = tk.BooleanVar(value=False)
        self.modifier_stroke_range = tk.DoubleVar(value=1.0)
        self.modifier_position_bias = tk.DoubleVar(value=0.0)
        self.modifier_smoothing = tk.DoubleVar(value=0.0)
        self.modifier_transition_seconds = tk.DoubleVar(value=0.2)
        self.modifier_tempo_scale = tk.DoubleVar(value=2.0)
        self.modifier_tempo_duration_seconds = tk.DoubleVar(value=30.0)
        self.modifier_status = tk.StringVar(value="Authored L0 unchanged")
        self.modifier_tempo_status = tk.StringVar(value="Tempo authored ×1.0")
        self._modifier_window = None
        self._tempo_lock = threading.RLock()
        self._tempo_scale_active = 1.0
        self._tempo_anchor_media = None
        self._tempo_anchor_clock = 0.0
        self._tempo_expires_at = 0.0
        self._tempo_transition_seconds_active = 0.2
        self._tempo_restore_started_at = 0.0
        self._tempo_restore_from = None
        self.send_four_phase_visual = tk.BooleanVar(value=False)
        self.controller_enabled = tk.BooleanVar(value=True)
        self.controller_target = tk.IntVar(value=0)
        self.controller_fine_step = tk.DoubleVar(value=0.05)
        self.controller_status = tk.StringVar(value="Disabled")
        self.direct_controller_enabled = tk.BooleanVar(value=True)
        self.variety_enabled = tk.BooleanVar(value=False)
        self.variety_frequency_cycle = tk.DoubleVar(value=4.0)
        self.variety_pulse_frequency_cycle = tk.DoubleVar(value=3.0)
        self.variety_pulse_rise_cycle = tk.DoubleVar(value=2.0)
        self.variety_pulse_width_cycle = tk.DoubleVar(value=1.0)
        self.variety_phase_cycle = tk.DoubleVar(value=5.0)
        self.variety_frequency = tk.BooleanVar(value=True)
        self.variety_pulse_frequency = tk.BooleanVar(value=False)
        self.variety_pulse_rise = tk.BooleanVar(value=False)
        self.variety_pulse_width = tk.BooleanVar(value=False)
        self.variety_phase = tk.BooleanVar(value=False)
        self.variety_status = tk.StringVar(value="Off")
        self._variety_started = time.monotonic()
        self._variety_baseline = {}
        self._controller_events: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()
        self.minimum_radius = tk.DoubleVar(value=0.10)
        self.speed_threshold = tk.DoubleVar(value=50.0)
        self.direction_probability = tk.DoubleVar(value=0.10)
        self.mode = tk.StringVar(value=MotionMode.TOP_LEFT_BOTTOM_RIGHT.value)
        self.diag_vars = {name: tk.StringVar(value="--") for name in (
            "raw_l0", "output_l0", "speed", "alpha", "beta", "buffer",
            "lookahead", "actual_delay", "input_count", "output_count", "state",
            "active_mode",
            "output_mode",
            "output_volume",
            "frequency",
            "pulse_frequency",
            "pulse_rise_time",
            "pulse_width",
            "alpha_prostate", "beta_prostate", "volume_prostate",
            "variation_depth",
        )}

        self._connection_events: deque[str] = deque(maxlen=200)
        self._last_connection_event: dict[str, str] = {}
        self._last_health_log_at = 0.0
        self._source_was_stale = False
        self._last_health_output_count = 0

        self.axis_router = AuthoredAxisRouter()
        self.event_engine = EventEngine()
        self._director_event_history: deque[dict] = deque(maxlen=12)
        self.director_bridge = DirectorBridge()
        self.director_server = DirectorServer(self.director_bridge)
        self.orchestrator = SessionOrchestrator(self._set_startup_status)
        self.restim = ReStimWebSocketClient(self._set_restim_status)
        self.prostate_restim = ReStimWebSocketClient(self._set_prostate_status)
        self.restim_sender = LatestFrameDispatcher("Primary", self._set_restim_status)
        self.prostate_sender = LatestFrameDispatcher("Prostate", self._set_prostate_status)
        self.engine = VectorEngine(self._send_sample)
        self._latest_authored_l0 = 0.5
        self.generated_motion = GeneratedMotionSource(self._receive_generated_l0)
        self.timeline = FunscriptTimeline()
        self._timeline_window = None
        self.timeline_file_display = tk.StringVar(value="No funscript loaded")
        self.timeline_status_display = tk.StringVar(value="Timeline idle")
        self.timeline_clock_source = tk.StringVar(value=FunscriptTimeline.CLOCK_AUTO)
        self.timeline_manual_position = tk.DoubleVar(value=0.0)
        self.timeline_media_host = tk.StringVar(value="127.0.0.1")
        self.timeline_vlc_port = tk.IntVar(value=8080)
        self.timeline_vlc_password = tk.StringVar(value="")
        self.timeline_mpc_port = tk.IntVar(value=13579)
        self.timeline_script_libraries = tk.StringVar(value="")
        self.timeline_auto_load_script = tk.BooleanVar(value=True)
        self._four_phase_last_l0 = 0.5
        self._four_phase_direction = 1
        self._four_phase_send_last_l0 = 0.5
        self._four_phase_send_direction = 1
        self._motion_send_last_l0 = 0.5
        self._motion_send_direction = 1
        self._four_phase_history = deque(maxlen=128)
        self._four_phase_effective_group_delay = 0.0
        self._four_phase_group_delay_last_time = None
        self._four_phase_live_lock = threading.Lock()
        self._four_phase_live_output = (
            (0.5, 0.5, 0.5, 0.5), "ABCD", "ABCD", 0.0, "stable")
        self.listener = MFPListener(self._receive_l0, self._set_mfp_status, self._on_mfp_command)
        self._controller_snapshot = controller_snapshot(0, False)
        self._controller_state_sequence = 0
        self.xinput = XInputController(self._xinput_buttons_threaded, self._xinput_status_threaded,
                                       self._xinput_state_threaded)
        self.sections = {}
        self._first_run = self._load_settings()
        self._apply_timeline_media_settings()
        # Focus dwell/history begins after saved settings are restored, so startup
        # loading is not mistaken for an intentional Director transition.
        self._top_focus_history = FocusHistory(self.director_top_focus.get())
        self._bottom_focus_history = FocusHistory(self.director_bottom_focus.get())
        self._bottom_focus_transition = BottomFocusTransition(self.director_bottom_focus.get())
        self._top_spatial_gain = SpatialGainController()
        self._bottom_spatial_gain = SpatialGainController()
        self.director_top_focus.trace_add("write", self._on_top_focus_changed)
        self.director_bottom_focus.trace_add("write", self._on_bottom_focus_changed)
        self._build()
        self._bind_controller_keys()
        self._controller_enabled_changed()
        self.xinput.start()
        self.engine.start()
        self.timeline.request_media_poll()
        if self._timeline_window is not None and self._timeline_window.winfo_exists():
            self._refresh_timeline_window()
        self.root.after(100, self._refresh)
        self.root.after(350, self._auto_start_session)
        self.root.after(450, self._auto_start_director)
        if self._first_run:
            self.root.after(500, self.show_setup_guide)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

    def _frame(self, title: str, row: int, column: int = 0, span: int = 1) -> ttk.Frame:
        collapsed_titles = {
            "Frequency", "Pulse frequency", "Pulse rise time", "Pulse width",
            "Prostate controls", "Four-phase primary motion",
            "Xbox controller", "Rolling Variety", "Live diagnostics",
        }
        section = CollapsibleSection(self.root, title, collapsed=(title in collapsed_titles))
        section.grid(row=row + 1, column=column, columnspan=span, sticky="nsew", padx=10, pady=3)
        self.sections[title] = section
        return section.body

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(12, weight=1)

        toolbar = ttk.Frame(self.root, padding=(12, 6))
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(toolbar, text="ReStim Vector Live", font=("TkDefaultFont", 10, "bold")).pack(side="left")
        ttk.Button(toolbar, text="START / RESUME", command=self.resume).pack(side="left", padx=(24, 6))
        ttk.Button(toolbar, text="Neutral", command=self.neutral).pack(side="left", padx=6)
        ttk.Button(toolbar, text="STOP", command=self.stop).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Setup guide", command=self.show_setup_guide).pack(side="left", padx=(18, 6))
        ttk.Button(toolbar, text="Rolling Variety", command=self.show_variety_window).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Presets A/B", command=self.show_preset_window).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Connection log", command=self.show_connection_log).pack(side="left", padx=6)
        ttk.Button(toolbar, text="MFP axes", command=self.show_axis_routing).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Session startup", command=self.show_session_startup).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Director", command=self.show_director_window).pack(side="left", padx=6)
        ttk.Button(toolbar, text="Script modifiers", command=self.show_modifier_window).pack(side="left", padx=6)
        ttk.Label(toolbar, textvariable=self.diag_vars["state"]).pack(side="right", padx=8)
        ttk.Label(toolbar, textvariable=self.director_status, font=("TkDefaultFont", 9, "bold")).pack(side="right", padx=12)
        ttk.Label(toolbar, textvariable=self.session_ready_status, font=("TkDefaultFont", 9, "bold")).pack(side="right", padx=12)

        mfp = self._frame("MultiFunPlayer input", 0, 0)
        ttk.Label(mfp, text="Bind address").grid(row=0, column=0, sticky="w")
        ttk.Entry(mfp, textvariable=self.mfp_host, width=16).grid(row=0, column=1, padx=5)
        ttk.Label(mfp, text="Port").grid(row=0, column=2)
        ttk.Spinbox(mfp, from_=1, to=65535, textvariable=self.mfp_port, width=7).grid(row=0, column=3, padx=5)
        ttk.Button(mfp, text="Start listener", command=self.start_listener).grid(row=1, column=0, pady=8)
        ttk.Button(mfp, text="Stop listener", command=self.listener.stop).grid(row=1, column=1, pady=8)
        ttk.Label(mfp, textvariable=self.mfp_status).grid(row=1, column=2, columnspan=2, sticky="w")
        ttk.Label(mfp, textvariable=self.authored_axes_status, foreground="#555").grid(
            row=2, column=0, columnspan=4, sticky="w", pady=(0, 4))
        ttk.Label(mfp, text="TCP / UDP / WebSocket on the same port; WebSocket path: /ws",
                  foreground="#555").grid(row=3, column=0, columnspan=4, sticky="w")

        restim = self._frame("ReStim output", 0, 1)
        ttk.Label(restim, text="Primary WS").grid(row=0, column=0, sticky="w")
        ttk.Entry(restim, textvariable=self.restim_host, width=16).grid(row=0, column=1, padx=5)
        ttk.Label(restim, text="Port").grid(row=0, column=2)
        ttk.Spinbox(restim, from_=1, to=65535, textvariable=self.restim_port, width=7).grid(row=0, column=3, padx=5)
        ttk.Button(restim, text="Connect", command=self.connect_restim).grid(row=1, column=0, pady=8)
        ttk.Button(restim, text="Disconnect", command=self.restim.disconnect).grid(row=1, column=1, pady=8)
        ttk.Label(restim, textvariable=self.restim_status).grid(row=1, column=2, columnspan=3, sticky="w")
        ttk.Label(restim, text="Prostate").grid(row=2, column=0, sticky="w")
        ttk.Entry(restim, textvariable=self.prostate_host, width=16).grid(row=2, column=1, padx=5)
        ttk.Label(restim, text="Port").grid(row=2, column=2, sticky="e")
        ttk.Spinbox(restim, from_=1, to=65535, textvariable=self.prostate_port, width=7).grid(row=2, column=3, padx=5)
        ttk.Button(restim, text="Connect", command=self.connect_prostate).grid(row=3, column=0, pady=6)
        ttk.Button(restim, text="Disconnect", command=self.prostate_restim.disconnect).grid(row=3, column=1, pady=6)
        ttk.Label(restim, textvariable=self.prostate_status).grid(row=3, column=2, columnspan=4, sticky="w")

        motion = self._frame("Motion", 1, 0, 2)
        ttk.Label(motion, text="Mode").grid(row=0, column=0, sticky="w")
        mode_box = ttk.Combobox(motion, textvariable=self.mode, state="readonly", width=38,
                                values=[mode.value for mode in MotionMode])
        mode_box.grid(row=0, column=1, columnspan=3, sticky="w", padx=6)
        mode_box.bind("<<ComboboxSelected>>", lambda _event: self.apply_config())
        fields = (
            ("Points per second", self.rate, 1, 200, 1),
            ("Look-ahead / delay (s)", self.lookahead, 0.05, 10, 0.05),
            ("Base volume", self.volume, 0, 1, 0.01),
            ("Minimum distance from center", self.minimum_radius, 0, 0.9, 0.05),
            ("Speed threshold (%)", self.speed_threshold, 0, 100, 1),
            ("Direction change probability", self.direction_probability, 0, 1, 0.05),
        )
        for index, (label, variable, low, high, step) in enumerate(fields):
            row = 1 + index // 3
            col = (index % 3) * 2
            ttk.Label(motion, text=label).grid(row=row, column=col, sticky="w", pady=4)
            ttk.Spinbox(motion, from_=low, to=high, increment=step, textvariable=variable,
                        width=10, command=self.apply_config).grid(row=row, column=col + 1, padx=6, sticky="w")
        ttk.Button(motion, text="Apply", command=self.apply_config).grid(row=3, column=5, sticky="e")
        ttk.Checkbutton(motion, text="Add smooth L0 position variation", variable=self.jitter_enabled,
                        command=self.apply_config).grid(row=3, column=0, sticky="w", pady=(5, 2))
        ttk.Label(motion, text="Maximum shift (±L0)").grid(row=3, column=1, sticky="e")
        ttk.Spinbox(motion, from_=0, to=.20, increment=.005,
                    textvariable=self.jitter_amplitude, width=8,
                    command=self.apply_config).grid(row=3, column=2, sticky="w")
        ttk.Label(motion, text="Variation cycle (s)").grid(row=3, column=3, sticky="e")
        ttk.Spinbox(motion, from_=.05, to=30, increment=.05,
                    textvariable=self.jitter_cycle_seconds, width=8,
                    command=self.apply_config).grid(row=3, column=4, sticky="w")
        ttk.Checkbutton(motion, text="Scale optional effects with speed",
                        variable=self.speed_linked_variation,
                        command=self.apply_config).grid(row=4, column=0, sticky="w", pady=(3, 0))
        ttk.Label(motion, text="Full effects at speed (%)").grid(row=4, column=1, sticky="e")
        ttk.Spinbox(motion, from_=1, to=100, increment=1,
                    textvariable=self.variation_full_speed_percent, width=8,
                    command=self.apply_config).grid(row=4, column=2, sticky="w")
        ttk.Label(motion, text="Response time (s)").grid(row=4, column=3, sticky="e")
        ttk.Spinbox(motion, from_=.05, to=10, increment=.05,
                    textvariable=self.variation_fade_seconds, width=8,
                    command=self.apply_config).grid(row=4, column=4, sticky="w")
        ttk.Label(motion, textvariable=self.variation_depth_live,
                  foreground="#555").grid(row=4, column=5, sticky="w", padx=8)
        ttk.Label(motion, text="Spatial response").grid(row=5, column=0, sticky="w", pady=(4, 0))
        ttk.Combobox(motion, textvariable=self.four_phase_spatial_curve,
                     values=("Linear", "S-curve", "Endpoint emphasis", "Centre emphasis"),
                     state="readonly", width=18).grid(row=5, column=1, sticky="w")
        ttk.Label(motion, text="Blend (1 = 100%)").grid(row=5, column=3, sticky="e")
        ttk.Spinbox(motion, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_spatial_blend, width=8,
                    command=self.apply_config).grid(row=5, column=4, sticky="w")
        ttk.Checkbutton(motion, text="Boost volume near stroke reversal",
                        variable=self.four_phase_reversal_emphasis).grid(row=6, column=0, sticky="w")
        ttk.Label(motion, text="Window either side (s)").grid(row=6, column=1, sticky="e")
        ttk.Spinbox(motion, from_=.05, to=1.5, increment=.05,
                    textvariable=self.four_phase_reversal_window, width=8).grid(row=6, column=2, sticky="w")
        ttk.Label(motion, text="Current-volume boost (+×)").grid(row=6, column=3, sticky="e")
        ttk.Spinbox(motion, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_reversal_strength, width=8).grid(row=6, column=4, sticky="w")
        ttk.Label(motion, textvariable=self.four_phase_reversal_live,
                  foreground="#555").grid(row=6, column=5, sticky="w", padx=8)
        ttk.Checkbutton(motion, text="Stroke-phase texture",
                        variable=self.four_phase_stroke_phase_texture).grid(row=7, column=0, sticky="w")
        ttk.Label(motion, text="L0 rising volume ×").grid(row=7, column=1, sticky="e")
        ttk.Spinbox(motion, from_=.8, to=1, increment=.01,
                    textvariable=self.motion_rising_volume_multiplier, width=8).grid(row=7, column=2, sticky="w")
        ttk.Label(motion, text="L0 falling volume ×").grid(row=7, column=3, sticky="e")
        ttk.Spinbox(motion, from_=.8, to=1, increment=.01,
                    textvariable=self.motion_falling_volume_multiplier, width=8).grid(row=7, column=4, sticky="w")
        ttk.Label(motion, text="Shared by 3-phase and 4-phase",
                   foreground="#555").grid(row=7, column=5, sticky="w", padx=8)
        ttk.Button(motion, text="Explain these controls", command=self.show_motion_guide).grid(
            row=8, column=5, sticky="e", pady=(5, 0))

        volume_frame = self._frame("Volume response", 2, 0, 2)
        ttk.Checkbutton(volume_frame, text="Reduce volume when motion stops",
                        variable=self.dynamic_volume, command=self.apply_config).grid(row=0, column=0, sticky="w")
        volume_fields = (("Rest level", self.volume_rest_level, 0, 1, 0.05),
                         ("Ramp | Speed ratio", self.volume_ratio, 10, 40, 1),
                         ("Return ramp (s)", self.volume_ramp_up, 0, 10, 0.1))
        for index, (label, variable, low, high, step) in enumerate(volume_fields):
            col = 1 + index * 2
            ttk.Label(volume_frame, text=label).grid(row=0, column=col, padx=(18, 4))
            ttk.Spinbox(volume_frame, from_=low, to=high, increment=step,
                        textvariable=variable, width=8, command=self.apply_config).grid(row=0, column=col + 1)
        ttk.Label(volume_frame, text="Primary volume ceiling").grid(
            row=0, column=7, padx=(18, 4))
        ttk.Spinbox(volume_frame, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_volume_ceiling, width=8).grid(
                        row=0, column=8)

        frequency_frame = self._frame("Frequency", 3, 0, 2)
        ttk.Label(frequency_frame, text="0").grid(row=0, column=0)
        self.frequency_bar = ttk.Progressbar(frequency_frame, orient="horizontal", mode="determinate",
                                             maximum=1.0, length=520)
        self.frequency_bar.grid(row=0, column=1, padx=8)
        ttk.Label(frequency_frame, text="1").grid(row=0, column=2)
        self.frequency_value = tk.StringVar(value="0.0000")
        ttk.Label(frequency_frame, textvariable=self.frequency_value,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=3, padx=8)
        ttk.Label(frequency_frame, text="Ramp level").grid(row=0, column=4, padx=(16, 4))
        ttk.Spinbox(frequency_frame, from_=0, to=1, increment=0.05,
                    textvariable=self.frequency_ramp_level, width=7,
                    command=self.apply_config).grid(row=0, column=5)
        ttk.Label(frequency_frame, text="Ramp | Speed ratio").grid(row=0, column=6, padx=(16, 4))
        ttk.Spinbox(frequency_frame, from_=1, to=10, increment=1,
                    textvariable=self.frequency_ratio, width=7,
                    command=self.apply_config).grid(row=0, column=7)

        pulse_frame = self._frame("Pulse frequency", 4, 0, 2)
        ttk.Label(pulse_frame, text="0").grid(row=0, column=0)
        self.pulse_frequency_bar = RangeBar(pulse_frame)
        self.pulse_frequency_bar.grid(row=0, column=1, padx=8)
        ttk.Label(pulse_frame, text="1").grid(row=0, column=2)
        self.pulse_frequency_value = tk.StringVar(value="0.0000")
        ttk.Label(pulse_frame, textvariable=self.pulse_frequency_value,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=3, padx=8)
        pulse_fields = (("Min", self.pulse_frequency_min),
                        ("Max", self.pulse_frequency_max),
                        ("Speed | Alpha ratio", self.pulse_frequency_ratio))
        for index, (label, variable) in enumerate(pulse_fields):
            col = 4 + index * 2
            ttk.Label(pulse_frame, text=label).grid(row=0, column=col, padx=(12, 4))
            ttk.Spinbox(pulse_frame, from_=0 if index < 2 else 1,
                        to=1 if index < 2 else 10, increment=0.05 if index < 2 else 1,
                        textvariable=variable, width=7,
                        command=self.apply_config).grid(row=0, column=col + 1)

        rise_frame = self._frame("Pulse rise time", 5, 0, 2)
        ttk.Label(rise_frame, text="0 sharp").grid(row=0, column=0)
        self.pulse_rise_bar = RangeBar(rise_frame)
        self.pulse_rise_bar.grid(row=0, column=1, padx=8)
        ttk.Label(rise_frame, text="1 soft").grid(row=0, column=2)
        self.pulse_rise_value = tk.StringVar(value="0.0000")
        ttk.Label(rise_frame, textvariable=self.pulse_rise_value,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=3, padx=8)
        rise_fields = (("Min", self.pulse_rise_min), ("Max", self.pulse_rise_max),
                       ("Inv Ramp | Inv Speed", self.pulse_rise_ratio))
        for index, (label, variable) in enumerate(rise_fields):
            col = 4 + index * 2
            ttk.Label(rise_frame, text=label).grid(row=0, column=col, padx=(12, 4))
            ttk.Spinbox(rise_frame, from_=0 if index < 2 else 1,
                        to=1 if index < 2 else 10, increment=0.05 if index < 2 else 1,
                        textvariable=variable, width=7,
                        command=self.apply_config).grid(row=0, column=col + 1)
        width_frame = self._frame("Pulse width", 6, 0, 2)
        ttk.Label(width_frame, text="0 narrow").grid(row=0, column=0)
        self.pulse_width_bar = RangeBar(width_frame)
        self.pulse_width_bar.grid(row=0, column=1, padx=8)
        ttk.Label(width_frame, text="1 wide").grid(row=0, column=2)
        self.pulse_width_value = tk.StringVar(value="0.0000")
        ttk.Label(width_frame, textvariable=self.pulse_width_value,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=3, padx=8)
        width_fields = (("Min", self.pulse_width_min), ("Max", self.pulse_width_max),
                        ("Speed | Inv L0 ratio", self.pulse_width_ratio))
        for index, (label, variable) in enumerate(width_fields):
            col = 4 + index * 2
            ttk.Label(width_frame, text=label).grid(row=0, column=col, padx=(12, 4))
            ttk.Spinbox(width_frame, from_=0 if index < 2 else 1,
                        to=1 if index < 2 else 10, increment=0.05 if index < 2 else 1,
                        textvariable=variable, width=7,
                        command=self.apply_config).grid(row=0, column=col + 1)

        prostate = self._frame("Prostate controls", 7, 0, 2)
        self.prostate_bars = {}
        self.prostate_values = {}
        for row, (label, key) in enumerate((("Alpha-prostate", "alpha_prostate"),
                                             ("Beta-prostate", "beta_prostate"),
                                             ("Volume-prostate", "volume_prostate"))):
            ttk.Label(prostate, text=label, width=18).grid(row=row, column=0, sticky="w")
            ttk.Label(prostate, text="0").grid(row=row, column=1)
            bar = ttk.Progressbar(prostate, orient="horizontal", mode="determinate",
                                  maximum=1.0, length=520)
            bar.grid(row=row, column=2, padx=8)
            ttk.Label(prostate, text="1").grid(row=row, column=3)
            value = tk.StringVar(value="0.0000")
            ttk.Label(prostate, textvariable=value, width=8,
                      font=("TkDefaultFont", 10, "bold")).grid(row=row, column=4, padx=8)
            self.prostate_bars[key] = bar
            self.prostate_values[key] = value
        ttk.Label(prostate, text="Return arc scale").grid(row=0, column=5, padx=(14, 4))
        ttk.Spinbox(prostate, from_=0, to=1, increment=.05, textvariable=self.prostate_narrow_ratio,
                    width=7, command=self.apply_config).grid(row=0, column=6)
        ttk.Label(prostate, text="Side arc depth").grid(row=2, column=5, padx=(14, 4))
        ttk.Spinbox(prostate, from_=0, to=1, increment=.05, textvariable=self.prostate_arc_depth,
                    width=7, command=self.apply_config).grid(row=2, column=6)
        ttk.Label(prostate, text="Stroke threshold").grid(row=1, column=5, padx=(14, 4))
        ttk.Spinbox(prostate, from_=0, to=1, increment=.05, textvariable=self.prostate_threshold,
                    width=7, command=self.apply_config).grid(row=1, column=6)
        ttk.Label(prostate, text="Volume ratio multiplier").grid(row=0, column=7, padx=(14, 4))
        ttk.Spinbox(prostate, from_=1, to=3, increment=.1, textvariable=self.prostate_volume_multiplier,
                    width=7, command=self.apply_config).grid(row=0, column=8)
        ttk.Label(prostate, text="Volume rest level").grid(row=1, column=7, padx=(14, 4))
        ttk.Spinbox(prostate, from_=0, to=1, increment=.05, textvariable=self.prostate_rest_level,
                    width=7, command=self.apply_config).grid(row=1, column=8)
        ttk.Label(prostate, text="Timing phase (degrees)").grid(row=2, column=7, padx=(14, 4))
        ttk.Spinbox(prostate, from_=-90, to=90, increment=5,
                    textvariable=self.prostate_phase_degrees, width=7,
                    command=self.apply_config).grid(row=2, column=8)

        four_phase = self._frame("Four-phase primary motion", 8, 0, 2)
        self.four_phase_bars, self.four_phase_values = [], []
        for row, label in enumerate(("A — top", "B", "C", "D — bottom")):
            ttk.Label(four_phase, text=label, width=18).grid(row=row, column=0, sticky="w")
            ttk.Label(four_phase, text="0").grid(row=row, column=1)
            bar = ttk.Progressbar(four_phase, orient="horizontal", mode="determinate",
                                  maximum=1.0, length=520)
            bar.grid(row=row, column=2, padx=8)
            ttk.Label(four_phase, text="1").grid(row=row, column=3)
            value = tk.StringVar(value="0.0000")
            ttk.Label(four_phase, textvariable=value, width=8,
                      font=("TkDefaultFont", 10, "bold")).grid(row=row, column=4, padx=8)
            self.four_phase_bars.append(bar); self.four_phase_values.append(value)
        ttk.Label(four_phase,
                  text="Last transmitted E1-E4 Primary output.",
                  foreground="#9b4b00").grid(row=0, column=5, rowspan=4, sticky="w", padx=18)
        ttk.Label(four_phase, text="Return depth").grid(row=4, column=0, sticky="w")
        ttk.Spinbox(four_phase, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_return_depth, width=7).grid(
                        row=4, column=1, sticky="w")
        ttk.Label(four_phase, text="Signed: primary +1.00 | return −depth | unused 0.00") \
            .grid(row=4, column=2, columnspan=4, sticky="w", padx=8)
        ttk.Checkbutton(four_phase, text="Reverse L0 direction", variable=self.four_phase_invert).grid(row=5, column=0, sticky="w")
        ttk.Checkbutton(four_phase, text="Add slow volume variation", variable=self.four_phase_volume_modulation).grid(row=5, column=3, sticky="w")
        ttk.Label(four_phase, text="Maximum addition").grid(row=5, column=4, sticky="e")
        ttk.Spinbox(four_phase, from_=0, to=1, increment=.05, textvariable=self.four_phase_volume_headroom, width=7).grid(row=5, column=5, sticky="w")
        ttk.Label(four_phase, text="Volume cycle (min)").grid(row=6, column=4, sticky="e")
        ttk.Spinbox(four_phase, from_=.5, to=30, increment=.5, textvariable=self.four_phase_volume_cycle, width=7).grid(row=6, column=5, sticky="w")
        ttk.Label(four_phase, text="Base crossover width").grid(row=6, column=0, sticky="w")
        ttk.Spinbox(four_phase, from_=.05, to=1, increment=.05,
                    textvariable=self.four_phase_crossover_width, width=7).grid(row=6, column=1, sticky="w")
        ttk.Label(four_phase, text="Crossover curve").grid(row=6, column=2, sticky="e", padx=(8, 4))
        ttk.Combobox(four_phase, textvariable=self.four_phase_crossover_curve,
                     values=("Cosine", "Linear", "Ease In", "Ease Out", "S-curve"),
                     state="readonly", width=10).grid(row=6, column=3, sticky="w")
        ttk.Label(four_phase, text="Crossover sharpness").grid(row=7, column=0, sticky="w")
        ttk.Spinbox(four_phase, from_=.2, to=5, increment=.1,
                    textvariable=self.four_phase_crossover_sharpness, width=7).grid(row=7, column=1, sticky="w")
        ttk.Label(four_phase, text="Signalling sequence").grid(row=7, column=2, sticky="e", padx=(8, 4))
        order_box = ttk.Combobox(four_phase, textvariable=self.electrode_order,
                                 values=ELECTRODE_ORDERS, state="readonly", width=7)
        order_box.grid(row=7, column=3, sticky="w")
        order_box.bind("<<ComboboxSelected>>", lambda _event: self._electrode_order_changed())
        ttk.Label(four_phase, text="Sequence blend (live)").grid(row=7, column=4, sticky="e", padx=(8, 4))
        self.electrode_morph_bar = ttk.Progressbar(
            four_phase, orient="horizontal", mode="determinate", maximum=1.0, length=120)
        self.electrode_morph_bar.grid(row=7, column=5, sticky="w")
        ttk.Checkbutton(four_phase, text="Change crossover width with speed",
                        variable=self.four_phase_adaptive_crossover).grid(
                            row=8, column=0, sticky="w")
        ttk.Label(four_phase, text="Low-speed width").grid(row=8, column=1, sticky="e")
        ttk.Spinbox(four_phase, from_=.05, to=1, increment=.05,
                    textvariable=self.four_phase_slow_crossover_width,
                    width=7).grid(row=8, column=2, sticky="w")
        ttk.Label(four_phase, text="High-speed width").grid(row=8, column=3, sticky="e")
        ttk.Spinbox(four_phase, from_=.05, to=1, increment=.05,
                    textvariable=self.four_phase_fast_crossover_width,
                    width=7).grid(row=8, column=4, sticky="w")
        ttk.Label(four_phase, textvariable=self.four_phase_effective_crossover_width,
                  width=12).grid(row=8, column=5, sticky="w", padx=8)
        ttk.Checkbutton(four_phase, text="Use different return-stroke crossover",
                        variable=self.four_phase_directional_trajectory).grid(
                            row=9, column=0, sticky="w")
        ttk.Label(four_phase, text="Return width ×").grid(row=9, column=1, sticky="e")
        ttk.Spinbox(four_phase, from_=.2, to=3, increment=.05,
                    textvariable=self.four_phase_reverse_width_scale,
                    width=7).grid(row=9, column=2, sticky="w")
        ttk.Label(four_phase, text="Return curve").grid(row=9, column=3, sticky="e")
        ttk.Combobox(four_phase, textvariable=self.four_phase_reverse_curve,
                     values=("Cosine", "Linear", "Ease In", "Ease Out", "S-curve"),
                     state="readonly", width=10).grid(row=9, column=4, sticky="w")
        reverse_sharpness = ttk.Frame(four_phase)
        reverse_sharpness.grid(row=9, column=5, sticky="w", padx=8)
        ttk.Label(reverse_sharpness, text="Sharpness").pack(side="left")
        ttk.Spinbox(reverse_sharpness, from_=.2, to=5, increment=.1,
                    textvariable=self.four_phase_reverse_sharpness,
                    width=7).pack(side="left", padx=(4, 0))
        ttk.Label(four_phase, text="Spatial model").grid(row=10, column=0, sticky="w")
        ttk.Combobox(four_phase, textvariable=self.four_phase_spatial_model,
                     values=SPATIAL_MODELS, state="readonly", width=14).grid(
                         row=10, column=1, sticky="w")
        ttk.Label(four_phase, text="Tip retention at full depth").grid(
            row=10, column=2, sticky="e", padx=(8, 4))
        ttk.Spinbox(four_phase, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_tip_retention, width=7).grid(
                        row=10, column=3, sticky="w")
        ttk.Label(four_phase, text="Spread softness").grid(
            row=10, column=4, sticky="e")
        ttk.Spinbox(four_phase, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_spread_softness, width=7).grid(
                        row=10, column=5, sticky="w")
        ttk.Label(four_phase, text="Full-depth capture").grid(
            row=11, column=0, sticky="w")
        ttk.Spinbox(four_phase, from_=0, to=.20, increment=.01,
                    textvariable=self.four_phase_full_depth_capture, width=7).grid(
                        row=11, column=1, sticky="w")
        ttk.Label(four_phase, textvariable=self.four_phase_model_live,
                  foreground="#9b4b00").grid(
                      row=11, column=2, columnspan=4, sticky="w", pady=(2, 4))
        ttk.Label(four_phase, text="Change width through each stroke").grid(row=12, column=0, sticky="w")
        ttk.Label(four_phase, text="Accelerating width ×").grid(row=12, column=1, sticky="e")
        ttk.Spinbox(four_phase, from_=.2, to=3, increment=.05,
                    textvariable=self.four_phase_acceleration_width_scale,
                    width=7).grid(row=12, column=2, sticky="w")
        ttk.Label(four_phase, text="Deceleration width ×").grid(row=12, column=3, sticky="e")
        ttk.Spinbox(four_phase, from_=.2, to=3, increment=.05,
                    textvariable=self.four_phase_deceleration_width_scale,
                    width=7).grid(row=12, column=4, sticky="w")
        ttk.Label(four_phase, textvariable=self.four_phase_stroke_phase_live,
                  width=20).grid(row=12, column=5, sticky="w", padx=8)
        ttk.Checkbutton(four_phase, text="Offset A/B versus C/D timing",
                        variable=self.four_phase_group_delay).grid(row=13, column=0, sticky="w")
        ttk.Label(four_phase, text="Group delay (ms; +A/B later)").grid(row=13, column=1, sticky="e")
        ttk.Spinbox(four_phase, from_=-300, to=300, increment=10,
                    textvariable=self.four_phase_group_delay_ms, width=7).grid(
                        row=13, column=2, sticky="w")
        ttk.Label(four_phase, text="Transition (s)").grid(row=13, column=3, sticky="e")
        ttk.Spinbox(four_phase, from_=.1, to=5, increment=.1,
                    textvariable=self.four_phase_group_delay_transition, width=7).grid(
                        row=13, column=4, sticky="w")
        ttk.Label(four_phase, textvariable=self.four_phase_group_delay_live,
                  foreground="#555").grid(row=13, column=5, sticky="w")
        ttk.Checkbutton(four_phase, text="Bias sequence within each stroke",
                        variable=self.four_phase_moving_sequence).grid(row=14, column=0, sticky="w")
        ttk.Label(four_phase, text="Maximum blend").grid(row=14, column=1, sticky="e")
        ttk.Spinbox(four_phase, from_=0, to=1, increment=.05,
                    textvariable=self.four_phase_moving_sequence_depth, width=7).grid(
                        row=14, column=2, sticky="w")
        ttk.Label(four_phase, text="Stroke portion").grid(row=14, column=3, sticky="e")
        ttk.Spinbox(four_phase, from_=.1, to=1, increment=.05,
                    textvariable=self.four_phase_moving_sequence_width, width=7).grid(
                        row=14, column=4, sticky="w")
        ttk.Label(four_phase, textvariable=self.four_phase_moving_sequence_live,
                   foreground="#555").grid(row=14, column=5, sticky="w")
        ttk.Button(four_phase, text="Explain these controls",
                   command=self.show_four_phase_guide).grid(
                       row=5, column=1, columnspan=2, sticky="w", padx=(8, 0))
        self.four_phase_signed_values = []
        for offset, label in enumerate(("A signed", "B signed", "C signed", "D signed")):
            row = offset + 15
            ttk.Label(four_phase, text=label, width=18).grid(row=row, column=0, sticky="w")
            value = tk.StringVar(value="+0.0000")
            ttk.Label(four_phase, textvariable=value, width=10,
                      font=("TkDefaultFont", 10, "bold")).grid(row=row, column=1, sticky="w")
            self.four_phase_signed_values.append(value)
        ttk.Label(four_phase, text="Conceptual relative potentials (−1 to +1); not T-code") \
            .grid(row=15, column=2, columnspan=4, sticky="w", padx=8)
        ttk.Separator(four_phase, orient="horizontal").grid(
            row=19, column=0, columnspan=6, sticky="ew", pady=7)
        self.four_phase_potential_bars, self.four_phase_potential_values = [], []
        for offset, label in enumerate(("E1 / A potential", "E2 / B potential",
                                        "E3 / C potential", "E4 / D potential")):
            row = offset + 20
            ttk.Label(four_phase, text=label, width=18).grid(row=row, column=0, sticky="w")
            ttk.Label(four_phase, text="0").grid(row=row, column=1)
            bar = ttk.Progressbar(four_phase, orient="horizontal", mode="determinate",
                                  maximum=1.0, length=520)
            bar.grid(row=row, column=2, padx=8)
            ttk.Label(four_phase, text="1").grid(row=row, column=3)
            value = tk.StringVar(value="0.0000")
            ttk.Label(four_phase, textvariable=value, width=8,
                      font=("TkDefaultFont", 10, "bold")).grid(row=row, column=4, padx=8)
            self.four_phase_potential_bars.append(bar)
            self.four_phase_potential_values.append(value)
        self.four_phase_roles = tk.StringVar(value="Primary -- | preferred return --")
        ttk.Label(four_phase, textvariable=self.four_phase_roles,
                  foreground="#9b4b00").grid(row=20, column=5, rowspan=4, sticky="w", padx=18)
        ttk.Checkbutton(four_phase,
                        text="Send E1–E4 visual test (FOC-Stim hardware MUST be disconnected)",
                        variable=self.send_four_phase_visual,
                        command=self._four_phase_send_toggle).grid(
                            row=24, column=0, columnspan=4, sticky="w", pady=(8, 2))
        ttk.Label(four_phase, textvariable=self.four_phase_status).grid(
            row=24, column=4, columnspan=2, sticky="w", padx=8)
        # The internal commissioning plots remain available to the refresh code,
        # but are intentionally hidden in the publication UI.
        for hidden_row in (*range(0, 5), *range(15, 20), 24):
            for widget in four_phase.grid_slaves(row=hidden_row):
                widget.grid_remove()

        controller = self._frame("Xbox controller", 9, 0, 2)
        ttk.Checkbutton(controller, text="Enable controller controls",
                        variable=self.controller_enabled,
                        command=self._controller_enabled_changed).grid(row=0, column=0, sticky="w", padx=6)
        ttk.Label(controller, textvariable=self.controller_status,
                  font=("TkDefaultFont", 10, "bold"), width=22).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(controller, text="Direct Xbox input (works without focus)",
                        variable=self.direct_controller_enabled).grid(row=0, column=6, padx=12)
        ttk.Label(controller, text="Step").grid(row=0, column=2, padx=(12, 4))
        ttk.Spinbox(controller, from_=0.005, to=.25, increment=.005,
                    textvariable=self.controller_fine_step, width=7).grid(row=0, column=3)
        ttk.Label(controller, text="Phase step (degrees)").grid(row=0, column=4, padx=(18, 4))
        ttk.Spinbox(controller, from_=1, to=45, increment=1,
                    textvariable=self.prostate_phase_step, width=7).grid(row=0, column=5)
        ttk.Label(controller, text="X / Page Up: prostate phase ahead | Y / Page Down: prostate phase behind") \
            .grid(row=2, column=0, columnspan=6, sticky="w", padx=6, pady=(2, 2))
        ttk.Label(controller,
                  text="Direct Xbox: D-pad frequency/pulse frequency | LB + D-pad rise/width | RB cycle signalling sequence | X/Y phase | A Resume | B Neutral | Menu Stop") \
            .grid(row=3, column=0, columnspan=7, sticky="w", padx=6, pady=(2, 2))
        ttk.Label(controller,
                  text="W/S Frequency ramp ±  •  A/D Pulse frequency range −/+  •  I/K Rise range +/−  •  J/L Width range −/+  •  Enter Resume  •  Space Neutral  •  Esc Stop") \
            .grid(row=1, column=0, columnspan=6, sticky="w", padx=6, pady=(6, 2))

        variety = self._frame("Rolling Variety", 10, 0, 2)
        ttk.Checkbutton(variety, text="Enable rolling variety", variable=self.variety_enabled,
                        command=self._variety_toggle).grid(row=0, column=0, padx=6)
        for column, (label, variable, cycle) in enumerate((
                ("Frequency 1.0-0.5", self.variety_frequency, self.variety_frequency_cycle),
                ("Pulse frequency +/-0.20", self.variety_pulse_frequency, self.variety_pulse_frequency_cycle),
                ("Rise +/-0.20", self.variety_pulse_rise, self.variety_pulse_rise_cycle),
                ("Width +/-0.20", self.variety_pulse_width, self.variety_pulse_width_cycle),
                ("Phase -45/+45", self.variety_phase, self.variety_phase_cycle),
                ("Sequence carousel (hold min)", self.variety_electrode_morph,
                 self.variety_electrode_morph_cycle)), start=0):
            ttk.Checkbutton(variety, text=label, variable=variable,
                            command=self._variety_toggle).grid(row=1, column=column, padx=8)
            ttk.Spinbox(variety, from_=0.5, to=30, increment=.5, textvariable=cycle,
                        width=6).grid(row=2, column=column, pady=(2, 0))
        ttk.Label(variety, text="Transition sec").grid(row=3, column=5, pady=(3, 0))
        ttk.Spinbox(variety, from_=1, to=15, increment=.5,
                    textvariable=self.variety_electrode_morph_transition_seconds,
                    width=6).grid(row=4, column=5)
        ttk.Label(variety, textvariable=self.variety_status,
                  font=("TkDefaultFont", 10, "bold")).grid(row=0, column=3, columnspan=3, padx=18)

        controls = self._frame("Commissioning controls", 11, 0, 2)
        ttk.Button(controls, text="Neutral", command=self.neutral, width=18).pack(side="left", padx=12)
        ttk.Button(controls, text="Resume", command=self.resume, width=18).pack(side="left", padx=12)
        ttk.Button(controls, text="STOP", command=self.stop, width=18).pack(side="left", padx=12)
        ttk.Label(controls, text="Test without FOCstim hardware connected.").pack(side="right", padx=12)
        self.sections["Commissioning controls"].grid_remove()

        diagnostics = self._frame("Live diagnostics", 12, 0, 2)
        diagnostics.columnconfigure(1, weight=1)
        diagnostics.columnconfigure(3, weight=1)
        labels = (
            ("Raw incoming L0", "raw_l0"), ("Buffered/current-output L0", "output_l0"),
            ("Calculated speed", "speed"), ("Alpha", "alpha"),
            ("Beta", "beta"), ("Buffer fill", "buffer"),
            ("Configured look-ahead", "lookahead"), ("Measured queue delay", "actual_delay"),
            ("Incoming L0 commands", "input_count"), ("Output samples", "output_count"),
            ("Engine state", "state"),
            ("Active calculation", "active_mode"),
            ("Released sample mode", "output_mode"),
            ("Released volume", "output_volume"),
            ("Frequency (0-1)", "frequency"),
            ("Pulse frequency (0-1)", "pulse_frequency"),
            ("Pulse rise time (0-1)", "pulse_rise_time"),
            ("Pulse width (0-1)", "pulse_width"),
            ("Alpha-prostate", "alpha_prostate"),
            ("Beta-prostate", "beta_prostate"),
            ("Volume-prostate", "volume_prostate"),
        )
        for index, (label, key) in enumerate(labels):
            row = index // 2
            col = (index % 2) * 2
            ttk.Label(diagnostics, text=label).grid(row=row, column=col, sticky="w", padx=8, pady=5)
            ttk.Label(diagnostics, textvariable=self.diag_vars[key], font=("TkDefaultFont", 10, "bold")) \
                .grid(row=row, column=col + 1, sticky="w", padx=8, pady=5)

    def _set_mfp_status(self, text: str) -> None:
        self._record_connection_event("MFP", text)
        self.root.after(0, self.mfp_status.set, text)

    def _set_restim_status(self, text: str) -> None:
        self._record_connection_event("Primary", text)
        self.root.after(0, self.restim_status.set, text)

    def _set_prostate_status(self, text: str) -> None:
        self._record_connection_event("Prostate", text)
        self.root.after(0, self.prostate_status.set, text)

    def _record_connection_event(self, source: str, text: str) -> None:
        if self._last_connection_event.get(source) == text:
            return
        self._last_connection_event[source] = text
        stamp = time.strftime("%H:%M:%S")
        self._connection_events.append(f"{stamp}  {source}: {text}")

    def show_connection_log(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Connection and recovery log")
        window.geometry("760x360")
        window.minsize(560, 260)
        body = ttk.Frame(window, padding=10)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=(
            "Recent connection changes. A quiet script is reported separately from a failed listener."
        )).pack(anchor="w", pady=(0, 8))
        text_box = tk.Text(body, wrap="word", height=14, state="normal")
        text_box.pack(fill="both", expand=True)
        text_box.insert("1.0", "\n".join(self._connection_events) or "No connection events yet.")
        text_box.configure(state="disabled")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))

        def copy_log() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(self._connection_events))

        def clear_log() -> None:
            self._connection_events.clear()
            self._last_connection_event.clear()
            text_box.configure(state="normal")
            text_box.delete("1.0", "end")
            text_box.insert("1.0", "Connection log cleared.")
            text_box.configure(state="disabled")

        ttk.Button(buttons, text="Copy", command=copy_log).pack(side="left")
        ttk.Button(buttons, text="Clear", command=clear_log).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def _on_mfp_command(self, command, received_at: float) -> None:
        """Capture all MFP axes; L0 still enters the proven engine separately."""
        self.axis_router.receive(command, received_at)

    def _set_startup_status(self, text: str) -> None:
        self._record_connection_event("Startup", text)
        try:
            self.root.after(0, self.startup_status.set, text)
        except (RuntimeError, tk.TclError):
            pass

    def _browse_launch_target(self, variable: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Select application or shortcut",
            filetypes=(("Applications and shortcuts", "*.exe *.lnk *.bat *.cmd"),
                       ("All files", "*.*")))
        if selected:
            variable.set(selected)

    def show_session_startup(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Session startup")
        window.transient(self.root)
        window.geometry("820x300")
        body = ttk.Frame(window, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=(
            "Optional standalone session coordinator. Vector can launch the selected applications, "
            "wait for ReStim services to become available, connect them, and report one session-ready state. "
            "Signal generation remains entirely inside Vector."), wraplength=760).grid(
                row=0, column=0, columnspan=4, sticky="w", pady=(0, 10))
        rows = (
            ("MultiFunPlayer", self.auto_start_mfp, self.mfp_launch_target),
            ("Primary ReStim", self.auto_start_restim, self.restim_launch_target),
            ("Prostate ReStim", self.auto_start_prostate, self.prostate_launch_target),
        )
        for row, (label, enabled, target) in enumerate(rows, 1):
            ttk.Checkbutton(body, text=f"Auto-start {label}", variable=enabled).grid(
                row=row, column=0, sticky="w", pady=5)
            ttk.Entry(body, textvariable=target, width=62).grid(
                row=row, column=1, columnspan=2, sticky="ew", padx=8)
            ttk.Button(body, text="Browse…",
                       command=lambda v=target: self._browse_launch_target(v)).grid(
                           row=row, column=3, sticky="e")
        ttk.Label(body, textvariable=self.startup_status, foreground="#555").grid(
            row=5, column=0, columnspan=4, sticky="w", pady=(12, 6))
        buttons = ttk.Frame(body)
        buttons.grid(row=6, column=0, columnspan=4, sticky="ew")
        ttk.Button(buttons, text="Start selected session", command=self._launch_session_apps).pack(side="left")
        ttk.Button(buttons, text="Save", command=self._save_settings).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")
        body.columnconfigure(1, weight=1)

    def _launch_session_apps(self) -> None:
        if self._startup_in_progress:
            self._set_startup_status("Session startup already in progress")
            return

        selected = {
            "mfp": bool(self.auto_start_mfp.get()),
            "restim": bool(self.auto_start_restim.get()),
            "prostate": bool(self.auto_start_prostate.get()),
        }
        targets = {
            "mfp": self.mfp_launch_target.get(),
            "restim": self.restim_launch_target.get(),
            "prostate": self.prostate_launch_target.get(),
        }
        hosts = {
            "restim": self.restim_host.get().strip(),
            "prostate": self.prostate_host.get().strip(),
        }
        ports = {
            "restim": int(self.restim_port.get()),
            "prostate": int(self.prostate_port.get()),
        }
        if not any(selected.values()):
            self.session_ready_status.set("SESSION: MANUAL")
            self._set_startup_status("No auto-start applications selected")
            self._save_settings()
            return

        self._startup_in_progress = True
        self.session_ready_status.set("SESSION: STARTING")
        self._set_startup_status("Starting selected session components…")
        self._save_settings()

        # MFP sends into Vector, so Vector can prepare the listener immediately.
        if selected["mfp"]:
            self.start_listener()

        def worker() -> None:
            messages: list[str] = []
            failed: list[str] = []
            if selected["mfp"]:
                result = self.orchestrator.launch("MultiFunPlayer", targets["mfp"])
                messages.append(result.message)
                if targets["mfp"].strip() and not result.launched and "already launched" not in result.message:
                    failed.append("MultiFunPlayer")

            for key, label in (("restim", "Primary ReStim"), ("prostate", "Prostate ReStim")):
                if not selected[key]:
                    continue
                host, port = hosts[key], ports[key]
                if port_is_open(host, port):
                    messages.append(f"{label}: already listening on {host}:{port}")
                else:
                    result = self.orchestrator.launch(label, targets[key])
                    messages.append(result.message)
                    if not wait_for_port(host, port, timeout=12.0):
                        failed.append(label)
                        messages.append(f"{label}: port {host}:{port} not ready after 12 s")

            def finish() -> None:
                # Only attempt WebSocket handshakes after the corresponding TCP service is ready.
                if selected["restim"] and "Primary ReStim" not in failed:
                    self.connect_restim()
                if selected["prostate"] and "Prostate ReStim" not in failed:
                    self.connect_prostate()
                self._startup_in_progress = False
                if failed:
                    self.session_ready_status.set("SESSION: ATTENTION")
                    messages.append("Attention: " + ", ".join(failed))
                else:
                    self.session_ready_status.set("SESSION: READY")
                    messages.append("READY")
                self._set_startup_status(" | ".join(messages))

            self.root.after(0, finish)

        threading.Thread(target=worker, name="vector-session-startup", daemon=True).start()

    def _auto_start_session(self) -> None:
        if self.auto_start_mfp.get() or self.auto_start_restim.get() or self.auto_start_prostate.get():
            self._launch_session_apps()

    def show_axis_routing(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("MFP authored-axis routing")
        window.transient(self.root)
        window.geometry("900x680")
        outer = ttk.Frame(window, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=(
            "Choose manual per-axis routing, or Auto authored ReStim set. Auto mode only takes over "
            "when MFP is clearly supplying ReStim-semantic axes (for example V0/C0/P0/P1/P3/E1-E4). "
            "It then passes the complete authored set, including L0/L1, on Vector's delayed timeline; "
            "any missing ReStim axes remain Vector-generated."),
            wraplength=840).pack(anchor="w", pady=(0, 8))
        policy = ttk.Frame(outer)
        policy.pack(fill="x", pady=(0, 8))
        ttk.Label(policy, text="Routing policy:", font=("TkDefaultFont", 9, "bold")).pack(side="left")
        ttk.Radiobutton(policy, text="Manual selected axes", variable=self.authored_routing_mode,
                        value="Manual selected axes", command=self._save_settings).pack(side="left", padx=(10, 4))
        ttk.Radiobutton(policy, text="Auto authored ReStim set", variable=self.authored_routing_mode,
                        value="Auto authored ReStim set", command=self._save_settings).pack(side="left", padx=4)

        state_frame = ttk.LabelFrame(outer, text="Live routing state", padding=(10, 7))
        state_frame.pack(fill="x", pady=(0, 8))
        discovered_text = tk.StringVar(value="Detected this session: none")
        live_text = tk.StringVar(value="Currently live: none")
        mode_text = tk.StringVar(value="Routing mode: VECTOR GENERATION")
        ttk.Label(state_frame, textvariable=discovered_text).pack(anchor="w")
        ttk.Label(state_frame, textvariable=live_text).pack(anchor="w", pady=(2, 0))
        ttk.Label(state_frame, textvariable=mode_text, font=("TkDefaultFont", 9, "bold")).pack(anchor="w", pady=(2, 0))

        frame = ttk.Frame(outer)
        frame.pack(fill="x", expand=False)
        controls: dict[str, tuple[tk.BooleanVar, ttk.Label, ttk.Label]] = {}

        ttk.Separator(outer).pack(fill="x", pady=(12, 8))
        ttk.Label(outer, text="Recent MFP packets (raw input → parsed axes)",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w")
        packet_box = tk.Text(outer, height=12, wrap="none")
        packet_box.pack(fill="both", expand=True, pady=(4, 6))
        packet_box.configure(state="disabled")
        packet_signature = [None]

        def copy_packets() -> None:
            packets = self.listener.recent_packets(40)
            lines = []
            now = time.monotonic()
            for packet in packets:
                age = max(0.0, now - float(packet["time"]))
                axes = ",".join(packet["axes"]) or "none"
                lines.append(f'{packet["transport"]} {age:5.2f}s  parsed=[{axes}]  raw={packet["raw"]}')
            self.root.clipboard_clear()
            self.root.clipboard_append("\n".join(lines))

        packet_buttons = ttk.Frame(outer)
        packet_buttons.pack(fill="x")
        ttk.Button(packet_buttons, text="Copy packet diagnostics",
                   command=copy_packets).pack(side="left")
        generated = {"L0", "L1", "E1", "E2", "E3", "E4", "V0", "C0", "P0", "P1", "P3"}
        axis_names = {
            "L0": "Alpha / primary position", "L1": "Beta",
            "V0": "Primary volume", "C0": "Frequency",
            "P0": "Pulse frequency", "P1": "Pulse width", "P3": "Pulse rise time",
            "E1": "Electrode A", "E2": "Electrode B", "E3": "Electrode C", "E4": "Electrode D",
            "V1": "Additional volume axis",
        }

        def toggle(axis: str, variable: tk.BooleanVar) -> None:
            self.axis_router.set_enabled(axis, variable.get())
            self._save_settings()

        def refresh_routes() -> None:
            if not window.winfo_exists():
                return
            now = time.monotonic()
            status = self.axis_router.axis_status(now)
            axes = sorted(set(status) | self.axis_router.enabled_axes())
            discovered = sorted(status)
            live_axes = sorted(self.axis_router.live_axes(now))
            discovered_text.set("Detected this session: " + (", ".join(discovered) if discovered else "none"))
            live_text.set("Currently live: " + (", ".join(live_axes) if live_axes else "none"))
            if not axes:
                self.authored_axes_status.set("No authored axes detected")
                mode_text.set("Routing mode: VECTOR GENERATION")
            else:
                enabled = sorted(self.axis_router.enabled_axes())
                if self.authored_routing_mode.get() == "Auto authored ReStim set":
                    auto_active = self.axis_router.auto_authored_active(now)
                    if auto_active:
                        suffix = " | AUTO full authored set"
                        mode_text.set("Routing mode: AUTO AUTHORED RESTIM")
                    else:
                        suffix = " | AUTO waiting; Vector generation"
                        mode_text.set("Routing mode: VECTOR GENERATION (auto waiting)")
                else:
                    suffix = (" | routed: " + ", ".join(enabled) if enabled else " | Vector generation active")
                    mode_text.set("Routing mode: MANUAL PASSTHROUGH" if enabled else "Routing mode: VECTOR GENERATION")
                self.authored_axes_status.set("Authored axes: " + ", ".join(axes) + suffix)
            packets = self.listener.recent_packets(12)
            signature = tuple((p["transport"], p["raw"], tuple(p["axes"])) for p in packets)
            if signature != packet_signature[0]:
                packet_signature[0] = signature
                packet_now = time.monotonic()
                lines = []
                for packet in packets:
                    age = max(0.0, packet_now - float(packet["time"]))
                    parsed = ",".join(packet["axes"]) or "none"
                    raw = str(packet["raw"]).replace("\r", "\\r").replace("\n", "\\n")
                    if len(raw) > 180:
                        raw = raw[:177] + "..."
                    lines.append(f'{packet["transport"]} {age:5.2f}s  parsed=[{parsed}]  raw={raw}')
                packet_box.configure(state="normal")
                packet_box.delete("1.0", "end")
                packet_box.insert("1.0", "\n".join(lines) if lines else "Waiting for MFP packets…")
                packet_box.configure(state="disabled")
            for axis in axes:
                if axis not in controls:
                    row = len(controls)
                    var = tk.BooleanVar(value=axis in self.axis_router.enabled_axes())
                    label = axis_names.get(axis, axis)
                    ttk.Checkbutton(frame, text=f"{axis}  {label}", variable=var,
                                    command=lambda a=axis, v=var: toggle(a, v)).grid(
                                        row=row, column=0, sticky="w", pady=4)
                    mode = "Vector candidate" if axis in generated else "additional axis"
                    owner = ttk.Label(frame, text=mode)
                    owner.grid(row=row, column=1, sticky="w", padx=12)
                    live = ttk.Label(frame, text="waiting")
                    live.grid(row=row, column=2, sticky="w", padx=12)
                    controls[axis] = (var, live, owner)
                info = status.get(axis)
                live = controls[axis][1]
                owner = controls[axis][2]
                is_live = axis in live_axes
                if self.authored_routing_mode.get() == "Auto authored ReStim set":
                    authored = self.axis_router.auto_authored_active(now) and is_live
                else:
                    authored = axis in self.axis_router.enabled_axes() and is_live
                if authored:
                    owner.configure(text="AUTHORED")
                elif axis in generated:
                    owner.configure(text="VECTOR")
                elif is_live:
                    owner.configure(text="MFP (not routed)")
                else:
                    owner.configure(text="inactive")
                if info is None:
                    live.configure(text="configured; not seen this session")
                else:
                    value = info.get("value")
                    age = float(info.get("last_seen_age", 0.0))
                    live.configure(text=f"{value:.3f} | {age:.1f}s ago" if value is not None else f"{age:.1f}s ago")
            window.after(300, refresh_routes)

        ttk.Separator(outer).pack(fill="x", pady=8)
        ttk.Button(outer, text="Close", command=window.destroy).pack(anchor="e")
        refresh_routes()

    def start_listener(self) -> None:
        try:
            self.listener.start(self.mfp_host.get().strip(), self.mfp_port.get())
        except Exception as exc:
            messagebox.showerror("MFP listener", str(exc))

    def connect_restim(self) -> None:
        try:
            self.restim.connect(self.restim_host.get().strip(), self.restim_port.get())
        except OSError as exc:
            self._set_restim_status(f"Connection failed: {exc}")

    def connect_prostate(self) -> None:
        try:
            self.prostate_restim.connect(self.prostate_host.get().strip(), self.prostate_port.get())
        except OSError as exc:
            self._set_prostate_status(f"Connection failed: {exc}")

    def _four_phase_send_toggle(self) -> None:
        if not self.send_four_phase_visual.get():
            return
        if not messagebox.askyesno(
                "Enable four-phase visual test",
                "Confirm FOC-Stim stimulation hardware is disconnected.\n\n"
                "Vector will send E1–E4 commands to the connected four-phase ReStim "
                "instance for visual commissioning only."):
            self.send_four_phase_visual.set(False)

    def _bind_controller_keys(self) -> None:
        for key, action in (("<w>", lambda: self._adjust_frequency_ramp(1)),
                            ("<s>", lambda: self._adjust_frequency_ramp(-1)),
                            ("<a>", lambda: self._shift_control_range("pulse_frequency", -1)),
                            ("<d>", lambda: self._shift_control_range("pulse_frequency", 1)),
                            ("<i>", lambda: self._shift_control_range("pulse_rise", 1)),
                            ("<k>", lambda: self._shift_control_range("pulse_rise", -1)),
                            ("<j>", lambda: self._shift_control_range("pulse_width", -1)),
                            ("<l>", lambda: self._shift_control_range("pulse_width", 1)),
                            ("<o>", self._cycle_electrode_order),
                            ("<bracketleft>", lambda: self._apply_preset("A")),
                            ("<bracketright>", lambda: self._apply_preset("B")),
                            ("<Prior>", lambda: self._adjust_prostate_phase(1)),
                            ("<Next>", lambda: self._adjust_prostate_phase(-1)),
                            ("<Return>", self.resume), ("<space>", self.neutral),
                            ("<Escape>", self.stop)):
            self.root.bind(key, lambda event, fn=action: self._controller_key(event, fn))

    def _controller_key(self, event, action):
        if not self.controller_enabled.get():
            return None
        if self.direct_controller_enabled.get() and self.xinput.connected:
            return "break"
        # Numeric/text editing retains ordinary keyboard behaviour.
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return None
        action()
        return "break"

    def _controller_enabled_changed(self) -> None:
        if self.controller_enabled.get():
            self.controller_status.set("Controller enabled; detecting Xbox input")
        else:
            self.controller_status.set("Disabled")
        self.apply_config()

    def _adjust_frequency_ramp(self, direction: int) -> None:
        self.variety_frequency.set(False)
        step = self.controller_fine_step.get()
        self.frequency_ramp_level.set(round(min(1.0, max(0.0,
            self.frequency_ramp_level.get() + direction * step)), 4))
        self.apply_config()

    def _shift_control_range(self, target: str, direction: int) -> None:
        {"pulse_frequency": self.variety_pulse_frequency,
         "pulse_rise": self.variety_pulse_rise,
         "pulse_width": self.variety_pulse_width}[target].set(False)
        pairs = {
            "pulse_frequency": (self.pulse_frequency_min, self.pulse_frequency_max),
            "pulse_rise": (self.pulse_rise_min, self.pulse_rise_max),
            "pulse_width": (self.pulse_width_min, self.pulse_width_max),
        }
        minimum, maximum = pairs[target]
        low, high = minimum.get(), maximum.get()
        delta = direction * self.controller_fine_step.get()
        if low + delta < 0.0:
            delta = -low
        if high + delta > 1.0:
            delta = 1.0 - high
        minimum.set(round(low + delta, 4))
        maximum.set(round(high + delta, 4))
        self.apply_config()

    def _adjust_prostate_phase(self, direction: int) -> None:
        self.variety_phase.set(False)
        phase = self.prostate_phase_degrees.get() + direction * self.prostate_phase_step.get()
        self.prostate_phase_degrees.set(round(min(90.0, max(-90.0, phase)), 1))
        self.apply_config()

    def _electrode_order_changed(self) -> None:
        self.variety_electrode_morph.set(False)

    def _cycle_electrode_order(self) -> None:
        self.variety_electrode_morph.set(False)
        try:
            index = ELECTRODE_ORDERS.index(self.electrode_order.get())
        except ValueError:
            index = -1
        self.electrode_order.set(ELECTRODE_ORDERS[(index + 1) % len(ELECTRODE_ORDERS)])

    def _xinput_status_threaded(self, status: str) -> None:
        self._controller_events.put(("status", status))

    def _set_xinput_status(self, status: str) -> None:
        if self.controller_enabled.get() and self.direct_controller_enabled.get():
            self.controller_status.set(status)

    def _xinput_buttons_threaded(self, buttons: int) -> None:
        self._controller_events.put(("buttons", buttons))

    def _xinput_state_threaded(self, buttons: int, connected: bool) -> None:
        self._controller_events.put(("state", (int(buttons), bool(connected))))

    def _drain_controller_events(self) -> None:
        while True:
            try:
                kind, value = self._controller_events.get_nowait()
            except queue.Empty:
                return
            if kind == "status":
                self._set_xinput_status(str(value))
            elif kind == "state":
                buttons, connected = value
                self._controller_snapshot = controller_snapshot(int(buttons), bool(connected))
                self._controller_state_sequence += 1
            else:
                self._handle_xinput_buttons(int(value))

    def _handle_xinput_buttons(self, buttons: int) -> None:
        if not self.controller_enabled.get() or not self.direct_controller_enabled.get():
            return
        modified = bool(buttons & LEFT_SHOULDER)
        if buttons & A: self.resume()
        if buttons & B: self.neutral()
        if buttons & START: self.stop()
        if buttons & X: self._adjust_prostate_phase(1)
        if buttons & Y: self._adjust_prostate_phase(-1)
        if buttons & RIGHT_SHOULDER:
            if modified:
                self._toggle_ab_preset()
            else:
                self._cycle_electrode_order()
        if modified:
            if buttons & DPAD_UP: self._shift_control_range("pulse_rise", 1)
            if buttons & DPAD_DOWN: self._shift_control_range("pulse_rise", -1)
            if buttons & DPAD_LEFT: self._shift_control_range("pulse_width", -1)
            if buttons & DPAD_RIGHT: self._shift_control_range("pulse_width", 1)
        else:
            if buttons & DPAD_UP: self._adjust_frequency_ramp(1)
            if buttons & DPAD_DOWN: self._adjust_frequency_ramp(-1)
            if buttons & DPAD_LEFT: self._shift_control_range("pulse_frequency", -1)
            if buttons & DPAD_RIGHT: self._shift_control_range("pulse_frequency", 1)

    def _variety_toggle(self) -> None:
        self._variety_started = time.monotonic()
        for enabled, variables in (
                (self.variety_pulse_frequency, (self.pulse_frequency_min, self.pulse_frequency_max)),
                (self.variety_pulse_rise, (self.pulse_rise_min, self.pulse_rise_max)),
                (self.variety_pulse_width, (self.pulse_width_min, self.pulse_width_max))):
            if enabled.get() and self.variety_enabled.get():
                low, high = fit_range_for_travel(variables[0].get(), variables[1].get())
                variables[0].set(low); variables[1].set(high)
        self._variety_baseline = {
            "frequency": self.frequency_ramp_level.get(),
            "pf": (self.pulse_frequency_min.get(), self.pulse_frequency_max.get()),
            "rise": (self.pulse_rise_min.get(), self.pulse_rise_max.get()),
            "width": (self.pulse_width_min.get(), self.pulse_width_max.get()),
            "phase": self.prostate_phase_degrees.get(),
        }
        self.variety_status.set("Running" if self.variety_enabled.get() else "Off")

    def show_variety_window(self) -> None:
        window = tk.Toplevel(self.root)
        window.title("Rolling Variety")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=16); body.pack(fill="both", expand=True)
        ttk.Checkbutton(body, text="Enable rolling variety", variable=self.variety_enabled,
                        command=self._variety_toggle).grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Item").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Label(body, text="Cycle minutes").grid(row=1, column=1, pady=8)
        options = (("Frequency ramp 1.0 to 0.5", self.variety_frequency, self.variety_frequency_cycle),
                   ("Pulse-frequency range +/-0.20", self.variety_pulse_frequency, self.variety_pulse_frequency_cycle),
                   ("Pulse-rise range +/-0.20", self.variety_pulse_rise, self.variety_pulse_rise_cycle),
                   ("Pulse-width range +/-0.20", self.variety_pulse_width, self.variety_pulse_width_cycle),
                   ("Prostate timing phase +/-45 degrees", self.variety_phase, self.variety_phase_cycle),
                   ("Sequence carousel (hold minutes)", self.variety_electrode_morph,
                    self.variety_electrode_morph_cycle))
        for row, (label, variable, cycle) in enumerate(options, start=2):
            ttk.Checkbutton(body, text=label, variable=variable,
                            command=self._variety_toggle).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(body, from_=0.5, to=30, increment=.5, textvariable=cycle,
                        width=8).grid(row=row, column=1, padx=12)
        ttk.Label(body, text="Sequence transition seconds").grid(
            row=8, column=0, sticky="w", pady=3)
        ttk.Spinbox(body, from_=1, to=15, increment=.5,
                    textvariable=self.variety_electrode_morph_transition_seconds,
                    width=8).grid(row=8, column=1, padx=12)
        ttk.Label(body, textvariable=self.variety_status,
                  font=("TkDefaultFont", 10, "bold")).grid(row=9, column=0, sticky="w", pady=(12, 0))
        ttk.Button(body, text="Restart cycle from current settings",
                   command=self._variety_toggle).grid(row=9, column=1, padx=12, pady=(12, 0))

    @staticmethod
    def _bounded_shift(pair: tuple[float, float], offset: float) -> tuple[float, float]:
        low, high = pair
        offset = max(-low, min(1.0 - high, offset))
        return round(low + offset, 4), round(high + offset, 4)

    def _update_variety(self) -> None:
        if not self.variety_enabled.get():
            return
        if not self._variety_baseline:
            self._variety_toggle()
        elapsed = time.monotonic() - self._variety_started
        depth = (self.engine.diagnostics().variation_depth
                 if self.speed_linked_variation.get() else 1.0)
        if self.variety_frequency.get():
            baseline = self._variety_baseline.get("frequency", 1.0)
            target = rolling_value(elapsed, self.variety_frequency_cycle.get(), .5, 1.0)
            self.frequency_ramp_level.set(round(baseline + (target - baseline) * depth, 4))
        for enabled, key, variables, travel, cycle in (
                (self.variety_pulse_frequency, "pf", (self.pulse_frequency_min, self.pulse_frequency_max), .20, self.variety_pulse_frequency_cycle),
                (self.variety_pulse_rise, "rise", (self.pulse_rise_min, self.pulse_rise_max), .20, self.variety_pulse_rise_cycle),
                (self.variety_pulse_width, "width", (self.pulse_width_min, self.pulse_width_max), .20, self.variety_pulse_width_cycle)):
            if enabled.get():
                offset = rolling_offset(elapsed, cycle.get())
                low, high = self._bounded_shift(
                    self._variety_baseline[key], offset * depth * travel)
                variables[0].set(low); variables[1].set(high)
        if self.variety_phase.get():
            baseline = self._variety_baseline["phase"]
            offset = rolling_offset(elapsed, self.variety_phase_cycle.get())
            self.prostate_phase_degrees.set(round(
                max(-90, min(90, baseline + offset * 45 * depth)), 1))
        self.variety_status.set(
            f"Running | {elapsed / 60:.1f} min | depth {depth * 100:.0f}% | independent cycles")
        self.apply_config()

    def _electrode_morph_state(self, at_time: float | None = None
                               ) -> tuple[str, str, float]:
        base = self.electrode_order.get()
        if not (self.variety_enabled.get() and self.variety_electrode_morph.get()):
            return base, base, 0.0
        elapsed = (time.monotonic() if at_time is None else at_time) - self._variety_started
        stage_seconds = max(1.0, self.variety_electrode_morph_cycle.get() * 60.0)
        transition_seconds = min(stage_seconds,
            max(.1, self.variety_electrode_morph_transition_seconds.get()))
        full_cycle = stage_seconds * len(ELECTRODE_ORDERS)
        return sequence_cycle_stage(
            base, (elapsed % full_cycle) / full_cycle,
            transition_seconds / stage_seconds)

    def _sequence_morph_state(self, direction: int, stroke_progress: float,
                              variation_depth: float, at_time: float | None = None
                              ) -> tuple[str, str, float, str]:
        if self.four_phase_spatial_model.get() == "Depth spread":
            order = self.electrode_order.get()
            return order, order, 0.0, "depth spread"
        carousel_active = self.variety_enabled.get() and self.variety_electrode_morph.get()
        if self.four_phase_moving_sequence.get() and not carousel_active:
            source, target, amount = moving_sequence_window(
                self.electrode_order.get(), direction, stroke_progress,
                self.four_phase_moving_sequence_depth.get() * variation_depth,
                self.four_phase_moving_sequence_width.get())
            return source, target, amount, "window"
        source, target, amount = self._electrode_morph_state(at_time)
        return source, target, amount, ("carousel" if carousel_active else "stable")

    def _effective_crossover_width(self, speed_percent: float) -> float:
        if not self.four_phase_adaptive_crossover.get():
            return min(1.0, max(.05, self.four_phase_crossover_width.get()))
        return adaptive_crossover_width(
            speed_percent, self.four_phase_slow_crossover_width.get(),
            self.four_phase_fast_crossover_width.get())

    def _crossover_profile(self, speed_percent: float, direction: int,
                           stroke_progress: float = .5, variation_depth: float = 1.0
                           ) -> tuple[float, str, float, str]:
        variation_depth = min(1.0, max(0.0, variation_depth))
        base_width = min(1.0, max(.05, self.four_phase_crossover_width.get()))
        adaptive_width = self._effective_crossover_width(speed_percent)
        adaptive_width = base_width + (adaptive_width - base_width) * variation_depth
        reverse_scale = 1.0 + (self.four_phase_reverse_width_scale.get() - 1.0) * variation_depth
        width, curve, sharpness, direction_name = directional_crossover_profile(
            direction, adaptive_width,
            self.four_phase_crossover_curve.get(),
            self.four_phase_crossover_sharpness.get(),
            self.four_phase_directional_trajectory.get() and variation_depth > .001,
            reverse_scale,
            self.four_phase_reverse_curve.get(),
            (self.four_phase_crossover_sharpness.get() +
             (self.four_phase_reverse_sharpness.get() -
              self.four_phase_crossover_sharpness.get()) * variation_depth))
        acceleration_scale = 1.0 + (
            self.four_phase_acceleration_width_scale.get() - 1.0) * variation_depth
        deceleration_scale = 1.0 + (
            self.four_phase_deceleration_width_scale.get() - 1.0) * variation_depth
        width, phase_name = stroke_phase_crossover(
            width, stroke_progress, self.four_phase_stroke_phase_texture.get(),
            acceleration_scale, deceleration_scale)
        if self.four_phase_stroke_phase_texture.get():
            direction_name = f"{direction_name} {phase_name}"
        return width, curve, sharpness, direction_name

    def _spatial_path(self, output_l0: float, variation_depth: float = 1.0) -> float:
        return 1.0 - output_l0 if self.four_phase_invert.get() else output_l0

    def _four_phase_profile(
            self, path_l0: float, direction: int, speed_percent: float,
            stroke_progress: float, variation_depth: float,
            at_time: float | None = None
            ) -> tuple[tuple[float, float, float, float], str, str, float, str]:
        """Build logical E1-E4 values, then apply physical sequence mapping."""
        if self.four_phase_spatial_model.get() == "Depth spread":
            logical = depth_spread(
                path_l0, self.four_phase_tip_retention.get(),
                self.four_phase_spread_softness.get(),
                self.four_phase_full_depth_capture.get())
            order = self.electrode_order.get()
            return map_electrode_order(logical, order), order, order, 0.0, "depth spread"

        width, curve, sharpness, _ = self._crossover_profile(
            speed_percent, direction, stroke_progress, variation_depth)
        logical = restim_crossfade(
            path_l0, direction, self.four_phase_return_depth.get(),
            width, curve, sharpness)
        source, target, amount, kind = self._sequence_morph_state(
            direction, stroke_progress, variation_depth, at_time)
        if source == target:
            return map_electrode_order(logical, source), source, target, amount, kind
        return (morph_electrode_order(logical, source, target, amount),
                source, target, amount, kind)

    def _update_modifier_status(self) -> None:
        if not self.modifier_enabled.get():
            self.modifier_status.set("Authored L0 unchanged")
            return
        self.modifier_status.set(
            f"ON  range ×{self.modifier_stroke_range.get():.2f} | "
            f"bias {self.modifier_position_bias.get():+.2f} | "
            f"smooth {self.modifier_smoothing.get():.2f}")

    def reset_modifiers(self) -> None:
        self.modifier_enabled.set(False)
        self.modifier_stroke_range.set(1.0)
        self.modifier_position_bias.set(0.0)
        self.modifier_smoothing.set(0.0)
        self.apply_config()
        self._save_settings()

    def show_modifier_window(self) -> None:
        if self._modifier_window is not None and self._modifier_window.winfo_exists():
            self._modifier_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._modifier_window = window
        window.title("Deterministic funscript modifiers — Alpha70")
        window.geometry("820x500")
        window.transient(self.root)
        body = ttk.Frame(window, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=(
            "Manual commissioning only. Vector transforms the authored L0 deterministically; "
            "the source script is never rewritten. Disable or Reset to return to authored motion."),
            wraplength=710).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        ttk.Checkbutton(body, text="Enable modifier layer", variable=self.modifier_enabled).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=6)
        rows = (
            ("Stroke range", self.modifier_stroke_range, 0.30, 1.50, 0.05,
             "One range control: compresses or expands authored L0 around 0.5; output clamps to 0..1."),
            ("Position bias", self.modifier_position_bias, -0.35, 0.35, 0.01,
             "Moves the path upward (+) or downward (-), bounded to 0..1."),
            ("Curve smoothing", self.modifier_smoothing, 0.00, 1.00, 0.05,
             "Blends authored positions toward a deterministic smoothstep curve."),
            ("Transition seconds", self.modifier_transition_seconds, 0.00, 5.00, 0.05,
             "Ramps modifier changes; commissioning default is 0.20 s."),
        )
        for r, (label, var, lo, hi, step, note) in enumerate(rows, 2):
            ttk.Label(body, text=label).grid(row=r, column=0, sticky="w", pady=7)
            ttk.Spinbox(body, from_=lo, to=hi, increment=step, textvariable=var, width=9).grid(
                row=r, column=1, sticky="w", padx=(8, 14))
            ttk.Label(body, text=note, foreground="#555", wraplength=430).grid(
                row=r, column=2, columnspan=2, sticky="w")
        ttk.Label(body, textvariable=self.modifier_status,
                  font=("TkDefaultFont", 10, "bold")).grid(
                      row=6, column=0, columnspan=4, sticky="w", pady=(14, 8))

        tempo = ttk.LabelFrame(body, text="Temporary authored-tempo window", padding=8)
        tempo.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(8, 6))
        ttk.Label(tempo, text="Scale").grid(row=0, column=0, sticky="w")
        ttk.Combobox(tempo, textvariable=self.modifier_tempo_scale, state="readonly", width=8,
                     values=(0.5, 1.0, 2.0)).grid(row=0, column=1, sticky="w", padx=(6, 16))
        ttk.Label(tempo, text="Duration seconds").grid(row=0, column=2, sticky="w")
        ttk.Combobox(tempo, textvariable=self.modifier_tempo_duration_seconds, state="readonly", width=8,
                     values=(10, 15, 30, 60, 90, 120)).grid(row=0, column=3, sticky="w", padx=(6, 16))
        ttk.Button(tempo, text="Start tempo window", command=self.start_tempo_window).grid(row=0, column=4, padx=6)
        ttk.Button(tempo, text="Restore ×1", command=self.restore_tempo).grid(row=0, column=5, padx=6)
        ttk.Label(tempo, textvariable=self.modifier_tempo_status, foreground="#555").grid(
            row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))
        ttk.Label(tempo, text=(
            "Tempo uses the loaded full funscript timeline, so 2× can read future authored positions. "
            "At the end of the window Vector rejoins the live authored position through the transition ramp."),
            wraplength=740, foreground="#555").grid(row=2, column=0, columnspan=6, sticky="w", pady=(5, 0))

        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Apply", command=self.apply_config).pack(side="left")
        ttk.Button(buttons, text="Reset to authored", command=self.reset_modifiers).pack(side="left", padx=8)
        ttk.Button(buttons, text="Save", command=self._save_settings).pack(side="left")
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    def start_tempo_window(self) -> None:
        try:
            scale = float(self.modifier_tempo_scale.get())
            if scale not in (0.5, 1.0, 2.0):
                raise ValueError("Tempo scale must be 0.5, 1.0 or 2.0")
            duration = min(600.0, max(1.0, float(self.modifier_tempo_duration_seconds.get())))
            if abs(scale - 1.0) < 1e-9:
                self.restore_tempo()
                return
            media_pos = self.timeline.position_seconds()
            if media_pos is None or not self.timeline.loaded:
                raise ValueError("Load and synchronize a funscript timeline before starting a tempo window")
            now = time.monotonic()
            with self._tempo_lock:
                self._tempo_scale_active = scale
                self._tempo_anchor_media = float(media_pos)
                self._tempo_anchor_clock = now
                self._tempo_expires_at = now + duration
                self._tempo_transition_seconds_active = min(5.0, max(0.0, float(self.modifier_transition_seconds.get())))
                self._tempo_restore_started_at = 0.0
                self._tempo_restore_from = None
            self.modifier_tempo_status.set(f"Tempo ×{scale:.1f} active for {duration:.0f} s")
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Tempo modifier", str(exc))

    def restore_tempo(self) -> None:
        now = time.monotonic()
        raw_pos = self.timeline.position_seconds()
        with self._tempo_lock:
            if self._tempo_scale_active != 1.0 and self._tempo_anchor_media is not None and raw_pos is not None:
                virtual = self._tempo_anchor_media + (float(raw_pos) - self._tempo_anchor_media) * self._tempo_scale_active
                self._tempo_restore_from = self.timeline.sample_position(virtual)
            self._tempo_scale_active = 1.0
            self._tempo_anchor_media = None
            self._tempo_expires_at = 0.0
            self._tempo_restore_started_at = now
        self.modifier_tempo_status.set("Tempo authored ×1.0")

    def _tempo_l0(self, raw_value: float, now: float) -> float:
        raw = min(1.0, max(0.0, float(raw_value)))
        with self._tempo_lock:
            scale = self._tempo_scale_active
            anchor_media = self._tempo_anchor_media
            anchor_clock = self._tempo_anchor_clock
            expires = self._tempo_expires_at
            transition = self._tempo_transition_seconds_active
            restore_started = self._tempo_restore_started_at
            restore_from = self._tempo_restore_from

        if scale != 1.0 and anchor_media is not None:
            media_pos = self.timeline.position_seconds()
            if media_pos is not None:
                virtual_seconds = anchor_media + (float(media_pos) - anchor_media) * scale
                warped = self.timeline.sample_position(virtual_seconds)
                if warped is not None:
                    if expires and now >= expires:
                        with self._tempo_lock:
                            self._tempo_scale_active = 1.0
                            self._tempo_anchor_media = None
                            self._tempo_expires_at = 0.0
                            self._tempo_restore_started_at = now
                            self._tempo_restore_from = float(warped)
                        restore_started = now
                        restore_from = float(warped)
                    else:
                        if transition <= 1e-9:
                            return float(warped)
                        blend = min(1.0, max(0.0, (now - anchor_clock) / transition))
                        return raw + (float(warped) - raw) * blend

        if restore_from is not None and restore_started > 0.0:
            if transition <= 1e-9:
                with self._tempo_lock:
                    self._tempo_restore_from = None
                    self._tempo_restore_started_at = 0.0
                return raw
            blend = min(1.0, max(0.0, (now - restore_started) / transition))
            if blend >= 1.0:
                with self._tempo_lock:
                    self._tempo_restore_from = None
                    self._tempo_restore_started_at = 0.0
                return raw
            return float(restore_from) + (raw - float(restore_from)) * blend
        return raw

    def apply_config(self) -> None:
        try:
            selected = MotionMode(self.mode.get())
            params = MotionParameters(self.minimum_radius.get(), self.speed_threshold.get(),
                                      self.direction_probability.get())
            pf_min, pf_max = self.pulse_frequency_min.get(), self.pulse_frequency_max.get()
            rise_min, rise_max = self.pulse_rise_min.get(), self.pulse_rise_max.get()
            width_min, width_max = self.pulse_width_min.get(), self.pulse_width_max.get()
            self.engine.configure(rate_hz=self.rate.get(), lookahead_seconds=self.lookahead.get(),
                                  volume=self.volume.get(), mode=selected, params=params,
                                  dynamic_volume=self.dynamic_volume.get(),
                                  volume_rest_level=self.volume_rest_level.get(),
                                  volume_ramp_speed_ratio=self.volume_ratio.get(),
                                  volume_ramp_up_seconds=self.volume_ramp_up.get(),
                                  frequency_ramp_level=self.frequency_ramp_level.get(),
                                  frequency_ramp_speed_ratio=self.frequency_ratio.get(),
                                  pulse_frequency_ratio=self.pulse_frequency_ratio.get(),
                                  pulse_frequency_min=pf_min,
                                  pulse_frequency_max=pf_max,
                                  pulse_rise_ratio=self.pulse_rise_ratio.get(),
                                  pulse_rise_min=rise_min,
                                  pulse_rise_max=rise_max,
                                  pulse_width_ratio=self.pulse_width_ratio.get(),
                                  pulse_width_min=width_min,
                                  pulse_width_max=width_max,
                                  prostate_narrow_ratio=self.prostate_narrow_ratio.get(),
                                  prostate_arc_depth=self.prostate_arc_depth.get(),
                                  prostate_stroke_threshold=self.prostate_threshold.get(),
                                  prostate_volume_multiplier=self.prostate_volume_multiplier.get(),
                                  prostate_rest_level=self.prostate_rest_level.get(),
                                  prostate_phase_degrees=self.prostate_phase_degrees.get(),
                                  jitter_enabled=self.jitter_enabled.get(),
                                  jitter_amplitude=self.jitter_amplitude.get(),
                                  jitter_cycle_seconds=self.jitter_cycle_seconds.get(),
                                  speed_linked_variation=self.speed_linked_variation.get(),
                                  variation_full_speed_percent=self.variation_full_speed_percent.get(),
                                  variation_fade_seconds=self.variation_fade_seconds.get(),
                                  spatial_curve=self.four_phase_spatial_curve.get(),
                                  spatial_blend=self.four_phase_spatial_blend.get())
            self.engine.configure_modifier(
                enabled=self.modifier_enabled.get(),
                stroke_range=self.modifier_stroke_range.get(),
                position_bias=self.modifier_position_bias.get(),
                smoothing=self.modifier_smoothing.get(),
                transition_seconds=self.modifier_transition_seconds.get())
            self._update_modifier_status()
        except (tk.TclError, ValueError) as exc:
            messagebox.showerror("Invalid settings", str(exc))

    def _on_top_focus_changed(self, *_args) -> None:
        if hasattr(self, "_top_focus_history"):
            self._top_focus_history.select(self.director_top_focus.get())

    def _on_bottom_focus_changed(self, *_args) -> None:
        if hasattr(self, "_bottom_focus_history"):
            self._bottom_focus_history.select(self.director_bottom_focus.get())
        if hasattr(self, "_bottom_focus_transition"):
            self._bottom_focus_transition.select(
                self.director_bottom_focus.get(), duration=1.0)

    def _focus_history_state(self) -> dict:
        top = self._top_focus_history.snapshot()
        bottom = self._bottom_focus_history.snapshot()
        bottom["strength"] = round(float(self.bottom_focus_strength.get()), 3)
        bottom["alpha_window"] = [round(x, 3) for x in bottom_focus_window(
            self.director_bottom_focus.get())]
        if hasattr(self, "_bottom_focus_transition"):
            bottom["transition"] = self._bottom_focus_transition.snapshot()
        top["strength"] = round(float(self.top_focus_strength.get()), 3)
        top["nominal_ceiling"] = round(float(self.top_focus_nominal_ceiling.get()), 3)
        return {"top": top, "bottom": bottom}

    def _spatial_gain_parameters(self, region: str) -> tuple[float, float, float, float]:
        if region == "top":
            return (self.top_spatial_gain_step_percent.get() / 100.0,
                    self.top_spatial_gain_min_percent.get() / 100.0,
                    self.top_spatial_gain_max_percent.get() / 100.0,
                    self.spatial_gain_ramp_percent_per_second.get() / 100.0)
        if region == "bottom":
            return (self.bottom_spatial_gain_step_percent.get() / 100.0,
                    self.bottom_spatial_gain_min_percent.get() / 100.0,
                    self.bottom_spatial_gain_max_percent.get() / 100.0,
                    self.spatial_gain_ramp_percent_per_second.get() / 100.0)
        raise ValueError("region must be top or bottom")

    def _change_spatial_gain(self, region: str, action: str) -> dict:
        step, minimum, maximum, ramp = self._spatial_gain_parameters(region)
        ctl = self._top_spatial_gain if region == "top" else self._bottom_spatial_gain
        display = self.top_spatial_gain_display if region == "top" else self.bottom_spatial_gain_display
        if action == "increase":
            ctl.step(+1, step=step, minimum=minimum, maximum=maximum)
        elif action == "decrease":
            ctl.step(-1, step=step, minimum=minimum, maximum=maximum)
        elif action == "restore":
            ctl.restore(minimum=minimum, maximum=maximum)
        else:
            raise ValueError("action must be increase, decrease, or restore")
        display.set(f"{ctl.target * 100:.0f}% target")
        self._save_settings()
        return ctl.snapshot(step=step, minimum=minimum, maximum=maximum,
                            ramp_per_second=ramp)

    TARGETING_PRESETS = {
        "authored": (1.0, 0.0),
        "base_prostate_broad": (0.70, -0.15),
        "base_prostate_focused": (0.50, -0.25),
        "base_prostate_tight": (0.30, -0.35),
        "glans_perineum_broad": (0.70, 0.15),
        "glans_perineum_focused": (0.50, 0.25),
        "glans_perineum_tight": (0.30, 0.35),
    }

    def _apply_targeting_preset(self, preset: str) -> dict:
        if preset not in self.TARGETING_PRESETS:
            raise ValueError("unknown targeting preset")
        stroke_range, bias = self.TARGETING_PRESETS[preset]
        if preset == "authored":
            self.modifier_enabled.set(False)
        else:
            self.modifier_enabled.set(True)
        self.modifier_stroke_range.set(stroke_range)
        self.modifier_position_bias.set(bias)
        if preset != "authored":
            self.modifier_smoothing.set(0.0)
        self.apply_config()
        self._save_settings()
        return {
            "preset": preset,
            "enabled": bool(self.modifier_enabled.get()),
            "stroke_range": round(float(self.modifier_stroke_range.get()), 3),
            "position_bias": round(float(self.modifier_position_bias.get()), 3),
            "transition_seconds": round(float(self.modifier_transition_seconds.get()), 3),
        }

    def _adjust_director_stroke_range(self, action: str) -> dict:
        action = str(action or "").strip().lower()
        current = float(self.modifier_stroke_range.get())
        if action == "narrower":
            target = max(0.30, current - 0.10)
        elif action == "wider":
            target = min(1.50, current + 0.10)
        elif action == "restore":
            target = 1.0
        else:
            raise ValueError("action must be narrower, wider, or restore")
        # Stroke-range changes are intentionally independent of position bias.
        # If another modifier is active, preserve it; otherwise enable only when
        # the requested range differs from authored 1.0.
        self.modifier_stroke_range.set(target)
        if abs(target - 1.0) > 1e-9 or abs(float(self.modifier_position_bias.get())) > 1e-9 or abs(float(self.modifier_smoothing.get())) > 1e-9:
            self.modifier_enabled.set(True)
        elif action == "restore":
            self.modifier_enabled.set(False)
        self.apply_config()
        self._save_settings()
        return {
            "action": action,
            "enabled": bool(self.modifier_enabled.get()),
            "stroke_range": round(float(self.modifier_stroke_range.get()), 3),
            "position_bias": round(float(self.modifier_position_bias.get()), 3),
            "transition_seconds": round(float(self.modifier_transition_seconds.get()), 3),
        }

    def _tempo_energy_band(self) -> str | None:
        snap = self.timeline.snapshot()
        now = snap.get("now") if isinstance(snap, dict) else None
        if isinstance(now, dict):
            band = str(now.get("energy_band") or "").strip().lower()
            return band or None
        return None

    def _start_director_tempo_window(self, scale: float, duration: float) -> dict:
        if scale not in (0.5, 2.0):
            raise ValueError("tempo scale must be 0.5 or 2.0")
        allowed = (10.0, 15.0, 30.0, 60.0, 90.0, 120.0)
        if duration not in allowed:
            raise ValueError("duration must be one of 10, 15, 30, 60, 90 or 120 seconds")
        media_pos = self.timeline.position_seconds()
        if media_pos is None or not self.timeline.loaded:
            raise ValueError("load and synchronize a funscript timeline before starting a tempo window")
        band = self._tempo_energy_band()
        # Commissioning guard: doubled tempo over an already challenging/testing
        # authored section is intentionally a short challenge.
        if scale == 2.0 and band in ("challenging", "testing") and duration > 15.0:
            raise ValueError(f"2x tempo is limited to 10 or 15 seconds while authored energy is {band}")
        self.modifier_tempo_scale.set(scale)
        self.modifier_tempo_duration_seconds.set(duration)
        self.start_tempo_window()
        return {
            "scale": scale,
            "duration_seconds": duration,
            "energy_band_at_start": band,
            "transition_seconds": round(float(self.modifier_transition_seconds.get()), 3),
        }

    def _director_capabilities(self) -> dict:
        return {
            "api_version": "0.9",
            "commands": {
                "preset": ["Baseline", "A", "B"],
                "rolling_variety": ["on", "off"],
                "neutral": True,
                "stop": {"enabled": True, "effect": "zero output and stop engine until Resume"},
                "generated_motion": {
                    "enabled": True,
                    "patterns": list(PATTERNS),
                    "minimum": [0.0, 0.90],
                    "maximum": [0.10, 1.0],
                    "minimum_travel": 0.10,
                    "stroke_duration_ms": [125, 3000],
                    "transition_seconds": [1, 15],
                    "duration_seconds": [30, 600],
                    "default_source": "authored_tcode",
                    "status": "Vector validates plans and deterministically generates fixed-cadence L0; raw samples are never accepted from Director.",
                },
                "modifier": {
                    "targeting_presets": list(self.TARGETING_PRESETS.keys()),
                    "stroke_range_actions": ["narrower", "wider", "restore"],
                    "stroke_range_step": 0.10,
                    "tempo_scales": [0.5, 2.0],
                    "tempo_durations_seconds": [10, 15, 30, 60, 90, 120],
                    "high_energy_2x_limit_seconds": 15,
                    "transition_seconds": round(float(self.modifier_transition_seconds.get()), 3),
                    "note": "Vector owns bounded deterministic maths; Director chooses semantic preset and time window.",
                },
                "semantic": {
                    "texture": {
                        "all_labels": list(self.TEXTURE_PROFILE_NAMES),
                        "available": [name for name in self.TEXTURE_PROFILE_NAMES
                                      if name in self._director_texture_profiles],
                    },
                    "primary_spatial": list(self.PRIMARY_SPATIAL_NAMES.keys()),
                    "secondary_spatial": list(self.SECONDARY_SPATIAL_NAMES.keys()),
                    "variation": {
                        "all_labels": list(self.VARIATION_PROFILE_NAMES),
                        "available": [name for name in self.VARIATION_PROFILE_NAMES
                                      if name in self._director_variation_profiles],
                    },
                    "top_focus": {
                        "all_labels": list(self.TOP_FOCUS_PROFILE_NAMES),
                        "available": list(self.TOP_FOCUS_PROFILE_NAMES),
                        "implementation": "E1-E4 neutral-centred weighting with nominal headroom",
                        "anatomy": {
                            "E1": "glans",
                            "E2": "shaft",
                            "E3": "lower shaft",
                            "E4": "root",
                        },
                    },
                    "bottom_focus": {
                        "all_labels": list(self.BOTTOM_FOCUS_PROFILE_NAMES),
                        "available": list(self.BOTTOM_FOCUS_PROFILE_NAMES),
                        "implementation": "secondary Alpha excursion window / dwell bias",
                        "anatomy": {
                            "A": "prostate",
                            "B": "anus",
                            "C": "testicles/perineum",
                        },
                    },
                },
            },
            "timeline": {
                "enabled": True,
                "read_only": True,
                "clock_sources": [FunscriptTimeline.CLOCK_MFP, FunscriptTimeline.CLOCK_MANUAL],
                "horizons_seconds": [1, 10, 30],
                "status": "full-funscript lookahead; MFP pattern-sync or internal manual preview clock",
            },
            "custom_events": {
                "enabled": bool(self.director_events_enabled.get()),
                "endpoint": "/v1/event/trigger",
                "cancel_endpoint": "/v1/event/cancel",
                "duration_seconds": {
                    "minimum": self.DIRECTOR_EVENT_MIN_SECONDS,
                    "maximum": self.DIRECTOR_EVENT_MAX_SECONDS,
                },
                "available": [
                    {
                        "id": event_id,
                        "label": details[0],
                        "description": details[1],
                        "default_duration_seconds": details[2],
                    }
                    for event_id, details in self.DIRECTOR_EVENT_CATALOG.items()
                ],
                "status": "operator opt-in; named recipes and duration bounds are enforced by Vector",
            },
            "spatial_focus_note": "For best effect, ensure electrode strength is properly calibrated in ReStim for the active electrode configuration.",
            "signal_authority": {
                "axis_control": {
                    "enabled": True,
                    "status": "bounded generated-motion plans only; direct raw-axis authority remains unavailable",
                },
                "spatial_gain": {
                    "enabled": True,
                    "top": {
                        "actions": ["increase", "decrease", "restore"],
                        "step_percent": round(self.top_spatial_gain_step_percent.get(), 1),
                        "minimum_percent": round(self.top_spatial_gain_min_percent.get(), 1),
                        "maximum_percent": round(self.top_spatial_gain_max_percent.get(), 1),
                    },
                    "bottom": {
                        "actions": ["increase", "decrease", "restore"],
                        "step_percent": round(self.bottom_spatial_gain_step_percent.get(), 1),
                        "minimum_percent": round(self.bottom_spatial_gain_min_percent.get(), 1),
                        "maximum_percent": round(self.bottom_spatial_gain_max_percent.get(), 1),
                    },
                    "ramp_percent_per_second": round(self.spatial_gain_ramp_percent_per_second.get(), 1),
                    "status": "bounded Vector-owned final V0 overlay; anatomical focus location is preserved",
                },
            },
        }

    def _director_controller_state(self) -> dict:
        snapshot = dict(self._controller_snapshot)
        snapshot.update({
            "ok": True,
            "sequence": self._controller_state_sequence,
            "source": "windows_xinput",
            "ptt_policy": "LB alone; LB+D-pad remains a Vector control gesture",
        })
        return snapshot

    def _director_event_state(self) -> dict:
        now = time.monotonic()
        active = self.event_engine.active_trigger_names(now)
        recent = []
        for entry in reversed(self._director_event_history):
            age = max(0.0, now - float(entry["started_at"]))
            recent.append({
                "event": entry["event"],
                "duration_seconds": entry["duration_seconds"],
                "age_seconds": round(age, 3),
                "active": entry["event"] in active and age < float(entry["duration_seconds"]),
            })
        return {
            "enabled": bool(self.director_events_enabled.get()),
            "active": active,
            "pending_count": self.event_engine.pending_trigger_count,
            "recent": recent[:6],
        }

    def _director_state(self) -> dict:
        diag = self.engine.diagnostics()
        live_axes = sorted(self.axis_router.live_axes())
        routing = ("AUTO AUTHORED RESTIM"
                   if self.authored_routing_mode.get() == "Auto authored ReStim set"
                   and self.axis_router.auto_authored_active(time.monotonic())
                   else "VECTOR GENERATION")
        preset_label = None
        if self._preset_active in ("A", "B"):
            preset_label = self.preset_a_name.get() if self._preset_active == "A" else self.preset_b_name.get()
        elif self._preset_active == "Baseline":
            preset_label = "Baseline"
        control = self.engine.control_state()
        mfp_receiving = self.mfp_status.get().startswith(("Receiving", "MFP Receiving"))
        return {
            "ok": True,
            "vector_version": __version__,
            "running": control["engine_state"] == "Running" and control["output_enabled"],
            "engine_state": control["engine_state"],
            "input_state": "Receiving" if mfp_receiving else "Idle",
            "output_enabled": control["output_enabled"],
            "mfp": {
                "receiving": mfp_receiving,
                "routing_mode": routing,
                "live_axes": live_axes,
            },
            "motion_source": self.generated_motion.snapshot(),
            "restim": {
                "primary_connected": self.restim.connected,
                "prostate_connected": self.prostate_restim.connected,
            },
            "preset": {
                "active": self._preset_active,
                "name": preset_label,
                "status": self.preset_status.get(),
            },
            "rolling_variety": {
                "enabled": self.variety_enabled.get(),
                "status": self.variety_status.get(),
                "depth": round(float(diag.variation_depth), 4),
            },
            "signal": self.engine.director_signal_snapshot(),
            "motion": {
                "l0": round(float(diag.output_l0), 4),
                "speed_percent": round(float(diag.speed_percent), 2),
                "alpha": round(float(diag.alpha), 4),
                "beta": round(float(diag.beta), 4),
                "stroke_progress": round(float(diag.stroke_progress), 4),
                "reversal_distance_seconds": (None if not math.isfinite(diag.reversal_distance_seconds)
                                                else round(float(diag.reversal_distance_seconds), 3)),
            },
            "future": self.engine.director_forecast(),
            "timeline": self.timeline.snapshot(),
            "custom_events": self._director_event_state(),
            "semantic": {
                "texture": self._active_director_profile("texture"),
                "primary_spatial": {
                    "id": ("top_depth_spread" if self.four_phase_spatial_model.get() == "Depth spread"
                           else "top_moving_focus"),
                    "label": (self.PRIMARY_SPATIAL_NAMES["top_depth_spread"]
                              if self.four_phase_spatial_model.get() == "Depth spread"
                              else self.PRIMARY_SPATIAL_NAMES["top_moving_focus"]),
                },
                "secondary_spatial": {
                    "id": "bottom_focus",
                    "label": self.SECONDARY_SPATIAL_NAMES["bottom_focus"],
                },
                "variation": self._active_director_profile("variation"),
                "top_focus": self.director_top_focus.get(),
                "bottom_focus": self.director_bottom_focus.get(),
                "anatomy_map": {
                    "top": {"E1": "glans", "E2": "shaft", "E3": "lower shaft", "E4": "root"},
                    "bottom": {"A": "prostate", "B": "anus", "C": "testicles/perineum"},
                },
                "focus_engine": {
                    "top_nominal_ceiling": round(float(self.top_focus_nominal_ceiling.get()), 3),
                    "top_strength": round(float(self.top_focus_strength.get()), 3),
                    "top_weights": [round(x, 3) for x in top_focus_weights(
                        self.director_top_focus.get(), diag.output_l0, self.top_focus_strength.get())],
                    "bottom_strength": round(float(self.bottom_focus_strength.get()), 3),
                    "bottom_alpha_window": [round(x, 3) for x in bottom_focus_window(
                        self.director_bottom_focus.get())],
                },
            },
            "modifier": {
                "enabled": bool(self.modifier_enabled.get()),
                "stroke_range": round(float(self.modifier_stroke_range.get()), 3),
                "position_bias": round(float(self.modifier_position_bias.get()), 3),
                "smoothing": round(float(self.modifier_smoothing.get()), 3),
                "transition_seconds": round(float(self.modifier_transition_seconds.get()), 3),
                "tempo_scale": round(float(self._tempo_scale_active), 3),
                "tempo_status": self.modifier_tempo_status.get(),
            },
            "focus_history": self._focus_history_state(),
            "spatial_gain": {
                "top": self._top_spatial_gain.snapshot(
                    step=self._spatial_gain_parameters("top")[0],
                    minimum=self._spatial_gain_parameters("top")[1],
                    maximum=self._spatial_gain_parameters("top")[2],
                    ramp_per_second=self._spatial_gain_parameters("top")[3]),
                "bottom": self._bottom_spatial_gain.snapshot(
                    step=self._spatial_gain_parameters("bottom")[0],
                    minimum=self._spatial_gain_parameters("bottom")[1],
                    maximum=self._spatial_gain_parameters("bottom")[2],
                    ramp_per_second=self._spatial_gain_parameters("bottom")[3]),
            },
            "controller": self._director_controller_state(),
            "capabilities": self._director_capabilities(),
        }

    def _trigger_director_event(self, body: dict) -> tuple[int, dict]:
        if not self.director_events_enabled.get():
            return 409, {"ok": False, "error": "Director custom events are disabled in Vector"}
        event_id = str(body.get("event", "")).strip()
        if event_id not in self.DIRECTOR_EVENT_CATALOG:
            return 400, {"ok": False, "error": "event is not in the curated catalogue"}
        default_duration = self.DIRECTOR_EVENT_CATALOG[event_id][2]
        try:
            duration = float(body.get("duration_seconds", default_duration))
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "duration_seconds must be a number"}
        if not self.DIRECTOR_EVENT_MIN_SECONDS <= duration <= self.DIRECTOR_EVENT_MAX_SECONDS:
            return 400, {
                "ok": False,
                "error": (f"duration_seconds must be between {self.DIRECTOR_EVENT_MIN_SECONDS:g} "
                          f"and {self.DIRECTOR_EVENT_MAX_SECONDS:g}"),
            }
        now = time.monotonic()
        params = dict(self.DIRECTOR_EVENT_PARAM_OVERRIDES.get(event_id, {}))
        params["duration_ms"] = int(round(duration * 1000.0))
        if not self.event_engine.schedule_trigger(event_id, params, now):
            return 500, {"ok": False, "error": "event recipe could not be expanded"}
        entry = {"event": event_id, "started_at": now,
                 "duration_seconds": round(duration, 3)}
        self._director_event_history.append(entry)
        return 202, {"ok": True, "accepted": True, **entry}

    def _drain_director_requests(self) -> None:
        while True:
            try:
                request = self.director_bridge.get_nowait()
            except queue.Empty:
                return
            try:
                if request.method == "GET" and request.path == "/v1/state":
                    request.status, request.response = 200, self._director_state()
                elif request.method == "GET" and request.path == "/v1/controller":
                    request.status, request.response = 200, self._director_controller_state()
                elif request.method == "GET" and request.path == "/v1/capabilities":
                    request.status, request.response = 200, {"ok": True, **self._director_capabilities()}
                elif request.method == "POST" and request.path == "/v1/preset":
                    preset = str(request.body.get("preset", "")).strip()
                    if preset not in ("Baseline", "A", "B"):
                        request.status = 400
                        request.response = {"ok": False, "error": "preset must be Baseline, A, or B"}
                    elif preset in ("A", "B") and preset not in self._preset_slots:
                        request.status = 409
                        request.response = {"ok": False, "error": f"Preset {preset} is empty"}
                    else:
                        self._apply_preset(preset)
                        request.status = 202
                        request.response = {"ok": True, "accepted": True, "preset": preset,
                                            "state": "transitioning"}
                elif request.method == "POST" and request.path == "/v1/rolling-variety":
                    enabled = request.body.get("enabled")
                    if not isinstance(enabled, bool):
                        request.status = 400
                        request.response = {"ok": False, "error": "enabled must be true or false"}
                    else:
                        self.variety_enabled.set(enabled)
                        self._variety_toggle()
                        self.apply_config()
                        request.status = 200
                        request.response = {"ok": True, "enabled": enabled}
                elif request.method == "POST" and request.path == "/v1/generated-motion/plan":
                    plan = MotionPlan.validated(request.body)
                    state = self.generated_motion.apply(plan, self.engine.diagnostics().output_l0)
                    request.status = 202
                    request.response = {"ok": True, "accepted": True, "motion_source": state}
                elif request.method == "POST" and request.path == "/v1/generated-motion/hold":
                    request.status = 200
                    request.response = {"ok": True, "motion_source": self.generated_motion.hold()}
                elif request.method == "POST" and request.path == "/v1/generated-motion/resume":
                    request.status = 200
                    request.response = {"ok": True, "motion_source": self.generated_motion.resume()}
                elif request.method == "POST" and request.path == "/v1/generated-motion/authored":
                    request.status = 200
                    request.response = {"ok": True, "motion_source": self.generated_motion.authored()}
                elif request.method == "POST" and request.path == "/v1/event/trigger":
                    request.status, request.response = self._trigger_director_event(request.body)
                elif request.method == "POST" and request.path == "/v1/event/cancel":
                    self.event_engine.clear_triggers()
                    request.status = 200
                    request.response = {"ok": True, "state": "custom events cancelled"}
                elif request.method == "POST" and request.path == "/v1/semantic/texture":
                    label = str(request.body.get("texture", "")).strip()
                    if label not in self.TEXTURE_PROFILE_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown texture label"}
                    elif label not in self._director_texture_profiles:
                        request.status = 409
                        request.response = {"ok": False, "error": f"Texture {label} is not captured"}
                    else:
                        self._apply_director_profile("texture", label)
                        request.status = 200
                        request.response = {"ok": True, "texture": label}
                elif request.method == "POST" and request.path == "/v1/semantic/primary-spatial":
                    choice = str(request.body.get("primary_spatial", "")).strip()
                    if choice not in self.PRIMARY_SPATIAL_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown primary spatial choice"}
                    else:
                        self._set_director_primary_spatial(choice)
                        request.status = 200
                        request.response = {"ok": True, "primary_spatial": choice}
                elif request.method == "POST" and request.path == "/v1/semantic/secondary-spatial":
                    choice = str(request.body.get("secondary_spatial", "")).strip()
                    if choice not in self.SECONDARY_SPATIAL_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown secondary spatial choice"}
                    else:
                        self.director_secondary_spatial.set(choice)
                        self._save_settings()
                        request.status = 200
                        request.response = {"ok": True, "secondary_spatial": choice}
                elif request.method == "POST" and request.path == "/v1/semantic/variation":
                    label = str(request.body.get("variation", "")).strip()
                    if label not in self.VARIATION_PROFILE_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown variation label"}
                    elif label not in self._director_variation_profiles:
                        request.status = 409
                        request.response = {"ok": False, "error": f"Variation {label} is not captured"}
                    else:
                        self._apply_director_profile("variation", label)
                        request.status = 200
                        request.response = {"ok": True, "variation": label}
                elif request.method == "POST" and request.path == "/v1/semantic/top-focus":
                    label = str(request.body.get("top_focus", "")).strip()
                    if label not in self.TOP_FOCUS_PROFILE_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown top-focus label"}
                    else:
                        self.director_top_focus.set(label)
                        self._save_settings()
                        request.status = 200
                        request.response = {"ok": True, "top_focus": label,
                                            "weights": [round(x, 3) for x in top_focus_weights(
                                                label, self.engine.diagnostics().output_l0, self.top_focus_strength.get())]}
                elif request.method == "POST" and request.path == "/v1/semantic/bottom-focus":
                    label = str(request.body.get("bottom_focus", "")).strip()
                    if label not in self.BOTTOM_FOCUS_PROFILE_NAMES:
                        request.status = 400
                        request.response = {"ok": False, "error": "unknown bottom-focus label"}
                    else:
                        self.director_bottom_focus.set(label)
                        self._save_settings()
                        request.status = 200
                        request.response = {"ok": True, "bottom_focus": label,
                                            "alpha_window": list(bottom_focus_window(label))}
                elif request.method == "POST" and request.path == "/v1/modifier/stroke-range":
                    action = str(request.body.get("action", "")).strip().lower()
                    try:
                        state = self._adjust_director_stroke_range(action)
                    except ValueError as exc:
                        request.status = 400
                        request.response = {"ok": False, "error": str(exc)}
                    else:
                        request.status = 200
                        request.response = {"ok": True, "stroke_range": state}
                elif request.method == "POST" and request.path == "/v1/modifier/target":
                    preset = str(request.body.get("preset", "")).strip().lower()
                    try:
                        state = self._apply_targeting_preset(preset)
                    except ValueError as exc:
                        request.status = 400
                        request.response = {"ok": False, "error": str(exc)}
                    else:
                        request.status = 200
                        request.response = {"ok": True, "targeting": state}
                elif request.method == "POST" and request.path == "/v1/modifier/tempo":
                    try:
                        scale = float(request.body.get("scale"))
                        duration = float(request.body.get("duration_seconds"))
                        state = self._start_director_tempo_window(scale, duration)
                    except (TypeError, ValueError) as exc:
                        request.status = 400
                        request.response = {"ok": False, "error": str(exc)}
                    else:
                        request.status = 200
                        request.response = {"ok": True, "tempo": state}
                elif request.method == "POST" and request.path == "/v1/modifier/restore":
                    self.reset_modifiers()
                    self.restore_tempo()
                    request.status = 200
                    request.response = {"ok": True, "modifier": "authored", "tempo_scale": 1.0}
                elif request.method == "POST" and request.path in ("/v1/spatial-gain/top", "/v1/spatial-gain/bottom"):
                    region = request.path.rsplit("/", 1)[-1]
                    action = str(request.body.get("action", "")).strip().lower()
                    if action not in ("increase", "decrease", "restore"):
                        request.status = 400
                        request.response = {"ok": False, "error": "action must be increase, decrease, or restore"}
                    else:
                        state = self._change_spatial_gain(region, action)
                        request.status = 200
                        request.response = {"ok": True, "region": region, "action": action,
                                            "spatial_gain": state}
                elif request.method == "POST" and request.path == "/v1/neutral":
                    self.neutral()
                    request.status = 200
                    request.response = {"ok": True, "state": "neutral"}
                elif request.method == "POST" and request.path == "/v1/stop":
                    self.stop()
                    request.status = 200
                    request.response = {"ok": True, "state": "stopped", "output_volume": 0.0}
                elif request.method == "POST" and request.path == "/v1/resume":
                    self.resume()
                    request.status = 200
                    request.response = {"ok": True, "state": "buffering", "resumed": True}
                else:
                    request.status = 404
                    request.response = {"ok": False, "error": "not found"}
            except Exception as exc:
                request.status = 500
                request.response = {"ok": False, "error": str(exc)}
            finally:
                request.completed.set()

    def _start_director(self) -> None:
        if self.director_server.running:
            self.director_status.set(f"DIRECTOR: {self.director_host.get()}:{self.director_port.get()}")
            return
        try:
            host, port = self.director_server.start(self.director_host.get().strip(), self.director_port.get())
        except (OSError, ValueError) as exc:
            self.director_status.set("DIRECTOR: ERROR")
            messagebox.showerror("Director API", str(exc))
            return
        self.director_status.set(f"DIRECTOR: {host}:{port}")

    def _stop_director(self) -> None:
        self.director_server.stop()
        self.director_status.set("DIRECTOR: OFF")

    def _director_enabled_changed(self) -> None:
        if self.director_enabled.get():
            self._start_director()
        else:
            self._stop_director()
        self._save_settings()

    def _director_events_enabled_changed(self) -> None:
        if not self.director_events_enabled.get():
            self.event_engine.clear_triggers()
        self._save_settings()

    def _auto_start_director(self) -> None:
        if self.director_enabled.get():
            self._start_director()

    def show_director_window(self) -> None:
        if self._director_window is not None and self._director_window.winfo_exists():
            self._director_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._director_window = window
        window.title("Director API")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=16)
        body.grid(sticky="nsew")
        ttk.Label(body, text=(
            "Optional loopback-only control interface. Vector remains fully standalone; "
            "no AI, voice, Ollama, or Gwendolyn component is required."), wraplength=650,
            justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))
        ttk.Checkbutton(body, text="Enable local Director API", variable=self.director_enabled,
                        command=self._director_enabled_changed).grid(row=1, column=0, columnspan=2, sticky="w")
        ttk.Label(body, text="Host").grid(row=2, column=0, sticky="w", pady=(10, 2))
        ttk.Entry(body, textvariable=self.director_host, width=18).grid(row=2, column=1, sticky="w", padx=6)
        ttk.Label(body, text="Port").grid(row=2, column=2, sticky="e")
        ttk.Spinbox(body, from_=1024, to=65535, textvariable=self.director_port, width=8).grid(row=2, column=3, padx=6)
        ttk.Label(body, textvariable=self.director_status,
                  font=("TkDefaultFont", 10, "bold")).grid(row=3, column=0, columnspan=4, sticky="w", pady=(10, 4))
        ttk.Checkbutton(
            body, text="Allow curated Director custom events",
            variable=self.director_events_enabled, command=self._director_events_enabled_changed,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 2))
        ttk.Label(body, text=("v0.5 commands: state/capabilities, Preset A/B/Baseline, Rolling Variety, Neutral, "
                              "semantic Texture/Spatial Focus/Variation, bounded Spatial Gain, and curated events."),
                  foreground="#555", wraplength=650, justify="left").grid(row=5, column=0, columnspan=4, sticky="w")
        ttk.Label(body, text=(
            "For best Spatial Focus effect, ensure electrode strength is properly calibrated in ReStim "
            "for the active electrode configuration. Spatial Gain is bounded and smoothly ramped by Vector."),
            foreground="#8a5a00", wraplength=650, justify="left").grid(
                row=6, column=0, columnspan=4, sticky="w", pady=(6, 12))
        ttk.Button(body, text="Semantic profiles", command=self.show_director_semantic_window).grid(row=7, column=0, sticky="w")
        ttk.Button(body, text="Funscript timeline...", command=self.show_timeline_window).grid(row=7, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Save", command=self._save_settings).grid(row=7, column=2, sticky="w", padx=6)
        ttk.Button(body, text="Close", command=window.destroy).grid(row=7, column=3, sticky="e")

    def show_timeline_window(self) -> None:
        if self._timeline_window is not None and self._timeline_window.winfo_exists():
            self._timeline_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._timeline_window = window
        window.title("Funscript Timeline")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=16)
        body.grid(sticky="nsew")
        ttk.Label(body, text=(
            "Read-only authored-script visibility. Vector can follow VLC/MPC directly and automatically resolve "
            "a matching .funscript, or fall back to MFP pattern sync/manual preview. Timeline data never drives output."),
            wraplength=700, justify="left").grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 12))
        ttk.Label(body, text="Funscript").grid(row=1, column=0, sticky="w")
        ttk.Label(body, textvariable=self.timeline_file_display, width=55).grid(row=1, column=1, columnspan=3, sticky="w", padx=6)
        ttk.Button(body, text="Load...", command=self._timeline_browse).grid(row=1, column=4, sticky="e")
        ttk.Label(body, text="Clock source").grid(row=2, column=0, sticky="w", pady=(10, 2))
        clock = ttk.Combobox(body, textvariable=self.timeline_clock_source, state="readonly", width=22,
                             values=(FunscriptTimeline.CLOCK_AUTO, FunscriptTimeline.CLOCK_VLC,
                                     FunscriptTimeline.CLOCK_MPC, FunscriptTimeline.CLOCK_MFP,
                                     FunscriptTimeline.CLOCK_MANUAL))
        clock.grid(row=2, column=1, sticky="w", padx=6)
        clock.bind("<<ComboboxSelected>>", lambda _e: self._timeline_clock_changed())
        ttk.Label(body, text="Player host").grid(row=3, column=0, sticky="w", pady=(10, 2))
        ttk.Entry(body, textvariable=self.timeline_media_host, width=18).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(body, text="VLC port").grid(row=3, column=2, sticky="e")
        ttk.Entry(body, textvariable=self.timeline_vlc_port, width=8).grid(row=3, column=3, sticky="w", padx=6)
        ttk.Label(body, text="MPC port").grid(row=3, column=4, sticky="w")
        ttk.Entry(body, textvariable=self.timeline_mpc_port, width=8).grid(row=3, column=5, sticky="w", padx=6)
        ttk.Label(body, text="VLC HTTP password").grid(row=4, column=0, sticky="w", pady=(6, 2))
        ttk.Entry(body, textvariable=self.timeline_vlc_password, show="*", width=18).grid(row=4, column=1, sticky="w", padx=6)
        ttk.Checkbutton(body, text="Auto-load matching funscript", variable=self.timeline_auto_load_script).grid(row=4, column=2, columnspan=2, sticky="w")
        ttk.Button(body, text="Apply player settings", command=self._apply_timeline_media_settings).grid(row=4, column=4, columnspan=2, sticky="w")
        ttk.Label(body, text="Script libraries (; separated)").grid(row=5, column=0, sticky="w", pady=(6, 2))
        ttk.Entry(body, textvariable=self.timeline_script_libraries, width=70).grid(row=5, column=1, columnspan=5, sticky="ew", padx=6)
        ttk.Label(body, text="Manual position (s)").grid(row=6, column=0, sticky="w", pady=(10, 2))
        ttk.Spinbox(body, from_=0, to=99999, increment=1, textvariable=self.timeline_manual_position, width=10).grid(row=6, column=1, sticky="w", padx=6)
        ttk.Button(body, text="Seek", command=self._timeline_seek).grid(row=6, column=2, sticky="w")
        ttk.Button(body, text="Play preview", command=self._timeline_play).grid(row=6, column=3, sticky="w", padx=6)
        ttk.Button(body, text="Pause", command=self._timeline_pause).grid(row=6, column=4, sticky="w")
        ttk.Separator(body, orient="horizontal").grid(row=7, column=0, columnspan=6, sticky="ew", pady=12)
        ttk.Label(body, textvariable=self.timeline_status_display, wraplength=760, justify="left").grid(row=8, column=0, columnspan=6, sticky="w")
        ttk.Label(body, text=(
            "Auto media player tries VLC first, then MPC. For local media, Vector reads the authoritative player time and "
            "looks beside the media for <video name>.funscript, then in configured script libraries. MFP pattern sync remains a fallback."),
            foreground="#555", wraplength=760, justify="left").grid(row=9, column=0, columnspan=6, sticky="w", pady=(8, 12))
        ttk.Button(body, text="Close", command=window.destroy).grid(row=10, column=5, sticky="e")
        self._refresh_timeline_window()

    def _timeline_browse(self) -> None:
        path = filedialog.askopenfilename(title="Load funscript", filetypes=[("Funscript", "*.funscript"), ("JSON", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            meta = self.timeline.load(path)
            self.timeline_file_display.set(meta.get("file") or path)
            self.timeline_status_display.set(f"Loaded {meta['actions']} actions, {meta['duration_seconds']:.1f} s")
            self._timeline_clock_changed()
        except Exception as exc:
            messagebox.showerror("Funscript Timeline", str(exc))

    def _apply_timeline_media_settings(self) -> None:
        libraries = [x.strip() for x in self.timeline_script_libraries.get().split(";") if x.strip()]
        try:
            self.timeline.configure_media(
                host=self.timeline_media_host.get(),
                vlc_port=self.timeline_vlc_port.get(),
                vlc_password=self.timeline_vlc_password.get(),
                mpc_port=self.timeline_mpc_port.get(),
                library_dirs=libraries,
                auto_load_script=self.timeline_auto_load_script.get(),
            )
            self.timeline.set_clock_mode(self.timeline_clock_source.get())
            self.timeline.request_media_poll()
            if self._timeline_window is not None and self._timeline_window.winfo_exists():
                self._refresh_timeline_window()
        except Exception as exc:
            if self._timeline_window is not None and self._timeline_window.winfo_exists():
                messagebox.showerror("Funscript Timeline", str(exc))

    def _timeline_clock_changed(self) -> None:
        try:
            self.timeline.set_clock_mode(self.timeline_clock_source.get())
            self._refresh_timeline_window()
        except Exception as exc:
            messagebox.showerror("Funscript Timeline", str(exc))

    def _timeline_seek(self) -> None:
        self.timeline.set_clock_mode(FunscriptTimeline.CLOCK_MANUAL)
        self.timeline_clock_source.set(FunscriptTimeline.CLOCK_MANUAL)
        self.timeline.manual_seek(self.timeline_manual_position.get())
        self._refresh_timeline_window()

    def _timeline_play(self) -> None:
        self.timeline.set_clock_mode(FunscriptTimeline.CLOCK_MANUAL)
        self.timeline_clock_source.set(FunscriptTimeline.CLOCK_MANUAL)
        self.timeline.manual_seek(self.timeline_manual_position.get())
        self.timeline.manual_play()
        self._refresh_timeline_window()

    def _timeline_pause(self) -> None:
        self.timeline.manual_pause()
        pos = self.timeline.position_seconds()
        if pos is not None:
            self.timeline_manual_position.set(round(pos, 2))
        self._refresh_timeline_window()

    def _refresh_timeline_window(self) -> None:
        snap = self.timeline.snapshot()
        if snap.get("loaded"):
            self.timeline_file_display.set(str(snap.get("file") or "Loaded funscript"))
        if not snap.get("loaded"):
            self.timeline_status_display.set("Timeline idle — load a .funscript to enable authored lookahead")
            return
        if not snap.get("synced"):
            conf = snap.get("sync_confidence")
            suffix = "" if conf is None else f" (match confidence {conf:.0%})"
            self.timeline_status_display.set("Loaded; waiting for timeline lock" + suffix)
            return
        pos = float(snap.get("position_seconds") or 0.0)
        self.timeline_manual_position.set(round(pos, 2))
        near = snap.get("next_10_seconds") or {}
        ahead = snap.get("next_30_seconds") or {}
        conf = snap.get("sync_confidence")
        conf_text = "" if conf is None else f" | sync {float(conf):.0%}"
        player = snap.get("media_player")
        media_text = f" | {player} {snap.get('media_state') or ''}" if player else ""
        health = snap.get("media_clock_health")
        health_text = f" | clock {health}" if player and health else ""
        raw = snap.get("media_raw_position")
        source = snap.get("media_position_source")
        raw_text = f" | raw {raw} ({source})" if player and raw is not None else ""
        auto_note = f" | {snap.get('auto_load_note')}" if snap.get("auto_load_note") else ""
        self.timeline_status_display.set(
            f"Position {pos:.2f}s{conf_text}{media_text}{health_text}{raw_text} | next 10s: {near.get('energy_band','?')} / {near.get('focus_region','?')} "
            f"| next 30s trend: {ahead.get('energy_trend','?')}{auto_note}")

    def _load_settings(self) -> bool:
        saved = load_settings()
        # Alpha68 had two perceptually redundant range controls. Preserve the
        # old global-range value when migrating, and retire stroke-amplitude.
        if "modifier_stroke_range" not in saved and "modifier_range_scale" in saved:
            saved["modifier_stroke_range"] = saved.get("modifier_range_scale", 1.0)
        for name in self.SETTINGS_FIELDS:
            if name in saved:
                try:
                    getattr(self, name).set(saved[name])
                except tk.TclError:
                    pass
        routes = saved.get("authored_axis_routes", [])
        if isinstance(routes, list):
            self.axis_router.set_enabled_axes(routes)
        mode = saved.get("authored_routing_mode")
        if mode in ("Manual selected axes", "Auto authored ReStim set"):
            self.authored_routing_mode.set(mode)
        slots = saved.get("four_phase_presets", {})
        if isinstance(slots, dict):
            for slot in ("A", "B"):
                if isinstance(slots.get(slot), dict):
                    self._preset_slots[slot] = slots[slot]
        texture_profiles = saved.get("director_texture_profiles", {})
        if isinstance(texture_profiles, dict):
            self._director_texture_profiles = {
                name: value for name, value in texture_profiles.items()
                if name in self.TEXTURE_PROFILE_NAMES and isinstance(value, dict)
            }
        variation_profiles = saved.get("director_variation_profiles", {})
        if isinstance(variation_profiles, dict):
            self._director_variation_profiles = {
                name: value for name, value in variation_profiles.items()
                if name in self.VARIATION_PROFILE_NAMES and isinstance(value, dict)
            }
        top_focus_profiles = saved.get("director_top_focus_profiles", {})
        if isinstance(top_focus_profiles, dict):
            self._director_top_focus_profiles = {
                name: value for name, value in top_focus_profiles.items()
                if name in self.TOP_FOCUS_PROFILE_NAMES and isinstance(value, dict)
            }
        bottom_focus_profiles = saved.get("director_bottom_focus_profiles", {})
        if isinstance(bottom_focus_profiles, dict):
            self._director_bottom_focus_profiles = {
                name: value for name, value in bottom_focus_profiles.items()
                if name in self.BOTTOM_FOCUS_PROFILE_NAMES and isinstance(value, dict)
            }
        if saved.get("director_texture") in self.TEXTURE_PROFILE_NAMES:
            self.director_texture.set(saved["director_texture"])
        if saved.get("director_variation") in self.VARIATION_PROFILE_NAMES:
            self.director_variation.set(saved["director_variation"])
        if saved.get("director_top_focus") in self.TOP_FOCUS_PROFILE_NAMES:
            self.director_top_focus.set(saved["director_top_focus"])
        if saved.get("director_bottom_focus") in self.BOTTOM_FOCUS_PROFILE_NAMES:
            self.director_bottom_focus.set(saved["director_bottom_focus"])
        if saved.get("director_primary_spatial") in self.PRIMARY_SPATIAL_NAMES:
            self.director_primary_spatial.set(saved["director_primary_spatial"])
        if saved.get("director_secondary_spatial") in self.SECONDARY_SPATIAL_NAMES:
            self.director_secondary_spatial.set(saved["director_secondary_spatial"])
        return not bool(saved.get("first_run_complete"))

    def _save_settings(self) -> None:
        values = {name: getattr(self, name).get() for name in self.SETTINGS_FIELDS}
        values["four_phase_presets"] = self._preset_slots
        values["authored_axis_routes"] = sorted(self.axis_router.enabled_axes())
        values["authored_routing_mode"] = self.authored_routing_mode.get()
        values["director_texture_profiles"] = self._director_texture_profiles
        values["director_variation_profiles"] = self._director_variation_profiles
        values["director_top_focus_profiles"] = self._director_top_focus_profiles
        values["director_bottom_focus_profiles"] = self._director_bottom_focus_profiles
        values["director_texture"] = self.director_texture.get()
        values["director_variation"] = self.director_variation.get()
        values["director_top_focus"] = self.director_top_focus.get()
        values["director_bottom_focus"] = self.director_bottom_focus.get()
        values["director_primary_spatial"] = self.director_primary_spatial.get()
        values["director_secondary_spatial"] = self.director_secondary_spatial.get()
        values["first_run_complete"] = True
        save_settings(values)

    def _director_profile_snapshot(self, kind: str) -> dict:
        if kind == "texture":
            fields = self.TEXTURE_PROFILE_FIELDS
        elif kind == "variation":
            fields = self.VARIATION_PROFILE_FIELDS
        elif kind == "top_focus":
            fields = self.TOP_FOCUS_PROFILE_FIELDS
        elif kind == "bottom_focus":
            fields = self.BOTTOM_FOCUS_PROFILE_FIELDS
        else:
            raise ValueError("unknown Director profile kind")
        return {name: getattr(self, name).get() for name in fields}

    def _director_profile_matches(self, kind: str, profile: dict) -> bool:
        current = self._director_profile_snapshot(kind)
        for name, expected in profile.items():
            actual = current.get(name)
            if isinstance(actual, (int, float)) and not isinstance(actual, bool):
                try:
                    if abs(float(actual) - float(expected)) > 1e-4:
                        return False
                except (TypeError, ValueError):
                    return False
            elif actual != expected:
                return False
        return True

    def _active_director_profile(self, kind: str) -> str:
        if kind == "texture":
            profiles, names = self._director_texture_profiles, self.TEXTURE_PROFILE_NAMES
        elif kind == "variation":
            profiles, names = self._director_variation_profiles, self.VARIATION_PROFILE_NAMES
        elif kind == "top_focus":
            profiles, names = self._director_top_focus_profiles, self.TOP_FOCUS_PROFILE_NAMES
        elif kind == "bottom_focus":
            profiles, names = self._director_bottom_focus_profiles, self.BOTTOM_FOCUS_PROFILE_NAMES
        else:
            return "Custom"
        for label in names:
            profile = profiles.get(label)
            if profile and self._director_profile_matches(kind, profile):
                return label
        return "Custom"

    def _refresh_director_profile_status(self) -> None:
        for label, var in self._director_texture_status_vars.items():
            var.set("Saved" if label in self._director_texture_profiles else "—")
        for label, var in self._director_variation_status_vars.items():
            var.set("Saved" if label in self._director_variation_profiles else "—")
        for label, var in self._director_top_focus_status_vars.items():
            var.set("Saved" if label in self._director_top_focus_profiles else "—")
        for label, var in self._director_bottom_focus_status_vars.items():
            var.set("Saved" if label in self._director_bottom_focus_profiles else "—")

    def _capture_director_profile(self, kind: str, label: str) -> None:
        if kind == "texture":
            self._director_texture_profiles[label] = self._director_profile_snapshot(kind)
            self.director_texture.set(label)
        elif kind == "variation":
            self._director_variation_profiles[label] = self._director_profile_snapshot(kind)
            self.director_variation.set(label)
        elif kind == "top_focus":
            self._director_top_focus_profiles[label] = self._director_profile_snapshot(kind)
            self.director_top_focus.set(label)
        elif kind == "bottom_focus":
            self._director_bottom_focus_profiles[label] = self._director_profile_snapshot(kind)
            self.director_bottom_focus.set(label)
        else:
            raise ValueError("unknown Director profile kind")
        self._save_settings()
        self._refresh_director_profile_status()
        self.director_semantic_status.set(f"{label} {kind} profile captured and saved")

    def _apply_director_profile(self, kind: str, label: str) -> None:
        if kind == "texture":
            profiles = self._director_texture_profiles
        elif kind == "variation":
            profiles = self._director_variation_profiles
        elif kind == "top_focus":
            profiles = self._director_top_focus_profiles
        elif kind == "bottom_focus":
            profiles = self._director_bottom_focus_profiles
        else:
            raise ValueError("unknown Director profile kind")
        profile = profiles.get(label)
        if not profile:
            return
        for name, value in profile.items():
            if hasattr(self, name):
                getattr(self, name).set(value)
        if kind == "texture":
            self.director_texture.set(label)
            self.apply_config()
        elif kind == "variation":
            self.director_variation.set(label)
            self._variety_toggle()
            self.apply_config()
        elif kind == "top_focus":
            self.director_top_focus.set(label)
            self.apply_config()
        else:
            self.director_bottom_focus.set(label)
            self.apply_config()
        self._save_settings()

    def _set_director_primary_spatial(self, choice: str) -> None:
        if choice == "top_moving_focus":
            self.four_phase_spatial_model.set("Moving focus")
        elif choice == "top_depth_spread":
            self.four_phase_spatial_model.set("Depth spread")
        else:
            raise ValueError("unknown primary spatial choice")
        self.director_primary_spatial.set(choice)
        self.apply_config()
        self._save_settings()

    def show_director_semantic_window(self) -> None:
        if self._director_semantic_window is not None and self._director_semantic_window.winfo_exists():
            self._director_semantic_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._director_semantic_window = window
        self.director_semantic_status.set("")
        window.title("Director semantic profiles")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=16)
        body.grid(sticky="nsew")
        ttk.Label(body, text=(
            "Texture and Variation remain perceptual profiles. Spatial Focus is now an engine transform: "
            "top focus weights E1-E4 with headroom; bottom focus remaps the secondary Alpha excursion."),
            wraplength=720, justify="left").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 12))

        ttk.Label(body, text="Texture", font=("TkDefaultFont", 10, "bold")).grid(row=1, column=0, sticky="w")
        ttk.Label(body, text="Captured?").grid(row=1, column=1, sticky="w")
        ttk.Label(body, text="Capture current").grid(row=1, column=2, sticky="w")
        ttk.Label(body, text="Apply").grid(row=1, column=3, sticky="w")
        row = 2
        for label in self.TEXTURE_PROFILE_NAMES:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            status_var = tk.StringVar(value="Saved" if label in self._director_texture_profiles else "—")
            self._director_texture_status_vars[label] = status_var
            ttk.Label(body, textvariable=status_var).grid(row=row, column=1, sticky="w", padx=(10, 20))
            ttk.Button(body, text="Capture", command=lambda x=label: self._capture_director_profile("texture", x)).grid(row=row, column=2, sticky="w", padx=4)
            ttk.Button(body, text="Apply", command=lambda x=label: self._apply_director_profile("texture", x)).grid(row=row, column=3, sticky="w", padx=4)
            row += 1

        ttk.Separator(body, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=10)
        row += 1
        ttk.Label(body, text="Primary spatial", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w")
        row += 1
        for key, label in self.PRIMARY_SPATIAL_NAMES.items():
            ttk.Radiobutton(body, text=label, value=key, variable=self.director_primary_spatial,
                            command=lambda k=key: self._set_director_primary_spatial(k)).grid(row=row, column=0, columnspan=3, sticky="w", pady=2)
            row += 1
        ttk.Label(body, text="Secondary spatial", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 0))
        row += 1
        ttk.Label(body, text="Bottom Focus — existing secondary/prostate generated path").grid(row=row, column=0, columnspan=4, sticky="w")
        row += 1

        ttk.Separator(body, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=10)
        row += 1
        ttk.Label(body, text="Top Spatial Focus", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w")
        ttk.Label(body, text="Model").grid(row=row, column=1, sticky="w")
        ttk.Label(body, text="").grid(row=row, column=2, sticky="w")
        ttk.Label(body, text="Apply").grid(row=row, column=3, sticky="w")
        row += 1
        ttk.Label(body, text="Electrode map: E1 glans · E2 shaft · E3 lower shaft · E4 root",
                  foreground="#555").grid(row=row, column=0, columnspan=4, sticky="w", pady=(0,4))
        row += 1
        for label in self.TOP_FOCUS_PROFILE_NAMES:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(body, text="Engine transform").grid(row=row, column=1, sticky="w", padx=(10, 20))
            ttk.Button(body, text="Apply", command=lambda x=label: (self.director_top_focus.set(x), self._save_settings())).grid(row=row, column=3, sticky="w", padx=4)
            row += 1

        ttk.Label(body, text="Bottom Spatial Focus", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8,0))
        ttk.Label(body, text="Model").grid(row=row, column=1, sticky="w", pady=(8,0))
        ttk.Label(body, text="").grid(row=row, column=2, sticky="w", pady=(8,0))
        ttk.Label(body, text="Apply").grid(row=row, column=3, sticky="w", pady=(8,0))
        row += 1
        ttk.Label(body, text="Zone map: A prostate · B anus · C testicles/perineum",
                  foreground="#555").grid(row=row, column=0, columnspan=4, sticky="w", pady=(0,4))
        row += 1
        for label in self.BOTTOM_FOCUS_PROFILE_NAMES:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Label(body, text="Engine transform").grid(row=row, column=1, sticky="w", padx=(10, 20))
            ttk.Button(body, text="Apply", command=lambda x=label: (self.director_bottom_focus.set(x), self._save_settings())).grid(row=row, column=3, sticky="w", padx=4)
            row += 1

        ttk.Label(body, text="Top nominal headroom ceiling").grid(row=row, column=0, sticky="w", pady=(8,0))
        ttk.Scale(body, from_=0.60, to=1.0, variable=self.top_focus_nominal_ceiling, orient="horizontal", length=220).grid(row=row, column=1, columnspan=2, sticky="w", pady=(8,0))
        row += 1
        ttk.Label(body, text="Top focus strength (0–175%)").grid(row=row, column=0, sticky="w")
        ttk.Scale(body, from_=0.0, to=1.75, variable=self.top_focus_strength, orient="horizontal", length=220).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1
        ttk.Label(body, text="Bottom focus strength").grid(row=row, column=0, sticky="w")
        ttk.Scale(body, from_=0.0, to=1.0, variable=self.bottom_focus_strength, orient="horizontal", length=220).grid(row=row, column=1, columnspan=2, sticky="w")
        row += 1
        ttk.Label(body, text="Top Spatial Gain", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8,0))
        ttk.Button(body, text="Decrease", command=lambda: self._change_spatial_gain("top", "decrease")).grid(row=row, column=1, sticky="w", pady=(8,0))
        ttk.Button(body, text="Increase", command=lambda: self._change_spatial_gain("top", "increase")).grid(row=row, column=2, sticky="w", pady=(8,0))
        ttk.Button(body, text="Restore", command=lambda: self._change_spatial_gain("top", "restore")).grid(row=row, column=3, sticky="w", pady=(8,0))
        row += 1
        ttk.Label(body, text="Top step (%)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(body, from_=1, to=25, increment=1, width=7,
                    textvariable=self.top_spatial_gain_step_percent).grid(row=row, column=1, sticky="w")
        ttk.Label(body, textvariable=self.top_spatial_gain_display, foreground="#555").grid(row=row, column=2, columnspan=2, sticky="w")
        row += 1
        ttk.Label(body, text="Bottom Spatial Gain", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8,0))
        ttk.Button(body, text="Decrease", command=lambda: self._change_spatial_gain("bottom", "decrease")).grid(row=row, column=1, sticky="w", pady=(8,0))
        ttk.Button(body, text="Increase", command=lambda: self._change_spatial_gain("bottom", "increase")).grid(row=row, column=2, sticky="w", pady=(8,0))
        ttk.Button(body, text="Restore", command=lambda: self._change_spatial_gain("bottom", "restore")).grid(row=row, column=3, sticky="w", pady=(8,0))
        row += 1
        ttk.Label(body, text="Bottom step (%)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(body, from_=1, to=25, increment=1, width=7,
                    textvariable=self.bottom_spatial_gain_step_percent).grid(row=row, column=1, sticky="w")
        ttk.Label(body, textvariable=self.bottom_spatial_gain_display, foreground="#555").grid(row=row, column=2, columnspan=2, sticky="w")
        row += 1
        ttk.Label(body, text="Top gain min / max (%)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(body, from_=10, to=100, increment=5, width=7,
                    textvariable=self.top_spatial_gain_min_percent).grid(row=row, column=1, sticky="w")
        ttk.Spinbox(body, from_=100, to=200, increment=5, width=7,
                    textvariable=self.top_spatial_gain_max_percent).grid(row=row, column=2, sticky="w")
        row += 1
        ttk.Label(body, text="Bottom gain min / max (%)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(body, from_=10, to=100, increment=5, width=7,
                    textvariable=self.bottom_spatial_gain_min_percent).grid(row=row, column=1, sticky="w")
        ttk.Spinbox(body, from_=100, to=200, increment=5, width=7,
                    textvariable=self.bottom_spatial_gain_max_percent).grid(row=row, column=2, sticky="w")
        row += 1
        ttk.Label(body, text="Spatial gain ramp (%/s)").grid(row=row, column=0, sticky="w")
        ttk.Spinbox(body, from_=1, to=100, increment=1, width=7,
                    textvariable=self.spatial_gain_ramp_percent_per_second).grid(row=row, column=1, sticky="w")
        ttk.Label(body, text="Default 20 percentage points/s", foreground="#555").grid(row=row, column=2, columnspan=2, sticky="w")
        row += 1
        ttk.Separator(body, orient="horizontal").grid(row=row, column=0, columnspan=4, sticky="ew", pady=10)
        row += 1
        ttk.Label(body, text="Variation", font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w")
        ttk.Label(body, text="Captured?").grid(row=row, column=1, sticky="w")
        ttk.Label(body, text="Capture current").grid(row=row, column=2, sticky="w")
        ttk.Label(body, text="Apply").grid(row=row, column=3, sticky="w")
        row += 1
        for label in self.VARIATION_PROFILE_NAMES:
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            status_var = tk.StringVar(value="Saved" if label in self._director_variation_profiles else "—")
            self._director_variation_status_vars[label] = status_var
            ttk.Label(body, textvariable=status_var).grid(row=row, column=1, sticky="w", padx=(10, 20))
            ttk.Button(body, text="Capture", command=lambda x=label: self._capture_director_profile("variation", x)).grid(row=row, column=2, sticky="w", padx=4)
            ttk.Button(body, text="Apply", command=lambda x=label: self._apply_director_profile("variation", x)).grid(row=row, column=3, sticky="w", padx=4)
            row += 1
        ttk.Label(body, text="Active texture:").grid(row=row, column=0, sticky="w", pady=(10,0))
        ttk.Label(body, textvariable=self.director_texture, foreground="#555").grid(row=row, column=1, sticky="w", pady=(10,0))
        ttk.Label(body, text="Active variation:").grid(row=row+1, column=0, sticky="w")
        ttk.Label(body, textvariable=self.director_variation, foreground="#555").grid(row=row+1, column=1, sticky="w")
        ttk.Label(body, text="Active top focus:").grid(row=row+2, column=0, sticky="w")
        ttk.Label(body, textvariable=self.director_top_focus, foreground="#555").grid(row=row+2, column=1, sticky="w")
        ttk.Label(body, text="Active bottom focus:").grid(row=row+3, column=0, sticky="w")
        ttk.Label(body, textvariable=self.director_bottom_focus, foreground="#555").grid(row=row+3, column=1, sticky="w")
        ttk.Label(body, textvariable=self.director_semantic_status, foreground="#356a35").grid(row=row+4, column=0, columnspan=3, sticky="w", pady=(8,0))
        ttk.Button(body, text="Close", command=window.destroy).grid(row=row+4, column=3, sticky="e", pady=(8,0))
        self._refresh_director_profile_status()

    def _preset_snapshot(self) -> dict:
        return {name: getattr(self, name).get()
                for name in self.FOUR_PHASE_PRESET_FIELDS}

    def _baseline_preset(self) -> dict:
        baseline = self._preset_snapshot()
        baseline.update({
            "four_phase_spatial_model": "Moving focus",
            "four_phase_tip_retention": .80,
            "four_phase_spread_softness": .20,
            "four_phase_full_depth_capture": .05,
            "four_phase_return_depth": .30,
            "four_phase_invert": False,
            "four_phase_volume_ceiling": .85,
            "four_phase_volume_modulation": False,
            "four_phase_crossover_width": .50,
            "four_phase_crossover_curve": "Linear",
            "four_phase_crossover_sharpness": 1.0,
            "four_phase_adaptive_crossover": False,
            "four_phase_directional_trajectory": False,
            "four_phase_spatial_curve": "Linear",
            "four_phase_spatial_blend": 0.0,
            "four_phase_reversal_emphasis": False,
            "four_phase_stroke_phase_texture": False,
            "electrode_order": "ABCD",
        })
        return baseline

    def _capture_preset(self, slot: str) -> None:
        self._preset_slots[slot] = self._preset_snapshot()
        self._preset_active = slot
        name = self.preset_a_name.get() if slot == "A" else self.preset_b_name.get()
        self.preset_status.set(f"Captured and active: {slot} — {name}")
        self._save_settings()

    def _apply_preset(self, slot: str) -> None:
        target = self._baseline_preset() if slot == "Baseline" else self._preset_slots.get(slot)
        if not target:
            self.preset_status.set(f"Preset {slot} is empty; capture it first")
            return
        duration = max(.1, min(10.0, self.preset_transition_seconds.get()))
        self._preset_transition = (self._preset_snapshot(), target.copy(),
                                   time.monotonic(), duration, slot)
        self._preset_active = slot
        self.preset_status.set(f"Transitioning to {slot}")
        self._preset_transition_tick()

    def _preset_transition_tick(self) -> None:
        if self._preset_transition is None:
            return
        start, target, started, duration, slot = self._preset_transition
        progress = min(1.0, max(0.0, (time.monotonic() - started) / duration))
        eased = progress * progress * (3.0 - 2.0 * progress)
        for name in self.FOUR_PHASE_PRESET_FIELDS:
            old, new = start.get(name), target.get(name)
            if old is None or new is None:
                continue
            if isinstance(old, bool) or isinstance(new, bool) or isinstance(old, str):
                value = new if progress >= .5 else old
            else:
                value = old + (new - old) * eased
            getattr(self, name).set(value)
        self.preset_status.set(f"Transitioning to {slot}: {progress * 100:.0f}%")
        if progress < 1.0:
            self.root.after(20, self._preset_transition_tick)
        else:
            self._preset_transition = None
            label = ("Baseline" if slot == "Baseline" else
                     (self.preset_a_name.get() if slot == "A" else self.preset_b_name.get()))
            self.preset_status.set(f"Active: {slot} — {label}")

    def _toggle_ab_preset(self) -> None:
        self._apply_preset("B" if self._preset_active == "A" else "A")

    def _preset_matches(self, target: dict) -> bool:
        current = self._preset_snapshot()
        for name in self.FOUR_PHASE_PRESET_FIELDS:
            left, right = current.get(name), target.get(name)
            if isinstance(left, (int, float)) and not isinstance(left, bool):
                if abs(float(left) - float(right)) > 1e-4:
                    return False
            elif left != right:
                return False
        return True

    def show_preset_window(self) -> None:
        if self._preset_window is not None and self._preset_window.winfo_exists():
            self._preset_window.lift()
            return
        window = tk.Toplevel(self.root)
        self._preset_window = window
        window.title("Four-phase presets A/B")
        window.resizable(False, False)
        body = ttk.Frame(window, padding=14)
        body.grid(sticky="nsew")
        ttk.Label(body, text="Name").grid(row=0, column=1, sticky="w")
        for row, (slot, variable) in enumerate((("A", self.preset_a_name),
                                                ("B", self.preset_b_name)), start=1):
            ttk.Label(body, text=f"Preset {slot}").grid(row=row, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=variable, width=24).grid(row=row, column=1, padx=6)
            ttk.Button(body, text="Capture current",
                       command=lambda s=slot: self._capture_preset(s)).grid(row=row, column=2, padx=4)
            ttk.Button(body, text="Apply",
                       command=lambda s=slot: self._apply_preset(s)).grid(row=row, column=3, padx=4)
        ttk.Button(body, text="Apply clean Baseline",
                   command=lambda: self._apply_preset("Baseline")).grid(
                       row=3, column=0, columnspan=2, sticky="w", pady=(10, 4))
        ttk.Label(body, text="Transition (s)").grid(row=3, column=2, sticky="e")
        ttk.Spinbox(body, from_=.1, to=10, increment=.1,
                    textvariable=self.preset_transition_seconds, width=7).grid(row=3, column=3)
        ttk.Label(body, textvariable=self.preset_status,
                  foreground="#555").grid(row=4, column=0, columnspan=4, sticky="w", pady=(10, 2))
        ttk.Label(body, text="Keyboard: [ applies A, ] applies B. Direct Xbox: hold LB and press RB to toggle A/B.",
                  foreground="#555").grid(row=5, column=0, columnspan=4, sticky="w")

    def show_setup_guide(self) -> None:
        messagebox.showinfo(
            "Vector 1A setup",
            "Safe visual commissioning\n\n"
            "1. Leave stimulation hardware disconnected.\n"
            "2. In MFP, send L0 by UDP/TCP to 127.0.0.1:12345, or add a WebSocket\n"
            "   output with URI ws://127.0.0.1:12345/ws. Use one MFP output to Vector.\n"
            "3. Set the MFP script offset to -2.00 seconds.\n"
            "4. Enable the primary ReStim WebSocket server and enter its port in Vector "
            "(normally 12346). Do NOT use ReStim's TCP port (commonly 12347).\n"
            "5. For prostate output, run a second ReStim WebSocket server on port 12350.\n"
            "6. Start the listener, connect both outputs, then select Start / Resume.\n\n"
            "Fine-tune MFP around -2.00 seconds while leaving Vector's delay at 2.00 seconds.\n\n"
            f"Settings are saved in:\n{settings_path()}"
        )

    def show_motion_guide(self) -> None:
        messagebox.showinfo(
            "Motion controls explained",
            "Motion modes\n\n"
            "Circular 0-180 follows a semicircle. Top-Left to Bottom-Right follows "
            "a 240-degree A-to-C arc with Vector's internal -30-degree alignment. "
            "Top-Right to Bottom-Left uses the corresponding +30-degree alignment. "
            "ReStim Original builds one arc per detected stroke.\n\n"
            "Base volume is the normal volume before the Volume response section "
            "and direction texture are applied.\n\n"
            "Smooth L0 position variation shifts the motion coordinate, not volume. "
            "Maximum shift 0.10 means up to approximately 0.10 either side of the "
            "scripted L0 position, clipped to the 0-1 range.\n\n"
            "Scale optional effects with speed fades variation out at rest and brings "
            "it in as motion accelerates. Full effects at speed is the calculated "
            "speed where the configured effects reach 100%; Response time controls "
            "how gently that depth changes. The live Effect depth readout shows the "
            "amount currently applied.\n\n"
            "Spatial response reshapes progress along the path without changing its "
            "endpoints. Blend 0 is linear; Blend 1 applies the selected curve fully.\n\n"
            "Boost volume near stroke reversal applies a short proportional increase "
            "around each known endpoint. A boost of 0.20 means up to 20% of the current "
            "volume, subject to the absolute 100% limit.\n\n"
            "Stroke-phase texture applies the selected volume multipliers according "
            "to whether L0 is rising or falling."
        )

    def show_four_phase_guide(self) -> None:
        messagebox.showinfo(
            "Four-phase controls explained",
            "Signal path\n\n"
            "The four green bars are the live E1-E4 commands sent to the Primary "
            "ReStim. Signalling sequence maps the logical path onto the physical "
            "electrodes. Moving focus replaces each electrode with the next as depth "
            "changes. Depth spread progressively retains A, then B and C as D joins; "
            "Tip retention controls how much A remains at full depth and Spread "
            "softness rounds each accumulating transition. Full-depth capture sets "
            "how much of the deepest L0 range holds D at 100%; 0.05 means the last "
            "5%. Reverse L0 direction "
            "swaps which end corresponds to low "
            "and high script positions. Return depth sets the preferred return "
            "electrode's relative negative contribution.\n\n"
            "Depth spread precedence\n\n"
            "Depth spread uses the selected static signalling sequence, but bypasses "
            "the sequence carousel, within-stroke sequence bias, crossover and "
            "direction textures, stroke-phase width changes, and A/B versus C/D "
            "timing separation. This keeps every transmitted profile inside ReStim's "
            "four-phase constraints. Spatial response and volume-only reversal "
            "emphasis remain active; speed-linked depth still scales compatible "
            "spatial and volume effects.\n\n"
            "Electrode crossover\n\n"
            "Crossover width controls how much of each transition is shared by two "
            "adjacent electrodes: smaller is more focused, larger is broader and "
            "smoother. Curve controls how that handover develops; Sharpness mainly "
            "changes the S-curve. Change crossover width with speed interpolates "
            "between the low- and high-speed widths.\n\n"
            "Stroke texture\n\n"
            "Use different return-stroke crossover gives falling/reverse motion its "
            "own width multiplier, curve and sharpness. Change width through each "
            "stroke moves smoothly from the accelerating multiplier to the "
            "decelerating multiplier.\n\n"
            "Timing and sequence movement\n\n"
            "A positive group delay makes A/B later; a negative value makes C/D "
            "later. Transition controls how gently a changed delay is introduced. "
            "Bias sequence within each stroke temporarily blends toward the next or "
            "previous signalling sequence near mid-stroke, returning to the selected "
            "sequence at the endpoints. Maximum blend is its strength; Stroke portion "
            "is how much of the stroke contains the effect.\n\n"
            "Slow volume variation uses up to Maximum addition over the selected "
            "cycle, never exceeding 100%. The live Sequence blend bar is a readout, "
            "not another setting."
        )

    def _send_sample(self, sample: OutputSample) -> None:
        variation_depth = (sample.variation_depth
                           if self.speed_linked_variation.get() else 1.0)
        motion_delta = sample.output_l0 - self._motion_send_last_l0
        if abs(motion_delta) > 0.0005:
            self._motion_send_direction = 1 if motion_delta > 0 else -1
        self._motion_send_last_l0 = sample.output_l0
        path_l0 = self._spatial_path(sample.output_l0, variation_depth)
        delta = path_l0 - self._four_phase_send_last_l0
        if abs(delta) > 0.0005:
            self._four_phase_send_direction = 1 if delta > 0 else -1
        self._four_phase_send_last_l0 = path_l0
        electrodes, morph_source, morph_target, morph_amount, profile_kind = \
            self._four_phase_profile(
            path_l0, self._four_phase_send_direction, sample.speed_percent,
            sample.stroke_progress, variation_depth, sample.due_at)
        self._four_phase_history.append((sample.due_at, electrodes))
        target_delay = 0.0
        if self.four_phase_group_delay.get() and profile_kind != "depth spread":
            target_delay = min(.300, max(-.300,
                self.four_phase_group_delay_ms.get() / 1000.0)) * variation_depth
        previous_time = self._four_phase_group_delay_last_time
        self._four_phase_group_delay_last_time = sample.due_at
        dt = max(0.0, sample.due_at - previous_time) if previous_time is not None else 0.0
        transition = max(.1, self.four_phase_group_delay_transition.get())
        blend = 1.0 - math.exp(-dt / transition) if dt > 0 else 0.0
        self._four_phase_effective_group_delay += (
            target_delay - self._four_phase_effective_group_delay) * blend
        if abs(target_delay) <= 1e-9 and abs(self._four_phase_effective_group_delay) < 1e-5:
            self._four_phase_effective_group_delay = 0.0
        if profile_kind == "depth spread":
            self._four_phase_effective_group_delay = 0.0
        else:
            electrodes = apply_group_delay(
                electrodes, list(self._four_phase_history), sample.due_at,
                self._four_phase_effective_group_delay)
        electrodes = apply_top_focus(
            electrodes, self.director_top_focus.get(),
            nominal_ceiling=self.top_focus_nominal_ceiling.get(),
            strength=self.top_focus_strength.get(), path_position=path_l0)
        with self._four_phase_live_lock:
            self._four_phase_live_output = (
                electrodes, morph_source, morph_target, morph_amount, profile_kind)
        ceiling = min(1.0, max(0.0, self.four_phase_volume_ceiling.get()))
        if self.four_phase_volume_modulation.get():
            cycle = max(.5, self.four_phase_volume_cycle.get()) * 60.0
            wave = (1.0 - math.cos((sample.calculated_at % cycle)
                                   * 2.0 * math.pi / cycle)) / 2.0
            ceiling = min(1.0, ceiling +
                          self.four_phase_volume_headroom.get() * wave * variation_depth)
        primary_volume = min(1.0, max(0.0,
            ceiling * sample.volume / max(self.volume.get(), 1e-9)))
        if self.four_phase_stroke_phase_texture.get():
            configured = (self.motion_rising_volume_multiplier.get()
                          if self._motion_send_direction > 0
                          else self.motion_falling_volume_multiplier.get())
            multiplier = 1.0 + (min(1.0, max(.8, configured)) - 1.0) * variation_depth
            primary_volume *= multiplier
        if self.four_phase_reversal_emphasis.get():
            reversal = reversal_emphasis_envelope(
                sample.reversal_distance_seconds, self.four_phase_reversal_window.get())
            boost = min(1.0, max(0.0,
                self.four_phase_reversal_strength.get() * variation_depth))
            primary_volume = proportional_reversal_boost(
                primary_volume, reversal, boost)
        primary_volume = min(1.0, max(0.0, primary_volume))
        now_gain = time.monotonic()
        _, _, _, gain_ramp = self._spatial_gain_parameters("top")
        top_gain = self._top_spatial_gain.update(ramp_per_second=gain_ramp, now=now_gain)
        _, _, _, bottom_gain_ramp = self._spatial_gain_parameters("bottom")
        bottom_gain = self._bottom_spatial_gain.update(ramp_per_second=bottom_gain_ramp, now=now_gain)
        self.top_spatial_gain_display.set(
            f"{self._top_spatial_gain.target * 100:.0f}% target · {top_gain * 100:.0f}% live")
        self.bottom_spatial_gain_display.set(
            f"{self._bottom_spatial_gain.target * 100:.0f}% target · {bottom_gain * 100:.0f}% live")
        primary_volume = apply_gain(primary_volume, top_gain)
        if self.authored_routing_mode.get() == "Auto authored ReStim set":
            authored_overrides = self.axis_router.snapshot_auto(sample.calculated_at)
        else:
            authored_overrides = self.axis_router.snapshot(sample.calculated_at)
        if authored_overrides:
            e_names = ("E1", "E2", "E3", "E4")
            source_e = tuple(authored_overrides.get(name, electrodes[i]) for i, name in enumerate(e_names))
            focused_e = apply_top_focus(
                source_e, self.director_top_focus.get(),
                nominal_ceiling=self.top_focus_nominal_ceiling.get(),
                strength=self.top_focus_strength.get(), path_position=path_l0)
            authored_overrides = dict(authored_overrides)
            for name, value in zip(e_names, focused_e):
                if name in authored_overrides:
                    authored_overrides[name] = value
            if "V0" in authored_overrides:
                authored_overrides["V0"] = apply_gain(authored_overrides["V0"], top_gain)
        focused_alpha_prostate = apply_bottom_focus_window(
            sample.alpha_prostate,
            self._bottom_focus_transition.window(now=sample.due_at),
            strength=self.bottom_focus_strength.get())
        bottom_volume = apply_gain(sample.volume_prostate, bottom_gain)
        primary_alpha = sample.alpha
        primary_beta = sample.beta
        primary_frequency = sample.frequency
        primary_pulse_frequency = sample.pulse_frequency
        primary_pulse_width = sample.pulse_width
        if self.director_events_enabled.get():
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
        primary_args = (
            primary_alpha, primary_beta, tuple(electrodes), primary_volume, primary_frequency,
            primary_pulse_frequency, sample.pulse_rise_time, primary_pulse_width)
        primary_overrides = dict(authored_overrides) if authored_overrides else None
        self.restim_sender.submit(
            lambda args=primary_args, overrides=primary_overrides:
                self.restim.send_primary(*args, overrides=overrides))
        prostate_args = (
            focused_alpha_prostate, sample.beta_prostate, bottom_volume,
            primary_frequency, primary_pulse_frequency, primary_pulse_width,
            sample.pulse_rise_time)
        self.prostate_sender.submit(
            lambda args=prostate_args: self.prostate_restim.send_prostate(*args))

    def _receive_l0(self, value: float, interval_ms: int = 0, received_at: float | None = None) -> None:
        now = time.monotonic() if received_at is None else float(received_at)
        self._latest_authored_l0 = max(0.0, min(1.0, float(value)))
        # Timeline sync always observes the untouched authored MFP signal. Tempo is
        # an output-side deterministic transform and must not poison clock matching.
        self.timeline.observe_live(value, now)
        if not self.generated_motion.active:
            self.engine.receive_l0(self._tempo_l0(value, now), interval_ms, now)

    def _receive_generated_l0(self, value: float, interval_ms: int = 0,
                              received_at: float | None = None) -> None:
        now = time.monotonic() if received_at is None else float(received_at)
        self.engine.receive_l0(self._tempo_l0(value, now), interval_ms, now)

    def neutral(self) -> None:
        self.event_engine.clear_triggers()
        self.apply_config()
        self._reset_four_phase_group_delay()
        self._motion_send_last_l0 = 0.5
        self._motion_send_direction = 1
        self.engine.neutral()
        neutral_volume = self.volume.get()
        self.restim_sender.submit(
            lambda: self.restim.send_primary(
                0.5, 0.5, (0.5, 0.5, 0.5, 0.5), neutral_volume, 0.5, 0.5, 0.5, 0.5),
            max_age_seconds=2.0)
        with self._four_phase_live_lock:
            order = self.electrode_order.get()
            self._four_phase_live_output = (
                (0.5, 0.5, 0.5, 0.5), order, order, 0.0, "neutral")
        self.prostate_sender.submit(
            lambda: self.prostate_restim.send_prostate(
                0.5, 0.5, neutral_volume, 0.5, 0.5, 0.5, 0.5),
            max_age_seconds=2.0)

    def resume(self) -> None:
        self.apply_config()
        self._reset_four_phase_group_delay()
        self.engine.resume()

    def stop(self) -> None:
        self.event_engine.clear_triggers()
        self.generated_motion.authored()
        self._reset_four_phase_group_delay()
        self._motion_send_last_l0 = 0.5
        self._motion_send_direction = 1
        self.engine.stop()
        self.restim_sender.submit(
            lambda: self.restim.send_primary(
                0.5, 0.5, (0.5, 0.5, 0.5, 0.5), 0.0, 0.5, 0.5, 0.5, 0.5),
            max_age_seconds=2.0)
        with self._four_phase_live_lock:
            order = self.electrode_order.get()
            self._four_phase_live_output = (
                (0.5, 0.5, 0.5, 0.5), order, order, 0.0, "stopped")
        self.prostate_sender.submit(
            lambda: self.prostate_restim.send_prostate(
                0.5, 0.5, 0.0, 0.5, 0.5, 0.5, 0.5),
            max_age_seconds=2.0)

    def _reset_four_phase_group_delay(self) -> None:
        self._four_phase_history.clear()
        self._four_phase_effective_group_delay = 0.0
        self._four_phase_group_delay_last_time = None

    def _refresh(self) -> None:
        self._drain_controller_events()
        self._drain_director_requests()
        # Keep direct VLC/MPC timeline clocks live even when the timeline window
        # is closed. request_media_poll() is internally rate-limited and async.
        self.timeline.request_media_poll()
        if not self._startup_in_progress and self.session_ready_status.get() == "SESSION: READY":
            missing = []
            if self.auto_start_restim.get() and not self.restim.connected:
                missing.append("Primary")
            if self.auto_start_prostate.get() and not self.prostate_restim.connected:
                missing.append("Prostate")
            if missing:
                self.session_ready_status.set("SESSION: ATTENTION")
                self._set_startup_status("Connection lost after READY: " + ", ".join(missing))
        self._update_variety()
        if self._preset_transition is None and self._preset_active:
            target = (self._baseline_preset() if self._preset_active == "Baseline"
                      else self._preset_slots.get(self._preset_active))
            if target:
                label = ("Baseline" if self._preset_active == "Baseline" else
                         (self.preset_a_name.get() if self._preset_active == "A"
                          else self.preset_b_name.get()))
                suffix = "" if self._preset_matches(target) else " (modified)"
                self.preset_status.set(
                    f"Active: {self._preset_active} — {label}{suffix}")
        diag = self.engine.diagnostics()
        self._emit_runtime_health(diag)
        values = {
            "raw_l0": f"{diag.raw_l0:.4f}", "output_l0": f"{diag.output_l0:.4f}",
            "speed": f"{diag.speed_percent:.2f}%", "alpha": f"{diag.alpha:.4f}",
            "beta": f"{diag.beta:.4f}", "buffer": f"{diag.buffer_fill} samples",
            "lookahead": f"{diag.lookahead_seconds:.3f} s",
            "actual_delay": f"{diag.actual_queue_delay:.4f} s" if diag.output_samples else "--",
            "input_count": str(diag.input_samples), "output_count": str(diag.output_samples),
            "state": diag.state,
            "active_mode": self.engine.mode.value,
            "output_mode": diag.output_mode,
            "output_volume": f"{diag.output_volume * 100:.1f}%",
            "frequency": f"{diag.frequency:.4f}",
            "pulse_frequency": f"{diag.pulse_frequency:.4f}",
            "pulse_rise_time": f"{diag.pulse_rise_time:.4f}",
            "pulse_width": f"{diag.pulse_width:.4f}",
            "alpha_prostate": f"{diag.alpha_prostate:.4f}",
            "beta_prostate": f"{diag.beta_prostate:.4f}",
            "volume_prostate": f"{diag.volume_prostate * 100:.1f}%",
            "variation_depth": f"{diag.variation_depth * 100:.1f}%",
        }
        for key, value in values.items():
            self.diag_vars[key].set(value)
        self.variation_depth_live.set(f"Effect depth {diag.variation_depth * 100:.0f}%")
        self.frequency_bar["value"] = diag.frequency
        self.frequency_value.set(f"{diag.frequency:.4f}")
        self.pulse_frequency_bar.set(self.pulse_frequency_min.get(),
                                     self.pulse_frequency_max.get(), diag.pulse_frequency)
        self.pulse_frequency_value.set(f"{diag.pulse_frequency:.4f}")
        self.pulse_rise_bar.set(self.pulse_rise_min.get(), self.pulse_rise_max.get(),
                                diag.pulse_rise_time)
        self.pulse_rise_value.set(f"{diag.pulse_rise_time:.4f}")
        self.pulse_width_bar.set(self.pulse_width_min.get(), self.pulse_width_max.get(),
                                 diag.pulse_width)
        self.pulse_width_value.set(f"{diag.pulse_width:.4f}")
        for key, value in (("alpha_prostate", diag.alpha_prostate),
                           ("beta_prostate", diag.beta_prostate),
                           ("volume_prostate", diag.volume_prostate)):
            self.prostate_bars[key]["value"] = value
            self.prostate_values[key].set(f"{value:.4f}")
        variation_depth = (diag.variation_depth
                           if self.speed_linked_variation.get() else 1.0)
        path_l0 = self._spatial_path(diag.output_l0, variation_depth)
        self.four_phase_spatial_live.set(f"live {path_l0:.3f}")
        reversal = (reversal_emphasis_envelope(
            diag.reversal_distance_seconds, self.four_phase_reversal_window.get())
            * variation_depth
            if self.four_phase_reversal_emphasis.get() else 0.0)
        self.four_phase_reversal_live.set(f"live {reversal:.3f}")
        delay_ms = self._four_phase_effective_group_delay * 1000.0
        delayed_group = "A/B later" if delay_ms > .5 else ("C/D later" if delay_ms < -.5 else "aligned")
        self.four_phase_group_delay_live.set(f"live {delay_ms:+.0f} ms | {delayed_group}")
        four_phase = vertical_crossfade(path_l0)
        for bar, variable, value in zip(self.four_phase_bars, self.four_phase_values,
                                        four_phase):
            bar["value"] = value
            variable.set(f"{value:.4f}")
        delta = path_l0 - self._four_phase_last_l0
        if abs(delta) > 0.0005:
            self._four_phase_direction = 1 if delta > 0 else -1
        self._four_phase_last_l0 = path_l0
        depth_mode = self.four_phase_spatial_model.get() == "Depth spread"
        if depth_mode:
            signed = depth_spread(
                path_l0, self.four_phase_tip_retention.get(),
                self.four_phase_spread_softness.get(),
                self.four_phase_full_depth_capture.get())
            self.four_phase_effective_crossover_width.set("bypassed")
            self.four_phase_stroke_phase_live.set("bypassed by Depth spread")
            self.four_phase_model_live.set(
                "Depth spread: static sequence only; sequence bias, crossover, "
                "direction, width texture and AB/CD delay are bypassed")
        else:
            signed = directed_signed(
                path_l0, self._four_phase_direction,
                self.four_phase_return_depth.get())[0]
            effective_crossover, _, _, direction_name = self._crossover_profile(
                diag.speed_percent, self._four_phase_direction,
                diag.stroke_progress, variation_depth)
            self.four_phase_effective_crossover_width.set(
                f"{direction_name} {effective_crossover:.3f}")
            if self.four_phase_stroke_phase_texture.get():
                phase_name = "accelerating" if diag.stroke_progress < .5 else "decelerating"
                self.four_phase_stroke_phase_live.set(
                    f"{phase_name} {diag.stroke_progress:.2f} | live {effective_crossover:.3f}")
            else:
                self.four_phase_stroke_phase_live.set("off")
            self.four_phase_model_live.set("Moving focus: crossover and sequence textures available")
        with self._four_phase_live_lock:
            (potentials, morph_source, morph_target,
             morph_amount, morph_kind) = self._four_phase_live_output
        self.electrode_morph_bar["value"] = morph_amount
        if morph_kind == "window":
            self.four_phase_moving_sequence_live.set(
                f"{morph_source}→{morph_target} | {morph_amount * 100:.0f}%")
        elif morph_kind == "carousel" and self.four_phase_moving_sequence.get():
            self.four_phase_moving_sequence_live.set("carousel priority")
        elif morph_kind == "depth spread":
            self.four_phase_moving_sequence_live.set("bypassed by Depth spread")
        else:
            self.four_phase_moving_sequence_live.set("off")
        for variable, value in zip(self.four_phase_signed_values, signed):
            variable.set(f"{value:+.4f}")
        for bar, variable, value in zip(self.four_phase_potential_bars,
                                        self.four_phase_potential_values, potentials):
            bar["value"] = value
            variable.set(f"{value:.4f}")
        primary, preferred_return = potential_roles(potentials)
        if morph_kind == "depth spread":
            sequence_status = f"Depth spread | static sequence {morph_source}"
        elif morph_source == morph_target:
            sequence_status = f"Current sequence {morph_source}"
        elif morph_amount <= .001:
            sequence_status = (f"Current sequence {morph_source} | next "
                               f"{morph_target}")
        elif morph_amount >= .999:
            sequence_status = (f"Current sequence {morph_target} | next stage pending")
        else:
            sequence_status = (f"{morph_source} morphing toward {morph_target} | "
                               f"{morph_amount * 100:.0f}%")
        self.four_phase_roles.set(sequence_status)
        current = self.listener.connection_label()
        if current.startswith(("Receiving", "Listening")):
            if not self.mfp_status.get().startswith("MFP "):
                self.mfp_status.set(current)
        summaries = {
            "MultiFunPlayer input": f"{self.mfp_status.get()} | {self.mfp_host.get()}:{self.mfp_port.get()}",
            "ReStim output": f"Primary: {self.restim_status.get()} | Prostate: {self.prostate_status.get()}",
            "Motion": f"{self.mode.get()} | {self.rate.get()} Hz | {self.lookahead.get():.2f} s delay",
            "Volume response": (
                f"Base {self.volume.get() * 100:.0f}% | "
                f"primary ceiling {self.four_phase_volume_ceiling.get() * 100:.0f}% | "
                f"rest {self.volume_rest_level.get() * 100:.0f}%"
            ),
            "Frequency": f"{diag.frequency:.3f} | ramp {self.frequency_ramp_level.get():.2f}",
            "Pulse frequency": f"{diag.pulse_frequency:.3f} | range {self.pulse_frequency_min.get():.2f}-{self.pulse_frequency_max.get():.2f}",
            "Pulse rise time": f"{diag.pulse_rise_time:.3f} | range {self.pulse_rise_min.get():.2f}-{self.pulse_rise_max.get():.2f}",
            "Pulse width": f"{diag.pulse_width:.3f} | range {self.pulse_width_min.get():.2f}-{self.pulse_width_max.get():.2f}",
            "Prostate controls": f"alpha {diag.alpha_prostate:.3f} beta {diag.beta_prostate:.3f} volume {diag.volume_prostate * 100:.0f}% | phase {self.prostate_phase_degrees.get():+.0f} degrees",
            "Four-phase primary motion": (
                f"{sequence_status} | "
                f"E1 {potentials[0]:.2f} E2 {potentials[1]:.2f} "
                f"E3 {potentials[2]:.2f} E4 {potentials[3]:.2f}"),
            "Xbox controller": f"{self.controller_status.get()} | step {self.controller_fine_step.get():.2f}",
            "Rolling Variety": self.variety_status.get(),
            "Commissioning controls": diag.state,
            "Live diagnostics": (f"{diag.state} | buffer {diag.buffer_fill} | delay {diag.actual_queue_delay:.4f} s"
                                 if diag.output_samples else
                                 f"{diag.state} | buffer {diag.buffer_fill} | waiting for output"),
        }
        for title, summary in summaries.items():
            self.sections[title].summary.set(summary)
        if self._timeline_window is not None and self._timeline_window.winfo_exists():
            self._refresh_timeline_window()
        self.root.after(100, self._refresh)

    @staticmethod
    def _health_age(value: object) -> str:
        return "never" if value is None else f"{float(value):.2f}s"

    def _emit_runtime_health(self, diag) -> None:
        now = time.monotonic()
        source = self.listener.health()
        source_age = source.get("last_l0_age")
        stale = source_age is not None and float(source_age) > 2.0
        if stale != self._source_was_stale:
            event = ("STALE INPUT WATCHDOG source=MFP entered stale state"
                     if stale else "STALE INPUT WATCHDOG source=MFP recovered")
            print(event, flush=True)
            self._record_connection_event("MFP", event)
            self._source_was_stale = stale
        if now - self._last_health_log_at < 2.0:
            return
        output_progress = diag.output_samples > self._last_health_output_count
        self._last_health_output_count = diag.output_samples
        clock = self.timeline.snapshot()
        media_state = clock.get("media_clock_health") or clock.get("clock_source") or "unknown"
        for label, client, sender in (
                ("A", self.restim, self.restim_sender),
                ("B", self.prostate_restim, self.prostate_sender)):
            socket_health = client.health()
            lane = sender.health()
            print(
                f"RESTIM {label} connected={socket_health['connected']} "
                f"socket={socket_health['socket_state']} "
                f"tx_age={self._health_age(socket_health['tx_age'])} "
                f"cadence={self._health_age(socket_health['send_cadence'])} "
                f"source_age={self._health_age(source_age)} media_clock={media_state} "
                f"engine={diag.state} loop_alive={self.engine.loop_alive()} "
                f"output_progress={output_progress} sender_alive={lane['alive']} "
                f"queue_pending={lane['pending']} dropped={lane['dropped']} stale={lane['stale']} "
                f"send_duration={self._health_age(lane['send_duration'])} "
                f"reconnects={socket_health['reconnect_successes']}/{socket_health['reconnect_attempts']} "
                f"failures={socket_health['send_failures'] + lane['failures']}", flush=True)
        self._last_health_log_at = now

    def close(self) -> None:
        self.generated_motion.close()
        self._save_settings()
        self.xinput.close()
        self.engine.close()
        self.listener.stop()
        self.restim_sender.close()
        self.prostate_sender.close()
        self.restim.close()
        self.prostate_restim.close()
        self.director_server.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    VectorApp(root)
    root.mainloop()
