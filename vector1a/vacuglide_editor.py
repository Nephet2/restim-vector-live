"""Vector's VacuGlide script editor and speed-track player."""
from dataclasses import replace
from pathlib import Path
from time import monotonic
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .settings import settings_path
from .vacuglide_control import MODES, PLAYHEAD_MODES, SCRIPT_MODES, VACUUM_INTERVALS, VacuGlideControl
from .vacuglide_credentials import forget_token, load_token, save_token
from .vacuglide_script import Event, LABELS, Preview, Script, import_instructions, parse_time, time_text


EXAMPLE = Path(__file__).with_name("vacuglide_three_minute_example.json")
COLORS = {"speed": "#2482c6", "minus": "#c07022", "plus": "#8a5bd3"}
LABEL_TO_KIND = {label: kind for kind, label in LABELS.items()}


def show_editor(app):
    existing = getattr(app, "_vacuglide_editor", None)
    if existing is not None and existing.window.winfo_exists():
        existing.window.lift()
        return
    app._vacuglide_editor = Editor(app.root, getattr(app, "vacuglide", None), app)


class Editor:
    def __init__(self, root, output=None, app=None):
        self.window = tk.Toplevel(root)
        self.window.title("VacuGlide Interface")
        self.window.geometry("980x790")
        self.window.minsize(860, 730)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.script = Script("Untitled VacuGlide script", 60000)
        self.preview = Preview(self.script)
        self.path = None
        self.dirty = False
        self.cursor_ms = 0
        self.last_tick = None
        self.job = None
        self.control = getattr(app, "vacuglide_control", None)
        if self.control is None and output is not None:
            self.control = VacuGlideControl(output, lambda: None)
        self.mode_job = None
        self.connection = None
        self.device_note = tk.StringVar()
        self.live_status = tk.StringVar()
        self.trim = tk.DoubleVar(value=self.control.trim if self.control else 0)
        self.last_chart_position = None
        self.last_speed_comparison = None
        self.playhead_drag = None
        self.status = tk.StringVar()
        self.readback = tk.StringVar()
        self.name = tk.StringVar()
        self.duration = tk.StringVar()
        self.description = tk.StringVar()
        self.director_approved = tk.BooleanVar()
        self.speed_stats = tk.StringVar()
        self.description.trace_add("write", self.mark_dirty)
        self.director_approved.trace_add("write", self.mark_dirty)
        self.kind = tk.StringVar(value="Speed")
        self.start = tk.StringVar(value="0:00")
        self.value = tk.StringVar(value="10")
        self.name.trace_add("write", self.mark_dirty)
        self.duration.trace_add("write", self.mark_dirty)
        self.build()
        if self.control is not None:
            self.control.catalog_load_guard = lambda: not self.dirty
        if self.control is not None and self.control.catalog_selection is not None:
            self.sync_catalog_selection()
        else:
            self.load_example()
        if self.control is not None:
            self.refresh_device()

    def build(self):
        body = ttk.Frame(self.window, padding=14)
        body.pack(fill="both", expand=True)

        if self.control is not None:
            self.build_device_controls(body)

        bar = ttk.Frame(body)
        bar.pack(fill="x")
        for label, action in (
                ("New", self.new), ("Open...", self.open_file), ("Save", self.save),
                ("Save as...", self.save_as), ("Paste instructions...", self.paste),
                ("Three-minute example", self.load_example)):
            ttk.Button(bar, text=label, command=action).pack(side="left", padx=(0, 6))


        meta = ttk.Frame(body)
        meta.pack(fill="x", pady=(12, 6))
        ttk.Label(meta, text="Script name").pack(side="left", padx=(0, 5))
        name = ttk.Entry(meta, textvariable=self.name)
        name.pack(side="left", fill="x", expand=True, padx=(0, 12))
        name.bind("<Return>", self.apply_info)
        ttk.Label(meta, text="Duration").pack(side="left", padx=(0, 5))
        duration = ttk.Entry(meta, textvariable=self.duration, width=9)
        duration.pack(side="left", padx=(0, 6))
        duration.bind("<Return>", self.apply_info)
        ttk.Button(meta, text="Apply", command=self.apply_info).pack(side="left")

        details = ttk.Frame(body)
        details.pack(fill="x", pady=(0, 6))
        ttk.Label(details, text="Description").pack(side="left", padx=(0, 6))
        ttk.Entry(details, textvariable=self.description).pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Checkbutton(details, text="Available to Gwendolyn", variable=self.director_approved).pack(side="left")
        ttk.Label(details, textvariable=self.speed_stats, width=26).pack(side="right", padx=(6, 0))

        chart_row = ttk.Frame(body)
        chart_row.pack(fill="x")
        self.canvas = tk.Canvas(chart_row, height=235, background="#f8fafc",
                                highlightthickness=1, highlightbackground="#cfdae4")
        self.canvas.pack(side="left", fill="x", expand=True)
        if self.control is not None:
            self.speed_meters = tk.Canvas(chart_row, width=218, height=235, background="#f8fafc",
                                         highlightthickness=1, highlightbackground="#cfdae4")
            self.speed_meters.pack(side="right", padx=(8, 0))
        self.canvas.bind("<Configure>", lambda _: self.draw())
        self.canvas.bind("<Button-1>", self.begin_scrub)
        self.canvas.bind("<B1-Motion>", self.drag_scrub)
        self.canvas.bind("<ButtonRelease-1>", self.end_scrub)
        self.canvas.bind("<Double-Button-1>", self.stage_on_timeline)
        ttk.Label(body, text="Click or drag to move the playhead. Double-click a track to prepare an event.",
                  foreground="#526373").pack(anchor="w", pady=(3, 0))

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(6, 10))
        ttk.Button(controls, text="Reset", command=self.reset).pack(side="left", padx=(0, 6))
        self.play_button = ttk.Button(controls, text="Play preview", width=13, command=self.toggle_preview)
        self.play_button.pack(side="left", padx=(0, 12))
        if self.control is None:
            ttk.Label(controls, text="Preview trim (%)").pack(side="left")
            ttk.Scale(controls, from_=0, to=100, variable=self.trim, length=105,
                      command=lambda _: self.draw()).pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.readback, width=72).pack(side="left", padx=(6, 0))

        table = ttk.Frame(body)
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=("time", "track", "value"), show="headings", height=6)
        for key, title, width in (("time", "Start", 100), ("track", "Track", 145), ("value", "Speed or duration", 145)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w", stretch=True)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", self.select_event)
        self.tree.bind("<Delete>", lambda _: self.delete_event())
        for kind, color in COLORS.items():
            self.tree.tag_configure(kind, foreground=color)

        form = ttk.Frame(body)
        form.pack(fill="x", pady=(8, 5))
        ttk.Label(form, text="Track").pack(side="left")
        ttk.Combobox(form, textvariable=self.kind, values=tuple(LABEL_TO_KIND),
                     state="readonly", width=12).pack(side="left", padx=(5, 12))
        ttk.Label(form, text="Start").pack(side="left")
        ttk.Entry(form, textvariable=self.start, width=11).pack(side="left", padx=(5, 12))
        ttk.Label(form, text="Speed % or valve seconds").pack(side="left")
        ttk.Entry(form, textvariable=self.value, width=9).pack(side="left", padx=(5, 10))
        ttk.Button(form, text="Add", command=lambda: self.edit_event(False)).pack(side="left", padx=(0, 5))
        ttk.Button(form, text="Update selected", command=lambda: self.edit_event(True)).pack(side="left", padx=(0, 5))
        ttk.Button(form, text="Delete", command=self.delete_event).pack(side="left")
        ttk.Label(body, textvariable=self.status, foreground="#526373", width=105, wraplength=780).pack(anchor="w")

    def build_device_controls(self, parent):
        panel = ttk.LabelFrame(parent, text="VacuGlide output", padding=(8, 5))
        panel.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        self.token = tk.StringVar()
        try:
            self.token.set(load_token())
        except (OSError, ValueError):
            self.device_note.set("Could not read the remembered token.")
        self.remember = tk.BooleanVar(value=bool(self.token.get()))
        self.claim_cap = tk.StringVar(value="30")
        ttk.Label(row, text="Device token").pack(side="left")
        self.token_entry = ttk.Entry(row, textvariable=self.token, width=25, show="*")
        self.token_entry.pack(side="left", padx=5)
        ttk.Checkbutton(row, text="Remember", variable=self.remember,
                        command=self.remember_changed).pack(side="left", padx=(0, 10))
        ttk.Label(row, text="Device cap %").pack(side="left")
        self.cap_entry = ttk.Entry(row, textvariable=self.claim_cap, width=5)
        self.cap_entry.pack(side="left", padx=5)
        self.connect_button = ttk.Button(row, width=13, text="Connect", command=self.toggle_connection)
        self.connect_button.pack(side="left", padx=5)

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        self.selected_source = tk.StringVar(value=self.control.mode)
        self.source_buttons = {}
        for mode, label in MODES.items():
            button = ttk.Radiobutton(row, text=f"Follow {label}", variable=self.selected_source,
                                     value=mode, command=lambda value=mode: self.select_mode(value))
            button.pack(side="left", padx=(0, 5))
            self.source_buttons[mode] = button
        self.mapped_source_indicator = ttk.Radiobutton(
            row, variable=self.selected_source, value="mapped", state="disabled")
        self.play_live_button = ttk.Button(row, width=9, text="Start", command=self.toggle_output)
        self.play_live_button.pack(side="left", padx=(6, 0))

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        state = self.control.output.state()
        self.trim_low = tk.StringVar(value=f"{state['director_min_speed_percent']:g}")
        self.trim_high = tk.StringVar(value=f"{state['director_max_speed_percent']:g}")
        self.trim_label = tk.StringVar()
        self.speed_setting = tk.DoubleVar(value=self.control.manual_speed)
        self.speed_label = tk.StringVar()
        ttk.Label(row, text="Trim").pack(side="left")
        trim_length = 130
        self.trim_scale = ttk.Scale(row, variable=self.trim, length=trim_length,
                                   command=self.trim_changed)
        self.trim_scale.pack(side="left", padx=5)
        ttk.Label(row, textvariable=self.trim_label, width=7).pack(side="left")
        ttk.Label(row, text="Gwendolyn min / max %").pack(side="left")
        for value in (self.trim_low, self.trim_high):
            entry = ttk.Entry(row, textvariable=value, width=5)
            entry.pack(side="left", padx=(5, 0))
            entry.bind("<Return>", lambda _: self.save_limits())
        ttk.Button(row, text="Set limits", command=self.save_limits).pack(side="left", padx=6)
        ttk.Label(row, text="Manual speed").pack(side="left", padx=(10, 0))
        self.speed_scale = ttk.Scale(row, from_=0, to=30, variable=self.speed_setting, length=112,
                                    command=self.speed_changed)
        self.speed_scale.pack(side="left", padx=5)
        ttk.Label(row, textvariable=self.speed_label, width=7).pack(side="left")

        row = ttk.Frame(panel)
        row.pack(fill="x", pady=2)
        for kind, label in (("minus", "Stroke −"), ("plus", "Stroke +")):
            ttk.Button(row, text=label, command=lambda value=kind: self.pulse_valve(value)).pack(
                side="left", padx=(0, 5))
        ttk.Label(row, text="Vacuum automation").pack(side="left", padx=(12, 5))
        self.automation = tk.StringVar(value=self.control.automation)
        for level in VACUUM_INTERVALS:
            ttk.Radiobutton(row, variable=self.automation, value=level, text=level,
                           command=lambda: self.control.set_automation(self.automation.get())).pack(
                               side="left", padx=(0, 5))

        motion = self.control.motion
        self.averaging_seconds = tk.DoubleVar(value=motion.speed_window)
        self.averaging_label = tk.StringVar(value=f"{motion.speed_window:.1f} s")
        ttk.Label(row, text="Funscript averaging").pack(side="left", padx=(12, 0))
        self.averaging_scale = ttk.Scale(row, from_=motion.MIN_SPEED_WINDOW, to=motion.MAX_SPEED_WINDOW,
                                         variable=self.averaging_seconds, length=98,
                                         command=self.averaging_changed)
        self.averaging_scale.pack(side="left", padx=5)
        ttk.Label(row, textvariable=self.averaging_label, width=6).pack(side="left")

        for value, color in ((self.live_status, "#27546b"), (self.device_note, "#8a5a00")):
            status_row = ttk.Frame(panel, height=32)
            status_row.pack(fill="x")
            status_row.pack_propagate(False)
            ttk.Label(status_row, textvariable=value, foreground=color, wraplength=780).pack(anchor="w")

    def remember_changed(self):
        if not self.remember.get():
            try:
                forget_token()
            except OSError:
                self.device_note.set("Could not remove the saved token.")

    def toggle_connection(self):
        if self.connection is not None:
            return
        self.device_note.set("")
        try:
            if self.control.output.state()["ownership"] == "vector":
                self.connection = (self.control.pause("Disconnected", release=True), None)
            else:
                token = self.token.get().strip()
                future = self.control.output.arm(token, float(self.claim_cap.get()))
                self.connection = (future, token if self.remember.get() else None)
        except ValueError as exc:
            self.device_note.set(str(exc))

    def trim_changed(self, value):
        self.control.set_trim(round(float(value), 1))
        self.draw()

    def speed_changed(self, value):
        self.control.manual_speed = round(float(value), 1)

    def averaging_changed(self, value):
        seconds = round(float(value), 1)
        self.control.motion.set_speed_window(seconds)
        self.averaging_label.set(f"{seconds:.1f} s")

    def save_limits(self):
        try:
            self.control.save_range(float(self.trim_low.get()), float(self.trim_high.get()))
            self.device_note.set("Gwendolyn trim limits saved.")
        except (OSError, ValueError) as exc:
            self.device_note.set(str(exc))

    def select_mode(self, mode):
        try:
            if (mode in SCRIPT_MODES and not (self.control.playing and self.control.mode in SCRIPT_MODES)
                    and not self.apply_info()):
                return
            self.control.select(mode, self.preview)
            self.device_note.set("")
        except ValueError as exc:
            self.device_note.set(str(exc))
        finally:
            self.refresh_source_selection()

    def refresh_source_selection(self):
        control = self.control
        if control.mapped_source:
            self.mapped_source_indicator.configure(text=control.source_name)
            if not self.mapped_source_indicator.winfo_manager():
                self.mapped_source_indicator.pack(side="left", before=self.play_live_button)
            selected = "mapped"
        else:
            self.mapped_source_indicator.pack_forget()
            selected = control.mode
        if self.selected_source.get() != selected:
            self.selected_source.set(selected)

    def toggle_output(self):
        try:
            if self.control.playing:
                self.control.pause()
            elif self.control.mode not in SCRIPT_MODES or self.apply_info():
                self.pause()
                self.control.start(self.preview)
            self.device_note.set("")
        except ValueError as exc:
            self.device_note.set(str(exc))

    def pulse_valve(self, kind):
        try:
            self.control.stroke(kind)
            self.device_note.set("")
        except ValueError as exc:
            self.device_note.set(str(exc))

    def sync_catalog_selection(self):
        selection = self.control.catalog_selection
        if selection is not None:
            self.control.catalog_selection = None
            path, script, preview = selection
            self.set_script(script, path, preview=preview)

    def refresh_device(self):
        self.sync_catalog_selection()
        control = self.control
        state = control.output.state()
        if self.connection is not None:
            future, token = self.connection
            if future.done():
                self.connection = None
                try:
                    receipt = future.result()[1]
                    if not receipt.get("ok"):
                        self.device_note.set(receipt.get("error") or "Device command failed.")
                    elif token and self.remember.get():
                        save_token(token)
                    elif state["ownership"] == "vector" and not self.remember.get():
                        self.token.set("")
                except (OSError, ValueError):
                    self.device_note.set("Could not complete the device or token operation.")
        connected = state["ownership"] == "vector"
        self.connect_button.configure(text="Disconnect" if connected else "Connect")
        self.connect_button.state(["disabled" if self.connection is not None else "!disabled"])
        for entry in (self.token_entry, self.cap_entry):
            entry.state(["disabled" if connected or self.connection is not None else "!disabled"])
        self.refresh_source_selection()
        self.play_live_button.configure(text="Pause" if control.playing else "Start")
        self.play_live_button.state(["!disabled" if connected and not control.stopping else "disabled"])
        low = state["director_min_speed_percent"]
        high = state["director_max_speed_percent"]
        cap = state["max_speed_percent"]
        self._set_scale(self.trim_scale, low, high)
        self._set_scale(self.speed_scale, 0, cap if cap is not None else 100)
        if cap is not None and control.manual_speed > cap:
            control.manual_speed = cap
        comparison = control.director_state(state)
        applied_trim = comparison["trim_percent"]
        trim_changed = self.trim.get() != applied_trim
        if trim_changed:
            self.trim.set(applied_trim)
        if self.speed_setting.get() != control.manual_speed:
            self.speed_setting.set(control.manual_speed)
        self.trim_label.set(f"{applied_trim:g}%")
        self.speed_label.set(f"{control.manual_speed:g}%")
        self.live_status.set(control.status(state))
        active = comparison["active_speed_source"]
        targets = comparison["targets_percent"]
        meters = (active, control.mode, control.source_name, tuple(targets.values()))
        if meters != self.last_speed_comparison:
            self.last_speed_comparison = meters
            self.draw_speed_meters(targets, active, control.mode)
        follows_script = control.mode in SCRIPT_MODES and (control.playing or control.stopping)
        if control.mode == "mfp":
            position = comparison["script_position_ms"]
        else:
            position = control.position_ms if follows_script else None
        if position is not None and self.job is None and self.playhead_drag is None:
            self.cursor_ms = position
        if trim_changed or position != self.last_chart_position:
            self.last_chart_position = position
            self.draw()
        self.mode_job = self.window.after(100, self.refresh_device)

    def draw_speed_meters(self, targets, active, mode):
        canvas = self.speed_meters
        canvas.delete("all")
        canvas.create_text(109, 16, text="Target speed", font="TkHeadingFont", fill="#21384c")
        top, bottom = 50, 176
        for percent in (0, 50, 100):
            y = bottom - (bottom - top) * percent / 100
            canvas.create_text(32, y, text=f"{percent}%", anchor="e", fill="#526373")
        for x, (source, label) in zip((62, 124, 185),
                                      (("script", "Script"), ("mfp", "Funscript"), ("manual", "Manual"))):
            selected = active == source
            color = "#117a6a" if selected else "#759ab4"
            speed = targets[source]
            height = (bottom - top) * speed / 100
            if source == ("mfp" if mode == "blend" else mode):
                background = "#e4f3ef" if selected else "#edf1f5"
                canvas.create_rectangle(x - 29, 27, x + 29, 200, fill=background, outline="")
            canvas.create_rectangle(x - 12, top, x + 12, bottom, fill="#e6edf3", outline="")
            if height > 0:
                canvas.create_rectangle(x - 12, bottom - height, x + 12, bottom, fill=color, outline="")
            canvas.create_text(x, 37, text=f"{speed:g}%", fill="#21384c")
            canvas.create_text(x, 190, text=label, fill=color if selected else "#526373")
        caption = f"Active: {self.control.source_name}" if active else f"Selected: {self.control.source_name}"
        canvas.create_text(109, 217, text=caption, fill="#27546b")

    @staticmethod
    def _set_scale(scale, low, high):
        if float(scale.cget("from")) != low or float(scale.cget("to")) != high:
            scale.configure(from_=low, to=high)

    def mark_dirty(self, *_):
        self.dirty = True

    def close(self):
        if self.connection is not None:
            self.device_note.set("Wait for the connection change to finish.")
            return
        if self.control is not None and (self.control.playing or self.control.timed_pause_active):
            self.control.pause()
        if self.confirm_discard():
            self.pause()
            if self.mode_job is not None:
                self.window.after_cancel(self.mode_job)
            if self.control is not None:
                self.control.catalog_load_guard = None
            self.window.destroy()

    def editing_available(self):
        if self.control is not None and self.control.playing and self.control.mode in SCRIPT_MODES:
            self.status.set("Pause playback before editing or opening a script.")
            return False
        return True

    def confirm_discard(self, *, replacing_live=False):
        if not replacing_live and not self.editing_available():
            return False
        if not self.dirty:
            return True
        choice = messagebox.askyesnocancel("Unsaved script", "Save changes before continuing?", parent=self.window)
        return choice is not None and (not choice or self.save(apply_changes=not replacing_live))

    def set_script(self, script, path=None, *, dirty=False, preview=None):
        self.pause()
        self.playhead_drag = None
        self.cursor_ms = 0
        self.script, self.path = script, path
        if self.control is None:
            self.trim.set(max((event.speed_percent for event in script.events if event.kind == "speed"), default=0))
        self.name.set(script.name)
        self.duration.set(time_text(script.duration_ms))
        self.description.set(script.description)
        self.director_approved.set(script.director_approved)
        self.dirty = dirty
        self.refresh(preview=preview)
        self.status.set(script.source_note or "Ready")

    def new(self):
        if self.confirm_discard():
            self.set_script(Script("Untitled VacuGlide script", 60000))

    def load_example(self):
        if self.confirm_discard():
            try:
                self.set_script(Script.load(EXAMPLE))
            except (OSError, ValueError) as exc:
                self.error(exc)

    def folder(self):
        path = self.control.catalog_folder if self.control is not None else settings_path().parent / "VacuglideScripts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def follows_script_live(self):
        return self.control is not None and self.control.playing and self.control.mode == "script"

    def open_file(self):
        if not self.confirm_discard(replacing_live=self.follows_script_live()):
            return
        try:
            selected = filedialog.askopenfilename(parent=self.window, initialdir=self.folder(),
                                                  filetypes=[("VacuGlide scripts", "*.json")])
            if selected:
                script = Script.load(selected)
                preview = Preview(script)
                if self.follows_script_live():
                    self.control.replace_script(preview)
                self.set_script(script, Path(selected), preview=preview)
        except (OSError, ValueError) as exc:
            self.error(exc)

    def apply_info(self, _=None):
        if not self.editing_available():
            return False
        try:
            updated = self.edited_script(self.script.events)
        except ValueError as exc:
            self.error(exc)
            return False
        if updated != self.script:
            self.script = updated
            self.dirty = True
            self.cursor_ms = min(self.cursor_ms, self.script.duration_ms)
            self.refresh()
        return True

    def edited_script(self, events):
        return replace(self.script, name=self.name.get().strip(),
                       duration_ms=parse_time(self.duration.get()), events=tuple(events),
                       description=self.description.get().strip(), director_approved=self.director_approved.get())

    def save(self, *, apply_changes=True):
        if self.path is None or self.path.resolve() == EXAMPLE.resolve():
            return self.save_as(apply_changes=apply_changes)
        return self.write_file(self.path, apply_changes=apply_changes)

    def save_as(self, *, apply_changes=True):
        if apply_changes and not self.apply_info():
            return False
        try:
            default = "".join(c for c in self.script.name if c.isalnum() or c in " -_").strip() or "VacuGlide script"
            selected = filedialog.asksaveasfilename(parent=self.window, initialdir=self.folder(),
                                                    initialfile=default + ".json", defaultextension=".json",
                                                    filetypes=[("VacuGlide scripts", "*.json")])
            if selected and Path(selected).resolve() == EXAMPLE.resolve():
                raise ValueError("Choose a different filename for your editable copy.")
            return bool(selected and self.write_file(Path(selected), apply_changes=apply_changes))
        except (OSError, ValueError) as exc:
            self.error(exc)
            return False

    def write_file(self, path, *, apply_changes=True):
        if apply_changes and not self.apply_info():
            return False
        try:
            self.script.save(path)
        except (OSError, ValueError) as exc:
            self.error(exc)
            return False
        self.path, self.dirty = path, False
        self.update_controller_script()
        self.status.set(f"Saved {path.name}")
        return True

    def paste(self):
        if not self.confirm_discard():
            return
        popup = tk.Toplevel(self.window)
        popup.title("Paste VacuGlide instructions")
        popup.transient(self.window)
        popup.grab_set()
        frame = ttk.Frame(popup, padding=12)
        frame.pack(fill="both", expand=True)
        name = tk.StringVar(value="Imported VacuGlide script")
        scale = tk.BooleanVar(value=True)
        ttk.Entry(frame, textvariable=name).pack(fill="x", pady=(0, 8))
        ttk.Label(frame, text="Paste the action, time, and duration rows from Script instructions.").pack(anchor="w")
        area = tk.Text(frame, width=72, height=18, wrap="word")
        area.pack(fill="both", expand=True, pady=6)
        area.focus_set()
        ttk.Checkbutton(frame, text="Scale source speeds into 0–25%", variable=scale).pack(anchor="w")

        def apply():
            try:
                script = import_instructions(area.get("1.0", "end-1c"), name.get().strip(), scale_to_25=scale.get())
            except ValueError as exc:
                messagebox.showerror("Import instructions", str(exc), parent=popup)
            else:
                popup.destroy()
                self.set_script(script, dirty=True)

        ttk.Button(frame, text="Import as editable script", command=apply).pack(anchor="e", pady=(8, 0))

    def error(self, error):
        messagebox.showerror("VacuGlide Script Editor", str(error), parent=self.window)

    def selected_index(self):
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def select_event(self, _=None):
        index = self.selected_index()
        if index is not None:
            event = self.script.events[index]
            self.kind.set(LABELS[event.kind])
            self.start.set(time_text(event.start_ms))
            self.value.set(f"{event.speed_percent:g}" if event.kind == "speed" else f"{event.duration_ms / 1000:g}")
            self.draw()

    def edit_event(self, overwrite):
        if not self.editing_available():
            return
        index = self.selected_index() if overwrite else None
        if overwrite and index is None:
            self.error("Select a row to update.")
            return
        try:
            kind = LABEL_TO_KIND[self.kind.get()]
            start = parse_time(self.start.get())
            value = self.value.get().strip()
            event = Event(start, kind, float(value)) if kind == "speed" else Event(start, kind, duration_ms=parse_time(value))
            events = list(self.script.events)
            if index is not None:
                events[index] = event
            else:
                events.append(event)
            self.script = self.edited_script(events)
        except (ValueError, OverflowError) as exc:
            self.error(exc)
            return
        self.dirty = True
        self.refresh(self.script.events.index(event))
        self.status.set("Event updated" if overwrite else "Event added")

    def delete_event(self):
        if not self.editing_available():
            return
        index = self.selected_index()
        if index is None:
            return
        self.script = replace(self.script, events=self.script.events[:index] + self.script.events[index + 1:])
        self.dirty = True
        self.refresh()
        self.status.set("Event deleted")

    def update_controller_script(self):
        if self.control is None:
            return
        in_library = self.path and self.path.resolve().parent == self.control.catalog_folder.resolve()
        script_id = self.path.name if in_library and not self.dirty else None
        self.control.update_loaded_preview(self.preview, script_id)

    def refresh(self, selected=None, *, preview=None):
        self.preview = Preview(self.script) if preview is None else preview
        self.update_controller_script()
        average, peak = self.script.speed_stats()
        self.speed_stats.set(f"Average {average:g}%  ·  Peak {peak:g}%")
        self.tree.delete(*self.tree.get_children())
        for index, event in enumerate(self.script.events):
            value = f"{event.speed_percent:g}%" if event.kind == "speed" else f"{event.duration_ms / 1000:g} s"
            self.tree.insert("", "end", iid=str(index), values=(time_text(event.start_ms), LABELS[event.kind], value),
                             tags=(event.kind,))
        if selected is not None:
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))
        self.draw()

    def chart_geometry(self):
        left, right = 74, max(75, self.canvas.winfo_width() - 22)
        speed_top, speed_bottom = 20, 135
        peak = max((event.speed_percent for event in self.preview.tracks["speed"]), default=0)
        shown_peak = self.trim.get()
        y_max = 100 if max(peak, shown_peak) > 25 else 25
        return left, right, speed_top, speed_bottom, y_max

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        left, right, top, bottom, y_max = self.chart_geometry()
        duration = self.script.duration_ms
        delta = right - left

        def x_at(ms):
            return left + delta * ms / duration

        def y_at(speed):
            return bottom - (bottom - top) * speed / y_max

        canvas.create_rectangle(left, top, right, bottom, fill="#ffffff", outline="")
        for i in range(6):
            value = i * y_max / 5
            y = y_at(value)
            canvas.create_line(left, y, right, y, fill="#deebf2")
            canvas.create_text(left - 9, y, text=f"{value:g}%", anchor="e", fill="#526373")
        for i in range(7):
            ms = duration * i // 6
            x = x_at(ms)
            canvas.create_line(x, top, x, 207, fill="#e2eaf2")
            canvas.create_text(x, 218, text=time_text(ms - ms % 1000) if duration >= 10000 else time_text(ms),
                               fill="#526373")

        state = self.control.output.state() if self.control is not None else None
        live = self.control is not None and self.control.playing and self.control.mode in SCRIPT_MODES
        cap = state["max_speed_percent"] if state else None
        ceiling = cap if cap is not None else 100
        requested_peak = self.trim.get()
        effective_peak = min(ceiling, requested_peak)
        authored_peak = max((event.speed_percent for event in self.preview.tracks["speed"]), default=0)
        gain = effective_peak / authored_peak if authored_peak else 0
        selected = self.selected_index()
        target = self.script.events[selected] if selected is not None else None
        for kind, y in (("minus", 153), ("plus", 181)):
            canvas.create_rectangle(left, y, right, y + 20, fill="#edf3f8", outline="")
            canvas.create_text(left - 9, y + 10, text=LABELS[kind], anchor="e", fill=COLORS[kind])
            for event in self.preview.tracks[kind]:
                x0, x1 = x_at(event.start_ms), x_at(event.end_ms)
                canvas.create_rectangle(x0, y, max(x0 + 2, x1), y + 20, fill=COLORS[kind],
                                        outline="#132c40" if event is target else "", width=2)
        steps = self.preview.tracks["speed"]
        coords = [left, y_at(0)]
        speed = 0
        for event in steps:
            pos = x_at(event.start_ms)
            coords.extend((pos, y_at(speed)))
            speed = event.speed_percent
            coords.extend((pos, y_at(speed)))
        coords.extend((right, y_at(speed)))
        canvas.create_line(*coords, fill=COLORS["speed"], width=2)
        if abs(gain - 1) > .001:
            applied = [left, y_at(0)]
            speed = 0
            for event in steps:
                pos = x_at(event.start_ms)
                applied.extend((pos, y_at(speed)))
                speed = min(ceiling, event.speed_percent * gain)
                applied.extend((pos, y_at(speed)))
            applied.extend((right, y_at(speed)))
            canvas.create_line(*applied, fill="#117a6a", dash=(4, 3), width=2)
        if target is not None and target.kind == "speed":
            x, y = x_at(target.start_ms), y_at(target.speed_percent)
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill="#132c40", outline="")
        cursor = x_at(self.cursor_ms)
        canvas.create_line(cursor, top, cursor, 205, fill="#20394e", width=1)
        speed, minus, plus = self.preview.at(self.cursor_ms, ceiling=ceiling, gain=gain)
        valves = " + ".join(label for active, label in ((minus, "Stroke −"), (plus, "Stroke +")) if active)
        valve_status = "Valve track preview only" if live else valves or "Valves closed"
        if live:
            valve_states = state["valves"]
            if any(value is None for value in valve_states.values()):
                valve_status = "Valve state awaiting confirmation"
            else:
                opened = [LABELS[kind] for kind, value in valve_states.items() if value]
                valve_status = f"{' / '.join(opened)} open" if opened else "Both valves confirmed closed"
        self.readback.set(f"{time_text(self.cursor_ms)} / {time_text(duration)}   ·   Trim {requested_peak:g}% peak   ·   "
                          f"{speed:g}% target   ·   {valve_status}")

    def point_to_time(self, x):
        left, right, *_ = self.chart_geometry()
        clamped = min(right, max(left, x))
        return round(self.script.duration_ms * (clamped - left) / (right - left))

    def begin_scrub(self, event):
        self.pause()
        self.playhead_drag = self.preview
        self.drag_scrub(event)

    def drag_scrub(self, event):
        if self.playhead_drag is None:
            return
        self.cursor_ms = self.point_to_time(event.x)
        self.draw()

    def end_scrub(self, event):
        if self.playhead_drag is not self.preview:
            self.playhead_drag = None
            return
        self.playhead_drag = None
        self.cursor_ms = self.point_to_time(event.x)
        if self.control is not None and self.control.mode in PLAYHEAD_MODES:
            try:
                self.cursor_ms = self.control.seek(self.preview, self.cursor_ms)
            except ValueError as exc:
                self.device_note.set(str(exc))
        self.draw()

    def stage_on_timeline(self, event):
        if not self.editing_available():
            self.begin_scrub(event)
            return
        _, _, top, bottom, y_max = self.chart_geometry()
        position = min(self.point_to_time(event.x), self.script.duration_ms - 1)
        if top <= event.y <= bottom:
            self.kind.set("Speed")
            self.value.set(f"{(bottom - event.y) * y_max / (bottom - top):.1f}")
        elif 153 <= event.y <= 201:
            self.kind.set("Stroke -" if event.y < 180 else "Stroke +")
            self.value.set(f"{min(1000, self.script.duration_ms - position) / 1000:g}")
        else:
            return
        selection = self.tree.selection()
        if selection:
            self.tree.selection_remove(*selection)
        self.start.set(time_text(position))
        self.status.set("Check the event fields, then click Add.")
        self.draw()

    def toggle_preview(self):
        if self.last_tick is not None:
            self.pause()
            return
        if not self.apply_info():
            return
        if self.cursor_ms >= self.script.duration_ms:
            self.cursor_ms = 0
        self.last_tick = monotonic()
        self.preview_start_ms = self.cursor_ms
        self.play_button.configure(text="Pause preview")
        self.tick()

    def tick(self):
        self.job = None
        position = self.preview_start_ms + round((monotonic() - self.last_tick) * 1000)
        self.cursor_ms = min(position, self.script.duration_ms)
        self.draw()
        if self.cursor_ms >= self.script.duration_ms:
            self.pause()
        else:
            self.job = self.window.after(40, self.tick)

    def pause(self):
        if self.job is not None:
            self.window.after_cancel(self.job)
            self.job = None
        self.last_tick = None
        self.play_button.configure(text="Play preview")

    def reset(self):
        if not self.editing_available():
            return
        self.pause()
        self.cursor_ms = 0
        if self.control is not None and (self.control.mode == "mfp" or
                                         (not self.control.playing and self.control.mode in SCRIPT_MODES)):
            self.control.seek(self.preview, 0)
        self.draw()
