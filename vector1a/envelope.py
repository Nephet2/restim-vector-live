"""Output envelope smoothing stages, independent of the engine and UI.

Three stages, applied per axis in this order:

1. ``AttackRelease``: first-order exponential filter with separate time
   constants.  The attack constant is used while the target is above the
   filtered value, the release constant while it is below.  Each constant is
   the time to cover about 63% of a sustained step.
2. ``JerkLimiter``: three cascaded trailing moving averages of N samples.
   For any input confined to a range R, the third difference of the output
   per dt^3 is at most 4 R / (N dt)^3, so ``jerk_window_samples`` picks the
   smallest N that keeps it under a limit.  Delay is 3 (N - 1) / 2 samples.
3. Smoothing-delay compensation: ``advance_lookup`` reads a processed history
   ``advance`` seconds ahead, with linear interpolation between samples.

Every stage forms averages or interpolations of earlier inputs, so outputs
never leave the range of the inputs they were made from.  With all stages off
the chain returns its input unchanged.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

COMPENSATION_MODES = ("none", "ma", "ma+attack")
_JERK_BOUND_FACTOR = 4.0     # max |x - 3x' + 3x'' - x'''| for x within a range R is 4 R.
_RESUM_INTERVAL = 4096       # Recompute running sums to stop float drift.


def _finite_non_negative(name: str, value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite number >= 0")
    return value


class AttackRelease:
    """Asymmetric first-order filter; step() takes the elapsed interval."""

    def __init__(self, tau_attack: float, tau_release: float) -> None:
        self.tau_attack = _finite_non_negative("tau_attack", tau_attack)
        self.tau_release = _finite_non_negative("tau_release", tau_release)
        self._value: float | None = None

    def reset(self, value: float | None = None) -> None:
        self._value = None if value is None else float(value)

    def step(self, target: float, dt: float) -> float:
        target = float(target)
        if self._value is None:
            self._value = target
            return target
        if dt <= 0.0:
            return self._value
        tau = self.tau_attack if target > self._value else self.tau_release
        if tau <= 0.0:
            self._value = target
        else:
            self._value += (target - self._value) * -math.expm1(-dt / tau)
        return self._value


def jerk_window_samples(jerk_limit: float | None, axis_range: float, dt: float) -> int:
    """Smallest moving-average length that bounds jerk for inputs within axis_range."""
    if not jerk_limit:
        return 1
    width = (_JERK_BOUND_FACTOR * float(axis_range) / float(jerk_limit)) ** (1.0 / 3.0)
    # The tolerance stops float noise (e.g. 10.000000000000002) adding a sample.
    return max(1, math.ceil(width / float(dt) - 1e-9))


class _MovingAverage:
    def __init__(self, samples: int) -> None:
        self.samples = samples
        self._buffer: list[float] = []
        self._index = 0
        self._total = 0.0
        self._steps = 0

    def reset(self, value: float | None) -> None:
        if value is None:
            self._buffer = []
        else:
            self._buffer = [float(value)] * self.samples
            self._total = float(value) * self.samples
        self._index = 0
        self._steps = 0

    def step(self, value: float) -> float:
        if not self._buffer:
            self.reset(value)
            return float(value)
        self._total += value - self._buffer[self._index]
        self._buffer[self._index] = value
        self._index = (self._index + 1) % self.samples
        self._steps += 1
        if self._steps >= _RESUM_INTERVAL:
            self._total = math.fsum(self._buffer)
            self._steps = 0
        return self._total / self.samples


class JerkLimiter:
    """Three cascaded trailing moving averages of the same length."""

    def __init__(self, samples: int) -> None:
        self.samples = max(1, int(samples))
        self._stages = [_MovingAverage(self.samples) for _ in range(3)]

    @property
    def delay_samples(self) -> float:
        return 3.0 * (self.samples - 1) / 2.0

    def reset(self, value: float | None = None) -> None:
        for stage in self._stages:
            stage.reset(value)

    def step(self, value: float) -> float:
        value = float(value)
        if self.samples <= 1:
            return value
        for stage in self._stages:
            value = stage.step(value)
        return value


def compensation_seconds(mode: str, samples: int, dt: float, tau_attack: float) -> float:
    """Advance that cancels the moving-average delay, optionally plus attack."""
    if mode not in COMPENSATION_MODES:
        raise ValueError(f"compensation must be one of {', '.join(COMPENSATION_MODES)}")
    if mode == "none":
        return 0.0
    seconds = 3.0 * (max(1, int(samples)) - 1) / 2.0 * float(dt)
    if mode == "ma+attack":
        seconds += float(tau_attack)
    return seconds


def advance_lookup(history: Sequence[tuple[float, float]], at_time: float,
                   advance: float) -> tuple[float | None, bool]:
    """Value of a time-sorted (time, value) history at at_time + advance.

    Returns (value, limited).  limited is True when the requested time lies
    outside the history, in which case the nearest end value is used.
    """
    if not history:
        return None, True
    target = float(at_time) + float(advance)
    first_time, first_value = history[0]
    if target <= first_time:
        return first_value, target < first_time
    last_time, last_value = history[-1]
    if target >= last_time:
        return last_value, target > last_time
    low, high = 0, len(history) - 1          # history[low].t < target < history[high].t
    while high - low > 1:
        middle = (low + high) // 2
        if history[middle][0] < target:
            low = middle
        else:
            high = middle
    right_time, right_value = history[high]
    if right_time == target:
        return right_value, False
    left_time, left_value = history[low]
    fraction = (target - left_time) / (right_time - left_time)
    return left_value + (right_value - left_value) * fraction, False


class EnvelopeChain:
    """Attack/release followed by jerk limiting at a fixed sample interval."""

    def __init__(self, dt: float, *, axis_range: float, tau_attack: float = 0.0,
                 tau_release: float = 0.0, jerk_limit: float | None = None,
                 compensation: str = "none") -> None:
        dt = float(dt)
        if not math.isfinite(dt) or dt <= 0.0:
            raise ValueError("dt must be a finite number > 0")
        axis_range = float(axis_range)
        if not math.isfinite(axis_range) or axis_range <= 0.0:
            raise ValueError("axis_range must be a finite number > 0")
        if jerk_limit is not None:
            jerk_limit = _finite_non_negative("jerk_limit", jerk_limit) or None
        self.dt = dt
        self.attack_release = AttackRelease(tau_attack, tau_release)
        self.jerk_limiter = JerkLimiter(jerk_window_samples(jerk_limit, axis_range, dt))
        self.advance_seconds = compensation_seconds(
            compensation, self.jerk_limiter.samples, dt, self.attack_release.tau_attack)

    @property
    def window_samples(self) -> int:
        return self.jerk_limiter.samples

    def reset(self, value: float | None = None) -> None:
        self.attack_release.reset(value)
        self.jerk_limiter.reset(value)

    def step(self, value: float) -> float:
        return self.jerk_limiter.step(self.attack_release.step(value, self.dt))
