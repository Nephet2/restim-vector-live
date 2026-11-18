"""Shared transport; all hardware commands retain their existing output owner."""
from math import isfinite
from time import monotonic

from .handy_control import HandyControl
from .handy_script import MotionScript
from .vacuglide_script import Script, Preview


class LocalPreview:
    api = None
    active = False
    connected = False
    pending = None
    error = ""
    def poll(self):
        pass
    def stop(self):
        pass


class IntensityTrack:
    """Read a VacuGlide speed track directly, retaining its authored envelope."""
    def __init__(self, path):
        script = Script.load(path)
        self.preview = Preview(script)
        self.name = script.name
        self.duration = script.duration_ms / 1000
        self.times = tuple(sorted({0., self.duration, *(e.start_ms / 1000 for e in script.events)}))
        self.note = "VacuGlide intensity track; valve events use the existing Script Editor"
    def sample(self, seconds, gradient=False):
        return self.preview.at(min(self.duration * 1000 - 1, max(0, seconds * 1000)), ceiling=100)[0] / 100


class IntensitySource:
    SOURCE_NAMES = {"follow": "Funscript", "script": "Script", "manual": "Manual"}

    @property
    def name(self):
        return f"Mapped {self.SOURCE_NAMES[self.control.mode]}"

    def __init__(self, transport, clock=monotonic):
        self.clock = clock
        self.control = HandyControl(LocalPreview(), transport, clock=clock)
        self.control.mode = "follow"
        self.position_mode = False
        self.invert = False
        self.offset = 0.
        self.active = False
        self.level = 0.
        self.history = []

    def select(self, mode):
        if mode not in self.SOURCE_NAMES:
            raise ValueError("Choose Funscript, Script or Manual.")
        self.control.select(mode)
        if self.active and not self.control.previewing:
            self.control.start(preview=True)

    def load(self, path):
        track = (path if isinstance(path, MotionScript) else IntensityTrack(path)
                 if str(path).lower().endswith(".json") else MotionScript.load(path))
        self.control.load(track)
        if self.active and not self.control.previewing:
            self.control.start(preview=True)

    def start(self):
        self.active = True
        if not self.control.previewing:
            self.control.start(preview=True)

    def pause(self):
        self.active = False
        self.level = 0.
        self.control.pause()

    def frame(self):
        now = self.clock()
        self.control.configure(offset=self.offset)
        valid = self.active
        mode = self.control.mode
        if mode == "manual":
            level = 1.
            intensity_track = False
        else:
            valid = valid and self.control.running and not self.control._waiting
            raw = self.control._raw()
            valid = valid and raw is not None and isfinite(raw)
            intensity_track = mode == "script" and isinstance(self.control.script, IntensityTrack)
            if not valid:
                level = 0.
            elif self.position_mode or intensity_track:
                level = raw
            else:
                # Match existing VacuGlide velocity normalisation and averaging.
                values = [self.control._raw(-.6 + i * .05) for i in range(13)]
                if any(x is None or not isfinite(x) for x in values):
                    valid, level = False, 0.
                else:
                    level = sum(abs(b - a) for a, b in zip(values, values[1:])) / .6 / 6
            if valid and self.invert:
                level = 1 - min(1, max(0, level))
        self.level = min(1., max(0., level)) if valid else 0.
        if not self.history or now > self.history[-1][0]:
            self.history.append((now, self.level))
            self.history = self.history[-120:]
        basis = "manual" if mode == "manual" else "authored intensity" if intensity_track else "position" if self.position_mode else "velocity"
        return {"playing": bool(valid), "l0": self.level, "received_at": now,
                "source": (self, mode, self.control.script.name), "position": self.control.position,
                "rate": 1., "label": f"{mode.title()} · {basis}"}


class OutputDesk:
    def __init__(self, app, clock=monotonic):
        self.handy = app.handy_control
        self.vacu = app.vacuglide_control
        self.source = IntensitySource(app._handy_transport, clock=clock)
        self.linked = {"handy": True, "vacu": True}
        self.pending_vacu = False
        self.pending_selection = None
        self.message = "Paused · linking does not start a device"

    def cancel_pending(self):
        self.pending_vacu = False
        self.pending_selection = None

    def select_mapped_intensity(self, mode):
        if mode not in self.source.SOURCE_NAMES:
            raise ValueError("Choose Funscript, Script or Manual.")
        self.vacu.select_mapped_intensity(self.source)
        self.source.select(mode)

    def _vacu_selection(self, state):
        return (state["stop_revision"], self.vacu.source_name, self.vacu.mapped_source,
                id(self.vacu.loaded_preview))

    def _ready(self, device):
        if device == "handy":
            if self.handy.playing:
                return
            if not self.handy.output.connected:
                raise ValueError("Connect Handy in Handy settings first.")
            if self.handy.output.pending and self.handy.output.pending[0] != "stop":
                raise ValueError("Wait for Handy's current command.")
            if not self.handy.native_manual:
                self.handy.output.validate_position_mode()
        else:
            if self.vacu.playing:
                return
            state = self.vacu.output.state()
            if state["max_speed_percent"] is None:
                raise ValueError("Connect and take control of VacuGlide in its connection settings first.")
            self.vacu.validate_selected()

    def resume(self, devices=None):
        devices = [key for key, linked in self.linked.items() if linked] if devices is None else devices
        if not devices:
            raise ValueError("Link at least one device or use its individual Resume button.")
        for device in devices:
            self._ready(device)
        started = []
        try:
            for device in devices:
                if device == "handy":
                    if self.handy.playing:
                        continue
                    if self.handy.output.pending:
                        self.handy._resume_pending = True
                    else:
                        self.handy.start()
                else:
                    if self.vacu.playing or self.pending_vacu:
                        continue
                    if self.vacu.stopping:
                        self.pending_selection = self._vacu_selection(self.vacu.output.state())
                        self.pending_vacu = True
                    else:
                        self.vacu.resume_selected()
                started.append(device)
        except (ValueError, OSError):
            self.pause(started)
            raise
        self.message = "Resume requested · each device reports its own confirmation"

    def pause(self, devices=None):
        linked_pause = devices is None
        devices = [key for key, linked in self.linked.items() if linked] if linked_pause else devices
        for device in devices:
            if device == "handy":
                self.handy.pause()
            else:
                self.cancel_pending()
                self.vacu.pause("Paused from shared output desk")
        names = {"handy": "Handy", "vacu": "VacuGlide"}
        scope = " and ".join(names[key] for key in devices)
        self.message = f"Pause requested for {scope}." if scope else "No outputs linked."
        if linked_pause and scope and not self.linked["vacu"]:
            self.message += " VacuGlide is unlinked."

    def tick(self):
        if not self.pending_vacu:
            return
        state = self.vacu.output.state()
        if self._vacu_selection(state) != self.pending_selection:
            self.cancel_pending()
            self.message = "VacuGlide Resume cancelled: source changed or output stopped."
            return
        if self.vacu.stopping:
            return
        self.cancel_pending()
        if state["state"] != "stopped" or state.get("stop_verified") is not True or self.vacu.error:
            self.message = "VacuGlide Resume cancelled: stop was not confirmed."
            return
        try:
            self.vacu.resume_selected()
        except (ValueError, OSError) as exc:
            self.message = f"VacuGlide: {exc}"
