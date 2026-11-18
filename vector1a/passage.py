"""Bounded, thread-safe passage envelope. No device or model authority."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math
import threading
import time
import uuid


def number(value, name, low, high):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return result


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


@dataclass(frozen=True)
class PassagePlan:
    build_seconds: float = 60.0
    hold_seconds: float = 30.0
    release_seconds: float = 60.0
    floor: float = 0.50
    peak: float = 1.0
    transition_seconds: float = 5.0
    clock: str = "elapsed"
    label: str = "Build, hold, release"
    target: str = "primary"

    @classmethod
    def validated(cls, body):
        if not isinstance(body, dict):
            raise ValueError("passage plan must be an object")
        unknown = set(body) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError("unknown passage fields: " + ", ".join(sorted(unknown)))
        defaults = asdict(cls())
        values = {}
        for name in ("build_seconds", "hold_seconds", "release_seconds"):
            values[name] = number(body.get(name, defaults[name]), name, 0, 600)
        total = sum(values.values())
        if not 5 <= total <= 1200:
            raise ValueError("build + hold + release must total 5 to 1200 seconds")
        # A nonzero rise or fall must not become an instantaneous change.
        for name in ("build_seconds", "release_seconds"):
            if 0 < values[name] < 2:
                raise ValueError(f"{name} must be zero or at least 2 seconds")
        values["floor"] = number(body.get("floor", defaults["floor"]), "floor", 0, 1)
        values["peak"] = number(body.get("peak", defaults["peak"]), "peak", values["floor"], 1)
        values["transition_seconds"] = number(body.get("transition_seconds", 5), "transition_seconds", 2, 15)
        for key, allowed in (("clock", ("elapsed", "media")), ("target", ("primary", "both"))):
            value = body.get(key, defaults[key])
            if value not in allowed:
                raise ValueError(f"{key} must be one of {allowed}")
            values[key] = value
        label = body.get("label", defaults["label"])
        if not isinstance(label, str) or len(label) > 160:
            raise ValueError("label must be text up to 160 characters")
        values["label"] = label.strip()
        return cls(**values)

    @property
    def duration(self):
        return self.build_seconds + self.hold_seconds + self.release_seconds

    def at(self, elapsed):
        t = max(0.0, elapsed)
        if t < self.build_seconds:
            return "build", self.floor + (self.peak - self.floor) * ease(t / self.build_seconds)
        t -= self.build_seconds
        if t < self.hold_seconds:
            return "hold", self.peak
        t -= self.hold_seconds
        if t < self.release_seconds:
            return "release", self.peak + (self.floor - self.peak) * ease(t / self.release_seconds)
        # A hold-only/build-only plan retains its terminal level, never jumps back.
        return "complete", self.floor if self.release_seconds else self.peak

    def preview(self):
        return [{"seconds": round(self.duration * i / 100, 3),
                 "factor": self.at(self.duration * i / 100)[1]} for i in range(101)]


class PassageController:
    """Envelope never exceeds baseline; final level latches until changed/restored.

    Media clock integrates positive transport deltas. Pause/missing clock freezes;
    backward or >2s seeks hold the factor until explicit Resume reanchors it.
    Both lanes slew independently, including replacement and target changes.
    """
    def __init__(self, clock=time.monotonic, transport=None):
        self.clock = clock
        self.transport = transport
        self.lock = threading.RLock()
        self.plan = None
        self.ident = None
        self.elapsed = 0.0
        self.held = False
        self.reason = ""
        self.phase = "idle"
        self.factors = [1.0, 1.0]
        self.last_time = clock()
        self.last_media = None
        self.last_source = None
        self.restoring = False

    def _advance(self):
        now = self.clock()
        dt = max(0.0, now - self.last_time)
        self.last_time = now
        if self.plan is None and not self.restoring:
            return
        if self.held:
            return
        elapsed_delta = dt
        if self.plan and self.plan.clock == "media":
            transport = self.transport() if self.transport else {}
            pos = transport.get("position_seconds")
            source = transport.get("source")
            if not transport.get("valid") or pos is None:
                self.reason = "waiting for media clock"
                self.last_media = None
                return
            if self.last_source is not None and source != self.last_source:
                self.held = True
                self.reason = "media changed; resume to reanchor"
                return
            delta = 0.0 if self.last_media is None else pos - self.last_media
            self.last_media, self.last_source = pos, source
            if delta < -0.25 or delta > max(2.0, dt * 4):
                self.held = True
                self.reason = "media seek; resume to reanchor"
                return
            elapsed_delta = max(0.0, delta)
            if not transport.get("playing"):
                self.reason = "media paused"
                return
        self.reason = ""
        if self.restoring:
            goals = (1.0, 1.0)
            transition = self.restore_seconds
            self.phase = "restoring"
        else:
            self.elapsed = min(self.plan.duration, self.elapsed + elapsed_delta)
            self.phase, value = self.plan.at(self.elapsed)
            goals = (value, value if self.plan.target == "both" else 1.0)
            transition = self.plan.transition_seconds
        # Absolute normalized units/second; long gaps never create an abrupt jump.
        step = min(dt, 0.10) / transition
        for i, goal in enumerate(goals):
            previous_factor = self.factors[i]
            self.factors[i] += min(step, max(-step, goal - self.factors[i]))
            limit = (max(1.0, self.factors[i]) if self.restoring else getattr(self.plan, "max_factor", 1.0)) if i == 0 else 1.0
            self.factors[i] = min(max(limit, previous_factor), max(0.0, self.factors[i]))
            if abs(self.factors[i] - goal) < 1e-9:
                self.factors[i] = goal
        if self.restoring and all(abs(v - 1) < 1e-9 for v in self.factors):
            self.restoring = False
            self.phase = "idle"

    def apply(self, plan):
        with self.lock:
            self._advance()
            if plan.clock == "media":
                transport = self.transport() if self.transport else {}
                if not transport.get("valid"):
                    raise ValueError("media passage requires a fresh, authoritative player clock")
            self.plan = plan
            self.ident = uuid.uuid4().hex
            self.elapsed = 0.0
            self.held = False
            self.restoring = False
            self.last_media = None
            self.last_source = None
            self.reason = ""
            self.phase = plan.at(0)[0]
            return self.snapshot()

    def hold(self):
        with self.lock:
            self._advance()
            self.held = True
            self.reason = "manual hold"
            return self.snapshot()

    def resume(self):
        with self.lock:
            self.last_time = self.clock()
            self.last_media = None
            self.last_source = None
            self.held = False
            self.reason = ""
            return self.snapshot()

    def restore(self, seconds=5.0):
        seconds = number(seconds, "transition_seconds", 2, 15)
        with self.lock:
            self._advance()
            self.plan = None
            self.ident = uuid.uuid4().hex
            self.restoring = True
            self.restore_seconds = seconds
            self.held = False
            return self.snapshot()

    def reset(self):
        with self.lock:
            self.plan = None
            self.restoring = False
            self.held = False
            self.factors = [1.0, 1.0]
            self.phase = "idle"
            self.reason = ""
            self.ident = None
            self.last_time = self.clock()

    def snapshot(self):
        with self.lock:
            self._advance()
            completed = self.plan is not None and self.phase == "complete"
            return {"id": self.ident, "active": (self.plan is not None and not completed) or self.restoring,
                    "completed": completed,
                    "remaining_seconds": max(0.0, self.plan.duration-self.elapsed) if self.plan else 0.0,
                    "held": self.held, "phase": self.phase, "reason": self.reason,
                    "elapsed_seconds": round(self.elapsed, 3),
                    "primary_factor": self.factors[0], "secondary_factor": self.factors[1],
                    "plan": asdict(self.plan) if self.plan else None,
                    "sequence": self.plan.detail_at(self.elapsed) if hasattr(self.plan, "detail_at") else None,
                    "nominal_ceiling": self.plan.baseline*self.factors[0] if hasattr(self.plan, "baseline") else None,
                    "note": "Relative to current output; complete retains terminal factor. No output arming."}

    def factors_now(self):
        with self.lock:
            self._advance()
            return tuple(self.factors)
