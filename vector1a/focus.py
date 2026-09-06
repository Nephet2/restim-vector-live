from __future__ import annotations

from typing import Iterable
import time


TOP_FOCUS_LABELS = (
    "Glans Focus", "Shaft Focus", "Lower Shaft Focus", "Root Focus",
    "Top Sweep", "Top Full",
)
BOTTOM_FOCUS_LABELS = (
    "Prostate Focus", "Anal Focus", "Perineum Focus", "Bottom Sweep", "Bottom Full",
)

_TOP_STATIC_WEIGHTS = {
    # Stronger commissioning envelope. The focused region receives a real
    # local increase while distant regions are deliberately attenuated.
    "Glans Focus": (1.30, 1.05, 0.80, 0.60),
    "Shaft Focus": (1.05, 1.30, 0.80, 0.60),
    "Lower Shaft Focus": (0.60, 0.80, 1.30, 1.05),
    "Root Focus": (0.60, 0.80, 1.05, 1.30),
    "Top Full": (1.00, 1.00, 1.00, 1.00),
}

_BOTTOM_WINDOWS = {
    "Prostate Focus": (0.50, 1.00),
    "Anal Focus": (0.25, 0.75),
    "Perineum Focus": (0.00, 0.50),
    "Bottom Sweep": (0.00, 1.00),
    "Bottom Full": (0.00, 1.00),
}


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def top_focus_weights(label: str, path_position: float = 0.5,
                      strength: float = 1.0) -> tuple[float, float, float, float]:
    """Return E1-E4 multipliers for a semantic anatomical focus.

    Top Sweep moves a 1.10 peak continuously E1 -> E4 using the current path.
    Strength blends all weights back toward 1.0 when reduced.
    """
    strength = min(1.75, max(0.0, float(strength)))
    if label == "Top Sweep":
        p = clamp01(path_position) * 3.0
        centres = (0.0, 1.0, 2.0, 3.0)
        # Match the stronger static envelope while allowing the peak to travel
        # continuously E1 -> E4. Values are linearly interpolated by distance.
        distance_profile = (1.30, 1.05, 0.80, 0.60)
        def weight_at_distance(d: float) -> float:
            d = min(3.0, max(0.0, d))
            i = min(2, int(d))
            frac = d - i
            return distance_profile[i] + (distance_profile[i + 1] - distance_profile[i]) * frac
        raw = tuple(weight_at_distance(abs(p - c)) for c in centres)
    else:
        raw = _TOP_STATIC_WEIGHTS.get(label, _TOP_STATIC_WEIGHTS["Top Full"])
    return tuple(1.0 + (w - 1.0) * strength for w in raw)  # type: ignore[return-value]


def apply_top_focus(values: Iterable[float], label: str, *, nominal_ceiling: float = 0.65,
                    strength: float = 1.0, path_position: float = 0.5
                    ) -> tuple[float, float, float, float]:
    """Apply top focus around the neutral E-axis centre (0.5).

    nominal_ceiling scales available excursion, leaving T-code headroom before
    the selected anatomical multiplier is applied. Neutral 0.5 remains neutral.
    """
    ceiling = min(1.0, max(0.0, float(nominal_ceiling)))
    weights = top_focus_weights(label, path_position, strength)
    src = tuple(float(v) for v in values)
    if len(src) != 4:
        raise ValueError("top focus requires exactly four E-axis values")
    return tuple(clamp01(0.5 + (v - 0.5) * ceiling * w)
                 for v, w in zip(src, weights))  # type: ignore[return-value]


def bottom_focus_window(label: str) -> tuple[float, float]:
    return _BOTTOM_WINDOWS.get(label, _BOTTOM_WINDOWS["Bottom Full"])


def apply_bottom_focus_window(alpha: float, window: tuple[float, float], *,
                              strength: float = 1.0) -> float:
    """Remap secondary Alpha through an explicit, potentially interpolated window."""
    alpha = clamp01(alpha)
    strength = clamp01(strength)
    low, high = (clamp01(window[0]), clamp01(window[1]))
    if high < low:
        low, high = high, low
    low *= strength
    high = 1.0 + (high - 1.0) * strength
    return clamp01(low + alpha * (high - low))


def apply_bottom_focus(alpha: float, label: str, *, strength: float = 1.0) -> float:
    """Remap secondary Alpha into a focus window.

    At strength 1, Prostate Focus maps ordinary 0..1 Alpha into 0.5..1.0.
    At strength 0, the original 0..1 excursion is retained.
    """
    return apply_bottom_focus_window(alpha, bottom_focus_window(label), strength=strength)


class BottomFocusTransition:
    """Continuously interpolate the secondary Alpha window when focus changes."""

    def __init__(self, label: str, *, now: float | None = None) -> None:
        t = time.monotonic() if now is None else float(now)
        window = bottom_focus_window(label)
        self.label = str(label)
        self._start = window
        self._target = window
        self._started_at = t
        self._duration = 0.0

    def window(self, *, now: float | None = None) -> tuple[float, float]:
        t = time.monotonic() if now is None else float(now)
        if self._duration <= 1e-9:
            return self._target
        progress = clamp01((t - self._started_at) / self._duration)
        eased = progress * progress * (3.0 - 2.0 * progress)
        return (
            self._start[0] + (self._target[0] - self._start[0]) * eased,
            self._start[1] + (self._target[1] - self._start[1]) * eased,
        )

    def select(self, label: str, *, duration: float = 1.0,
               now: float | None = None) -> None:
        label = str(label)
        t = time.monotonic() if now is None else float(now)
        target = bottom_focus_window(label)
        if label == self.label and target == self._target:
            return
        self._start = self.window(now=t)
        self._target = target
        self._started_at = t
        self._duration = max(0.0, float(duration))
        self.label = label

    def snapshot(self, *, now: float | None = None) -> dict:
        effective = self.window(now=now)
        return {
            "target": [round(value, 4) for value in self._target],
            "effective": [round(value, 4) for value in effective],
            "transitioning": any(abs(a - b) > 1e-4 for a, b in zip(effective, self._target)),
            "duration_seconds": round(self._duration, 3),
        }


class FocusHistory:
    """Track semantic focus dwell and the immediately preceding focus.

    Timing is monotonic wall-clock time from selection changes. Vector's engine
    state is reported separately, so the Director can distinguish selected dwell
    from whether playback is currently running.
    """
    def __init__(self, initial_label: str, now: float | None = None) -> None:
        t = time.monotonic() if now is None else float(now)
        self.current_label = str(initial_label)
        self.current_since = t
        self.previous_label: str | None = None
        self.previous_duration = 0.0

    def select(self, label: str, now: float | None = None) -> None:
        label = str(label)
        if label == self.current_label:
            return
        t = time.monotonic() if now is None else float(now)
        self.previous_label = self.current_label
        self.previous_duration = max(0.0, t - self.current_since)
        self.current_label = label
        self.current_since = t

    def snapshot(self, now: float | None = None) -> dict:
        t = time.monotonic() if now is None else float(now)
        return {
            "current": self.current_label,
            "selected_for_seconds": round(max(0.0, t - self.current_since), 2),
            "previous": self.previous_label,
            "previous_duration_seconds": round(self.previous_duration, 2),
        }
