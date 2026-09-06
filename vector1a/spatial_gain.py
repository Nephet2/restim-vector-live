from __future__ import annotations

import time


def clamp(value: float, low: float, high: float) -> float:
    return min(float(high), max(float(low), float(value)))


class SpatialGainController:
    """Bounded, smoothly-ramped multiplicative spatial intensity overlay.

    Gain 1.0 is neutral. The target can be moved in operator-configured steps,
    while effective gain approaches it at a bounded rate. History records target
    selections, not claims about delivered electrical dwell; engine state is
    reported separately by Vector.
    """

    def __init__(self, *, initial: float = 1.0, now: float | None = None) -> None:
        t = time.monotonic() if now is None else float(now)
        self.target = float(initial)
        self.effective = float(initial)
        self._last_update = t
        self._target_since = t
        self.previous_target: float | None = None
        self.previous_duration = 0.0

    def set_target(self, target: float, *, minimum: float, maximum: float,
                   now: float | None = None) -> float:
        t = time.monotonic() if now is None else float(now)
        target = clamp(target, minimum, maximum)
        if abs(target - self.target) <= 1e-9:
            return self.target
        self.previous_target = self.target
        self.previous_duration = max(0.0, t - self._target_since)
        self.target = target
        self._target_since = t
        return self.target

    def step(self, direction: int, *, step: float, minimum: float, maximum: float,
             now: float | None = None) -> float:
        return self.set_target(self.target + (1 if direction >= 0 else -1) * abs(float(step)),
                               minimum=minimum, maximum=maximum, now=now)

    def restore(self, *, minimum: float, maximum: float,
                now: float | None = None) -> float:
        return self.set_target(1.0, minimum=minimum, maximum=maximum, now=now)

    def update(self, *, ramp_per_second: float, now: float | None = None) -> float:
        t = time.monotonic() if now is None else float(now)
        dt = max(0.0, t - self._last_update)
        self._last_update = t
        max_delta = max(0.0, float(ramp_per_second)) * dt
        delta = self.target - self.effective
        if abs(delta) <= max_delta or max_delta <= 0.0:
            if max_delta > 0.0:
                self.effective = self.target
        else:
            self.effective += max_delta if delta > 0 else -max_delta
        return self.effective

    def snapshot(self, *, step: float, minimum: float, maximum: float,
                 ramp_per_second: float, now: float | None = None) -> dict:
        t = time.monotonic() if now is None else float(now)
        return {
            "target": round(self.target, 4),
            "target_percent": round(self.target * 100.0, 1),
            "effective": round(self.effective, 4),
            "effective_percent": round(self.effective * 100.0, 1),
            "selected_for_seconds": round(max(0.0, t - self._target_since), 2),
            "previous_target": None if self.previous_target is None else round(self.previous_target, 4),
            "previous_target_percent": None if self.previous_target is None else round(self.previous_target * 100.0, 1),
            "previous_duration_seconds": round(self.previous_duration, 2),
            "step_percent": round(float(step) * 100.0, 1),
            "minimum_percent": round(float(minimum) * 100.0, 1),
            "maximum_percent": round(float(maximum) * 100.0, 1),
            "ramp_percent_per_second": round(float(ramp_per_second) * 100.0, 1),
        }


def apply_gain(value: float, gain: float) -> float:
    return min(1.0, max(0.0, float(value) * float(gain)))
