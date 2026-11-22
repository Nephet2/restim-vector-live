"""Display recent T-code socket writes without interacting with the sender."""
import time
import tkinter as tk
from tkinter import ttk
from statistics import fmean

from .tcode import parse_message


AXES = {
    "V0": "Volume",
    "C0": "Frequency",
    "P0": "Pulse frequency",
    "P3": "Pulse rise time",
    "P1": "Pulse width",
    "L0": "L0",
    "L1": "L1",
    **{f"E{index}": f"E{index}" for index in range(1, 5)},
}
GAP_SECONDS = 0.25
TRACE_COLORS = dict(zip(AXES, (
    "#57c7ef", "#ffad63", "#8ddb95", "#f190c8", "#e4d06e",
    "#a89fff", "#f78073", "#50dec7", "#c99a74", "#9cc7ff", "#dce1ea",
)))


def trace_segments(history, axes, cutoff):
    """Break the trace at missing axes and between bursts of writes."""
    segments = {axis: [] for axis in axes}
    active = {axis: [] for axis in axes}
    for timestamp, message in history:
        if timestamp < cutoff:
            continue
        values = {command.axis: command.value * 100 for command in parse_message(message)}
        for axis, segment in active.items():
            value = values.get(axis)
            if segment and (value is None or timestamp - segment[-1][0] > GAP_SECONDS):
                segments[axis].append(segment)
                segment = active[axis] = []
            if value is not None:
                segment.append((timestamp, value))
    for axis, segment in active.items():
        if segment:
            segments[axis].append(segment)
    return segments


class SignalQualityPanel:
    def __init__(self, panel, primary, prostate):
        self.clients = {"Primary": primary, "Prostate": prostate}
        self.last_refresh = -float("inf")
        toolbar = ttk.Frame(panel)
        toolbar.pack(fill="x", pady=(0, 5))
        self.endpoint = self._selector(toolbar, "Output", tuple(self.clients), 11)
        self.span = self._selector(toolbar, "Window", ("10 s", "5 s", "30 s"), 6)
        axes_frame = ttk.LabelFrame(panel, text="Axes", padding=(5, 2))
        axes_frame.pack(fill="x", pady=(0, 5))
        self.axis_selected = {}
        self.axis_checks = {}
        for index, (axis, label) in enumerate(AXES.items()):
            if index in (0, 5):
                row = ttk.Frame(axes_frame)
                row.pack(fill="x")
            choice = ttk.Frame(row)
            choice.pack(side="left", padx=(0, 10))
            swatch = tk.Label(choice, background=TRACE_COLORS[axis], width=2,
                              relief="solid", borderwidth=1)
            swatch.pack(side="left", padx=(0, 3))
            selected = self.axis_selected[axis] = tk.BooleanVar(value=axis == "V0")
            check = self.axis_checks[axis] = ttk.Checkbutton(
                choice, text=label if label == axis else f"{axis} {label}",
                variable=selected, command=lambda: self.refresh(force=True))
            check.pack(side="left")
        self.summary = tk.StringVar(value="Waiting for T-code writes")
        ttk.Label(panel, textvariable=self.summary).pack(anchor="w", pady=(0, 5))
        self.canvas = tk.Canvas(panel, height=190, width=1, background="#172232",
                                highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _: self.refresh(force=True))
        stats_frame = ttk.Frame(panel)
        stats_frame.pack(fill="x", pady=(5, 0))
        columns = ("axis", "latest", "range", "step", "count")
        self.stats = ttk.Treeview(stats_frame, columns=columns, show="headings",
                                  selectmode="none", height=4)
        for column, title, width in zip(columns, ("Axis", "Latest", "Range", "Mean step", "Values"),
                                        (60, 75, 125, 95, 70)):
            self.stats.heading(column, text=title)
            self.stats.column(column, width=width, minwidth=45,
                              anchor="w" if column == "axis" else "e")
        scrollbar = ttk.Scrollbar(stats_frame, orient="vertical", command=self.stats.yview)
        self.stats.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.stats.pack(side="left", fill="x", expand=True)
        ttk.Label(panel, text="Successful socket writes · T-code scale 0–100 · Gaps show missing writes or axes",
                  foreground="#555", wraplength=640).pack(anchor="w", pady=(5, 0))

    def _selector(self, frame, label, choices, width):
        ttk.Label(frame, text=label).pack(side="left", padx=(0, 4))
        selector = ttk.Combobox(frame, values=choices, width=width, state="readonly")
        selector.pack(side="left", padx=(0, 12))
        selector.current(0)
        selector.bind("<<ComboboxSelected>>", lambda _: self.refresh(force=True))
        return selector

    def refresh(self, force=False):
        if not self.canvas.winfo_ismapped():
            return
        now = time.monotonic()
        if not force and now - self.last_refresh < 0.24:
            return
        self.last_refresh = now
        client = self.clients[self.endpoint.get()]
        seconds = int(self.span.get().split()[0])
        axes = tuple(axis for axis, selected in self.axis_selected.items() if selected.get())
        traces = trace_segments(client.tcode_history(), axes, now - seconds) if axes else {}
        state = "Connected" if client.connected else "Disconnected"
        message = (f"{state} · {len(axes)} selected" if axes
                   else f"{state} · Select an axis to plot")
        if axes and not any(traces.values()):
            message += f" · No writes for the selected axes in the last {seconds} s"
        self.summary.set(message)
        self._update_stats(traces)
        self._draw(traces, now, seconds)

    def _update_stats(self, traces):
        for axis in self.stats.get_children():
            if axis not in traces:
                self.stats.delete(axis)
        for index, (axis, segments) in enumerate(traces.items()):
            values = [value for segment in segments for _, value in segment]
            steps = [abs(right[1] - left[1]) for segment in segments
                     for left, right in zip(segment, segment[1:])]
            row = (axis, f"{values[-1]:.2f}" if values else "—",
                   f"{min(values):.2f}–{max(values):.2f}" if values else "—",
                   f"{fmean(steps):.3f}" if steps else "—", f"{len(values):,}")
            if self.stats.exists(axis):
                self.stats.item(axis, values=row)
            else:
                self.stats.insert("", index, iid=axis, values=row)

    def _draw(self, traces, now, seconds):
        canvas = self.canvas
        canvas.delete("all")
        left, right = 40, canvas.winfo_width() - 16
        top, bottom = 12, canvas.winfo_height() - 23
        if right <= left or bottom <= top:
            return
        for value in (0, 25, 50, 75, 100):
            y = bottom - (bottom - top) * value / 100
            canvas.create_line(left, y, right, y, fill="#34475c")
            canvas.create_text(left - 6, y, text=str(value), anchor="e", fill="#bdcad9")
        for tick in range(6):
            x = left + (right - left) * tick / 5
            label = f"−{seconds * (5 - tick) / 5:g} s" if tick < 5 else "Now"
            canvas.create_line(x, top, x, bottom, fill="#34475c")
            canvas.create_text(x, bottom + 12, text=label, fill="#bdcad9")
        for axis, segments in traces.items():
            color = TRACE_COLORS[axis]
            for segment in segments:
                points = [(right - (right - left) * max(0.0, now - ts) / seconds,
                           bottom - (bottom - top) * value / 100)
                          for ts, value in segment]
                if len(points) == 1:
                    x, y = points[0]
                    canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color,
                                       outline="", tags=(axis,))
                else:
                    canvas.create_line(points, fill=color, width=2, tags=(axis,))
