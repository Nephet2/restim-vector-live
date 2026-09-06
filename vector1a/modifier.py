from __future__ import annotations

from dataclasses import dataclass, replace

from .motion import SegmentState


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _smoothstep(value: float) -> float:
    x = _clamp01(value)
    return x * x * (3.0 - 2.0 * x)


@dataclass(frozen=True)
class ModifierValues:
    """Bounded deterministic spatial modifier values.

    Alpha69 deliberately keeps only one range control. Alpha68's stroke-amplitude
    and global-range controls proved perceptually redundant during commissioning.
    Tempo is handled separately against the full authored timeline because a true
    2x transform requires future script positions rather than endpoint clipping.
    """
    stroke_range: float = 1.0
    position_bias: float = 0.0
    smoothing: float = 0.0

    def bounded(self) -> "ModifierValues":
        return ModifierValues(
            stroke_range=min(1.5, max(0.3, float(self.stroke_range))),
            position_bias=min(0.35, max(-0.35, float(self.position_bias))),
            smoothing=min(1.0, max(0.0, float(self.smoothing))),
        )

    def is_neutral(self) -> bool:
        return (abs(self.stroke_range - 1.0) < 1e-9
                and abs(self.position_bias) < 1e-9
                and abs(self.smoothing) < 1e-9)


def transform_segment(segment: SegmentState, values: ModifierValues) -> SegmentState:
    """Return a bounded deterministic L0 segment while leaving source untouched.

    Order: optional deterministic curve smoothing, one range transform around L0
    neutral, then position bias. Output is explicitly clamped to ReStim's 0..1
    input range.
    """
    values = values.bounded()
    if values.is_neutral():
        return segment

    start = float(segment.start_position)
    end = float(segment.end_position)
    smooth = values.smoothing
    if smooth > 0.0:
        start = start + (_smoothstep(start) - start) * smooth
        end = end + (_smoothstep(end) - end) * smooth

    start = 0.5 + (start - 0.5) * values.stroke_range + values.position_bias
    end = 0.5 + (end - 0.5) * values.stroke_range + values.position_bias
    return replace(segment, start_position=_clamp01(start), end_position=_clamp01(end))


def interpolate(a: ModifierValues, b: ModifierValues, amount: float) -> ModifierValues:
    t = _clamp01(amount)
    return ModifierValues(
        a.stroke_range + (b.stroke_range - a.stroke_range) * t,
        a.position_bias + (b.position_bias - a.position_bias) * t,
        a.smoothing + (b.smoothing - a.smoothing) * t,
    )
