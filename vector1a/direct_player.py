"""Player-driven L0 from a locally loaded Funscript."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import socket
import struct
import threading
import time
from urllib.parse import urlsplit

from .media_clock import MediaSnapshot, _file_uri_to_path, find_matching_funscript, local_smb_path, poll_mpc
from .timeline import FunscriptTimeline


MFP = "MultiFunPlayer"
MPC = "MPC-HC"
HERESPHERE = "HereSphere"
DEOVR = "DeoVR"


def vr_snapshot(source, message):
    if not isinstance(message, dict):
        return MediaSnapshot(source, False)
    resource = message.get("path")
    if source == HERESPHERE:
        resource = message.get("resource") or resource
    position, state = message.get("currentTime"), message.get("playerState")
    if not isinstance(resource, str) or not resource.strip() or type(state) is not int:
        return MediaSnapshot(source, False)
    if type(position) not in (int, float) or not math.isfinite(position) or position < 0:
        return MediaSnapshot(source, False)
    rate = message.get("playbackSpeed", 1)
    if type(rate) not in (int, float) or not math.isfinite(rate) or rate <= 0:
        rate = 1.0
    if source == DEOVR and state not in (0, 1):
        return MediaSnapshot(source, False)
    duration = message.get("duration") if source == DEOVR else None
    if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
        duration = None
    return MediaSnapshot(source, True, "playing" if state == 0 else "paused",
                         position_seconds=position, duration_seconds=duration,
                         rate=rate, media_path=resource)


@dataclass(frozen=True)
class PlayerFrame:
    snapshot: MediaSnapshot
    received: float
    script: FunscriptTimeline | None
    script_name: str
    revision: int


class DirectPlayerInput:
    def __init__(self, source, host, port, libraries=(), *, clock=time.monotonic):
        self.source, self.host, self.port = source, host, port
        self.libraries = tuple(libraries)
        self.clock = clock
        self.frame = None
        self._manual_lock = threading.Lock()
        self._manual = None
        self._stop = threading.Event()
        self._revision = 0
        self._script_resource = None
        self._script_retry_at = 0.0
        self._script = None
        self._script_name = ""
        self._max_age = .75 if source == MPC else 1.6

    def start(self):
        threading.Thread(target=self._run, name=f"Vector {self.source} input", daemon=True).start()

    def close(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                if self.source == MPC:
                    self._accept(poll_mpc(self.host, self.port))
                else:
                    self._read_vr_player()
                    self.frame = None
            except (OSError, ValueError, OverflowError):
                self.frame = None
            self._stop.wait(.15 if self.source == MPC else .5)

    def _read_vr_player(self):
        with socket.create_connection((self.host, self.port), timeout=.75) as connection:
            connection.settimeout(.20)
            pending = bytearray()
            next_ping = 0.0
            while not self._stop.is_set():
                now = self.clock()
                if now >= next_ping:
                    connection.sendall(bytes(4))
                    next_ping = now + 1.0
                try:
                    block = connection.recv(8192)
                except socket.timeout:
                    continue
                if not block:
                    return
                pending.extend(block)
                while len(pending) >= 4:
                    length, = struct.unpack_from("<i", pending)
                    if not 0 <= length <= 65536:
                        raise ValueError("Invalid VR player packet length")
                    if len(pending) < 4 + length:
                        break
                    if length:
                        message = json.loads(bytes(pending[4:4 + length]))
                        self._accept(vr_snapshot(self.source, message))
                    elif self.source == DEOVR:
                        self.frame = None
                    del pending[:4 + length]

    def _load_script(self, resource):
        resource = resource.strip().removeprefix('"').removesuffix('"')
        if self.source == DEOVR and resource.lower().startswith(("http://", "https://")):
            host = (urlsplit(resource).hostname or "").rstrip(".")
            if host == "sexlikereal.com" or host.endswith(".sexlikereal.com"):
                return None, "SLR stream: select MultiFunPlayer, or load a local funscript"
            return None, "Online video; load a local funscript"
        if resource.lower().startswith("smb://"):
            path = local_smb_path(resource)
        else:
            path = Path(_file_uri_to_path(resource) or resource)
        if path is None or not path.is_absolute():
            return None, "Video path is unavailable on this PC"
        match = find_matching_funscript(str(path), self.libraries)
        if match is None:
            return None, "No matching funscript"
        script = FunscriptTimeline()
        script.load(match)
        return script, Path(match).name

    def load_manual(self, path, resource):
        script = FunscriptTimeline()
        script.load(path)
        with self._manual_lock:
            if self.frame is None or self.frame.snapshot.media_path != resource:
                raise ValueError("The video changed before the script could be loaded.")
            self._manual = (script, Path(path).name)

    def _accept(self, snapshot):
        now = self.clock()
        position = snapshot.position_seconds
        if (not snapshot.connected or not snapshot.media_path or position is None
                or not math.isfinite(position) or position < 0):
            self.frame = None
            return
        previous = self.frame
        with self._manual_lock:
            if snapshot.media_path != self._script_resource:
                self.frame = None
                self._manual = None
                self._script_resource = snapshot.media_path
                self._script = None
                self._script_retry_at = now
            manual = self._manual is not None

        if not manual and self._script is None and now >= self._script_retry_at:
            try:
                self._script, self._script_name = self._load_script(snapshot.media_path)
            except (OSError, ValueError, OverflowError):
                self._script, self._script_name = None, "Could not load matching funscript"
            self._script_retry_at = now + 1.5

        if previous is None or snapshot.media_path != previous.snapshot.media_path:
            self._revision += 1
        elif snapshot.state == "playing" and previous.snapshot.state == "playing":
            old = previous.snapshot
            if position == old.position_seconds and previous.script is self._script:
                # Repeated frozen timestamps must not renew the output lease.
                return
            elapsed = now - previous.received
            expected = old.position_seconds + elapsed * old.rate
            max_age = 1.6 if snapshot.position_source == "positionstring" else self._max_age
            if elapsed > max_age or abs(position - expected) > .8:
                self._revision += 1
        elif snapshot.state != previous.snapshot.state:
            self._revision += 1
        self.frame = PlayerFrame(snapshot, now, self._script, self._script_name, self._revision)

    def _clock_frame(self, now):
        with self._manual_lock:
            frame, manual = self.frame, self._manual
        max_age = 1.6 if frame and frame.snapshot.position_source == "positionstring" else self._max_age
        stale = frame is not None and now - frame.received > max_age
        return frame, manual, stale

    def session_status(self, now):
        frame, manual, stale = self._clock_frame(now)
        if frame is None:
            return "Waiting for player clock", "No funscript"
        script, name = manual if manual is not None else (frame.script, frame.script_name)
        clock = "Stale player clock" if stale else (frame.snapshot.state or "Clock available").capitalize()
        return clock, name if script is not None else (name or "No matching funscript")

    def _playback(self, now):
        frame, manual, stale = self._clock_frame(now)
        if frame is None or stale:
            return None, "Waiting for video clock"
        script, name = manual if manual is not None else (frame.script, frame.script_name)
        if script is None:
            return None, name
        return (frame, script, name, (frame.revision, manual)), None

    def _live_position(self, frame, now):
        snap = frame.snapshot
        if snap.state != "playing" or not math.isfinite(snap.rate) or snap.rate <= 0:
            return None
        position = snap.position_seconds + max(0.0, now - frame.received) * snap.rate
        if snap.duration_seconds and position >= snap.duration_seconds:
            return None
        return position

    def sample(self, now, interpolation, lead=0.0):
        value, revision, message, _ = self.sample_frame(now, interpolation, lead)
        return value, revision, message

    def sample_frame(self, now, interpolation, lead=0.0, *, include_keyframe_arc=False):
        playback, message = self._playback(now)
        if playback is None:
            return None, None, message, None
        frame, script, name, revision = playback
        position = self._live_position(frame, now)
        if position is None:
            return None, None, f"{frame.snapshot.state.title()}: {name}", None
        script_lead = lead * frame.snapshot.rate
        value = script.sample_playing_position(position, interpolation, script_lead)
        if value is None:
            return None, None, f"Outside script: {name}", None
        arc = script.sample_keyframe_arc(position + script_lead) if include_keyframe_arc else None
        return value, revision, f"Playing: {name}", arc

    def follow_transport(self, now, interpolation):
        playback, _ = self._playback(now)
        if playback is None:
            return None
        frame, script, _, revision = playback
        position = self._live_position(frame, now)
        value = None if position is None else script.sample_playing_position(position, interpolation, 0.0)
        return {
            "playing": value is not None, "position": frame.snapshot.position_seconds if position is None else position,
            "received_at": now, "source": (self, revision), "label": self.source,
            "precise": frame.snapshot.position_source != "positionstring", "rate": frame.snapshot.rate,
            "l0": value,
        }

    def handy_transport(self, now, interpolation):
        playback, _ = self._playback(now)
        if playback is None:
            return None
        frame, script, _, revision = playback
        position = self._live_position(frame, now)
        if position is None:
            return None
        return {"playing": True, "position": position, "received_at": now,
                "source": (self, revision), "label": self.source,
                "precise": frame.snapshot.position_source != "positionstring",
                "rate": frame.snapshot.rate,
                "sample": lambda seconds: script.sample_position(seconds, interpolation),
                "sample_gradient": lambda seconds: script.sample_position(seconds, "Gradient"),
                "action_times": script.action_times}
