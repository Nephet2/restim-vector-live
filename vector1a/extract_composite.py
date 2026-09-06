"""SCD Relentless→Extract→overload composite for mcb_extract / mcb_extract_4p.

Vendored from funscript-tools for Vector live expand. Hub–spoke motion is baked
at expand time (optional seed). Vector uses primary alpha/beta only (no -2 /
prostate position axes).

Beat-sync siblings (mcb_extract_beat / mcb_extract_4p_beat): same shell; pole
dwells advance every 2nd L0 beat (or switch_offsets_ms from the events file).
Fallback to SCD ~dur when no beats. Stdlib-only (no numpy).
"""
from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

# Default SCD span: Relentless start → end of pleasure overload (Ch2).
EXTRACT_BASE_MS = 265367
EXTRACT_MIN_MS = 60_000

EXTRACT_SCD_EVENTS = frozenset({"mcb_extract", "mcb_extract_4p"})
EXTRACT_BEAT_EVENTS = frozenset({"mcb_extract_beat", "mcb_extract_4p_beat"})
EXTRACT_EVENTS = EXTRACT_SCD_EVENTS | EXTRACT_BEAT_EVENTS

# Soft glide ≈ SCD thetaLag 0.9s (capped per dwell).
_SOFT_LAG_MS = 900

# L0 turnaround beats: skip chatter closer than this.
_MIN_BEAT_INTERVAL_MS = 80
# Advance to next pole/pad on every Nth L0 beat.
_BEAT_EVERY_N = 2

# poles @ ρ=1 → α/β with α=(x+1)/2, β=(y+1)/2 from ρ·(cos θ, sin θ)
_ZETA = 2.0 * math.pi / 3.0
_POLE_THETA = {
    "N": 0.0,
    "L": _ZETA,
    "R": 2.0 * _ZETA,
}

# Carrier amp ladder (fraction start → amp level); last runs to 1.0
_AMP_CUES: Tuple[Tuple[float, int], ...] = (
    (0.0, 1),
    (0.073, 2),
    (0.176, 3),
    (0.472, 2),
    (0.530, 1),
    (0.588, 2),
    (0.618, 3),
    (0.647, 2),
    (0.706, 3),
    (0.824, 4),
)

# Pulse Hz segments (start_frac, end_frac, hz)
_PULSE_SEGS: Tuple[Tuple[float, float, int], ...] = (
    (0.0, 0.353, 60),
    (0.353, 0.588, 40),
    (0.588, 0.647, 50),
    (0.647, 0.882, 60),
    (0.882, 1.0, 120),
)

# ~dur (seconds) by fraction start
_DUR_CUES: Tuple[Tuple[float, float], ...] = (
    (0.0, 1.0),
    (0.176, 0.8),
    (0.353, 0.75),
    (0.706, 0.5),
    (0.882, 1.0),
)

_ALPHA_AXES = "alpha"
_BETA_AXES = "beta"
_E_AXES = ("e1", "e2", "e3", "e4")


def _ms(duration_ms: float, frac: float) -> int:
    return int(round(duration_ms * frac))


def _dwell_s_at(frac: float) -> float:
    dwell = _DUR_CUES[0][1]
    for start, value in _DUR_CUES:
        if frac + 1e-12 >= start:
            dwell = value
    return dwell


def _pole_ab(pole: str, rho: float) -> Tuple[float, float]:
    th = _POLE_THETA[pole]
    x = rho * math.cos(th)
    y = rho * math.sin(th)
    return 0.5 + 0.5 * x, 0.5 + 0.5 * y


def _soft_ms(dwell_ms: int) -> int:
    if dwell_ms <= 1:
        return 0
    return max(1, min(_SOFT_LAG_MS, dwell_ms // 2))


def _linear_step(
    axis: str,
    start_offset: int,
    duration_ms: int,
    start_value: float,
    end_value: float,
    *,
    ramp_in_ms: int = 0,
    ramp_out_ms: int = 0,
    mode: str = "overwrite",
) -> Dict[str, Any]:
    return {
        "operation": "apply_linear_change",
        "axis": axis,
        "start_offset": start_offset,
        "params": {
            "start_value": start_value,
            "end_value": end_value,
            "duration_ms": max(1, int(duration_ms)),
            "ramp_in_ms": int(ramp_in_ms),
            "ramp_out_ms": int(ramp_out_ms),
            "mode": mode,
        },
    }


def _is_4p(event_name: str) -> bool:
    return event_name in ("mcb_extract_4p", "mcb_extract_4p_beat")


def _pick_spoke(
    rng: random.Random,
    options: Sequence[str],
    previous: Optional[str],
) -> str:
    """Random spoke that is never the same as the previous burst's spoke."""
    choices = list(options)
    if previous is not None and len(choices) > 1:
        filtered = [c for c in choices if c != previous]
        if filtered:
            choices = filtered
    return rng.choice(choices)


def detect_l0_beats(
    times_s: Union[Sequence[float], List[float]],
    values: Union[Sequence[float], List[float]],
    t0_ms: int,
    t1_ms: int,
    *,
    min_interval_ms: int = _MIN_BEAT_INTERVAL_MS,
) -> List[int]:
    """Detect L0 turnarounds in [t0_ms, t1_ms); return offsets ms from t0_ms."""
    if t1_ms <= t0_ms:
        return []

    x = [float(v) for v in times_s]
    y = [float(v) for v in values]
    if len(x) < 3 or len(y) != len(x):
        return []

    t0_s = t0_ms / 1000.0
    t1_s = t1_ms / 1000.0
    in_win = [i for i, t in enumerate(x) if t0_s <= t <= t1_s]
    if len(in_win) < 3:
        return []

    i0 = max(0, in_win[0] - 1)
    i1 = min(len(x) - 1, in_win[-1] + 1)
    xs = x[i0 : i1 + 1]
    ys = y[i0 : i1 + 1]

    raw: List[int] = []
    for i in range(1, len(ys) - 1):
        left = ys[i] - ys[i - 1]
        right = ys[i + 1] - ys[i]
        is_peak = left > 0 and right <= 0
        is_valley = left < 0 and right >= 0
        if not (is_peak or is_valley):
            continue
        off = int(round((xs[i] - t0_s) * 1000.0))
        if 0 <= off < (t1_ms - t0_ms):
            raw.append(off)

    if not raw:
        return []

    raw.sort()
    filtered = [raw[0]]
    for b in raw[1:]:
        if b - filtered[-1] >= min_interval_ms:
            filtered.append(b)
    return filtered


def every_nth_beat(beats: Sequence[int], n: int = _BEAT_EVERY_N) -> List[int]:
    if n < 1:
        n = 1
    return [int(b) for b in beats[::n]]


def switch_offsets_to_segments(
    switch_offsets_ms: Sequence[int],
    duration_ms: int,
) -> List[Tuple[int, int]]:
    """Build (start_offset, dwell_ms) covering [0, duration_ms) from switch times."""
    bounds = [0]
    for s in switch_offsets_ms:
        try:
            si = int(s)
        except (TypeError, ValueError):
            continue
        if 0 < si < duration_ms:
            bounds.append(si)
    bounds.append(int(duration_ms))
    bounds = sorted(set(bounds))
    segs: List[Tuple[int, int]] = []
    for i in range(len(bounds) - 1):
        dwell = bounds[i + 1] - bounds[i]
        if dwell > 0:
            segs.append((bounds[i], dwell))
    return segs


def _scd_segments(duration_ms: int) -> List[Tuple[int, int]]:
    """Hub+spoke pairs with SCD ~dur (same timing as original extract bake)."""
    segs: List[Tuple[int, int]] = []
    t = 0
    while t < duration_ms:
        frac = t / duration_ms
        dwell_ms = max(1, int(round(_dwell_s_at(frac) * 1000.0)))
        for _ in range(2):
            if t >= duration_ms:
                break
            this_dwell = min(dwell_ms, duration_ms - t)
            segs.append((t, this_dwell))
            t += this_dwell
    return segs


def _parse_switch_offsets(final_params: dict) -> Optional[List[int]]:
    raw = final_params.get("switch_offsets_ms")
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        try:
            return [int(float(p)) for p in parts]
        except ValueError:
            return None
    if isinstance(raw, (list, tuple)):
        out: List[int] = []
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                continue
        return out
    return None


def resolve_extract_segments(
    final_params: dict,
    event_name: str,
    *,
    l0_times_s: Optional[Sequence[float]] = None,
    l0_values: Optional[Sequence[float]] = None,
    event_start_ms: int = 0,
) -> List[Tuple[int, int]]:
    """Dwell schedule for motion bake. Beat events prefer L0 / switch_offsets_ms."""
    duration_ms = int(round(float(final_params["duration_ms"])))

    if event_name not in EXTRACT_BEAT_EVENTS:
        return _scd_segments(duration_ms)

    baked = _parse_switch_offsets(final_params)
    if baked is not None:
        segs = switch_offsets_to_segments(baked, duration_ms)
        if segs:
            return segs

    if l0_times_s is not None and l0_values is not None:
        beats = detect_l0_beats(
            l0_times_s,
            l0_values,
            event_start_ms,
            event_start_ms + duration_ms,
        )
        switches = every_nth_beat(beats, _BEAT_EVERY_N)
        final_params["switch_offsets_ms"] = list(switches)
        segs = switch_offsets_to_segments(switches, duration_ms)
        if len(segs) >= 2:
            return segs

    # Sparse / missing L0 → SCD ~dur fallback
    return _scd_segments(duration_ms)


def derive_extract_params(final_params: dict, event_name: str) -> None:
    """Fill proportional pulse/amp segment tokens; enforce min duration."""
    if event_name not in EXTRACT_EVENTS:
        return

    try:
        duration_ms = float(final_params.get("duration_ms", 0))
    except (TypeError, ValueError) as e:
        raise ValueError(
            f"Event '{event_name}': invalid duration_ms: {e}"
        ) from e

    if duration_ms < EXTRACT_MIN_MS:
        raise ValueError(
            f"Event '{event_name}': duration_ms ({duration_ms:g}) must be at least "
            f"{EXTRACT_MIN_MS} ms."
        )

    final_params["pulse_width"] = float(final_params.get("pulse_width", 65))
    final_params["ramp_ms"] = int(final_params.get("ramp_ms", 500))

    # Pulse segments → offset_pulse_i / seg_pulse_i / hz_pulse_i
    for i, (f0, f1, hz) in enumerate(_PULSE_SEGS):
        final_params[f"offset_pulse_{i}_ms"] = _ms(duration_ms, f0)
        final_params[f"seg_pulse_{i}_ms"] = max(1, _ms(duration_ms, f1) - _ms(duration_ms, f0))
        final_params[f"hz_pulse_{i}"] = float(hz)

    # Amp segments
    for i, (f0, level) in enumerate(_AMP_CUES):
        f1 = _AMP_CUES[i + 1][0] if i + 1 < len(_AMP_CUES) else 1.0
        final_params[f"offset_amp_{i}_ms"] = _ms(duration_ms, f0)
        final_params[f"seg_amp_{i}_ms"] = max(1, _ms(duration_ms, f1) - _ms(duration_ms, f0))
        final_params[f"amp_{i}"] = level / 100.0


def build_extract_motion_steps(
    final_params: dict,
    event_name: str,
    *,
    rng: Optional[random.Random] = None,
    l0_times_s: Optional[Sequence[float]] = None,
    l0_values: Optional[Sequence[float]] = None,
    event_start_ms: int = 0,
) -> List[Dict[str, Any]]:
    """Bake hub–spoke overwrite steps for the full duration (Apply/expand-time RNG)."""
    if event_name not in EXTRACT_EVENTS:
        return []

    duration_ms = int(round(float(final_params["duration_ms"])))
    if rng is None:
        seed = final_params.get("seed", None)
        rng = random.Random(seed) if seed is not None else random.Random()

    segments = resolve_extract_segments(
        final_params,
        event_name,
        l0_times_s=l0_times_s,
        l0_values=l0_values,
        event_start_ms=event_start_ms,
    )

    if _is_4p(event_name):
        return _build_4p_motion(duration_ms, rng, final_params, segments)
    return _build_3p_motion(duration_ms, rng, final_params, segments)


def _build_3p_motion(
    duration_ms: int,
    rng: random.Random,
    final_params: dict,
    segments: List[Tuple[int, int]],
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    prev_a, prev_b = _pole_ab("N", 0.85)
    first = True
    ramp_ms = int(final_params.get("ramp_ms", 500))
    next_spoke = "L"
    prev_spoke: Optional[str] = None

    for idx, (t, this_dwell) in enumerate(segments):
        if idx % 2 == 0:
            next_spoke = _pick_spoke(rng, ("L", "R"), prev_spoke)
            prev_spoke = next_spoke
            pole = "N"
        else:
            pole = next_spoke

        rho = rng.uniform(0.75, 0.95)
        a, b = _pole_ab(pole, rho)
        soft = 0 if first else _soft_ms(this_dwell)
        first = False

        if soft > 0:
            steps.append(_linear_step(_ALPHA_AXES, t, soft, prev_a, a))
            steps.append(_linear_step(_BETA_AXES, t, soft, prev_b, b))
            hold_off = t + soft
            hold_dur = this_dwell - soft
        else:
            hold_off = t
            hold_dur = this_dwell
            steps.append(
                _linear_step(
                    _ALPHA_AXES, hold_off, hold_dur, a, a,
                    ramp_in_ms=min(ramp_ms, hold_dur),
                    ramp_out_ms=0,
                )
            )
            steps.append(
                _linear_step(
                    _BETA_AXES, hold_off, hold_dur, b, b,
                    ramp_in_ms=min(ramp_ms, hold_dur),
                    ramp_out_ms=0,
                )
            )
            prev_a, prev_b = a, b
            continue

        if hold_dur > 0:
            steps.append(_linear_step(_ALPHA_AXES, hold_off, hold_dur, a, a))
            steps.append(_linear_step(_BETA_AXES, hold_off, hold_dur, b, b))

        prev_a, prev_b = a, b

    if steps:
        out = min(int(final_params.get("ramp_ms", 500)), 1500)
        end_t = max(0, duration_ms - out)
        steps.append(_linear_step(_ALPHA_AXES, end_t, out, prev_a, 0.5, ramp_out_ms=0))
        steps.append(_linear_step(_BETA_AXES, end_t, out, prev_b, 0.5, ramp_out_ms=0))

    return steps


def _e_levels(active: str, rho: float) -> Dict[str, float]:
    levels = {ax: 0.0 for ax in _E_AXES}
    levels[active] = float(rho)
    return levels


def _build_4p_motion(
    duration_ms: int,
    rng: random.Random,
    final_params: dict,
    segments: List[Tuple[int, int]],
) -> List[Dict[str, Any]]:
    steps: List[Dict[str, Any]] = []
    prev = _e_levels("e1", 0.85)
    first = True
    ramp_ms = int(final_params.get("ramp_ms", 500))
    spokes: Sequence[str] = ("e2", "e3", "e4")
    next_spoke = "e2"
    prev_spoke: Optional[str] = None

    for idx, (t, this_dwell) in enumerate(segments):
        if idx % 2 == 0:
            next_spoke = _pick_spoke(rng, spokes, prev_spoke)
            prev_spoke = next_spoke
            pad = "e1"
        else:
            pad = next_spoke

        rho = rng.uniform(0.75, 0.95)
        curr = _e_levels(pad, rho)
        soft = 0 if first else _soft_ms(this_dwell)
        first = False

        if soft > 0:
            for ax in _E_AXES:
                steps.append(_linear_step(ax, t, soft, prev[ax], curr[ax]))
            hold_off = t + soft
            hold_dur = this_dwell - soft
        else:
            hold_off = t
            hold_dur = this_dwell
            for ax in _E_AXES:
                steps.append(
                    _linear_step(
                        ax, hold_off, hold_dur, curr[ax], curr[ax],
                        ramp_in_ms=min(ramp_ms, hold_dur) if ax == "e1" else 0,
                    )
                )
            prev = curr
            continue

        if hold_dur > 0:
            for ax in _E_AXES:
                steps.append(_linear_step(ax, hold_off, hold_dur, curr[ax], curr[ax]))

        prev = curr

    if steps:
        out = min(int(final_params.get("ramp_ms", 500)), 1500)
        end_t = max(0, duration_ms - out)
        for ax in _E_AXES:
            steps.append(_linear_step(ax, end_t, out, prev[ax], 0.0))

    return steps
