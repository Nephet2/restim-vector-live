"""UI-independent input routing and stateful tempo transformation."""
from __future__ import annotations
import threading

class TempoController:
    def __init__(self, timeline):
        self.timeline = timeline
        self._tempo_lock = threading.RLock()
        self._tempo_scale_active = 1.0
        self._tempo_anchor_media = None
        self._tempo_anchor_clock = 0.0
        self._tempo_expires_at = 0.0
        self._tempo_transition_seconds_active = 0.2
        self._tempo_restore_started_at = 0.0
        self._tempo_restore_from = None

    @property
    def scale(self) -> float:
        with self._tempo_lock:
            return self._tempo_scale_active

    def start(self, scale: float, media_pos: float, now: float,
              duration: float, transition: float) -> None:
        with self._tempo_lock:
            self._tempo_scale_active = scale
            self._tempo_anchor_media = float(media_pos)
            self._tempo_anchor_clock = now
            self._tempo_expires_at = now + duration
            self._tempo_transition_seconds_active = min(5.0, max(0.0, float(transition)))
            self._tempo_restore_started_at = 0.0
            self._tempo_restore_from = None

    def restore(self, now: float) -> None:
        raw_pos = self.timeline.position_seconds()
        with self._tempo_lock:
            if self._tempo_scale_active != 1.0 and self._tempo_anchor_media is not None and raw_pos is not None:
                virtual = self._tempo_anchor_media + (float(raw_pos) - self._tempo_anchor_media) * self._tempo_scale_active
                self._tempo_restore_from = self.timeline.sample_position(virtual)
            self._tempo_scale_active = 1.0
            self._tempo_anchor_media = None
            self._tempo_expires_at = 0.0
            self._tempo_restore_started_at = now


    def transform(self, raw_value: float, now: float) -> float:
        raw = min(1.0, max(0.0, float(raw_value)))
        with self._tempo_lock:
            scale = self._tempo_scale_active
            anchor_media = self._tempo_anchor_media
            anchor_clock = self._tempo_anchor_clock
            expires = self._tempo_expires_at
            transition = self._tempo_transition_seconds_active
            restore_started = self._tempo_restore_started_at
            restore_from = self._tempo_restore_from

        if scale != 1.0 and anchor_media is not None:
            media_pos = self.timeline.position_seconds()
            if media_pos is not None:
                virtual_seconds = anchor_media + (float(media_pos) - anchor_media) * scale
                warped = self.timeline.sample_position(virtual_seconds)
                if warped is not None:
                    if expires and now >= expires:
                        with self._tempo_lock:
                            self._tempo_scale_active = 1.0
                            self._tempo_anchor_media = None
                            self._tempo_expires_at = 0.0
                            self._tempo_restore_started_at = now
                            self._tempo_restore_from = float(warped)
                        restore_started = now
                        restore_from = float(warped)
                    else:
                        if transition <= 1e-9:
                            return float(warped)
                        blend = min(1.0, max(0.0, (now - anchor_clock) / transition))
                        return raw + (float(warped) - raw) * blend

        if restore_from is not None and restore_started > 0.0:
            if transition <= 1e-9:
                with self._tempo_lock:
                    self._tempo_restore_from = None
                    self._tempo_restore_started_at = 0.0
                return raw
            blend = min(1.0, max(0.0, (now - restore_started) / transition))
            if blend >= 1.0:
                with self._tempo_lock:
                    self._tempo_restore_from = None
                    self._tempo_restore_started_at = 0.0
                return raw
            return float(restore_from) + (raw - float(restore_from)) * blend
        return raw



class InputPipeline:
    def __init__(self, engine, timeline, generated_motion, tempo):
        self.engine = engine
        self.timeline = timeline
        self.generated_motion = generated_motion
        self.tempo = tempo
        self.latest_authored_l0 = 0.5

    def receive_authored(self, value: float, interval_ms: int, now: float) -> None:
        self.latest_authored_l0 = max(0.0, min(1.0, float(value)))
        # Observe the original signal before any output-side tempo transform.
        self.timeline.observe_live(value, now)
        if not self.generated_motion.active:
            self.engine.receive_l0(self.tempo.transform(value, now), interval_ms, now)

    def receive_generated(self, value: float, interval_ms: int, now: float) -> None:
        self.engine.receive_l0(self.tempo.transform(value, now), interval_ms, now,
                               stroke_bounds=self.generated_motion.stroke_bounds(now))
