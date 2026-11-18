"""Device-independent Handy playback and live controls."""
from collections import deque
from math import ceil, floor, isfinite, cos, pi
from time import monotonic

from .handy_script import curated_scripts


MODES = {"follow": "Follow Funscript", "script": "Script Library", "manual": "Manual"}
TEMPOS = (.25, .5, 1., 2.)


class HandyControl:
    def __init__(self, output, transport, clock=monotonic):
        self.output, self.transport, self.clock = output, transport, clock
        self.mode = "script"
        self.script = next(iter(curated_scripts().values()))
        self.playing = False
        self.previewing = False
        self.position = 0.
        self.low, self.high = 0., 100.
        self.tempo = 1.
        self.cycles = .5
        self.manual_speed = 5.
        self.manual_native = True
        self.gradient = True
        self.invert = False
        self.offset = 0.
        self._resume_pending = False
        self.loop = True
        self.target = 0.
        self.detail = "Stopped"
        self.history = deque(maxlen=500)
        self._last = clock()
        self._follow = None
        self._follow_source = None
        self._follow_previous = None
        self._follow_script = 0.
        self._follow_clock = None
        self.follow_clock_error = 0.
        self._waiting = False

    @property
    def running(self):
        return self.playing or self.previewing or self._resume_pending

    @property
    def native_manual(self):
        return self.mode == "manual" and (self.manual_native or (self.output.api is not None and self.output.api.version != 3))

    def select(self, mode):
        if mode not in MODES:
            raise ValueError("Unknown Handy mode.")
        if mode == self.mode:
            return
        playing, preview = self.playing or self._resume_pending, self.previewing
        self.pause()
        self.mode = mode
        self.position = 0.
        self._follow_previous = None
        self.history.clear()
        if preview:
            self.start(preview=True)
        elif playing:
            self._resume_pending = True
            self.detail = "Switching mode; waiting for stop confirmation"

    def load(self, script):
        playing, preview = self.playing or self._resume_pending, self.previewing
        self.pause()
        self.script = script
        self.position = 0.
        if self.mode == "script":
            if preview:
                self.start(preview=True)
            elif playing:
                self._resume_pending = True

    def configure(self, low=None, high=None, tempo=None, cycles=None, speed=None,
                  invert=None, offset=None, gradient=None, manual_native=None):
        self.tick(send_output=False)
        lo = self.low if low is None else float(low)
        hi = self.high if high is None else float(high)
        rate = self.tempo if tempo is None else float(tempo)
        hz = self.cycles if cycles is None else float(cycles)
        native_speed = self.manual_speed if speed is None else float(speed)
        shift = self.offset if offset is None else float(offset)
        if not all(isfinite(x) for x in (lo, hi, rate, hz, native_speed, shift)) or not 0 <= lo <= hi <= 100:
            raise ValueError("Use a range between 0 and 100%, with minimum ≤ maximum.")
        if not .25 <= rate <= 2 or not .05 <= hz <= 3:
            raise ValueError("Choose a tempo preset and a manual rate between 0.05 and 3 cycles/s.")
        if not 0 <= native_speed <= 100:
            raise ValueError("Manual native speed must be between 0 and 100%.")
        if not -10 <= shift <= 10:
            raise ValueError("Time offset must be between -10 and +10 seconds.")
        change_backend = manual_native is not None and bool(manual_native) != self.manual_native and self.mode == "manual"
        resume, preview = self.playing or self._resume_pending, self.previewing
        if change_backend:
            self.pause()
        # Rebase the manual phase to keep changing its rate continuous.
        if self.mode == "manual":
            self.position *= self.cycles * self.tempo / (hz * rate)
        self.low, self.high, self.tempo, self.cycles = lo, hi, rate, hz
        self.manual_speed = native_speed
        self.offset = shift
        if invert is not None:
            self.invert = bool(invert)
        if gradient is not None:
            self.gradient = bool(gradient)
        if manual_native is not None:
            self.manual_native = bool(manual_native)
        if change_backend:
            if preview:
                self.start(preview=True)
            elif resume:
                self._resume_pending = True

    def start(self, preview=False):
        self._resume_pending = False
        if self.running:
            self.pause()
        if not preview:
            if self.mode != "manual" or not self.native_manual:
                self.output.validate_position_mode()
            self.output.start()
        self.previewing = preview
        self.playing = not preview
        self._last = self.clock()
        self._follow_previous = None
        self._waiting = False
        self.detail = "Preview only" if preview else "Playing"

    def pause(self):
        self._resume_pending = False
        was_playing = self.playing
        self.playing = self.previewing = False
        self.detail = "Paused"
        if was_playing or self.output.active:
            return self.output.stop()

    def stop(self):
        self._resume_pending = False
        self.playing = self.previewing = False
        self.position = 0.
        self._follow_previous = None
        self.detail = "Stopped"
        return self.output.stop()

    def seek(self, seconds):
        if self.mode != "script":
            raise ValueError("Seek is available in Script Library mode.")
        self.pause()
        self.position = max(0., min(self.script.duration, float(seconds)))

    def _raw(self, delta=0):
        if self.mode == "manual":
            phase = (self.position + delta) * self.cycles * self.tempo
            if self.gradient:
                return (1 - cos(2 * pi * phase)) / 2
            return 1 - abs(2 * (phase % 1) - 1)
        if self.mode == "follow":
            if not self._follow:
                return None
            sample = self._follow.get("sample_gradient", self._follow["sample"]) if self.gradient else self._follow["sample"]
            return sample(self._follow_script + delta * self._follow.get("rate", 1) * self.tempo + self.offset)
        pos = self.position + delta * self.tempo + self.offset
        if self.loop:
            pos %= self.script.duration
        return self.script.sample(min(self.script.duration, max(0, pos)), gradient=self.gradient)

    def sample(self, delta=0):
        raw = self._raw(delta)
        if raw is None or not isfinite(raw):
            return None
        if self.invert:
            raw = 1 - raw
        return (self.low + (self.high - self.low) * max(0, min(1, raw))) / 100

    def breakpoints(self, start, end):
        if self.mode == "manual":
            half = .5 / (self.cycles * self.tempo)
            first = floor((self.position + start) / half) + 1
            return [i * half - self.position for i in range(first, floor((self.position + end) / half) + 1)]
        if self.mode == "follow":
            times = self._follow.get("action_times") if self._follow else None
            rate = self.tempo * self._follow.get("rate", 1) if self._follow else 1
            return [(t - self.position - self.offset) / rate for t in times(self.position + start * rate + self.offset,
                    self.position + end * rate + self.offset)] if times else []
        duration = self.script.duration
        left, right = self.position + start * self.tempo + self.offset, self.position + end * self.tempo + self.offset
        loops = range(floor(left / duration), floor(right / duration) + 1) if self.loop else (0,)
        return [(t + loop * duration - self.position - self.offset) / self.tempo for loop in loops
                for t in self.script.times if left <= t + loop * duration <= right]

    def tick(self, send_output=True):
        now = self.clock()
        self.output.poll()
        if self._resume_pending:
            if self.output.error or not self.output.connected:
                self._resume_pending = False
                self.detail = self.output.error or "Disconnected"
            elif not self.output.pending:
                self.start()
            else:
                self._last = now
                return
        dt, self._last = max(0, now - self._last), now
        if self.playing and (self.output.error or not self.output.connected):
            self.pause()
            self.detail = self.output.error or "Disconnected"
        if not self.running:
            return
        discontinuous = False
        if self.mode == "follow":
            frame = self.transport()
            valid = (frame and frame.get("playing") and callable(frame.get("sample"))
                     and now - frame.get("received_at", -1e9) < 1.5)
            if not valid:
                if self.playing and self.output.active:
                    self.output.stop()
                self._waiting = True
                self._follow_previous = None
                self.detail = "Waiting for a player clock and loaded funscript"
                return
            pos, source = frame["position"], frame["source"]
            if not isfinite(pos):
                self.pause()
                self.detail = "Invalid source clock"
                return
            precise = frame.get("precise", True)
            expected = (self._follow_clock + dt * frame.get("rate", 1)
                        if self._follow_clock is not None else pos)
            jumped = (self._follow_previous is None or source != self._follow_source or
                      abs(pos - expected) > (.6 if precise else 1.5))
            if jumped:
                self._follow_script = pos
                self._follow_clock = pos
                self.history.clear()
                self.follow_clock_error = 0.
                discontinuous = True
                if self.playing and self.output.active and self.output.stream_started:
                    self.output.stop()
                    self._waiting = True
            else:
                # Player polls are measurements, not an actuator clock. Even
                # millisecond fields can move backwards after network jitter.
                # Advance monotonically and slew small corrections at <=5%
                # of source speed; actual seeks retain the reset path above.
                advance = dt * frame.get("rate", 1)
                predicted = self._follow_clock + advance
                correction = 0.
                error = pos - predicted
                self.follow_clock_error = error
                if precise and abs(error) > .02:
                    limit = advance * .05
                    correction = max(-limit, min(limit, error * .1))
                self._follow_clock = predicted + correction
                self._follow_script += (advance + correction) * self.tempo
            self._follow_previous, self._follow_source = pos, source
            self._follow = frame
            self.position = self._follow_script
            if self._waiting and self.playing:
                if self.output.pending:
                    return
                self.output.start()
                self._waiting = False
            self.detail = f"Following {frame.get('label', 'funscript')}"
        else:
            self.position += dt * (self.tempo if self.mode == "script" else 1)
            if self.mode == "script" and self.position >= self.script.duration:
                if self.loop:
                    self.position %= self.script.duration
                else:
                    self.position = self.script.duration
                    self.pause()
                    self.detail = "Finished"
                    return
        value = self.sample()
        if value is None:
            self.pause()
            self.detail = "Script has no position at this time"
            return
        self.target = value
        if not self.native_manual:
            # The app's transport tick is 10 Hz; draw the trajectory at 50 Hz
            # rather than making smooth fast strokes look like polygon spikes.
            count = 1 if discontinuous else max(1, ceil(min(dt, .2) / .02 - 1e-7))
            for i in range(count - 1, -1, -1):
                delta = -i * .02
                target = self.sample(delta)
                if target is not None:
                    stamp = now + delta
                    if not self.history or stamp > self.history[-1][0] + 1e-9:
                        self.history.append((stamp, target))
        if self.playing and send_output:
            if self.native_manual:
                self.output.manual(self.low, self.high, self.manual_speed, self.tempo, now)
            else:
                revision = (self.mode, self.low, self.high, self.tempo, self.cycles, self.loop,
                            self.invert, self.offset, self.gradient,
                            self._follow.get("rate", 1) if self.mode == "follow" and self._follow else 1)
                self.output.stream(lambda delta: self.sample(delta) if self.sample(delta) is not None else value,
                                   now, revision=revision, breakpoints=self.breakpoints)
