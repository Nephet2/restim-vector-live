"""One VacuGlide output owner for script, Funscript, blend and manual speed."""
from bisect import bisect_right
from collections import deque
from concurrent.futures import Future
from math import isfinite
from time import monotonic
from uuid import uuid4

from .settings import settings_path
from .vacuglide_script import Preview, Script
from .vacuglide_mfp import MfpFollower, TimedL0
from .vacuglide_playback import LivePlayback


MODES = {"script": "Script", "mfp": "Funscript", "blend": "Blend", "manual": "Speed slider"}
SCRIPT_MODES = ("script", "blend")
PLAYHEAD_MODES = (*SCRIPT_MODES, "mfp")
MFP_MODES = ("mfp", "blend")
VACUUM_INTERVALS = {"Off": None, "Low": 120, "Medium": 60, "High": 20}


class VacuGlideControl:
    UPDATE_INTERVAL = LivePlayback.UPDATE_INTERVAL
    HANDOFF_RATE = 20.0
    MOTION_DEADBAND = MfpFollower.SPEED_DEADBAND
    SCRIPT_TRIAL_SECONDS = 30

    def __init__(self, output, transport, clock=monotonic):
        self.output = output
        self.transport = transport
        self._mapped_intensity = None
        self.clock = clock
        self.motion = TimedL0()
        self.mode = "script"
        self.playing = False
        self.position_ms = 0
        self.trim = output.state()["director_max_speed_percent"]
        self.manual_speed = 0.0
        self.preview = None
        self.loaded_preview = None
        self.catalog_folder = settings_path().parent / "VacuglideScripts"
        self.catalog_load_guard = None
        self.catalog_selection = None
        self.selected_script_id = None
        self.automation = "Off"
        self.detail = "Paused"
        self.error = ""
        self.target = 0.0
        self.envelope = None
        self._lease = None
        self._pending = None
        self._transport = None
        self._clear_valves()
        self._handoff_until = 0.0
        self._slew = False
        self._next_update = 0.0
        self._last_sent = 0.0
        self._last_applied_trim = self.trim
        self._resume_after = -1
        self._script_resume = (None, 0)
        self._seeked_while_paused = False
        self._trial_deadline = None
        self._timed_pause = None
        self._return_pending = False
        self._events = deque(maxlen=12)
        self._event_session = uuid4().hex
        self._event_number = 0

    def _clear_valves(self):
        self._pulse = None
        self._auto_at = None

    @property
    def stopping(self):
        return self._pending is not None and self._pending[0] == "stop"

    @property
    def timed_pause_active(self):
        return self._timed_pause is not None

    def set_trim(self, speed):
        if not isfinite(speed) or not 0 <= speed <= 100:
            raise ValueError("Enter a trim between 0% and 100%.")
        state = self.output.state()
        low = state["director_min_speed_percent"]
        high = state["director_max_speed_percent"]
        self.trim = min(high, max(low, speed))

    def save_range(self, low, high):
        self.output.save_director_range(low, high)
        self.set_trim(self.trim)

    def _director_reply(self, **details):
        future = Future()
        future.set_result((200, {"ok": True, **self.director_state(), **details}))
        return future

    def _director_start(self, speed):
        if self.playing and not self.output.owns_timeline(self._lease):
            raise ValueError("Vector is finishing a stop. Try Start again after it confirms.")
        if speed is None:
            self.start(self.loaded_preview)
            return self._director_reply()
        if type(speed) not in (int, float) or not 0 < speed <= 100:
            raise ValueError("Speed must be above 0% and at most 100%.")
        if self.playing and self.mode != "manual":
            self.set_trim(speed)
            return self._director_reply()
        state = self.output.state()
        cap = state["max_speed_percent"]
        if cap is None:
            raise ValueError("Connect VacuGlide in Vector before starting it.")
        target = min(cap, state["director_max_speed_percent"], max(state["director_min_speed_percent"], speed))
        if target == 0:
            raise ValueError("The current Director limit allows only 0% speed.")
        self._reserve()
        self.select("manual", self.loaded_preview)
        self.manual_speed = target
        self.start(self.loaded_preview)
        return self._director_reply()

    def _approved_scripts(self):
        for path in sorted(self.catalog_folder.glob("*.json"), key=lambda entry: entry.name.casefold()):
            try:
                if path.is_symlink() or path.resolve().parent != self.catalog_folder.resolve():
                    continue
                script = Script.load(path)
                if not script.director_approved:
                    continue
                self._validate("script", Preview(script))
            except (OSError, ValueError):
                continue
            yield path, script

    def _catalog(self):
        catalog = []
        for path, script in self._approved_scripts():
            average, peak = script.speed_stats()
            catalog.append({"id": path.name, "name": script.name, "description": script.description,
                            "average_speed": average, "peak_speed": peak, "duration_ms": script.duration_ms})
        return catalog

    def _load_approved_script(self, script_id):
        if self.catalog_load_guard is not None and not self.catalog_load_guard():
            raise ValueError("Save the open VacuGlide script before Gwendolyn selects another.")
        for path, script in self._approved_scripts():
            if path.name == script_id:
                if self.selected_script_id == script_id and self.loaded_preview is not None:
                    self.select("script", self.loaded_preview)
                else:
                    preview = Preview(script)
                    if self.playing and self.mode == "script":
                        self.replace_script(preview)
                    else:
                        self.select("script", preview)
                        self.update_loaded_preview(preview)
                    self.selected_script_id = script_id
                    self.catalog_selection = (path, script, preview)
                return self._director_reply(script_name=script.name)
        raise ValueError("That script is unavailable or has not been approved for Gwendolyn.")

    def director_command(self, action, speed, *, script_id=None, expected_revision=None):
        if expected_revision is not None:
            state = self.output.state()
            if type(expected_revision) is not int or expected_revision != state["stop_revision"]:
                raise ValueError("VacuGlide was paused or stopped by the operator.")
            if not self.playing and action not in ("catalog", "start"):
                raise ValueError("VacuGlide playback is paused.")
        if action == "catalog":
            return self._director_reply(scripts=self._catalog())
        if action == "load_script":
            return self._load_approved_script(script_id)
        if action == "conducted_manual":
            if not self.playing or not self.output.owns_timeline(self._lease):
                raise ValueError("Start playback before changing the conducted source.")
            self.manual_speed = self.trim
            self.select("manual", self.loaded_preview)
            return self._director_reply()
        if isinstance(action, str) and action.startswith("follow_"):
            self.select(action.removeprefix("follow_"), self.loaded_preview)
            return self._director_reply()
        if action == "script_trial":
            self._start_script_trial()
            return self._director_reply()
        if action == "timed_pause":
            if not self.playing or not self.output.owns_timeline(self._lease):
                raise ValueError("Start VacuGlide playback before setting a timed pause.")
            future = self.pause("Timed pause")
            self._timed_pause = {
                "revision": self.output.state()["stop_revision"],
                "deadline": None,
                "preview": self.loaded_preview,
            }
            return future
        if action in ("trim", "trim_delta", "conducted_trim"):
            if (not self.playing or (self.mode == "manual" and action != "conducted_trim")
                    or not self.output.owns_timeline(self._lease)):
                raise ValueError("Trim applies during Follow Script, MFP, or Blend playback.")
            if type(speed) not in (int, float) or not isfinite(speed) or not -100 <= speed <= 100:
                raise ValueError("Enter a trim percentage between 0 and 100, or a signed adjustment.")
            previous = self.trim
            self.set_trim(min(100, max(0, previous + speed)) if action == "trim_delta" else speed)
            if self.mode == "manual":
                self.manual_speed = self.trim
            return self._director_reply(previous_trim_percent=previous)
        if action == "stop" or (action in ("start", "speed") and type(speed) in (int, float) and speed == 0):
            return self.pause("Paused by Gwendolyn")
        if action == "start":
            return self._director_start(speed)
        if self.playing and self.mode != "manual" and action == "speed":
            if type(speed) not in (int, float) or not 0 < speed <= 100:
                raise ValueError("Speed must be between 0% and 100%.")
            self.set_trim(speed)
            future = Future()
            future.set_result((200, {"ok": True, **self.output.state(), "trim_percent": self.trim}))
            return future
        return self.output.director_command(action, speed)

    def _resume_timed_pause(self):
        plan = self._timed_pause
        if plan is None:
            return
        state = self.output.state()
        if (state["stop_revision"] != plan["revision"] or state["state"] != "stopped"
                or state.get("stop_verified") is not True):
            self._timed_pause = None
            return
        if plan["deadline"] is None:
            plan["deadline"] = self.clock() + self.SCRIPT_TRIAL_SECONDS
            return
        if self.clock() < plan["deadline"]:
            return
        self._timed_pause = None
        if self.mode in MFP_MODES and not self._mfp_ready():
            self.detail = "Funscript motion unavailable after timed pause"
            self._record_event("timed_pause_ended", "Funscript has no live timed motion")
            return
        try:
            self.start(plan["preview"])
        except ValueError as exc:
            self.detail = str(exc)
            self._record_event("timed_pause_ended", self.detail)
        else:
            self._record_event("timed_pause_ended", "Playback source restored")

    def _record_event(self, kind, reason=None):
        self._event_number += 1
        self._events.append({"id": f"{self._event_session}:{self._event_number}",
                             "kind": kind, "reason": reason})

    def _cancel_trial(self, reason):
        if self._trial_deadline is not None or self._return_pending:
            self._trial_deadline = None
            self._return_pending = False
            self._record_event("trial_cancelled", reason)

    def _mfp_ready(self):
        transport = self.mapped_source() if self.mapped_source else self.transport()
        level = transport.get("l0") if self.mapped_source and transport else self.motion.level(self.clock())
        cap = self.output.state()["max_speed_percent"]
        peak = self.trim if cap is None else min(cap, self.trim)
        return bool(transport and transport["playing"] and self._mfp_target(level, peak))

    def _start_script_trial(self):
        if (not self.playing or self.mode != "mfp" or not self.output.owns_timeline(self._lease)
                or not self._mfp_ready()):
            raise ValueError("Start Follow Funscript with live motion before trying the script.")
        if self.loaded_preview is None:
            raise ValueError("Open a VacuGlide script before starting the trial.")
        self.select("script", self.loaded_preview)
        self._trial_deadline = self.clock() + self.SCRIPT_TRIAL_SECONDS
        self._record_event("trial_started")

    def _advance_trial(self, now):
        if self._trial_deadline is not None and now >= self._trial_deadline:
            self._trial_deadline = None
            if not self._mfp_ready():
                self._record_event("return_unavailable", "Funscript has no live timed motion")
                self.pause("Funscript motion unavailable after script trial")
                return False
            self.select("mfp", self.loaded_preview)
            self._return_pending = True
            return True
        if self._return_pending:
            if not self._mfp_ready():
                self._return_pending = False
                self._record_event("return_unavailable", "Funscript has no live timed motion")
                self.pause("Funscript motion unavailable after script trial")
                return False
        return True

    def _confirm_mfp_return(self):
        if self._return_pending:
            self._return_pending = False
            self._record_event("mfp_resumed")

    @property
    def mapped_source(self):
        source = self._mapped_intensity
        return source.frame if source is not None else None

    @property
    def source_name(self):
        if self._mapped_intensity is not None:
            return self._mapped_intensity.name
        return MODES[self.mode]

    def select_mapped_intensity(self, source):
        if self._mapped_intensity is source:
            return
        if self.playing or self.stopping:
            raise ValueError("Pause VacuGlide and wait for it to stop before selecting mapped intensity.")
        self.select("mfp", self.loaded_preview)
        self._timed_pause = None
        self._mapped_intensity = source
        self.detail = "Mapped intensity selected"

    def validate_selected(self):
        self._validate(self.mode, self.loaded_preview, mapped_source=self.mapped_source)

    def resume_selected(self):
        self.start(self.loaded_preview)

    def _validate(self, mode, preview, *, mapped_source=None):
        if mode == "script":
            LivePlayback.validate(preview, True)
        elif mode == "blend":
            LivePlayback.validate(preview, True, require_speed=False)
        if mode in MFP_MODES and (mapped_source() if mapped_source else self.transport()) is None:
            raise ValueError("Connect the playback input and load its funscript. For MFP, enable the MPC-HC timeline clock.")

    def _playhead(self, now):
        elapsed_ms = self._start_position_ms + max(0, int((now - self._began) * 1000))
        return divmod(elapsed_ms, self.preview.duration_ms)

    def _set_playhead(self, position, now, *, skip_interrupted_valve=False):
        self.position_ms = position
        self._began = now
        self._start_position_ms = position
        self._cycle = 0
        self._resume_after = position if skip_interrupted_valve and position > 0 else -1

    def _save_playhead(self, now):
        if self.playing and self.mode in SCRIPT_MODES:
            _, self.position_ms = self._playhead(now)
        if self.mode == "script":
            self._script_resume = (self.preview, self.position_ms)

    def _script_position(self, preview):
        saved_preview, position = self._script_resume
        return position if saved_preview is preview else 0

    def _pending_script_position(self, preview, now):
        if self.mode == "script" and self.playing and preview is self.preview:
            return self._playhead(now)[1]
        return self._script_position(preview)

    @staticmethod
    def _script_target(preview, position, peak):
        if preview is None:
            return 0.0
        authored_peak = max((event.speed_percent for event in preview.tracks["speed"]), default=0)
        if not authored_peak:
            return 0.0
        speed = preview.at(position, ceiling=100)[0]
        return speed * peak / authored_peak

    @staticmethod
    def _mfp_target(envelope, peak):
        target = (envelope or 0) * peak
        return target if target >= 1 else 0.0

    def director_state(self, state=None):
        if state is None:
            state = self.output.state()
        now = self.clock()
        transport = self.mapped_source() if self.mapped_source else self.transport()
        preview = self.loaded_preview
        position = self._pending_script_position(preview, now)
        cap = state["max_speed_percent"]
        cap = 100 if cap is None else cap
        peak = min(cap, self.trim)
        envelope = ((transport.get("l0") if self.mapped_source else self.motion.level(now))
                    if transport is not None and transport["playing"] else None)
        targets = {
            "script": self._script_target(preview, position, peak),
            "mfp": self._mfp_target(envelope, peak),
            "manual": min(cap, self.manual_speed),
        }
        selected = "mfp" if self.mode == "blend" else self.mode
        if self.playing and self.mode in MFP_MODES and envelope in (None, 0.0) and now < self._handoff_until:
            if transport is not None and transport["playing"] and peak > 0:
                targets["mfp"] = state["confirmed_speed_percent"] or self._last_sent
        return {**state, "mode": self.mode, "playing": self.playing,
                "active_speed_source": selected if self.playing else None,
                "targets_percent": {source: round(speed, 1) for source, speed in targets.items()},
                "script_position_ms": position if preview is not None else None,
                "mfp_averaging_seconds": self.motion.speed_window,
                "manual_speed_percent": self.manual_speed,
                "script_id": self.selected_script_id,
                "timed_pause_active": self.timed_pause_active,
                "trim_percent": self.trim,
                "effective_trim_percent": peak,
                "mfp_motion_ready": self._mfp_ready(),
                "script_trial_seconds_remaining": (None if self._trial_deadline is None else
                                                   round(max(0, self._trial_deadline - now), 1)),
                "playback_events": list(self._events)}

    def select(self, mode, preview):
        if mode not in MODES:
            raise ValueError("Unknown VacuGlide source.")
        if mode == self.mode and self._mapped_intensity is None:
            return
        now = self.clock()
        if self.playing:
            self._validate(mode, preview)
        self._pause_mapped_intensity()
        self._mapped_intensity = None
        self._timed_pause = None
        self._cancel_trial("Mode changed")
        self._save_playhead(now)
        if mode == "mfp" and self.mode == "blend" and self.preview is preview:
            self._script_resume = (preview, self.position_ms)
        self.loaded_preview = preview
        self.mode = mode
        self.preview = preview if mode in SCRIPT_MODES else None
        position = self._script_position(preview) if mode == "script" else 0
        self._set_playhead(position, now, skip_interrupted_valve=True)
        self._seeked_while_paused = False
        if self.playing:
            self._handoff_until = now + TimedL0.IDLE_TIMEOUT
            self._slew = True
            self._pulse = None
            self.detail = f"Switching to {MODES[mode]}"

    def replace_script(self, preview):
        """Start a validated replacement on the current output lease."""
        if not self.playing or self.mode != "script":
            raise ValueError("Follow Script must be playing to replace the live script.")
        self._validate("script", preview)
        self._cancel_trial("Script replaced")
        self.preview = self.loaded_preview = preview
        self._script_resume = (preview, 0)
        self._set_playhead(0, self.clock())

    def update_loaded_preview(self, preview, script_id=None):
        if self.loaded_preview is not preview:
            self._timed_pause = None
        self.loaded_preview = preview
        self.selected_script_id = script_id

    def seek(self, preview, position_ms):
        self._timed_pause = None
        position = min(preview.duration_ms - 1, max(0, position_ms))
        if self.mode == "mfp":
            self._script_resume = (preview, position)
            return position
        if self.mode not in SCRIPT_MODES or (self.playing and preview is not self.preview):
            raise ValueError("The displayed script is not the current playback source.")
        self.preview = preview
        self._set_playhead(position, self.clock())
        self._seeked_while_paused = not self.playing
        if self.mode == "script":
            self._script_resume = (preview, position)
        return position

    def _reserve(self):
        if self.stopping:
            raise ValueError("Wait for the current pause to finish.")
        if self._lease is None:
            self._lease, _ = self.output.reserve_timeline(valves=True, source="VacuGlide Interface")

    def start(self, preview):
        if self.playing:
            return
        self._validate(self.mode, preview, mapped_source=self.mapped_source)
        self._reserve()
        if self._mapped_intensity is not None:
            self._mapped_intensity.start()
        self._timed_pause = None
        if self.mode == "script":
            position = self._script_position(preview)
        else:
            position = self.position_ms if self.mode == "blend" and self.preview is preview else 0
        self.preview = self.loaded_preview = preview
        now = self.clock()
        self._set_playhead(position, now, skip_interrupted_valve=not self._seeked_while_paused)
        self._seeked_while_paused = False
        self._next_update = now
        self._handoff_until = 0
        self._slew = False
        self._last_sent = 0
        self.playing = True
        self.error = ""
        self._schedule_auto(now)

    def _pause_mapped_intensity(self):
        if self._mapped_intensity is not None:
            self._mapped_intensity.pause()

    def pause(self, reason="Paused", *, release=False):
        self._pause_mapped_intensity()
        self._timed_pause = None
        if self.playing:
            self._cancel_trial(reason)
            self._record_event("playback_ended", reason)
        self._save_playhead(self.clock())
        self.playing = False
        self.target = 0
        self.detail = reason
        self._clear_valves()
        self._lease = None
        future = self.output.stop(release=release)
        self._pending = ("stop", future)
        return future

    def stroke(self, kind):
        if kind not in ("minus", "plus"):
            raise ValueError("Choose Stroke Minus or Stroke Plus.")
        self._reserve()
        self._timed_pause = None
        self.error = ""
        self._pulse = (kind, None)

    def set_automation(self, setting):
        self.automation = setting
        self._schedule_auto(self.clock())

    def _schedule_auto(self, now):
        interval = VACUUM_INTERVALS[self.automation]
        self._auto_at = now + interval if interval is not None else None

    def _media(self):
        if self.mapped_source is not None:
            self.motion.accept(False)
            self._transport = self.mapped_source()
            return bool(self._transport and self._transport["playing"])
        current = self.transport()
        if current is None or not current["playing"]:
            self.motion.accept(False)
        else:
            previous = self._transport
            if previous is not None and (previous["source"] != current["source"]
                                         or MfpFollower._jumped(previous, current)):
                self.motion.accept(False)
                self._handoff_until = 0
                previous = None
            self.motion.accept(True)
            if current.get("l0") is not None:
                elapsed = (current["received_at"] - previous["received_at"]
                           if previous is not None and previous["playing"] else 0)
                interval = round(elapsed * 1000) if 0 < elapsed < TimedL0.IDLE_TIMEOUT else 0
                self.motion.receive(current["l0"], interval, current["received_at"])
        self._transport = current
        return current is not None and current["playing"]

    def _read_pending(self):
        if self._pending is None:
            return True
        action, future = self._pending
        if not future.done():
            return False
        self._pending = None
        try:
            reply = future.result()[1]
        except Exception:
            reply = {}
        if not reply.get("ok"):
            self._timed_pause = None
            self.error = reply.get("error") or "VacuGlide did not confirm the command."
            if action != "stop":
                self.pause("Output error")
            return False
        if action == "speed" and reply.get("state") == "running" and self._mfp_ready():
            self._confirm_mfp_return()
        return True

    def _targets(self, now, media_playing, cap, state):
        self.envelope = ((self._transport or {}).get("l0") if self.mapped_source
                         else self.motion.level(now))
        minus = plus = False
        if self.mode in SCRIPT_MODES:
            cycle, self.position_ms = self._playhead(now)
            if cycle != self._cycle:
                self._resume_after = -1
                self._cycle = cycle
            _, minus, plus = self.preview.at(self.position_ms, ceiling=100)
            if self._resume_after >= 0 and (minus or plus):
                kind = "minus" if minus else "plus"
                start = self.preview.starts[kind][bisect_right(self.preview.starts[kind], self.position_ms) - 1]
                if start <= self._resume_after:
                    minus = plus = False
        peak = min(cap, self.trim)
        if self.mode == "script":
            target = self._script_target(self.preview, self.position_ms, peak)
        elif self.mode == "manual":
            target = min(cap, self.manual_speed)
        elif not media_playing or peak == 0:
            target = 0
        elif not self.envelope and now < self._handoff_until:
            target = state["confirmed_speed_percent"] or self._last_sent
        else:
            target = self._mfp_target(self.envelope, peak)
        valve = "minus" if minus else "plus" if plus else None
        return target, valve if target > 0 else None

    def _valve_target(self, now, scripted, valves):
        if self.playing and self._auto_at is not None and now >= self._auto_at:
            if self.target > 0 and self._pulse is None and scripted is None:
                self._pulse = ("minus", None)
                self._schedule_auto(now)
        if self._pulse is not None:
            kind, until = self._pulse
            if until is None and valves[kind]:
                until = now + 1.0
                self._pulse = (kind, until)
            if until is None or now < until:
                return kind
            self._pulse = None
        return scripted

    def tick(self):
        try:
            media_playing = self._media()
            if self.mapped_source and self._transport and self._transport["playing"]:
                level = self._transport.get("l0")
                if not isinstance(level, (int, float)) or not isfinite(level) or not 0 <= level <= 1:
                    raise ValueError("Invalid mapped intensity")
        except (ValueError, OSError, TypeError, KeyError):
            self.error = "Intensity source unavailable or invalid."
            self.pause("Source error")
            return
        if not self._read_pending():
            return
        self._resume_timed_pause()
        if self._lease is None:
            return
        if not self.output.owns_timeline(self._lease):
            self._pause_mapped_intensity()
            self._cancel_trial("Stopped by Vector")
            if self.playing:
                self._record_event("playback_ended", "Stopped by Vector")
            self._save_playhead(self.clock())
            self._lease = None
            self.playing = False
            self.target = 0
            self._clear_valves()
            self.detail = "Stopped by Vector"
            return
        now = self.clock()
        state = self.output.state()
        if not self._advance_trial(now):
            return
        cap = state["max_speed_percent"]
        scripted = None
        if self.playing and self.mode in MFP_MODES and self._transport is None:
            self.pause("Funscript clock or script unavailable")
            return
        if self.playing:
            self.target, scripted = self._targets(now, media_playing, cap, state)
            if not self.playing:
                return
        valve = self._valve_target(now, scripted, state["valves"])
        try:
            self._apply(now, state, valve)
        except ValueError as exc:
            self.error = str(exc)
            self.pause("Output error")

    def _apply(self, now, state, valve):
        for kind, opened in state["valves"].items():
            if opened is None or (opened and kind != valve):
                self._pending = ("valve", self.output.valve(self._lease, kind, False))
                return
        if not self.playing and valve is None:
            self.output.cancel_timeline(self._lease)
            self._lease = None
            return
        if valve is not None and not state["valves"][valve]:
            self._pending = ("valve", self.output.valve(self._lease, valve, True))
            return
        if self.playing:
            running = state["state"] == "running"
            desired = round(self.target, 1)
            if desired == 0 and running:
                self._pending = ("speed", self.output.motor_rest(self._lease))
                self._last_sent = 0
                self._slew = False
                self._handoff_until = 0
                return
            if desired > 0 and now >= self._next_update:
                speed = desired
                if running and self._slew:
                    prior = state["confirmed_speed_percent"] or self._last_sent
                    step = self.HANDOFF_RATE * self.UPDATE_INTERVAL
                    speed = round(min(prior + step, max(prior - step, desired)), 1)
                    if speed == desired and not (self.mode in MFP_MODES and not self.envelope
                                                 and now < self._handoff_until):
                        self._slew = False
                unchanged_trim = self._last_applied_trim == self.trim
                minimum_change = (self.MOTION_DEADBAND
                                  if self.mode in MFP_MODES and not self._slew and unchanged_trim else 0)
                self._last_applied_trim = self.trim
                if not running or (speed != self._last_sent and abs(speed - self._last_sent) >= minimum_change):
                    self._pending = ("speed", self.output.command("speed" if running else "start", speed,
                                                                  timeline=self._lease))
                    self._last_sent = speed
                    self._next_update = now + self.UPDATE_INTERVAL
                    return
                if running:
                    self._confirm_mfp_return()

    def status(self, state):
        if self.stopping and state["state"] == "stopping":
            return f"{self.source_name} | Stop requested; waiting for VacuGlide confirmation"
        if self.error:
            return self.error
        confirmed = state["confirmed_speed_percent"]
        actual = "--" if confirmed is None else f"{confirmed:g}%"
        if self.mapped_source and self.playing:
            return f"{(self._transport or {}).get('label', 'Output desk')} | Target {self.target:.1f}% | Confirmed {actual}"
        if not self.playing:
            if self._timed_pause is not None and self._timed_pause["deadline"] is not None:
                left = max(0, self._timed_pause["deadline"] - self.clock())
                return f"Timed pause | {left:.0f} s left | Confirmed {actual}"
            return f"{self.source_name} | {self.detail} | {state['state']} | Confirmed {actual}"
        line = f"{MODES[self.mode]} | Target {self.target:.1f}% | Confirmed {actual}"
        if self.mode in MFP_MODES:
            age, timed = self.motion.packet_status(self.clock())
            envelope = "--" if self.envelope is None else f"{self.envelope:.0%}"
            l0 = "waiting for L0" if age is None else f"L0 {age:.1f}s ago"
            if age is not None and not timed:
                l0 += " (no recent move times)"
            if self._transport is None or not self._transport["playing"]:
                l0 = "Playback paused or outside the script"
            player = (self._transport or {}).get("label", "MFP")
            line += f" | {player} | Envelope {envelope} | {l0}"
        return line
