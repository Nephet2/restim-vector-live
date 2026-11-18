from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import random

from .fourphase import spatial_response


class MotionMode(str, Enum):
    CIRCULAR = "Circular 0-180"
    TOP_LEFT_BOTTOM_RIGHT = "Top-Left -> Bottom-Right 0-90"
    TOP_RIGHT_BOTTOM_LEFT = "Top-Right -> Bottom-Left 0-270"
    RESTIM_ORIGINAL = "ReStim Original 0-360"


def numbered_mode_box(parent, variable, **kwargs):
    """Display speech-friendly names while retaining saved/API enum values."""
    import tkinter as tk
    from tkinter import ttk
    labels={mode.value:f'Mode {i} - {mode.value}' for i,mode in enumerate(MotionMode,1)}
    selected=tk.StringVar(parent,value=labels.get(variable.get(),variable.get()))
    box=ttk.Combobox(parent,textvariable=selected,values=list(labels.values()),state='readonly',**kwargs)
    reverse={label:value for value,label in labels.items()}
    box.bind('<<ComboboxSelected>>',lambda event:variable.set(reverse[selected.get()]))
    token=variable.trace_add('write',lambda *args:selected.set(labels.get(variable.get(),variable.get())))
    box.bind('<Destroy>',lambda event:variable.trace_remove('write',token) if event.widget is box else None)
    return box


@dataclass(frozen=True)
class MotionParameters:
    min_distance_from_center: float = 0.1
    speed_threshold_percent: float = 50.0
    direction_change_probability: float = 0.1


@dataclass(frozen=True)
class SegmentState:
    sequence: int
    start_time: float
    end_time: float
    start_position: float
    end_position: float
    measured_speed_percent: float | None = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)

    def progress(self, at_time: float) -> float:
        if self.duration <= 0:
            return 1.0
        return min(1.0, max(0.0, (at_time - self.start_time) / self.duration))

    def position(self, at_time: float) -> float:
        p = self.progress(at_time)
        return self.start_position + p * (self.end_position - self.start_position)

    @property
    def speed_percent(self) -> float:
        if self.measured_speed_percent is not None:
            return min(100.0, max(0.0, self.measured_speed_percent))
        if self.duration <= 0:
            return 0.0
        # Matches funscript-tools' fallback segment speed calculation.
        return min(abs(self.end_position - self.start_position) / self.duration / 2.0, 1.0) * 100.0


def restim_arc(start: float, end: float, progress: float, direction: int) -> tuple[float, float]:
    center = (start + end) / 2.0
    radius = (start - end) / 2.0
    return (center + radius * math.cos(progress * math.pi),
            0.5 + radius * direction * math.sin(progress * math.pi))


class MotionCalculator:
    def __init__(self, seed: int | None = None) -> None:
        self._random = random.Random(seed)
        self._segment_directions: dict[int, int] = {}
        self._direction = 1

    def _radius(self, speed: float, params: MotionParameters) -> float:
        threshold = max(float(params.speed_threshold_percent), 1e-10)
        minimum = min(0.9, max(0.0, params.min_distance_from_center))
        scale = 1.0 if speed >= threshold else minimum + (1.0 - minimum) * speed / threshold
        return 0.5 * scale

    def _direction_for(self, segment: SegmentState, probability: float) -> int:
        if segment.sequence not in self._segment_directions:
            if self._random.random() < min(1.0, max(0.0, probability)):
                self._direction *= -1
            self._segment_directions[segment.sequence] = self._direction
            # Bound memory without affecting current/recent segments.
            if len(self._segment_directions) > 512:
                # IDs include both completed strokes and provisional strokes
                # (offset by a billion). Numeric order is not cache age: sorting
                # can evict a completed stroke immediately after inserting it.
                oldest = list(self._segment_directions)[:-256]
                for key in oldest:
                    del self._segment_directions[key]
        return self._segment_directions[segment.sequence]

    @staticmethod
    def _rotate_about_center(alpha: float, beta: float,
                             degrees: float) -> tuple[float, float]:
        """Rotate Cartesian alpha/beta around neutral; positive is clockwise on screen."""
        angle = math.radians(degrees)
        x, y = alpha - .5, beta - .5
        return (.5 + x * math.cos(angle) - y * math.sin(angle),
                .5 + x * math.sin(angle) + y * math.cos(angle))

    def calculate(self, mode: MotionMode, segment: SegmentState, at_time: float,
                  params: MotionParameters, spatial_curve: str = "Linear",
                  spatial_blend: float = 0.0) -> tuple[float, float, float, float]:
        position = spatial_response(segment.position(at_time), spatial_curve, spatial_blend)
        speed = segment.speed_percent

        if mode == MotionMode.RESTIM_ORIGINAL:
            progress = segment.progress(at_time)
            start = spatial_response(segment.start_position, spatial_curve, spatial_blend)
            end = spatial_response(segment.end_position, spatial_curve, spatial_blend)
            direction = self._direction_for(segment, params.direction_change_probability)
            alpha, beta = restim_arc(start, end, progress, direction)
        elif mode == MotionMode.CIRCULAR:
            radius = self._radius(speed, params)
            theta = (1.0 - position) * math.pi
            alpha = 0.5 + radius * math.cos(theta)
            beta = 0.5 + radius * math.sin(theta)
        else:
            # Smooth electrode-aligned arc from A/top to C/right.  Starting at
            # 270 degrees and sweeping 240 degrees finishes at 30 degrees (C)
            # instead of continuing to the 3-o'clock point.
            radius = self._radius(speed, params)
            theta = (3.0 * math.pi / 2.0) - position * (4.0 * math.pi / 3.0)
            alpha = 0.5 + radius * math.cos(theta)
            beta = 0.5 + radius * math.sin(theta)
            if mode == MotionMode.TOP_RIGHT_BOTTOM_LEFT:
                beta = 1.0 - beta
                alpha, beta = self._rotate_about_center(alpha, beta, 30.0)
            else:
                alpha, beta = self._rotate_about_center(alpha, beta, -30.0)

        clamp = lambda value: min(1.0, max(0.0, value))
        return clamp(alpha), clamp(beta), position, speed
