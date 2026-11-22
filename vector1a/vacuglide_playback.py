"""Run saved speed and valve tracks against one monotonic playhead."""
from bisect import bisect_right
from math import floor
from time import monotonic


class LivePlayback:
    UPDATE_INTERVAL = 0.5

    def __init__(self, output, clock=monotonic):
        self.output = output
        self.clock = clock
        self.phase = "idle"
        self.detail = ""
        self.position_ms = 0
        self.needs_stop = False
        self._reservation = None
        self._pending = None

    @property
    def active(self):
        return self.phase in ("arming", "playing", "stopping")

    @staticmethod
    def validate(preview, valves, *, require_speed=True):
        if preview is None:
            raise ValueError("Open a script before selecting this mode.")
        if require_speed and not any(event.speed_percent > 0 for event in preview.tracks["speed"]):
            raise ValueError("The script needs at least one speed step above zero.")
        blocks = sorted(
            (*preview.tracks["minus"], *preview.tracks["plus"]), key=lambda event: event.start_ms
        ) if valves else []
        if any(next_block.start_ms < block.end_ms for block, next_block in zip(blocks, blocks[1:])):
            raise ValueError("Stroke Plus and Stroke Minus blocks cannot overlap during live playback.")
        return blocks

    def start(self, preview, *, valves=False):
        if self.active or self.needs_stop:
            raise ValueError("Wait for a confirmed stop before starting another script.")
        self.valve_blocks = self.validate(preview, valves)
        self._valve_starts = [block.start_ms for block in self.valve_blocks]
        self._resume_after_ms = -1
        self._open_block = None
        self._reservation, self.cap = self.output.reserve_timeline(valves=bool(self.valve_blocks))
        self.preview = preview
        self.authored_peak = max(event.speed_percent for event in preview.tracks["speed"])
        self.position_ms = 0
        if self.valve_blocks:
            self.phase, self.detail = "arming", "Confirming both valves are closed"
            self._pending = self.output.stop(timeline=self._reservation, keep_timeline=True)
        else:
            self._begin()

    def _begin(self):
        self.phase = "playing"
        self.detail = "Playing speed and valve tracks" if self.valve_blocks else "Playing speed track"
        self._began = self.clock()
        self._next_update = self._began
        self._last_target = 0.0

    def pause(self):
        if self.phase != "playing":
            return
        if not self.output.owns_timeline(self._reservation):
            self.stop("Stopped by another Vector control")
            return
        self.position_ms = min(self.preview.duration_ms, int((self.clock() - self._began) * 1000))
        if self.position_ms >= self.preview.duration_ms:
            self.stop("Finished")
            return
        self._completion = "Paused"
        self.phase, self.detail = "stopping", "Pausing. Waiting for device stop confirmation."
        self._pending = self.output.stop(timeline=self._reservation, keep_timeline=True)

    def resume(self):
        if self.phase != "paused":
            raise ValueError("Pause live playback before resuming.")
        if not self.output.owns_timeline(self._reservation):
            self.stop("Stopped by another Vector control")
            raise ValueError("Vector no longer controls the paused script. Start a new live run.")
        self._resume_after_ms = self.position_ms
        self._open_block = None
        self.phase = "playing"
        self.detail = "Playing speed and valve tracks" if self.valve_blocks else "Playing speed track"
        now = self.clock()
        self._began = now - self.position_ms / 1000
        self._next_update, self._last_target = now, 0.0

    def stop(self, reason="Stopped"):
        if self.phase == "stopping" and self._completion != "Paused":
            return
        if not (self.active or self.phase == "paused" or self.needs_stop):
            return
        self._completion = reason
        self.phase, self.detail = "stopping", "Waiting for device stop confirmation"
        if self._reservation is None:
            self._pending = self.output.stop()
        else:
            self._pending = self.output.stop(timeline=self._reservation)
            self._reservation = None

    def tick(self, peak):
        if not self.active:
            return
        if self.phase == "stopping":
            if self._pending.done():
                self._finish_stop()
            return

        if self.phase == "arming":
            if not self._pending.done():
                return
            try:
                receipt = self._pending.result()[1]
            except Exception:
                receipt = {}
            self._pending = None
            if receipt.get("ok") and self.output.owns_timeline(self._reservation):
                self._begin()
            else:
                self.stop("Stopped before playback")
                return

        now = self.clock()
        if not self.output.owns_timeline(self._reservation):
            self.stop("Stopped by another Vector control")
            return
        self.position_ms = min(self.preview.duration_ms, max(0, int((now - self._began) * 1000)))
        if self.position_ms >= self.preview.duration_ms:
            self.stop("Finished")
            return
        if self._pending is not None:
            if not self._pending.done():
                return
            try:
                receipt = self._pending.result()[1]
            except Exception:
                self.stop("Stopped after an output error")
                return
            self._pending = None
            if not receipt.get("ok"):
                self.stop("Stopped after an output error")
                return
            if receipt.get("skipped"):
                self._open_block = None

        block = self._valve_at_position()
        if self._open_block is not None and self._open_block is not block:
            try:
                self._pending = self.output.valve(self._reservation, self._open_block.kind, False)
            except ValueError:
                self.stop("Stopped after an output error")
            self._open_block = None
            return

        gain = min(self.cap, peak) / self.authored_peak
        speed, _, _ = self.preview.at(self.position_ms, ceiling=self.cap, gain=gain)
        target = floor(speed * 10 + 1e-9) / 10
        try:
            if target != self._last_target:
                if target > 0 and now < self._next_update:
                    return
                if target == 0:
                    self._pending = self.output.motor_rest(self._reservation)
                else:
                    action = "start" if self._last_target == 0 else "speed"
                    self._pending = self.output.command(action, target, timeline=self._reservation)
                self._last_target = target
                self._next_update = now + self.UPDATE_INTERVAL
            elif block is not None and self._open_block is None:
                remaining = (block.end_ms - self.position_ms) / 1000
                self._pending = self.output.valve(self._reservation, block.kind, True,
                                                  deadline=monotonic() + remaining)
                self._open_block = block
        except ValueError:
            self.stop("Stopped after an output error")

    def _valve_at_position(self):
        index = bisect_right(self._valve_starts, self.position_ms) - 1
        if index >= 0:
            block = self.valve_blocks[index]
            if self._resume_after_ms < block.start_ms and self.position_ms < block.end_ms:
                return block
        return None

    def _finish_stop(self):
        try:
            receipt = self._pending.result()[1]
        except Exception:
            receipt = {}
        self._pending = None
        if receipt.get("ok") and receipt.get("state") in ("stopped", "released"):
            outcome = self._completion
            if outcome == "Paused" and not self.output.owns_timeline(self._reservation):
                outcome = "Stopped by another Vector control"
            self.phase = {"Paused": "paused", "Finished": "finished"}.get(outcome, "stopped")
            closed = " Both valves confirmed closed." if self.valve_blocks else ""
            self.detail = f"{outcome}. Device confirmed stop.{closed}"
            self.needs_stop = False
        else:
            if self._reservation is not None:
                self.output.cancel_timeline(self._reservation)
                self._reservation = None
            self.phase = "failed"
            self.detail = receipt.get("error") or "Stop unconfirmed. Use the VacuGlide's physical power control."
            self.needs_stop = True

