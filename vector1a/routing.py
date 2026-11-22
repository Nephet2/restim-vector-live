from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import threading
import time

from .tcode import TCodeCommand


@dataclass(frozen=True)
class AxisSegment:
    received_at: float
    start_at: float
    end_at: float
    start_value: float
    target_value: float

    def value_at(self, at_time: float) -> float:
        if self.end_at <= self.start_at or at_time >= self.end_at:
            return self.target_value
        if at_time <= self.start_at:
            return self.start_value
        progress = (at_time - self.start_at) / (self.end_at - self.start_at)
        return self.start_value + (self.target_value - self.start_value) * progress


class AuthoredAxisRouter:
    """Thread-safe history for optional non-L0 MFP axis passthrough.

    Values are retained against their original receive timeline so an authored
    axis can be sampled later when Vector releases a look-ahead-delayed sample.
    """

    def __init__(self, history_seconds: float = 15.0,
                 clock=time.monotonic) -> None:
        self.history_seconds = max(5.0, float(history_seconds))
        self.clock = clock
        self._lock = threading.RLock()
        self._tracks: dict[str, deque[AxisSegment]] = {}
        self._last_seen: dict[str, float] = {}
        self._enabled: set[str] = set()

    def receive(self, command: TCodeCommand, received_at: float | None = None) -> None:
        received_at = self.clock() if received_at is None else float(received_at)
        axis = command.axis.upper()
        with self._lock:
            previous = self._value_at_locked(axis, received_at)
            if previous is None:
                previous = command.value
            end_at = received_at + max(0, command.interval_ms) / 1000.0
            segment = AxisSegment(received_at, received_at, end_at,
                                  previous, command.value)
            track = self._tracks.setdefault(axis, deque())
            track.append(segment)
            self._last_seen[axis] = received_at
            cutoff = received_at - self.history_seconds
            while len(track) > 1 and track[1].received_at < cutoff:
                track.popleft()

    def clear_history(self) -> None:
        with self._lock:
            self._tracks.clear()
            self._last_seen.clear()

    def set_enabled(self, axis: str, enabled: bool) -> None:
        axis = axis.upper()
        with self._lock:
            if enabled:
                self._enabled.add(axis)
            else:
                self._enabled.discard(axis)

    def set_enabled_axes(self, axes) -> None:
        with self._lock:
            self._enabled = {str(axis).upper() for axis in axes}

    def enabled_axes(self) -> set[str]:
        with self._lock:
            return set(self._enabled)

    def available_axes(self) -> list[str]:
        with self._lock:
            return sorted(self._tracks)

    def axis_status(self, now: float | None = None) -> dict[str, dict[str, object]]:
        now = self.clock() if now is None else float(now)
        with self._lock:
            return {
                axis: {
                    "enabled": axis in self._enabled,
                    "last_seen_age": max(0.0, now - seen),
                    "value": self._value_at_locked(axis, now),
                }
                for axis, seen in self._last_seen.items()
            }


    RESTIM_SIGNATURE_AXES = frozenset({
        "V0", "C0", "F0", "P0", "P1", "P3",
        "E1", "E2", "E3", "E4",
    })

    def _latest_received_at_or_before_locked(self, axis: str, at_time: float) -> float | None:
        """Return the newest receive timestamp that existed at *at_time*.

        The router is sampled on Vector's delayed/original timeline.  The track may
        already contain newer commands received during the look-ahead delay, so
        using track[-1] would incorrectly make a historically-live axis look stale
        (or "from the future") and disable authored overrides.
        """
        track = self._tracks.get(axis)
        if not track:
            return None
        latest = None
        for segment in track:
            if segment.received_at <= at_time:
                latest = segment.received_at
            else:
                break
        return latest

    def _live_axes_locked(self, at_time: float, freshness_seconds: float = 1.0) -> set[str]:
        freshness = max(0.05, float(freshness_seconds))
        live: set[str] = set()
        for axis in self._tracks:
            latest = self._latest_received_at_or_before_locked(axis, at_time)
            if latest is not None and 0.0 <= at_time - latest <= freshness:
                live.add(axis)
        return live

    def live_axes(self, at_time: float | None = None, freshness_seconds: float = 1.0) -> set[str]:
        """Return axes that are currently fresh on the requested timeline."""
        at_time = self.clock() if at_time is None else float(at_time)
        with self._lock:
            return set(self._live_axes_locked(at_time, freshness_seconds))

    def auto_authored_active(self, at_time: float, freshness_seconds: float = 1.0) -> bool:
        """True when the stream at *at_time* is unmistakably ReStim-authored.

        L0/L1 alone are ambiguous because they can also be ordinary motion axes.
        A fresh ReStim-specific companion axis is therefore required before
        automatic full passthrough is enabled.
        """
        with self._lock:
            live = self._live_axes_locked(at_time, freshness_seconds)
            return bool(live & self.RESTIM_SIGNATURE_AXES)

    def snapshot_auto(self, at_time: float, freshness_seconds: float = 1.0) -> dict[str, float]:
        """Route the complete authored set when a ReStim-authored stream is detected.

        Missing axes are intentionally omitted, allowing Vector's generated values
        to remain as fallbacks at the final output merge.
        """
        with self._lock:
            live = self._live_axes_locked(at_time, freshness_seconds)
            if not (live & self.RESTIM_SIGNATURE_AXES):
                return {}
            result: dict[str, float] = {}
            for axis in live:
                value = self._value_at_locked(axis, at_time)
                if value is not None:
                    result[axis] = value
            return result

    def snapshot(self, at_time: float) -> dict[str, float]:
        with self._lock:
            result: dict[str, float] = {}
            for axis in self._enabled:
                value = self._value_at_locked(axis, at_time)
                if value is not None:
                    result[axis] = value
            return result

    def _value_at_locked(self, axis: str, at_time: float) -> float | None:
        track = self._tracks.get(axis)
        if not track:
            return None
        chosen: AxisSegment | None = None
        for segment in track:
            if segment.received_at <= at_time:
                chosen = segment
            else:
                break
        if chosen is None:
            return track[0].start_value
        return chosen.value_at(at_time)
