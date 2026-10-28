from __future__ import annotations

import tkinter as tk


from .output_ranges import unit_range


class RangeBar(tk.Canvas):
    """Compact dual-handle range editor with a separate live-value marker."""
    def __init__(self, parent, width=520, height=20, *, minimum_var=None,
                 maximum_var=None, command=None):
        super().__init__(parent, width=width, height=height, highlightthickness=1,
                         highlightbackground="#999", background="#e6e6e6",
                         takefocus=True)
        self._width, self._height = width, height
        self._minimum_var, self._maximum_var = minimum_var, maximum_var
        self._command = command
        self._minimum, self._maximum, self._value = 0., 1., 0.
        self._active = "minimum"
        self._dragging = False
        self._notify_id = None
        self._traces = []
        self.bind("<Configure>", self._resize)
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._drag)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Left>", lambda e: self._nudge(-.01))
        self.bind("<Right>", lambda e: self._nudge(.01))
        self.bind("<Shift-Left>", lambda e: self._nudge(-.05))
        self.bind("<Shift-Right>", lambda e: self._nudge(.05))
        self.bind("<Up>", lambda e: self._select("maximum"))
        self.bind("<Down>", lambda e: self._select("minimum"))
        self.bind("<FocusIn>", lambda e: self._draw())
        self.bind("<FocusOut>", lambda e: self._draw())
        self.bind("<Destroy>", self._destroyed)
        for variable in (minimum_var, maximum_var):
            if variable is not None:
                self._traces.append((variable, variable.trace_add("write", self._changed)))
        self._read_bounds()
        self._draw()

    def _read_bounds(self):
        if self._minimum_var is None or self._maximum_var is None:
            return
        try:
            self._minimum, self._maximum = unit_range(
                self._minimum_var.get(), self._maximum_var.get())
        except (tk.TclError, ValueError, TypeError):
            pass  # A spinbox may temporarily contain incomplete text.

    def _changed(self, *_):
        self._read_bounds()
        self._draw()
        if self._command is not None and self._notify_id is None:
            self._notify_id = self.after_idle(self._notify)

    def _notify(self):
        self._notify_id = None
        try:
            unit_range(self._minimum_var.get(), self._maximum_var.get())
        except (tk.TclError, ValueError, TypeError):
            return
        self._command()

    def _resize(self, event):
        self._width, self._height = event.width - 2, event.height - 2
        self._draw()

    def set(self, minimum, maximum, value):
        self._minimum, self._maximum = unit_range(minimum, maximum)
        self._value = min(1., max(0., float(value)))
        self._draw()

    def _x(self, value):
        return 5 + value * max(1, self._width - 10)

    def _at(self, x):
        return round(min(1., max(0., (x - 5) / max(1, self._width - 10))), 3)

    def _draw(self):
        self.delete("all")
        h = self._height
        x0, x1 = self._x(self._minimum), self._x(self._maximum)
        self.create_rectangle(5, 5, self._width - 5, h - 4, fill="#cbd0d5", outline="")
        self.create_rectangle(x0, 5, x1, h - 4, fill="#27ad61", outline="")
        marker = self._x(self._value)
        self.create_line(marker, 3, marker, h - 2, fill="#173b8f", width=2)
        if self._minimum_var is not None:
            # Split handles remain independently selectable even at equal bounds.
            self.create_rectangle(x0-4, 2, x0+4, h/2, fill="#354b60", outline="#fff")
            self.create_rectangle(x1-4, h/2, x1+4, h-1, fill="#354b60", outline="#fff")
            if self.focus_get() == self:
                x = x0 if self._active == "minimum" else x1
                y0, y1 = (1, h/2+1) if self._active == "minimum" else (h/2-1, h)
                self.create_rectangle(x-5, y0, x+5, y1, outline="#1769aa", width=2)
        self.configure(cursor="hand2" if self._minimum_var is not None else "")

    def _press(self, event):
        if self._minimum_var is None:
            return
        self.focus_set()
        low_distance = abs(event.x - self._x(self._minimum))
        high_distance = abs(event.x - self._x(self._maximum))
        if abs(low_distance - high_distance) < 1:
            self._active = "minimum" if event.y < self._height/2 else "maximum"
        else:
            self._active = "minimum" if low_distance < high_distance else "maximum"
        self._dragging = True
        self._move(self._at(event.x))

    def _move(self, value):
        if self._active == "minimum":
            self._minimum_var.set(min(self._maximum, max(0., value)))
        else:
            self._maximum_var.set(max(self._minimum, min(1., value)))

    def _drag(self, event):
        if self._dragging:
            self._move(self._at(event.x))

    def _release(self, event):
        self._dragging = False

    def _select(self, handle):
        self._active = handle
        self._draw()
        return "break"

    def _nudge(self, delta):
        if self._minimum_var is not None:
            value = self._minimum if self._active == "minimum" else self._maximum
            self._move(round(value + delta, 3))
        return "break"

    def _destroyed(self, event):
        if event.widget != self:
            return
        if self._notify_id is not None:
            self.after_cancel(self._notify_id)
        for variable, trace in self._traces:
            variable.trace_remove("write", trace)
