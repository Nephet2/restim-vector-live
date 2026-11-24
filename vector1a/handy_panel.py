"""Handy interface using Vector/VacuGlide's library and playback layout."""
import json
from pathlib import Path
import shutil
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .handy_control import MODES, TEMPOS
from .handy_script import MotionScript, curated_scripts
from .settings import settings_path
from .vacuglide_credentials import _protect
from .vacuglide_script import time_text


class RangeControl(tk.Canvas):
    """Two range handles and a separately labelled commanded-position marker."""
    def __init__(self, parent, low, high, command):
        super().__init__(parent, height=45, background="#eef3f5", highlightthickness=0, takefocus=True)
        self.low, self.high, self.command = low, high, command
        self.position = None
        self.handle = "low"
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<Button-1>", self.begin)
        self.bind("<B1-Motion>", self.move)
        self.bind("<Left>", lambda _: self.nudge(-1))
        self.bind("<Right>", lambda _: self.nudge(1))
        self.bind("<space>", lambda _: self.swap())

    def swap(self):
        self.handle = "high" if self.handle == "low" else "low"
        self.redraw()

    def begin(self, event):
        self.focus_set()
        value = self.value(event.x)
        if self.low.get() == self.high.get():
            self.handle = "high" if value >= self.high.get() else "low"
        else:
            self.handle = "low" if abs(value - self.low.get()) <= abs(value - self.high.get()) else "high"
        self.move(event)

    def value(self, x):
        return max(0, min(100, (x - 14) / max(1, self.winfo_width() - 28) * 100))

    def nudge(self, delta):
        var = self.low if self.handle == "low" else self.high
        self.apply(var.get() + delta)

    def move(self, event):
        self.apply(self.value(event.x))

    def apply(self, value):
        if self.handle == "low":
            self.low.set(max(0, min(self.high.get(), value)))
        else:
            self.high.set(min(100, max(self.low.get(), value)))
        self.command(self.handle)
        self.redraw()

    def redraw(self):
        self.delete("all")
        def x(value):
            return 14 + value / 100 * max(1, self.winfo_width() - 28)
        self.create_line(x(0), 19, x(100), 19, fill="#a2b4be", width=4)
        self.create_line(x(self.low.get()), 19, x(self.high.get()), 19, fill="#327e9d", width=6)
        for name, var in (("low", self.low), ("high", self.high)):
            at = x(var.get())
            self.create_rectangle(at - 6, 9, at + 6, 29, fill="#1675ac",
                                  outline="#183849" if name == self.handle else "#1675ac")
        if self.position is not None:
            at = x(self.position * 100)
            self.create_polygon(at - 5, 2, at + 5, 2, at, 10, fill="#a95b00")
        self.create_text(x(0), 39, text="0", anchor="w", fill="#526a78")
        self.create_text(x(100), 39, text="100%", anchor="e", fill="#526a78")


def bind_offset_editor(spin, commit):
    """Commit typed offsets only when the operator changed the entry."""
    original = spin.get()

    def remember(_event=None):
        nonlocal original
        original = spin.get()

    def apply(_event=None):
        if spin.get() != original:
            commit()
            remember()

    def step():
        commit()
        remember()

    spin.configure(command=step)
    spin.bind("<FocusIn>", remember)
    spin.bind("<Return>", apply)
    spin.bind("<FocusOut>", apply)


def configure_range_handle(control, handle, value):
    if handle == "low":
        control.configure(low=min(control.high, value))
    else:
        control.configure(high=max(control.low, value))


def show_handy(app):
    existing = getattr(app, "_handy_panel", None)
    if existing is not None and existing.window.winfo_exists():
        existing.window.deiconify()
        existing.window.lift()
        return
    app._handy_panel = HandyPanel(app)


class HandyPanel:
    def __init__(self, app):
        self.app, self.control = app, app.handy_control
        self.output = self.control.output
        self.window = tk.Toplevel(app.root)
        self.window.title("Handy Interface")
        self.window.geometry("1040x790")
        self.window.minsize(900, 700)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.job = None
        self.credentials = settings_path().with_name("handy-credentials.dpapi")
        self.folder = settings_path().parent / "HandyScripts"
        self.folder.mkdir(parents=True, exist_ok=True)
        for name, script in curated_scripts().items():
            path = self.folder / (name + ".funscript")
            if not path.exists():
                path.write_text(json.dumps({"version": "1.0", "inverted": False,
                    "actions": [{"at": round(t * 1000), "pos": round(x * 100)} for t, x in script.points],
                    "metadata": {"title": name, "description": script.note}}, indent=2), encoding="utf-8")
        self.key = tk.StringVar()
        self.api_key = tk.StringVar()
        self.remember = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Disconnected")
        self.note = tk.StringVar(value=self.control.script.note)
        self.mode = tk.StringVar(value=self.control.mode)
        self.low = tk.DoubleVar(value=self.control.low)
        self.high = tk.DoubleVar(value=self.control.high)
        self.tempo = tk.DoubleVar(value=self.control.tempo)
        self.cycles = tk.DoubleVar(value=self.control.cycles)
        self.manual_speed = tk.DoubleVar(value=self.control.manual_speed)
        self.native = tk.BooleanVar(value=self.control.manual_native)
        self.gradient = tk.BooleanVar(value=self.control.gradient)
        self.invert = tk.BooleanVar(value=self.control.invert)
        self.offset = tk.DoubleVar(value=self.control.offset)
        self._native_slider = None
        self.loop = tk.BooleanVar(value=self.control.loop)
        self.range_label = tk.StringVar()
        self.speed_label = tk.StringVar()
        self.time_label = tk.StringVar()
        self.device_limit_label = tk.StringVar(value="Device limits: read on connection")
        self.selected = tk.StringVar(value=self.control.script.name)
        self.catalog = {}
        self._read_credentials()
        self._build()
        self.refresh_catalog()
        self.refresh()

    def _read_credentials(self):
        try:
            if self.credentials.exists():
                values = json.loads(_protect(self.credentials.read_bytes(), decrypt=True))
                self.key.set(values.get("key", ""))
                self.api_key.set(values.get("api_key", ""))
                self.remember.set(True)
        except (OSError, ValueError):
            self.note.set("Could not read the saved Handy keys; enter them again.")

    def _build(self):
        body = ttk.Frame(self.window, padding=10)
        body.pack(fill="both", expand=True)
        connection = ttk.LabelFrame(body, text="Handy connection", padding=8)
        connection.pack(fill="x")
        row = ttk.Frame(connection)
        row.pack(fill="x")
        ttk.Label(row, text="Connection key").pack(side="left")
        self.key_entry = ttk.Entry(row, textvariable=self.key, width=21)
        self.key_entry.pack(side="left", padx=6)
        ttk.Label(row, text="Application key / token").pack(side="left", padx=(12, 0))
        self.api_entry = ttk.Entry(row, textvariable=self.api_key, show="•", width=26)
        self.api_entry.pack(side="left", padx=6)
        self.connect_button = ttk.Button(row, text="Connect", command=lambda: self.act(self.connect))
        self.connect_button.pack(side="left", padx=4)
        ttk.Checkbutton(row, text="Remember keys", variable=self.remember,
                        command=lambda: self.act(self.remember_changed)).pack(side="left", padx=5)
        ttk.Button(row, text="Diagnostics…", command=self.show_diagnostics).pack(side="right")
        ttk.Label(connection, text="Connection key only: native manual speed control. "
            "Firmware 4 timed scripts/strokes require a Handy Application Key (buffered HSP).",
            wraplength=960).pack(anchor="w", pady=(5, 0))
        ttk.Label(connection, text="Control uses Handy's cloud. Keys are saved with Windows user encryption only when selected.",
                  foreground="#657681").pack(anchor="w")
        limits = ttk.Frame(connection)
        limits.pack(fill="x", pady=3)
        ttk.Label(limits, textvariable=self.device_limit_label).pack(side="left")
        self.limit_read = ttk.Button(limits, text="Read device limits",
                                    command=lambda: self.act(self.output.device_range))
        self.limit_read.pack(side="right", padx=3)
        self.limit_reset = ttk.Button(limits, text="Set device 0–100%",
                                     command=lambda: self.act(lambda: self.output.device_range(reset=True)))
        self.limit_reset.pack(side="right", padx=3)
        link = ttk.Label(connection, text="Get a Handy Application Key at user.handyfeeling.com",
                         foreground="#276ba1", cursor="hand2")
        link.pack(anchor="w")
        link.bind("<Button-1>", lambda _: webbrowser.open("https://user.handyfeeling.com/"))

        panel = ttk.LabelFrame(body, text="Playback and live controls", padding=8)
        panel.pack(fill="x", pady=8)
        row = ttk.Frame(panel)
        row.pack(fill="x")
        for mode, name in MODES.items():
            ttk.Radiobutton(row, text=name, value=mode, variable=self.mode,
                command=lambda: self.act(lambda: self.control.select(self.mode.get()))).pack(side="left", padx=(0, 15))
        ttk.Checkbutton(row, text="Loop library script", variable=self.loop,
                        command=lambda: self.settings_changed("loop")).pack(side="right")
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=7)
        self.play_button = ttk.Button(row, text="Start / Resume", command=lambda: self.act(self.toggle))
        self.play_button.pack(side="left", padx=(0, 5))
        ttk.Button(row, text="Stop / Reset", command=lambda: self.act(self.control.stop)).pack(side="left", padx=5)
        self.preview_button = ttk.Button(row, text="Preview only", command=lambda: self.act(self.preview))
        self.preview_button.pack(side="left", padx=5)
        ttk.Label(row, text="Tempo").pack(side="left", padx=(20, 5))
        for rate in TEMPOS:
            ttk.Radiobutton(row, text=f"{rate:g}×", variable=self.tempo, value=rate,
                            command=lambda: self.settings_changed("tempo")).pack(side="left", padx=5)
        self.tempo_label = ttk.Label(row, width=7)
        self.tempo_label.pack(side="right")
        ttk.Scale(row, from_=.25, to=2, variable=self.tempo, length=120,
                  command=lambda _: self.settings_changed("tempo")).pack(side="right", padx=4)
        row = ttk.Frame(panel)
        row.pack(fill="x")
        ttk.Label(row, text="Stroke range", width=15).pack(side="left")
        self.range_control = RangeControl(row, self.low, self.high, self.settings_changed)
        self.range_control.pack(side="left", fill="x", expand=True)
        ttk.Label(row, textvariable=self.range_label, width=15, anchor="e").pack(side="left", padx=5)
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        self.rate_title = ttk.Label(row, text="Manual speed", width=20)
        self.rate_title.pack(side="left")
        self.rate_scale = ttk.Scale(row, from_=.05, to=3, variable=self.cycles,
                                    command=lambda _: self.settings_changed("manual_rate"), length=300)
        self.rate_scale.pack(side="left")
        ttk.Label(row, textvariable=self.speed_label).pack(side="left", padx=8)
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=4)
        ttk.Checkbutton(row, text="Native motor (Manual only)", variable=self.native,
                        command=lambda: self.settings_changed("manual_native")).pack(side="left")
        ttk.Checkbutton(row, text="Gradient (timed motion)", variable=self.gradient,
                        command=lambda: self.settings_changed("gradient")).pack(side="left", padx=10)
        ttk.Checkbutton(row, text="Invert script", variable=self.invert,
                        command=lambda: self.settings_changed("invert")).pack(side="left", padx=8)
        ttk.Label(row, text="Offset (s)").pack(side="left", padx=(10, 3))
        self.offset_box = ttk.Spinbox(row, from_=-10, to=10, increment=.05, width=7,
                                      textvariable=self.offset)
        self.offset_box.pack(side="left")
        bind_offset_editor(self.offset_box, lambda: self.settings_changed("offset"))
        ttk.Label(row, text="+ leads / − delays script").pack(side="left", padx=5)
        ttk.Label(panel, text="Follow uses Vector's MPC / HereSphere / MFP funscript timeline. "
            "Use 1× for original video timing; other tempos rescale script time until the next seek.",
            wraplength=960, foreground="#657681").pack(anchor="w", pady=(3, 0))
        ttk.Label(panel, text="Native Manual runs continuously on Handy; its speed is a motor percentage. "
            "Untick Native for timed strokes with Gradient reversals. "
            "Range marker = timed target, not measured position. Cloud delay still applies.", wraplength=960,
            foreground="#657681").pack(anchor="w")

        library = ttk.LabelFrame(body, text="Script library • funscripts and VacuGlide speed tracks", padding=8)
        library.pack(fill="x")
        row = ttk.Frame(library)
        row.pack(fill="x")
        self.library_box = ttk.Combobox(row, textvariable=self.selected, state="readonly", width=43)
        self.library_box.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self.library_box.bind("<<ComboboxSelected>>", lambda _: self.act(self.load_selected))
        ttk.Button(row, text="Import…", command=lambda: self.act(self.import_script)).pack(side="left", padx=3)
        ttk.Button(row, text="Open file…", command=lambda: self.act(self.open_script)).pack(side="left", padx=3)
        ttk.Button(row, text="Refresh", command=lambda: self.act(self.refresh_catalog)).pack(side="left", padx=3)
        ttk.Label(library, textvariable=self.note, foreground="#657681", wraplength=960).pack(anchor="w", pady=(5, 0))

        display = ttk.LabelFrame(body, text="Output visualisation • commanded positions, not device telemetry", padding=6)
        display.pack(fill="both", expand=True, pady=8)
        self.canvas = tk.Canvas(display, height=190, background="#101e28", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.seek)
        ttk.Label(display, textvariable=self.time_label).pack(anchor="w", pady=(4, 0))
        ttk.Label(body, textvariable=self.status, foreground="#27546b", wraplength=990).pack(anchor="w")

    def act(self, action):
        try:
            action()
        except (OSError, ValueError, TypeError, tk.TclError) as exc:
            messagebox.showerror("Handy Interface", str(exc), parent=self.window)

    def remember_changed(self):
        if not self.remember.get():
            self.credentials.unlink(missing_ok=True)

    def show_diagnostics(self):
        window = tk.Toplevel(self.window)
        window.title("Handy protocol diagnostics")
        window.geometry("850x550")
        text = tk.Text(window, wrap="word")
        text.pack(fill="both", expand=True, padx=8, pady=8)
        def refresh():
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", self.output.diagnostics())
            if self.control.mode == "follow":
                text.insert("end", f"\n\nFollow raw clock: {self.control._follow_previous}\n"
                            f"Follow smoothed clock: {self.control._follow_clock}\n"
                            f"Last source-clock error: {self.control.follow_clock_error * 1000:.1f} ms\n"
                            "Small clock corrections slew at up to 5%; seeks reset playback.\n")
            text.configure(state="disabled")
            text.see("end")
        ttk.Button(window, text="Refresh", command=refresh).pack(pady=(0, 8))
        refresh()

    def connect(self):
        if self.output.connected:
            self.control.stop()
            self.output.connected = False
            return
        self.output.connect(self.key.get(), self.api_key.get())
        self._save_after_connect = True

    def _save_credentials(self):
        if self.remember.get():
            data = json.dumps({"key": self.key.get(), "api_key": self.api_key.get()}).encode()
            temporary = self.credentials.with_suffix(".tmp")
            temporary.write_bytes(_protect(data))
            temporary.replace(self.credentials)
        else:
            self.credentials.unlink(missing_ok=True)

    def settings_changed(self, field):
        def apply():
            if field == "loop":
                self.control.loop = self.loop.get()
            elif field in ("low", "high"):
                configure_range_handle(self.control, field, getattr(self, field).get())
            else:
                variables = {"manual_native": self.native, "speed": self.manual_speed,
                             "cycles": self.cycles, "tempo": self.tempo, "offset": self.offset,
                             "invert": self.invert, "gradient": self.gradient}
                name = ("speed" if self._native_slider else "cycles") if field == "manual_rate" else field
                self.control.configure(**{name: variables[name].get()})
        self.act(apply)

    def toggle(self):
        if self.control.running:
            self.control.pause()
        else:
            self.control.start()

    def preview(self):
        if self.control.previewing:
            self.control.pause()
        else:
            self.control.start(preview=True)

    def refresh_catalog(self):
        self.catalog = {}
        for prefix, folder in (("Handy", self.folder), ("VacuGlide", settings_path().parent / "VacuglideScripts")):
            if folder.exists():
                for path in sorted(folder.iterdir()):
                    if path.is_file() and path.suffix.lower() in (".funscript", ".json"):
                        self.catalog[f"{prefix} / {path.stem}"] = path
        self.library_box.configure(values=list(self.catalog))

    def load_selected(self):
        path = self.catalog.get(self.selected.get())
        if path:
            self.load(path)

    def load(self, path):
        script = MotionScript.load(path)
        self.control.load(script)
        self.note.set(script.note)
        self.selected.set(next((name for name, item in self.catalog.items() if item == Path(path)), script.name))

    def choose_file(self):
        return filedialog.askopenfilename(parent=self.window, title="Open Handy or VacuGlide script",
            filetypes=(("Position / speed scripts", "*.funscript *.json"), ("All files", "*.*")))

    def open_script(self):
        path = self.choose_file()
        if path:
            self.load(path)

    def import_script(self):
        path = self.choose_file()
        if not path:
            return
        MotionScript.load(path)  # Validate before copying anything into the library.
        source = Path(path)
        target = self.folder / source.name
        if source.resolve() != target.resolve():
            i = 2
            while target.exists():
                target = self.folder / f"{source.stem} ({i}){source.suffix}"
                i += 1
            shutil.copy2(source, target)
        self.refresh_catalog()
        self.load(target)

    def seek(self, event):
        if self.control.mode == "script":
            x = max(0, min(1, (event.x - 44) / max(1, self.canvas.winfo_width() - 62)))
            self.act(lambda: self.control.seek(x * self.control.script.duration))

    def draw(self):
        c, control = self.canvas, self.control
        c.delete("all")
        width, height = max(100, c.winfo_width()), max(80, c.winfo_height())
        left, right, top, bottom = 44, width - 18, 22, height - 28
        def y(x):
            return bottom - x * (bottom - top)
        c.create_rectangle(left, y(control.high / 100), right, y(control.low / 100), fill="#183849", outline="")
        for level in (0, .25, .5, .75, 1):
            c.create_line(left, y(level), right, y(level), fill="#2a414e")
            c.create_text(left - 7, y(level), text=f"{level * 100:g}", fill="#9db1bc", anchor="e")
        if control.native_manual:
            speed = min(100., control.manual_speed * control.tempo)
            c.create_text((left + right) / 2, (top + bottom) / 2 - 16,
                          text=f"Native speed {speed:.0f}%", fill="#53d9bb", font=("TkDefaultFont", 18))
            c.create_text((left + right) / 2, (top + bottom) / 2 + 14,
                          text=f"Commanded range {control.low:.0f}–{control.high:.0f}%", fill="#9db1bc")
            c.create_text(left, height - 10, text="HAMP provides no position/phase telemetry; cycle rate is not measured",
                          fill="#9db1bc", anchor="w")
        elif control.mode == "script":
            points = []
            for i in range(501):
                position = control.script.sample(control.script.duration * i / 500, gradient=control.gradient)
                if control.invert:
                    position = 1 - position
                value = (control.low + (control.high - control.low) * position) / 100
                points.extend((left + (right - left) * i / 500, y(value)))
            c.create_line(*points, fill="#68b7df", width=1.5)
            x = left + (right - left) * min(1, control.position / control.script.duration)
            c.create_line(x, top, x, bottom, fill="#f0bc62", width=2)
            c.create_text(left, height - 10, text="0:00", fill="#9db1bc", anchor="w")
            c.create_text(right, height - 10, text=time_text(round(control.script.duration * 1000)), fill="#9db1bc", anchor="e")
        else:
            now = control.clock()
            points = []
            for stamp, value in control.history:
                if now - 10 <= stamp <= now:
                    points.extend((right - (now - stamp) / 10 * (right - left), y(value)))
            if len(points) >= 4:
                c.create_line(*points, fill="#68b7df", width=2)
            c.create_text(left, height - 10, text="Last 10 seconds", fill="#9db1bc", anchor="w")
        if control.running and not control._waiting and not control.native_manual:
            c.create_line(left, y(control.target), right, y(control.target), fill="#53d9bb", dash=(4, 4))
            label = "Estimated" if control.mode == "manual" else "Target"
            c.create_text(right, top - 9, text=f"{label} {control.target * 100:.0f}%", fill="#53d9bb", anchor="e")

    def refresh(self):
        if not self.window.winfo_exists():
            return
        if getattr(self, "_save_after_connect", False) and self.output.pending is None:
            self._save_after_connect = False
            if self.output.connected:
                self.act(self._save_credentials)
        for variable, value in (
                (self.mode, self.control.mode), (self.loop, self.control.loop),
                (self.low, self.control.low), (self.high, self.control.high),
                (self.tempo, self.control.tempo), (self.cycles, self.control.cycles),
                (self.manual_speed, self.control.manual_speed), (self.native, self.control.manual_native),
                (self.invert, self.control.invert), (self.gradient, self.control.gradient)):
            if variable.get() != value:
                variable.set(value)
        # Tk path comparison; focus_get() can raise KeyError while a dropdown is open.
        if str(self.window.tk.call("focus")) != str(self.offset_box) and self.offset_box.get() != str(self.control.offset):
            self.offset.set(self.control.offset)
        self.connect_button.configure(text="Disconnect" if self.output.connected else "Connect")
        self.connect_button.state(["disabled" if self.output.pending else "!disabled"])
        for entry in (self.key_entry, self.api_entry):
            entry.state(["disabled" if self.output.connected or self.output.pending else "!disabled"])
        self.play_button.configure(text="Pause" if self.control.running else "Start / Resume")
        self.play_button.state(["!disabled" if self.output.connected and (not self.output.pending or self.control.playing) else "disabled"])
        self.preview_button.configure(text="Pause preview" if self.control.previewing else "Preview only")
        self.rate_scale.state(["!disabled" if self.control.mode == "manual" else "disabled"])
        native_slider = self.control.manual_native or (self.output.api is not None and self.output.api.version != 3)
        if self._native_slider != native_slider:
            self._native_slider = native_slider
            self.rate_scale.configure(from_=0 if native_slider else .05, to=100 if native_slider else 3,
                                      variable=self.manual_speed if native_slider else self.cycles)
            self.rate_title.configure(text="Manual speed" if native_slider else "Manual stroke rate")
        self.range_label.set(f"{self.control.low:.0f}–{self.control.high:.0f}%")
        limits = getattr(self.output.api, "global_stroke", None)
        if limits:
            a, b = limits["min"], limits["max"]
            lo = a + (b - a) * self.control.low / 100
            hi = a + (b - a) * self.control.high / 100
            self.device_limit_label.set(f"Device limits {a:g}–{b:g}% · effective requested range {lo:.1f}–{hi:.1f}%")
        for button in (self.limit_read, self.limit_reset):
            button.state(["!disabled" if self.output.connected and not self.output.active
                          and not self.output.pending and not self.control.running else "disabled"])
        self.tempo_label.configure(text=f"{self.control.tempo:.2f}×")
        self.range_control.position = (self.control.target if self.control.running and not self.control.native_manual
                                       and not self.control._waiting else None)
        self.range_control.redraw()
        self.speed_label.set(f"{self.control.manual_speed:.0f}% × {self.control.tempo:g} (native speed)" if native_slider
                             else f"{self.control.cycles:.2f} cycles/s × {self.control.tempo:g} (timed target)")
        self.time_label.set(f"{time_text(round(self.control.position * 1000))}  •  {self.control.script.name if self.control.mode == 'script' else MODES[self.control.mode]}" +
                            ("  •  click timeline to seek (pauses output)" if self.control.mode == "script" else ""))
        self.status.set(f"{self.control.detail}  |  {self.output.detail}")
        firmware = str(getattr(self.output.api, "info", {}).get("firmware", ""))
        if (self.output.connected and getattr(self.output.api, "version", 2) == 2
                and firmware.startswith("4.") and self.control.mode != "manual"):
            self.play_button.state(["disabled"])
            self.status.set("Buffered HSP required for timed playback: add your Handy Application Key and reconnect. "
                            "Preview remains available.")
        self.draw()
        self.job = self.window.after(100, self.refresh)

    def close(self):
        self.control.pause()
        if self.job:
            self.window.after_cancel(self.job)
        self.window.destroy()
