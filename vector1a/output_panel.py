"""Shared Handy motion / VacuGlide intensity desktop panel."""
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from .output_desk import OutputDesk
from .handy_panel import RangeControl, bind_offset_editor, configure_range_handle, show_handy
from .vacuglide_panel import show_vacuglide_panel
from .settings import settings_path
from .handy_script import MotionScript, curated_scripts


def show_outputs(app):
    panel = getattr(app, "_output_panel", None)
    if panel is not None and panel.window.winfo_exists():
        panel.window.lift()
        return
    if getattr(app, "output_desk", None) is None:
        app.output_desk = OutputDesk(app)
    app._output_panel = OutputPanel(app)


class OutputPanel:
    def __init__(self, app):
        self.app, self.desk = app, app.output_desk
        self.handy, self.source = self.desk.handy, self.desk.source
        self.vacu = self.desk.vacu
        self.window = tk.Toplevel(app.root)
        self.window.title("Vector · Motion and intensity")
        self.window.geometry("1120x790")
        self.window.minsize(1000, 720)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.job = None
        self.vacu_history = deque(maxlen=120)
        self.catalog = {}
        body = ttk.Frame(self.window, padding=12)
        body.pack(fill="both", expand=True)
        bar = ttk.Frame(body)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Label(bar, text="Motion + intensity", font=("TkDefaultFont", 14, "bold")).pack(side="left", padx=(0, 20))
        for label, action in (("Pause linked", self.desk.pause), ("Resume linked", self.desk.resume),
                              ("STOP ALL", app.stop)):
            ttk.Button(bar, text=label, command=lambda a=action: self.act(a)).pack(side="left", padx=4)
        ttk.Label(body, text="Link checkboxes choose which devices follow shared Pause/Resume. Linking does not start motion.").pack(anchor="w")
        columns = ttk.Frame(body)
        columns.pack(fill="both", expand=True, pady=10)
        columns.columnconfigure((0, 1), weight=1, uniform="device")
        columns.rowconfigure(0, weight=1)
        self.frames = {}
        self.links = {}
        for col, (key, title, connection) in enumerate((("handy", "Handy · motion", lambda: show_handy(app)),
                                                        ("vacu", "VacuGlide · intensity", lambda: show_vacuglide_panel(app)))):
            frame = ttk.LabelFrame(columns, text=title, padding=10)
            frame.grid(row=0, column=col, sticky="nsew", padx=(0, 5) if col == 0 else (5, 0))
            self.frames[key] = frame
            row = ttk.Frame(frame); row.pack(fill="x")
            var = self.links[key] = tk.BooleanVar(value=self.desk.linked[key])
            ttk.Checkbutton(row, text="Link to shared transport", variable=var,
                            command=lambda k=key, v=var: self.desk.linked.__setitem__(k, v.get())).pack(side="left")
            ttk.Button(row, text="Connection / settings…", command=connection).pack(side="right")
            row = ttk.Frame(frame); row.pack(fill="x", pady=8)
            for label, action in (("Pause", lambda k=key: self.desk.pause([k])),
                                  ("Resume", lambda k=key: self.desk.resume([k]))):
                ttk.Button(row, text=label, command=lambda a=action: self.act(a)).pack(side="left", padx=(0, 5))
        self.build_handy(self.frames["handy"])
        self.build_vacu(self.frames["vacu"])
        self.message = tk.StringVar()
        ttk.Label(body, textvariable=self.message, wraplength=1080).pack(anchor="w")
        ttk.Label(body, text="Charts show requested output. Closing this panel pauses both devices. STOP ALL includes unlinked devices.",
                  foreground="#657681").pack(anchor="w", pady=(6, 0))
        self.refresh_catalog()
        self.refresh()

    def act(self, action):
        try:
            action()
        except (ValueError, OSError, TypeError, tk.TclError) as exc:
            self.desk.message = str(exc)
            messagebox.showerror("Motion and intensity", str(exc), parent=self.window)

    def sources(self, parent, value, command):
        row = ttk.Frame(parent); row.pack(fill="x", pady=4)
        ttk.Label(row, text="Source (choose one)").pack(side="left", padx=(0, 6))
        for key, label in (("follow", "Funscript"), ("script", "Script"), ("manual", "Manual")):
            ttk.Checkbutton(row, text=label, variable=value, onvalue=key, offvalue=key,
                            command=lambda: self.act(command)).pack(side="left", padx=4)

    def offset_row(self, parent, value, action):
        row = ttk.Frame(parent); row.pack(fill="x", pady=5)
        ttk.Label(row, text="Time offset (s)", width=18).pack(side="left")
        spin = ttk.Spinbox(row, from_=-10, to=10, increment=.05, width=8, textvariable=value)
        spin.pack(side="left")
        bind_offset_editor(spin, lambda: self.act(action))
        ttk.Label(row, text="+ leads / − delays script").pack(side="left", padx=7)

        return spin

    def library(self, parent, key):
        row = ttk.Frame(parent); row.pack(fill="x", pady=5)
        value = tk.StringVar()
        box = ttk.Combobox(row, textvariable=value, state="readonly", width=25)
        box.pack(side="left", fill="x", expand=True)
        box.bind("<<ComboboxSelected>>", lambda _: self.act(lambda: self.load(key, self.catalog[value.get()])) )
        ttk.Button(row, text="Open…", command=lambda: self.open_file(key)).pack(side="left", padx=3)
        ttk.Button(row, text="↻", width=3, command=self.refresh_catalog).pack(side="left")
        return value, box

    def build_handy(self, frame):
        h = self.handy
        self.hmode = tk.StringVar(value=h.mode)
        self.sources(frame, self.hmode, lambda: h.select(self.hmode.get()))
        self.hscript, self.hbox = self.library(frame, "handy")
        self.hscript.set(h.script.name)
        self.hinvert = tk.BooleanVar(value=h.invert)
        self.hgradient = tk.BooleanVar(value=h.gradient)
        self.hnative = tk.BooleanVar(value=h.manual_native)
        row = ttk.Frame(frame); row.pack(fill="x", pady=5)
        for text, field, var in (("Invert script", "invert", self.hinvert),
                                 ("Gradient", "gradient", self.hgradient),
                                 ("Native Manual", "manual_native", self.hnative)):
            ttk.Checkbutton(row, text=text, variable=var,
                            command=lambda key=field, value=var: self.change_handy(key, value)).pack(side="left", padx=(0, 8))
        self.hlow, self.hhigh = tk.DoubleVar(value=h.low), tk.DoubleVar(value=h.high)
        self.hrange_label = ttk.Label(frame, wraplength=480)
        self.hrange_label.pack(anchor="w")
        self.range = RangeControl(frame, self.hlow, self.hhigh, self.change_handy_range)
        self.range.pack(fill="x")
        self.htempo = tk.DoubleVar(value=h.tempo)
        row = ttk.Frame(frame); row.pack(fill="x", pady=5)
        self.htempo_label = ttk.Label(row, width=18); self.htempo_label.pack(side="left")
        ttk.Scale(row, from_=.25, to=2, variable=self.htempo,
                  command=lambda _: self.change_handy("tempo", self.htempo)).pack(side="left", fill="x", expand=True)
        row = ttk.Frame(frame); row.pack(fill="x")
        for rate in (.25, .5, 1., 2.):
            ttk.Button(row, text=f"{rate:g}×", width=5, command=lambda r=rate: self.set_tempo(r)).pack(side="left", padx=3)
        self.hspeed = tk.DoubleVar(value=h.manual_speed)
        self.hcycles = tk.DoubleVar(value=h.cycles)
        self.hspeed_label = ttk.Label(frame); self.hspeed_label.pack(anchor="w", pady=(8, 0))
        self.hspeed_scale = ttk.Scale(frame, variable=self.hspeed, from_=0, to=100,
                                      command=lambda _: self.change_manual_rate())
        self.hspeed_scale.pack(fill="x")
        self.hoffset = tk.DoubleVar(value=h.offset)
        self.hoffset_box = self.offset_row(frame, self.hoffset,
                                           lambda: self.handy.configure(offset=self.hoffset.get()))
        self.hstatus = ttk.Label(frame, wraplength=500); self.hstatus.pack(anchor="w", pady=8)
        self.hcanvas = tk.Canvas(frame, height=150, background="#101e28", highlightthickness=0)
        self.hcanvas.pack(fill="both", expand=True)

    def build_vacu(self, frame):
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=(0, 4))
        self.vroute = ttk.Label(row)
        self.vroute.pack(side="left")
        self.vmode = tk.StringVar()
        self.sources(frame, self.vmode, self.change_vacu_source)
        self.vscript, self.vbox = self.library(frame, "vacu")
        self.vscript.set(self.source.control.script.name)
        self.vinvert = tk.BooleanVar(value=self.source.invert)
        self.vposition = tk.BooleanVar(value=self.source.position_mode)
        row = ttk.Frame(frame); row.pack(fill="x", pady=8)
        ttk.Checkbutton(row, text="Invert script", variable=self.vinvert, command=lambda: self.act(self.vsettings)).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(row, text="Position rather than velocity", variable=self.vposition,
                        command=lambda: self.act(self.vsettings)).pack(side="left")
        ttk.Label(frame, text="Position: script height → intensity. Velocity: movement speed → intensity.",
                  wraplength=480, foreground="#657681").pack(anchor="w")
        self.vtrim = tk.DoubleVar(value=self.vacu.trim)
        self.vtrim_label = ttk.Label(frame); self.vtrim_label.pack(anchor="w", pady=(10, 0))
        ttk.Scale(frame, from_=0, to=100, variable=self.vtrim,
                  command=lambda _: self.act(lambda: self.vacu.set_trim(self.vtrim.get()))).pack(fill="x")
        self.voffset = tk.DoubleVar(value=self.source.offset)
        self.offset_row(frame, self.voffset, self.vsettings)
        row = ttk.Frame(frame); row.pack(fill="x", pady=8)
        for kind, text in (("plus", "+stroke · introduces air"), ("minus", "−stroke")):
            ttk.Button(row, text=text, command=lambda k=kind: self.act(lambda: self.vacu.stroke(k))).pack(side="left", padx=(0, 7))
        ttk.Label(frame, text="Manual uses the trim as its intensity. JSON library files supply their speed/intensity track; "
                  "their valve events remain in the existing Script Editor.", wraplength=480, foreground="#657681").pack(anchor="w")
        self.vstatus = ttk.Label(frame, wraplength=500); self.vstatus.pack(anchor="w", pady=10)
        self.vcanvas = tk.Canvas(frame, height=150, background="#101e28", highlightthickness=0)
        self.vcanvas.pack(fill="both", expand=True)

    def change_vacu_source(self):
        try:
            self.desk.select_mapped_intensity(self.vmode.get())
        finally:
            self.refresh_vacu_source()

    def refresh_vacu_source(self):
        mode = self.source.control.mode if self.vacu.mapped_source == self.source.frame else ""
        if self.vmode.get() != mode:
            self.vmode.set(mode)
        self.vroute.configure(text=f"Selected source: {self.vacu.source_name}")

    def change_handy(self, field, variable):
        self.act(lambda: self.handy.configure(**{field: variable.get()}))

    def change_handy_range(self, handle):
        variable = self.hlow if handle == "low" else self.hhigh
        self.act(lambda: configure_range_handle(self.handy, handle, variable.get()))

    def change_manual_rate(self):
        if self._native_slider:
            self.change_handy("speed", self.hspeed)
        else:
            self.change_handy("cycles", self.hcycles)

    def vsettings(self):
        offset = self.voffset.get()
        if not -10 <= offset <= 10:
            raise ValueError("Use an offset between −10 and +10 seconds.")
        self.source.offset, self.source.invert, self.source.position_mode = offset, self.vinvert.get(), self.vposition.get()

    def set_tempo(self, rate):
        self.htempo.set(rate)
        self.change_handy("tempo", self.htempo)

    def refresh_catalog(self):
        self.catalog = {f"Starter / {name}": script for name, script in curated_scripts().items()}
        root = settings_path().parent
        for prefix, folder in (("Handy", root / "HandyScripts"), ("VacuGlide", root / "VacuglideScripts")):
            if folder.exists():
                for path in sorted(folder.iterdir()):
                    if path.suffix.lower() in (".funscript", ".json") and path.is_file():
                        self.catalog[f"{prefix} / {path.stem}"] = path
        for box in (self.hbox, self.vbox):
            box.configure(values=list(self.catalog))

    def load(self, key, path):
        if key == "handy":
            track = path if isinstance(path, MotionScript) else MotionScript.load(path)
            self.handy.load(track)
            self.hscript.set(track.name)
        else:
            self.source.load(path)
            self.vscript.set(self.source.control.script.name)

    def open_file(self, key):
        path = filedialog.askopenfilename(parent=self.window, title="Choose output script",
                                         filetypes=(("Funscript / VacuGlide script", "*.funscript *.json"),))
        if path:
            self.act(lambda: self.load(key, path))

    def plot(self, canvas, history, text):
        canvas.delete("all")
        w, h = max(100, canvas.winfo_width()), max(80, canvas.winfo_height())
        for level in (0, .5, 1):
            y = h - 18 - level * (h - 38)
            canvas.create_line(25, y, w - 10, y, fill="#29414f")
            canvas.create_text(23, y, text=f"{level * 100:g}", anchor="e", fill="#9db1bc")
        now = self.handy.clock()
        points = [coordinate for t, value in history if now - 10 <= t <= now
                  for coordinate in (w - 10 - (now - t) / 10 * (w - 35), h - 18 - value * (h - 38))]
        if len(points) >= 4:
            canvas.create_line(*points, fill="#68b7df", width=2)
        canvas.create_text(30, 10, text=text, anchor="w", fill="#53d9bb")

    def refresh(self):
        self.message.set(self.desk.message)
        h = self.handy
        for variable, value in (
                (self.hmode, h.mode), (self.hlow, h.low), (self.hhigh, h.high),
                (self.htempo, h.tempo), (self.hspeed, h.manual_speed), (self.hcycles, h.cycles),
                (self.hinvert, h.invert), (self.hgradient, h.gradient), (self.hnative, h.manual_native)):
            if variable.get() != value:
                variable.set(value)
        if self.window.focus_get() != self.hoffset_box and self.hoffset_box.get() != str(h.offset):
            self.hoffset.set(h.offset)
        if self.hscript.get() != h.script.name and getattr(self, "_displayed_hscript", None) is not h.script:
            self.hscript.set(h.script.name)
        self._displayed_hscript = h.script
        device_limits = getattr(h.output.api, "global_stroke", None)
        limit_text = (f" · device window {device_limits['min']:g}–{device_limits['max']:g}%" if device_limits else "")
        self.hrange_label.configure(text=f"Stroke range {h.low:.0f}–{h.high:.0f}%{limit_text} · marker is timed target")
        self.range.position = h.target if h.running and not h.native_manual and not h._waiting else None
        self.range.redraw()
        self.htempo_label.configure(text=f"Tempo {h.tempo:.2f}×")
        native = h.manual_native or (h.output.api is not None and h.output.api.version != 3)
        if getattr(self, "_native_slider", None) != native:
            self._native_slider = native
            self.hspeed_scale.configure(from_=0 if native else .05, to=100 if native else 3,
                                        variable=self.hspeed if native else self.hcycles)
        self.hspeed_scale.state(["!disabled" if h.mode == "manual" else "disabled"])
        self.hspeed_label.configure(text=f"Manual speed {h.manual_speed:.0f}%" if native else f"Manual stroke rate {h.cycles:.2f} cycles/s")
        self.hstatus.configure(text=f"{h.detail} | {h.output.detail}")
        self.plot(self.hcanvas, h.history if not h.native_manual else [], "Native motor · no phase telemetry" if h.native_manual else "Handy requested position")
        state = self.vacu.output.state()
        self.refresh_vacu_source()
        self.vtrim.set(self.vacu.trim)
        self.vtrim_label.configure(text=f"Intensity trim {self.vacu.trim:.0f}%")
        self.vstatus.configure(text=self.vacu.status(state))
        self.vacu_history.append((h.clock(), self.vacu.target / 100 if self.vacu.playing else 0.))
        self.plot(self.vcanvas, self.vacu_history, "VacuGlide requested intensity")
        self.job = self.window.after(100, self.refresh)

    def close(self):
        self.desk.pause(["handy", "vacu"])
        if self.job:
            self.window.after_cancel(self.job)
        self.window.destroy()
