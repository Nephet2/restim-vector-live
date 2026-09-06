from __future__ import annotations

from bisect import bisect_right
from collections import deque
from dataclasses import dataclass
import json
import math
import os
import threading
import time
from typing import Callable

from .media_clock import MediaSnapshot, find_matching_funscript, poll_mpc, poll_vlc


@dataclass(frozen=True)
class FunscriptAction:
    at: float  # seconds
    pos: float  # 0..1


class FunscriptTimeline:
    """Read-only funscript timeline and lightweight MFP/L0 synchroniser.

    The timeline never drives Vector output in this release.  It observes incoming
    L0 to estimate media/script time, or can run an internal preview clock for
    commissioning.  All summaries are deterministic and AI-independent.
    """

    CLOCK_AUTO = "Auto media player"
    CLOCK_VLC = "VLC direct"
    CLOCK_MPC = "MPC direct"
    CLOCK_MFP = "MFP pattern sync"
    CLOCK_MANUAL = "Manual preview"

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self._lock = threading.RLock()
        self._actions: list[FunscriptAction] = []
        self._times: list[float] = []
        self._path: str = ""
        self._duration = 0.0
        self._clock_mode = self.CLOCK_MFP
        self._manual_position = 0.0
        self._manual_anchor_position = 0.0
        self._manual_anchor_clock = clock()
        self._manual_playing = False
        self._live: deque[tuple[float, float]] = deque(maxlen=256)
        self._last_live_kept = -math.inf
        self._match_position: float | None = None
        self._match_score: float | None = None
        self._match_updated_at = 0.0
        self._global_peak_speed = 1.0
        self._global_mean_amplitude = 0.5
        self._media_host = "127.0.0.1"
        self._vlc_port = 8080
        self._vlc_password = ""
        self._mpc_port = 13579
        self._script_library_dirs: list[str] = []
        self._auto_load_script = True
        self._media_snapshot: MediaSnapshot | None = None
        self._media_snapshot_received_at: float | None = None
        self._media_poll_inflight = False
        self._last_media_poll_at = -math.inf
        self._last_media_path: str | None = None
        self._last_auto_loaded_for_media: str | None = None
        self._auto_load_note: str | None = None
        self._media_clock_health = "unknown"
        self._media_last_position: float | None = None
        self._media_progress_changed_at: float | None = None

    @property
    def loaded(self) -> bool:
        with self._lock:
            return bool(self._actions)

    def load(self, path: str) -> dict:
        path = os.path.abspath(os.path.expanduser(path))
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
        raw = data.get("actions") if isinstance(data, dict) else None
        if not isinstance(raw, list) or len(raw) < 2:
            raise ValueError("funscript must contain at least two actions")
        actions: list[FunscriptAction] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                at = float(item["at"]) / 1000.0
                pos = min(1.0, max(0.0, float(item["pos"]) / 100.0))
            except (KeyError, TypeError, ValueError):
                continue
            if actions and at < actions[-1].at:
                raise ValueError("funscript actions must be ordered by time")
            if actions and abs(at - actions[-1].at) < 1e-9:
                actions[-1] = FunscriptAction(at, pos)
            else:
                actions.append(FunscriptAction(at, pos))
        if len(actions) < 2:
            raise ValueError("funscript contains too few valid actions")
        duration = actions[-1].at
        peak = 0.0
        amplitudes: list[float] = []
        for a, b in zip(actions, actions[1:]):
            dt = max(1e-6, b.at - a.at)
            peak = max(peak, abs(b.pos - a.pos) / dt)
            amplitudes.append(abs(b.pos - a.pos))
        with self._lock:
            self._actions = actions
            self._times = [x.at for x in actions]
            self._path = path
            self._duration = duration
            self._manual_position = 0.0
            self._manual_anchor_position = 0.0
            self._manual_anchor_clock = self.clock()
            self._manual_playing = False
            self._live.clear()
            self._match_position = None
            self._match_score = None
            self._match_updated_at = 0.0
            self._global_peak_speed = max(0.05, peak)
            self._global_mean_amplitude = max(0.05, sum(amplitudes) / len(amplitudes))
        return self.metadata()

    def clear(self) -> None:
        with self._lock:
            self._actions = []
            self._times = []
            self._path = ""
            self._duration = 0.0
            self._live.clear()
            self._match_position = None
            self._match_score = None
            self._manual_playing = False

    def metadata(self) -> dict:
        with self._lock:
            return {
                "loaded": bool(self._actions),
                "file": os.path.basename(self._path) if self._path else None,
                "path": self._path or None,
                "actions": len(self._actions),
                "duration_seconds": round(self._duration, 3),
                "clock_source": self._clock_mode,
                "media_player": (self._media_snapshot.player if self._media_snapshot else None),
                "media_connected": bool(self._media_snapshot and self._media_snapshot.connected),
                "media_state": (self._media_snapshot.state if self._media_snapshot else None),
                "media_path": (self._media_snapshot.media_path if self._media_snapshot else None),
                "media_title": (self._media_snapshot.title if self._media_snapshot else None),
                "media_duration_seconds": (self._media_snapshot.duration_seconds if self._media_snapshot else None),
                "media_rate": (self._media_snapshot.rate if self._media_snapshot else None),
                "media_sample_age_seconds": (None if self._media_snapshot_received_at is None else round(max(0.0, self.clock() - self._media_snapshot_received_at), 3)),
                "media_clock_health": self._media_clock_health,
                "media_raw_position": (self._media_snapshot.raw_position if self._media_snapshot else None),
                "media_raw_duration": (self._media_snapshot.raw_duration if self._media_snapshot else None),
                "media_position_source": (self._media_snapshot.position_source if self._media_snapshot else None),
                "auto_load_note": self._auto_load_note,
            }

    def configure_media(self, *, host: str = "127.0.0.1", vlc_port: int = 8080,
                        vlc_password: str = "", mpc_port: int = 13579,
                        library_dirs: list[str] | tuple[str, ...] = (),
                        auto_load_script: bool = True) -> None:
        with self._lock:
            self._media_host = str(host or "127.0.0.1")
            self._vlc_port = int(vlc_port)
            self._vlc_password = str(vlc_password or "")
            self._mpc_port = int(mpc_port)
            self._script_library_dirs = [str(x).strip() for x in library_dirs if str(x).strip()]
            self._auto_load_script = bool(auto_load_script)

    def media_config(self) -> dict:
        with self._lock:
            return {
                "host": self._media_host,
                "vlc_port": self._vlc_port,
                "mpc_port": self._mpc_port,
                "library_dirs": list(self._script_library_dirs),
                "auto_load_script": self._auto_load_script,
            }

    def request_media_poll(self) -> None:
        with self._lock:
            if self._clock_mode not in (self.CLOCK_AUTO, self.CLOCK_VLC, self.CLOCK_MPC):
                return
            now = self.clock()
            if self._media_poll_inflight or now - self._last_media_poll_at < 0.45:
                return
            self._media_poll_inflight = True
            self._last_media_poll_at = now
            mode = self._clock_mode
            host = self._media_host
            vlc_port = self._vlc_port
            password = self._vlc_password
            mpc_port = self._mpc_port
        threading.Thread(target=self._media_poll_worker,
                         args=(mode, host, vlc_port, password, mpc_port),
                         name="VectorTimelineMediaClock", daemon=True).start()

    def _media_poll_worker(self, mode: str, host: str, vlc_port: int, password: str, mpc_port: int) -> None:
        try:
            if mode == self.CLOCK_VLC:
                snap = poll_vlc(host, vlc_port, password)
            elif mode == self.CLOCK_MPC:
                snap = poll_mpc(host, mpc_port)
            else:
                vlc = poll_vlc(host, vlc_port, password)
                snap = vlc if vlc.connected else poll_mpc(host, mpc_port)
            auto_candidate = None
            with self._lock:
                received_at = self.clock()
                state = str(snap.state or "").strip().lower()
                pos = snap.position_seconds
                if not snap.connected or pos is None:
                    self._media_clock_health = "disconnected" if not snap.connected else "no-position"
                    self._media_last_position = None
                    self._media_progress_changed_at = None
                elif state in {"playing", "play"}:
                    if self._media_last_position is None or abs(float(pos) - self._media_last_position) >= 0.02:
                        self._media_clock_health = "live"
                        self._media_progress_changed_at = received_at
                    elif self._media_progress_changed_at is None:
                        self._media_progress_changed_at = received_at
                        self._media_clock_health = "checking"
                    elif received_at - self._media_progress_changed_at >= 2.0:
                        self._media_clock_health = "stale"
                    else:
                        self._media_clock_health = "checking"
                    self._media_last_position = float(pos)
                else:
                    self._media_clock_health = "paused" if state in {"paused", "pause"} else "idle"
                    self._media_last_position = float(pos)
                    self._media_progress_changed_at = received_at
                self._media_snapshot = snap
                self._media_snapshot_received_at = received_at
                self._last_media_poll_at = received_at
                if snap.connected and snap.media_path:
                    self._last_media_path = snap.media_path
                    should_resolve = (self._auto_load_script and
                                      snap.media_path != self._last_auto_loaded_for_media)
                    libraries = list(self._script_library_dirs)
                else:
                    should_resolve = False
                    libraries = []
            if should_resolve:
                auto_candidate = find_matching_funscript(snap.media_path, libraries)
                if auto_candidate:
                    try:
                        self.load(auto_candidate)
                        with self._lock:
                            self._last_auto_loaded_for_media = snap.media_path
                            self._auto_load_note = f"auto-loaded {os.path.basename(auto_candidate)}"
                    except Exception as exc:
                        with self._lock:
                            self._auto_load_note = f"auto-load failed: {exc}"
                else:
                    with self._lock:
                        self._last_auto_loaded_for_media = snap.media_path
                        self._auto_load_note = "no matching funscript found"
        finally:
            with self._lock:
                self._media_poll_inflight = False

    def set_clock_mode(self, mode: str) -> None:
        if mode not in (self.CLOCK_AUTO, self.CLOCK_VLC, self.CLOCK_MPC, self.CLOCK_MFP, self.CLOCK_MANUAL):
            raise ValueError("unknown timeline clock source")
        with self._lock:
            current = self.position_seconds()
            self._clock_mode = mode
            if mode == self.CLOCK_MANUAL:
                self._manual_position = current or 0.0
                self._manual_anchor_position = self._manual_position
                self._manual_anchor_clock = self.clock()
                self._manual_playing = False

    def manual_seek(self, seconds: float) -> float:
        with self._lock:
            value = min(self._duration, max(0.0, float(seconds))) if self._actions else 0.0
            self._manual_position = value
            self._manual_anchor_position = value
            self._manual_anchor_clock = self.clock()
            return value

    def manual_play(self) -> None:
        with self._lock:
            if not self._actions:
                return
            current = self._manual_current_locked()
            self._manual_anchor_position = current
            self._manual_anchor_clock = self.clock()
            self._manual_playing = True

    def manual_pause(self) -> None:
        with self._lock:
            self._manual_position = self._manual_current_locked()
            self._manual_anchor_position = self._manual_position
            self._manual_anchor_clock = self.clock()
            self._manual_playing = False

    def _manual_current_locked(self) -> float:
        if not self._manual_playing:
            return self._manual_position
        pos = self._manual_anchor_position + max(0.0, self.clock() - self._manual_anchor_clock)
        if pos >= self._duration:
            self._manual_position = self._duration
            self._manual_playing = False
            return self._duration
        return pos

    def observe_live(self, value: float, received_at: float | None = None) -> None:
        now = self.clock() if received_at is None else float(received_at)
        with self._lock:
            if not self._actions:
                return
            # Keep a tiny MFP/L0 history even in direct-clock mode. It is normally
            # dormant, but gives Auto mode a safe fallback if a player claims to be
            # playing while its web clock is frozen.
            if now - self._last_live_kept < 0.09:
                return
            self._last_live_kept = now
            self._live.append((now, min(1.0, max(0.0, float(value)))))
            while self._live and self._live[0][0] < now - 4.0:
                self._live.popleft()
            should_match = (self._clock_mode == self.CLOCK_MFP or
                            (self._clock_mode == self.CLOCK_AUTO and self._media_clock_health == "stale"))
            if should_match and now - self._match_updated_at >= 0.45 and len(self._live) >= 8:
                self._match_updated_at = now
                self._match_locked(now)

    def _interp_locked(self, seconds: float) -> float:
        if not self._actions:
            return 0.5
        if seconds <= self._actions[0].at:
            return self._actions[0].pos
        if seconds >= self._duration:
            return self._actions[-1].pos
        idx = bisect_right(self._times, seconds)
        a = self._actions[idx - 1]
        b = self._actions[idx]
        span = max(1e-9, b.at - a.at)
        p = (seconds - a.at) / span
        return a.pos + (b.pos - a.pos) * p

    def _match_locked(self, now: float) -> None:
        samples = list(self._live)
        if len(samples) < 8:
            return
        recent = samples[-24:]
        rel = [(t - recent[-1][0], p) for t, p in recent]

        if self._match_position is None:
            step = 0.50
            start, end = 0.0, self._duration
        else:
            step = 0.05
            start = max(0.0, self._match_position - 5.0)
            end = min(self._duration, self._match_position + 5.0)

        best_t: float | None = None
        best_err = math.inf
        candidate = start
        while candidate <= end + 1e-9:
            err = 0.0
            for dt, observed in rel:
                expected = self._interp_locked(candidate + dt)
                diff = expected - observed
                err += diff * diff
            err /= len(rel)
            if err < best_err:
                best_err, best_t = err, candidate
            candidate += step

        if best_t is None:
            return
        # Reject very poor matches.  RMSE 0.22 still permits ordinary sampling/noise,
        # but prevents confident timeline claims when the loaded script is unrelated.
        rmse = math.sqrt(best_err)
        if rmse > 0.22:
            self._match_score = max(0.0, 1.0 - rmse / 0.5)
            return
        if self._match_position is None:
            self._match_position = best_t
        else:
            # Light smoothing prevents clock chatter while still tracking seeks quickly.
            delta = best_t - self._match_position
            self._match_position += delta * (0.75 if abs(delta) < 1.0 else 1.0)
        self._match_score = max(0.0, min(1.0, 1.0 - rmse / 0.22))

    def sample_position(self, seconds: float) -> float | None:
        """Return authored L0 at an arbitrary script time without changing clock state."""
        with self._lock:
            if not self._actions:
                return None
            return self._interp_locked(min(self._duration, max(0.0, float(seconds))))

    def position_seconds(self) -> float | None:
        # Playback position is extrapolated between authoritative player polls.
        # The Vector app refresh loop keeps those polls alive in direct-clock mode.
        with self._lock:
            if not self._actions:
                return None
            if self._clock_mode == self.CLOCK_MANUAL:
                return self._manual_current_locked()
            if self._clock_mode in (self.CLOCK_AUTO, self.CLOCK_VLC, self.CLOCK_MPC):
                snap = self._media_snapshot
                if self._clock_mode == self.CLOCK_AUTO and self._media_clock_health == "stale" and self._match_position is not None:
                    return self._match_position
                if snap and snap.connected and snap.position_seconds is not None:
                    pos = float(snap.position_seconds)
                    state = str(snap.state or '').strip().lower()
                    if state in {'playing', 'play'} and self._media_snapshot_received_at is not None:
                        elapsed = max(0.0, self.clock() - self._media_snapshot_received_at)
                        pos += elapsed * max(0.0, float(snap.rate or 1.0))
                    if snap.duration_seconds is not None:
                        pos = min(float(snap.duration_seconds), pos)
                    return pos
                return None
            return self._match_position

    @staticmethod
    def _band(score: float) -> str:
        if score < 25.0:
            return "relaxing"
        if score < 50.0:
            return "moderate"
        if score < 75.0:
            return "challenging"
        return "testing"

    def _window_locked(self, start: float, horizon: float) -> dict:
        end = min(self._duration, start + max(0.05, horizon))
        if end <= start:
            return {"horizon_seconds": 0.0, "activity": "ended", "energy_band": "relaxing"}
        # Sample at 10 Hz plus all authored actions in the window.
        points: list[tuple[float, float]] = []
        t = start
        while t <= end + 1e-9:
            points.append((t, self._interp_locked(t)))
            t += 0.10
        left = bisect_right(self._times, start)
        right = bisect_right(self._times, end)
        for action in self._actions[left:right]:
            points.append((action.at, action.pos))
        points.sort(key=lambda x: x[0])
        dedup: list[tuple[float, float]] = []
        for item in points:
            if dedup and abs(item[0] - dedup[-1][0]) < 1e-8:
                dedup[-1] = item
            else:
                dedup.append(item)
        points = dedup
        positions = [p for _, p in points]
        speeds: list[float] = []
        directions: list[int] = []
        reversal_times: list[float] = []
        prev_dir = 0
        for (ta, pa), (tb, pb) in zip(points, points[1:]):
            dt = max(1e-6, tb - ta)
            v = (pb - pa) / dt
            speeds.append(abs(v))
            direction = 1 if v > 1e-4 else (-1 if v < -1e-4 else 0)
            directions.append(direction)
            if direction and prev_dir and direction != prev_dir:
                reversal_times.append(tb)
            if direction:
                prev_dir = direction
        local_min = min(positions)
        local_max = max(positions)
        amplitude = local_max - local_min
        mean_speed = sum(speeds) / len(speeds) if speeds else 0.0
        peak_speed = max(speeds, default=0.0)
        reversal_rate = len(reversal_times) / max(0.1, end - start)
        speed_norm = min(1.0, mean_speed / max(0.05, self._global_peak_speed * 0.45))
        amplitude_norm = min(1.0, amplitude / max(0.10, self._global_mean_amplitude * 3.0))
        reversal_norm = min(1.0, reversal_rate / 2.0)
        energy = 100.0 * (0.55 * speed_norm + 0.30 * amplitude_norm + 0.15 * reversal_norm)
        if mean_speed < 0.02 and amplitude < 0.04:
            activity = "lull"
        elif mean_speed < 0.05 and amplitude < 0.10:
            activity = "hold"
        else:
            activity = "active"
        center = (local_min + local_max) / 2.0
        focus = "lower" if center < 0.34 else ("upper" if center > 0.66 else "middle")
        first_pos, last_pos = positions[0], positions[-1]
        delta = last_pos - first_pos
        direction = "rising" if delta > 0.04 else ("falling" if delta < -0.04 else "mixed/steady")
        return {
            "horizon_seconds": round(end - start, 3),
            "activity": activity,
            "direction": direction,
            "position_range": [round(local_min, 4), round(local_max, 4)],
            "amplitude": round(amplitude, 4),
            "focus_region": focus,
            "mean_speed_per_second": round(mean_speed, 3),
            "peak_speed_per_second": round(peak_speed, 3),
            "reversals": len(reversal_times),
            "reversals_per_second": round(reversal_rate, 3),
            "energy_score": round(energy, 1),
            "energy_band": self._band(energy),
            "first_reversal_seconds": (None if not reversal_times else round(max(0.0, reversal_times[0] - start), 3)),
        }

    def snapshot(self) -> dict:
        with self._lock:
            meta = self.metadata()
            if not self._actions:
                return {**meta, "synced": False}
            pos = self.position_seconds()
            if pos is None:
                return {
                    **meta,
                    "synced": False,
                    "sync_confidence": None if self._match_score is None else round(self._match_score, 3),
                    "note": "timeline loaded; waiting for enough matching live L0 to establish position",
                }
            pos = min(self._duration, max(0.0, pos))
            now = self._window_locked(pos, 1.0)
            near = self._window_locked(pos, 10.0)
            ahead = self._window_locked(pos, 30.0)
            # Compare halves of the 30 s window to give the Director a compact trend.
            first = self._window_locked(pos, min(15.0, max(0.1, self._duration - pos)))
            second_start = min(self._duration, pos + 15.0)
            second = self._window_locked(second_start, 15.0) if second_start < self._duration else first
            delta = float(second.get("energy_score", 0.0)) - float(first.get("energy_score", 0.0))
            trend = "building" if delta > 10.0 else ("easing" if delta < -10.0 else "steady/mixed")
            return {
                **meta,
                "synced": True,
                "position_seconds": round(pos, 3),
                "remaining_seconds": round(max(0.0, self._duration - pos), 3),
                "sync_confidence": (1.0 if self._clock_mode == self.CLOCK_MANUAL or
                                      (self._clock_mode in (self.CLOCK_AUTO, self.CLOCK_VLC, self.CLOCK_MPC) and self._media_clock_health != "stale")
                                      else None if self._match_score is None else round(self._match_score, 3)),
                "clock_authoritative": (self._clock_mode in (self.CLOCK_AUTO, self.CLOCK_VLC, self.CLOCK_MPC) and
                                        self._media_clock_health != "stale"),
                "now": now,
                "next_10_seconds": near,
                "next_30_seconds": {**ahead, "energy_trend": trend},
                "energy_note": "relative authored-script energy derived from position, speed, amplitude and reversals; not physical output intensity",
            }
