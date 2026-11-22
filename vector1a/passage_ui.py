"""Passage workbench: preview never writes to the output engine."""
import tkinter as tk
from tkinter import ttk, messagebox
from .passage import PassagePlan
from .sequence_ui import show_sequences
from .generated_motion import MotionPlan, PATTERNS


def add_passage_controls(app, body):
    card = body.grid_slaves(row=1, column=0)[0]
    ttk.Button(card, text="Passages / generated motion...",
               command=lambda: show_sequences(app)).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))


def show_passages(app):
    old = getattr(app, "_passage_window", None)
    if old is not None and old.winfo_exists():
        old.lift()
        return
    window = tk.Toplevel(app.root)
    app._passage_window = window
    window.title("Vector - passage and motion workbench")
    window.geometry("880x740")
    window.minsize(780, 520)
    shell = ttk.Frame(window)
    shell.pack(fill="both", expand=True)
    scroll_canvas = tk.Canvas(shell, highlightthickness=0, yscrollincrement=24)
    scrollbar = ttk.Scrollbar(shell, orient="vertical", command=scroll_canvas.yview)
    scroll_canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    scroll_canvas.pack(side="left", fill="both", expand=True)
    body = ttk.Frame(scroll_canvas, padding=14)
    content = scroll_canvas.create_window(0, 0, window=body, anchor="nw")
    body.bind("<Configure>", lambda event: scroll_canvas.configure(scrollregion=scroll_canvas.bbox("all")))
    scroll_canvas.bind("<Configure>", lambda event: scroll_canvas.itemconfigure(content, width=event.width))
    def wheel(event):
        if event.widget.winfo_class() not in ('Entry', 'TEntry', 'TCombobox', 'Spinbox', 'TSpinbox'):
            scroll_canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
    window.bind('<MouseWheel>', wheel, add='+')
    body.columnconfigure(1, weight=1)
    ttk.Label(body, text="Build a passage", font=("TkDefaultFont", 13, "bold")).grid(row=0, column=0, columnspan=4, sticky="w")
    ttk.Label(body, text="Factors scale current volume after textures, authored channels and events. 100% is the existing output.\n"
              "Completion retains the last factor. Restore returns smoothly to 100%. Stop clears the passage.",
              wraplength=800).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 10))
    variables = {}
    values = [("label", "Narrative intention", "Patient build and release"),
              ("build_seconds", "Build seconds", "60"), ("hold_seconds", "Hold seconds", "30"),
              ("release_seconds", "Release seconds", "60"), ("floor", "Floor factor (0-1)", "0.50"),
              ("peak", "Peak factor (0-1)", "1.0"), ("transition_seconds", "Transition seconds", "5")]
    for row, (key, label, default) in enumerate(values, 2):
        variables[key] = tk.StringVar(value=default)
        ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(body, textvariable=variables[key], width=40 if key == "label" else 12).grid(row=row, column=1, columnspan=3, sticky="ew" if key == "label" else "w")
    for row, (key, options, default) in enumerate((("clock", ("elapsed", "media"), "elapsed"),
                                                 ("target", ("primary", "both"), "primary")), 9):
        variables[key] = tk.StringVar(value=default)
        ttk.Label(body, text=key.title()).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(body, values=options, textvariable=variables[key], state="readonly", width=12).grid(row=row, column=1, sticky="w")
    ttk.Label(body, text="Media follows the player; pause freezes, seek holds until Resume. Elapsed follows running time.",
              wraplength=790).grid(row=11, column=0, columnspan=4, sticky="w", pady=5)
    canvas = tk.Canvas(body, height=125, background="#13202e", highlightthickness=0)
    canvas.grid(row=12, column=0, columnspan=4, sticky="ew", pady=5)
    status = tk.StringVar(value="Preview a plan, then apply when Vector is running.")

    def plan():
        return PassagePlan.validated({key: value.get() for key, value in variables.items()})

    def draw(_event=None):
        try:
            candidate = plan()
            width = max(400, canvas.winfo_width())
            canvas.delete("all")
            canvas.create_line(30, 15, width-20, 15, fill="#46586a", dash=(3, 3))
            points = []
            for item in candidate.preview():
                points.extend((30 + (width-50)*item["seconds"]/candidate.duration, 105-90*item["factor"]))
            canvas.create_line(*points, fill="#50d3b4", width=3)
            canvas.create_text(35, 115, anchor="w", fill="white", text="0s")
            canvas.create_text(width-20, 115, anchor="e", fill="white", text=f"{candidate.duration:g}s - target contour; live factor slews from its current value")
        except ValueError as exc:
            status.set(str(exc))

    def perform(action):
        try:
            if action == "apply":
                state = app.engine.control_state()
                if state["engine_state"] != "Running" or not state["output_enabled"]:
                    raise ValueError("Start Vector manually before applying a passage")
                app.passage.apply(plan())
            elif action == "restore":
                app.passage.restore()
            else:
                getattr(app.passage, action)()
        except ValueError as exc:
            messagebox.showerror("Passage", str(exc), parent=window)

    buttons = ttk.Frame(body)
    buttons.grid(row=13, column=0, columnspan=4, sticky="w", pady=5)
    ttk.Button(buttons, text="Preview", command=draw).pack(side="left", padx=(0, 5))
    for label, action in (("Apply passage", "apply"), ("Hold", "hold"), ("Resume passage", "resume"), ("Restore 100%", "restore")):
        ttk.Button(buttons, text=label, command=lambda a=action: perform(a)).pack(side="left", padx=3)
    ttk.Label(body, textvariable=status, wraplength=790).grid(row=14, column=0, columnspan=4, sticky="w", pady=5)
    motion = ttk.LabelFrame(body, text="Optional generated motion - replaces incoming authored motion", padding=8)
    motion.grid(row=15, column=0, columnspan=4, sticky="ew", pady=(8, 0))
    motion_vars = {}
    for col, (key, label, default) in enumerate((("minimum", "Min", "0.20"), ("maximum", "Max", "0.80"),
                                               ("stroke_duration_ms", "Stroke ms", "750"), ("variation", "Variation 0-1", "0.50"))):
        motion_vars[key] = tk.StringVar(value=default)
        ttk.Label(motion, text=label).grid(row=0, column=col, sticky="w")
        ttk.Entry(motion, textvariable=motion_vars[key], width=13).grid(row=1, column=col, padx=(0, 10))
    pattern = tk.StringVar(value="sine")
    ttk.Combobox(motion, values=PATTERNS, textvariable=pattern, state="readonly", width=12).grid(row=2, column=0, pady=8)

    def motion_plan():
        data = {key: value.get() for key, value in motion_vars.items()}
        data.update(pattern=pattern.get(), transition_seconds=5, duration_seconds=180, reason="Passage workbench")
        return MotionPlan.validated(data)

    def start_motion():
        try:
            state = app.engine.control_state()
            if state["engine_state"] != "Running" or not state["output_enabled"]:
                raise ValueError("Start Vector manually first")
            app.generated_motion.apply(motion_plan(), app.engine.diagnostics().output_l0)
        except ValueError as exc:
            messagebox.showerror("Generated motion", str(exc), parent=window)
    ttk.Button(motion, text="Start generated motion", command=start_motion).grid(row=2, column=1, columnspan=2, padx=8)
    ttk.Button(motion, text="Return to authored", command=app.generated_motion.authored).grid(row=2, column=3)
    ttk.Label(motion, text="Variation adds slow depth, centre and pace changes within the chosen limits. Zero retains the original pattern.",
              wraplength=760).grid(row=3, column=0, columnspan=4, sticky="w")

    waveform = tk.Canvas(motion, height=100, background="#13202e", highlightthickness=0)
    waveform.grid(row=5, column=0, columnspan=4, sticky="ew", pady=5)
    def draw_motion(event=None):
        try:
            candidate = motion_plan()
            width = max(400, waveform.winfo_width())
            waveform.delete("all")
            points = []
            for i in range(1501):
                seconds = i * .04
                lo, hi = candidate.bounds_at(seconds)
                value = lo + (hi-lo)*app.generated_motion._wave(candidate.pattern, candidate.phase_at(seconds))
                points.extend((10+(width-20)*i/1500, 85-75*value))
            waveform.create_line(*points, fill="#70b9ff", width=1)
            waveform.create_text(12, 93, anchor="w", text="60-second motion preview - does not start output", fill="white")
        except ValueError as exc:
            messagebox.showerror("Motion preview", str(exc), parent=window)
    ttk.Button(motion, text="Preview motion", command=draw_motion).grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
    waveform.bind('<Configure>', draw_motion)

    def refresh():
        if not window.winfo_exists():
            return
        state = app.passage.snapshot()
        label = (state["plan"] or {}).get("label", "")
        status.set(f"{label} | {state['phase']} | {state['elapsed_seconds']:.1f}s | "
                   f"primary {state['primary_factor']:.0%}, secondary {state['secondary_factor']:.0%} | "
                   + (state["reason"] or ("held" if state["held"] else "")))
        window.after(250, refresh)
    canvas.bind("<Configure>", draw)
    window.after(50, draw)
    refresh()
