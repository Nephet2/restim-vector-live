"""Position scripts and explicit speed-to-stroke conversion for Handy."""
from bisect import bisect_right
from dataclasses import dataclass
import json
from math import isfinite
from pathlib import Path

from .vacuglide_script import Script
from .timeline import FunscriptAction, FunscriptTimeline


@dataclass(frozen=True)
class MotionScript:
    name: str
    points: tuple
    note: str = ""

    def __post_init__(self):
        if not self.points or len(self.points) > 500000:
            raise ValueError("A script needs 1 to 500,000 positions.")
        previous = -1
        for t, x in self.points:
            if (not isfinite(t) or not isfinite(x) or t < 0 or t <= previous
                    or t > 86400 or not 0 <= x <= 1):
                raise ValueError("Script times must increase within 24 hours; positions must be 0–100%.")
            previous = t
        if self.points[-1][0] <= 0:
            raise ValueError("The script must have a positive duration.")
        object.__setattr__(self, "times", tuple(t for t, _ in self.points))
        object.__setattr__(self, "gradients", FunscriptTimeline._monotone_gradients(
            [FunscriptAction(t, x) for t, x in self.points]))

    @property
    def duration(self):
        return self.points[-1][0]

    def sample(self, seconds, gradient=False):
        i = bisect_right(self.times, seconds) - 1
        if i < 0:
            return self.points[0][1]
        if i >= len(self.points) - 1:
            return self.points[-1][1]
        t, x = self.points[i]
        end, y = self.points[i + 1]
        p = (seconds - t) / (end - t)
        if not gradient:
            return x + (y - x) * p
        a, b = self.gradients[i] * (end - t), self.gradients[i + 1] * (end - t)
        return x + p * (a + p * (3 * (y - x) - 2 * a - b + p * (2 * (x - y) + a + b)))

    @classmethod
    def load(cls, path):
        path = Path(path)
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError("Script files must be smaller than 32 MB.")
        if path.suffix.lower() != ".funscript":
            return from_vacuglide(Script.load(path))
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        try:
            actions = data["actions"]
            if not isinstance(actions, list) or not 1 <= len(actions) <= 500000:
                raise ValueError("Invalid funscript action count.")
            points = tuple((float(a["at"]) / 1000, float(a["pos"]) / 100) for a in actions)
            # Inverted files explicitly request the opposite position axis.
            if data.get("inverted") is True:
                points = tuple((t, 1 - x) for t, x in points)
            return cls(path.stem, points, "Funscript position track")
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError("Invalid funscript position track.") from exc


def from_vacuglide(script):
    """Integrate speed steps into triangular strokes. Zero speed is a hold.

    100% means two full cycles/second; valve instructions have no Handy analogue.
    """
    steps = [e for e in script.events if e.kind == "speed"]
    times = [e.start_ms for e in steps]
    phase = 0.0
    points = [(0.0, 0.0)]
    interval = max(20, (script.duration_ms + 499998) // 499999)
    for ms in range(interval, script.duration_ms + interval, interval):
        ms = min(ms, script.duration_ms)
        start = int(round(points[-1][0] * 1000))
        boundaries = [start] + times[bisect_right(times, start):bisect_right(times, ms - 1)] + [ms]
        for a, b in zip(boundaries, boundaries[1:]):
            i = bisect_right(times, a) - 1
            speed = 0 if i < 0 else steps[i].speed_percent / 100
            phase += (b - a) / 1000 * 2 * speed
        x = 1 - abs(2 * (phase % 1) - 1)
        points.append((ms / 1000, x))
    return MotionScript(script.name, tuple(points),
                        "VacuGlide speed → strokes (100% = 2 cycles/s); vacuum events ignored")


def curated_scripts():
    """Original position patterns; no third-party catalogue downloads."""
    result = {}
    for name, period, low, high in (("Slow full strokes", 4, 0, 1),
                                   ("Steady full strokes", 2, 0, 1),
                                   ("Short upper strokes", 1.5, .55, 1)):
        pts = [(0., low)]
        t = period / 2
        while t <= 120:
            pts.append((t, high if len(pts) % 2 else low))
            t += period / 2
        result[name] = MotionScript(name, tuple(pts), "Original Vector pattern • 2 minutes")
    pts = [(0., 0.)]
    t = 0.
    while t < 120:
        period = 4 - 3 * min(1, t / 100)
        t = min(120, t + period / 2)
        pts.append((t, 1. if len(pts) % 2 else 0.))
    result["Gradual build"] = MotionScript("Gradual build", tuple(pts), "Original Vector pattern • 2 minutes")
    pts = [(0., 0.)]
    for block in range(6):
        base = block * 20
        for i in range(1, 13):
            pts.append((base + i, float(i % 2)))
        pts.append((base + 20., 0.))
    result["Pulses and rests"] = MotionScript("Pulses and rests", tuple(pts), "12 seconds motion / 8 seconds hold")
    return result
