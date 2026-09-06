from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable


PATTERNS = ("sine", "triangle", "breathing")


@dataclass(frozen=True)
class MotionPlan:
    pattern: str = "sine"
    minimum: float = 0.20
    maximum: float = 0.80
    stroke_duration_ms: float = 750.0
    transition_seconds: float = 5.0
    duration_seconds: float = 180.0
    reason: str = ""

    @classmethod
    def validated(cls, body: dict) -> "MotionPlan":
        pattern = str(body.get("pattern", "sine")).strip().lower()
        if pattern not in PATTERNS:
            raise ValueError(f"pattern must be one of {', '.join(PATTERNS)}")
        try:
            minimum = float(body.get("minimum"))
            maximum = float(body.get("maximum"))
            stroke_ms = float(body.get("stroke_duration_ms"))
            transition = float(body.get("transition_seconds", 5.0))
            duration = float(body.get("duration_seconds", 180.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("motion-plan values must be numeric") from exc
        if not 0.0 <= minimum <= 0.90:
            raise ValueError("minimum must be between 0.0 and 0.90")
        if not 0.10 <= maximum <= 1.0:
            raise ValueError("maximum must be between 0.10 and 1.0")
        if maximum - minimum < 0.10:
            raise ValueError("maximum must be at least 0.10 above minimum")
        if not 125.0 <= stroke_ms <= 3000.0:
            raise ValueError("stroke_duration_ms must be between 125 and 3000")
        if not 1.0 <= transition <= 15.0:
            raise ValueError("transition_seconds must be between 1 and 15")
        if not 30.0 <= duration <= 600.0:
            raise ValueError("duration_seconds must be between 30 and 600")
        return cls(pattern, minimum, maximum, stroke_ms, transition, duration,
                   str(body.get("reason", "")).strip()[:240])


class GeneratedMotionSource:
    """Vector-owned fixed-cadence L0 generator selected by bounded plans."""

    def __init__(self, emit: Callable[[float, int, float], None], cadence_hz: float = 25.0):
        self._emit = emit
        self._cadence_hz = cadence_hz
        self._lock = threading.Lock()
        self._plan = MotionPlan()
        self._active = False
        self._held = False
        self._started_at = 0.0
        self._plan_started_at = 0.0
        self._transition_from = 0.5
        self._last_value = 0.5
        self._sequence = 0
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, name="Vector generated L0", daemon=True)
        self._thread.start()

    @property
    def active(self) -> bool:
        with self._lock:
            return self._active

    def apply(self, plan: MotionPlan, starting_value: float) -> dict:
        now = time.monotonic()
        with self._lock:
            self._plan = replace(plan)
            self._active = True
            self._held = False
            self._started_at = self._started_at or now
            self._plan_started_at = now
            self._transition_from = max(0.0, min(1.0, float(starting_value)))
            self._last_value = self._transition_from
            self._sequence += 1
        return self.snapshot()

    def hold(self) -> dict:
        with self._lock:
            if self._active:
                self._held = True
        return self.snapshot()

    def resume(self) -> dict:
        with self._lock:
            if self._active:
                self._held = False
                self._plan_started_at = time.monotonic()
                self._transition_from = self._last_value
        return self.snapshot()

    def authored(self) -> dict:
        with self._lock:
            self._active = False
            self._held = False
            self._started_at = 0.0
        return self.snapshot()

    def close(self) -> None:
        self._stop_event.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def snapshot(self) -> dict:
        with self._lock:
            plan = self._plan
            active, held = self._active, self._held
            started, plan_started = self._started_at, self._plan_started_at
            value, sequence = self._last_value, self._sequence
        now = time.monotonic()
        return {
            "source": "gwendolyn_generated" if active else "authored_tcode",
            "active": active,
            "held": held,
            "sequence": sequence,
            "current_l0": round(value, 4),
            "session_elapsed_seconds": round(max(0.0, now - started), 2) if active else 0.0,
            "plan_elapsed_seconds": round(max(0.0, now - plan_started), 2) if active else 0.0,
            "review_due": bool(active and now - plan_started >= plan.duration_seconds),
            "plan": {
                "pattern": plan.pattern, "minimum": plan.minimum, "maximum": plan.maximum,
                "stroke_duration_ms": plan.stroke_duration_ms,
                "derived_cycles_per_minute": round(30000.0 / plan.stroke_duration_ms, 2),
                "transition_seconds": plan.transition_seconds,
                "duration_seconds": plan.duration_seconds, "reason": plan.reason,
            } if active else None,
        }

    @staticmethod
    def _wave(pattern: str, phase: float) -> float:
        phase %= 1.0
        if pattern == "triangle":
            return 1.0 - abs(2.0 * phase - 1.0)
        if pattern == "breathing":
            return (1.0 - math.cos(2.0 * math.pi * phase)) * 0.5
        return (1.0 + math.sin(2.0 * math.pi * phase - math.pi / 2.0)) * 0.5

    def _run(self) -> None:
        interval = 1.0 / self._cadence_hz
        while not self._stop_event.wait(interval):
            now = time.monotonic()
            with self._lock:
                if not self._active:
                    continue
                if self._held:
                    emitted = self._last_value
                    plan = None
                else:
                    plan = self._plan
                if plan is None:
                    pass
                else:
                    elapsed = now - self._plan_started_at
                    # duration_seconds is a review horizon, not a motion kill-switch.
                    # A delayed or failed Director decision must not flatten L0.
                    phase = elapsed / (2.0 * plan.stroke_duration_ms / 1000.0)
                    target = plan.minimum + (plan.maximum - plan.minimum) * self._wave(plan.pattern, phase)
                    blend = min(1.0, elapsed / plan.transition_seconds)
                    blend = blend * blend * (3.0 - 2.0 * blend)
                    value = self._transition_from + (target - self._transition_from) * blend
                    self._last_value = max(0.0, min(1.0, value))
                    emitted = self._last_value
            self._emit(emitted, round(interval * 1000), now)
