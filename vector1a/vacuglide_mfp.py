"""Follow MultiFunPlayer's timed L0 input using MPC-HC transport for start and stop."""
from collections import deque
from math import floor, isfinite
from threading import Lock
from time import monotonic

from .vacuglide_playback import LivePlayback


class TimedL0:
    """Average timed L0 velocity without treating short packet gaps as new moves."""

    IDLE_TIMEOUT = 1.50
    MIN_SPEED_WINDOW = 0.2
    MAX_SPEED_WINDOW = 3.0
    DEFAULT_SPEED_WINDOW = 0.6

    def __init__(self):
        self._lock = Lock()
        self._accepting = False
        self._previous = None
        self._segments = deque(maxlen=1024)
        self._speed_window = self.DEFAULT_SPEED_WINDOW
        self._last_packet = None
        self._last_timed_packet = None

    @property
    def speed_window(self):
        with self._lock:
            return self._speed_window

    def set_speed_window(self, seconds):
        if not isfinite(seconds) or not self.MIN_SPEED_WINDOW <= seconds <= self.MAX_SPEED_WINDOW:
            raise ValueError("Funscript averaging must be between 0.2 and 3.0 seconds.")
        with self._lock:
            self._speed_window = seconds

    def accept(self, enabled):
        with self._lock:
            if self._accepting != enabled:
                self._accepting = enabled
                self._previous = None
                self._segments.clear()
                self._last_packet = None
                self._last_timed_packet = None

    def receive(self, value, interval_ms, now):
        with self._lock:
            if not self._accepting:
                return
            self._last_packet = now
            if interval_ms > 0:
                self._last_timed_packet = now
            previous = self._previous
            self._previous = value
            if previous is None or interval_ms <= 0:
                return
            seconds = interval_ms / 1000
            # A full-scale L0 move in 1/6 s is the manufacturer's 100% velocity.
            level = min(1.0, abs(value - previous) / seconds / 6)
            # Repeated holds must not keep the motor alive or force a stop between moves.
            if level == 0:
                return
            if self._segments:
                begin, end, old_level = self._segments[-1]
                if now >= max(end, begin + self.IDLE_TIMEOUT):
                    self._segments.clear()
                elif begin == now:
                    self._segments.pop()
                else:
                    self._segments[-1] = (begin, now, old_level)
            self._segments.append((now, now + seconds, level))

    def packet_status(self, now):
        with self._lock:
            age = None if self._last_packet is None else max(0, now - self._last_packet)
            timed = (self._last_timed_packet is not None
                     and now - self._last_timed_packet < self.IDLE_TIMEOUT)
            return age, timed

    def level(self, now):
        with self._lock:
            if not self._segments:
                return None
            begin, end, current_level = self._segments[-1]
            if now >= max(end, begin + self.IDLE_TIMEOUT):
                return 0.0
            # Between real moves keep the last envelope instead of decaying to zero.
            sample_at = min(now, end)
            lower = sample_at - self._speed_window
            # Retain the widest window so increasing the slider works immediately.
            oldest = sample_at - self.MAX_SPEED_WINDOW
            while len(self._segments) > 1 and self._segments[0][1] <= oldest:
                self._segments.popleft()
            weighted = counted = 0.0
            for start, stop, level in reversed(self._segments):
                if stop <= lower:
                    break
                duration = max(0.0, min(stop, sample_at) - max(start, lower))
                weighted += duration * level
                counted += duration
            return weighted / counted if counted > 0 else current_level


class MfpFollower:
    SPEED_DEADBAND = 0.75

    def __init__(self, output, transport, clock=monotonic):
        self.output = output
        self.transport = transport
        self.clock = clock
        self.motion = TimedL0()
        self.trim = 25.0
        self.phase = "idle"
        self.detail = "MultiFunPlayer follow off"
        self._reservation = None
        self._pending = None
        self._holding = False
        self._pulse = None
        self._pulse_close_at = None
        self._next_pulse = None
        self._trim_changed = False
        self.pulse_settings = None
        self.envelope = None
        self.target_speed = 0.0
        self._target = 0.0

    def status(self, state):
        if self.phase != "active":
            return self.detail
        age, _ = self.motion.packet_status(self.clock())
        envelope = "--" if self.envelope is None else f"{self.envelope:.0%}"
        confirmed = state["confirmed_speed_percent"]
        received = "--" if age is None else f"{age:.1f}s ago"
        actual = "--" if confirmed is None else f"{confirmed:g}%"
        return (f"{self.detail} | Last L0 {received} | Envelope {envelope} | "
                f"Target {self.target_speed:g}% | Last command {self._target:g}% | Confirmed {actual}")

    def set_trim(self, value):
        if not isfinite(value) or not 0 <= value <= 100:
            raise ValueError("Speed trim must be between 0% and 100%.")
        if value != self.trim:
            self._trim_changed = True
            self.trim = value
        if value == 0 and self.phase == "active" and not self._holding:
            self._hold()

    def validate_start(self, pulse):
        transport = self.transport()
        if transport is None:
            raise ValueError("Open media in MPC-HC and select MPC direct in Vector's Funscript timeline.")
        if pulse is not None:
            interval, duration = pulse
            if not (isfinite(interval) and isfinite(duration) and 0 < duration < interval):
                raise ValueError("Enter a positive pulse duration shorter than its interval.")
        return transport

    def start(self, *, pulse=None):
        if self.phase != "idle":
            raise ValueError("Wait for a confirmed stop before following MultiFunPlayer.")
        transport = self.validate_start(pulse)
        self._reservation, self._cap = self.output.reserve_timeline(
            valves=pulse is not None, source="MultiFunPlayer")
        self._pulse = self.pulse_settings = pulse
        self.envelope = None
        self.target_speed = 0.0
        self._pulse_close_at = self._next_pulse = None
        self._holding = False
        self._last = transport
        self._gated = False
        self._target = 0.0
        self._next_update = self.clock()
        self._pending = None
        self.phase = "active"
        self.detail = "Waiting for timed L0 from MultiFunPlayer"
        if pulse is not None or self.trim == 0:
            self._hold()

    def _hold(self):
        self.motion.accept(False)
        self._gated = False
        self._holding = True
        self._pulse_close_at = self._next_pulse = None
        # Queue the stop before considering further L0 or a pending speed receipt.
        self._pending = self.output.stop(timeline=self._reservation, keep_timeline=True)
        self.envelope = None
        self.target_speed = self._target = 0.0
        self.detail = "Waiting for VacuGlide stop confirmation"

    def stop(self, reason="MultiFunPlayer follow stopped"):
        if self.phase in ("idle", "stopping"):
            return
        self.motion.accept(False)
        self._reason = reason
        self._pending = (self.output.stop(timeline=self._reservation)
                         if self._reservation is not None else self.output.stop())
        self._reservation = None
        self.phase = "stopping"
        self.detail = "Waiting for VacuGlide stop confirmation"

    @staticmethod
    def _jumped(previous, current):
        if previous["received_at"] == current["received_at"]:
            return False
        if current["source"] != previous["source"]:
            return True
        if not (current["playing"] and previous["playing"]):
            return False
        elapsed = current["received_at"] - previous["received_at"]
        expected = previous["position"] + elapsed * previous["rate"]
        tolerance = 0.75 if current["precise"] and previous["precise"] else 1.5
        return abs(current["position"] - expected) >= tolerance

    def _read_receipt(self):
        try:
            return self._pending.result()[1]
        except Exception:
            return {"ok": False}
        finally:
            self._pending = None

    def _output_failed(self, receipt):
        reason = (receipt.get("error") or "VacuGlide command returned no confirmation.").rstrip(".")
        if receipt.get("state") == "stopped" and self._pulse is None:
            # A failed speed write already tried the motor stop, so avoid a redundant request.
            self.motion.accept(False)
            self.output.cancel_timeline(self._reservation)
            self._reservation = None
            self.phase = "idle"
            self.detail = f"{reason}. Device confirmed stop."
            return
        self.stop(reason)

    def tick(self):
        if self.phase == "stopping":
            if self._pending.done():
                receipt = self._read_receipt()
                if receipt.get("ok") and receipt.get("state") in ("stopped", "released"):
                    self.phase = "idle"
                    self.detail = f"{self._reason}. Device confirmed stop."
                else:
                    self.phase = "failed"
                    reason = receipt.get("error") or "Stop unconfirmed. Use the VacuGlide's physical power control."
                    self.detail = f"{self._reason}. {reason}"
            return
        if self.phase != "active":
            return
        if not self.output.owns_timeline(self._reservation):
            self.stop("Stopped by another Vector control")
            return
        current = self.transport()
        if current is None:
            self.stop("MPC-HC clock unavailable")
            return
        jumped = self._jumped(self._last, current)
        self._last = current
        if not self._holding and (jumped or (self._gated and not current["playing"])
                                  or self.trim == 0 and self._gated):
            self._hold()
        if self._pending is not None:
            if not self._pending.done():
                self.detail = ("Waiting for stop confirmation" if not self._gated
                               else "Waiting for device confirmation")
                return
            receipt = self._read_receipt()
            if not receipt.get("ok"):
                self._output_failed(receipt)
                return
            if receipt.get("skipped"):
                self._pulse_close_at = None
        if self.trim == 0:
            self.detail = "Trim 0%. Device confirmed stop."
            return
        if not current["playing"]:
            self.detail = "MPC-HC paused or stopped"
            return
        if not self._gated:
            self.motion.accept(True)
            self._gated = True
            self._holding = False

        now = self.clock()
        level = self.motion.level(now)
        self.envelope = level
        age, timed = self.motion.packet_status(now)
        if level:
            self.detail = "Following MultiFunPlayer" if age < self.motion.IDLE_TIMEOUT else "Holding last timed move"
        elif age is None:
            self.detail = "Waiting for timed L0 from MultiFunPlayer"
        elif not timed and age < self.motion.IDLE_TIMEOUT:
            self.detail = "L0 packets arriving without recent move durations"
        elif level is None and timed:
            self.detail = "Waiting for timed L0 movement"
        elif age >= self.motion.IDLE_TIMEOUT:
            self.detail = "No recent L0 packets"
        else:
            self.detail = "L0 packets arriving with no active move"
        target = floor((level or 0) * min(self.trim, self._cap) * 10 + 1e-9) / 10
        # Treat values below the first whole percentage point as rest.
        if target < 1:
            target = 0
        self.target_speed = target
        changed = target != self._target and (
            target == 0 or self._target == 0 or self._trim_changed
            or abs(target - self._target) >= self.SPEED_DEADBAND
        )
        try:
            if self._pulse_close_at is not None:
                if target == 0:
                    # Close both valves and stop the motor before accepting another move.
                    self._hold()
                elif now >= self._pulse_close_at:
                    self._pending = self.output.valve(self._reservation, "minus", False)
                    self._pulse_close_at = None
                else:
                    self.detail = "Following MultiFunPlayer · Stroke − pulse"
                return
            if changed and (target == 0 or now >= self._next_update):
                if target == 0:
                    self._pending = self.output.motor_rest(self._reservation)
                else:
                    action = "start" if self._target == 0 else "speed"
                    self._pending = self.output.command(action, target, timeline=self._reservation)
                self._target = target
                self._trim_changed = False
                self._next_update = now + LivePlayback.UPDATE_INTERVAL
            elif self._pulse is not None and target > 0 and self._target > 0:
                interval, duration = self._pulse
                if self._next_pulse is None:
                    self._next_pulse = now + interval
                elif now >= self._next_pulse:
                    self._pending = self.output.valve(self._reservation, "minus", True,
                                                      deadline=monotonic() + duration)
                    self._pulse_close_at = now + duration
                    self._next_pulse = now + interval
        except ValueError as exc:
            self.stop(str(exc).rstrip("."))

