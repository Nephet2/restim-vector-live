"""Independent Civet attenuation for Signal Lab and Vector output layers."""
from array import array
import json
import math
from pathlib import Path
import re
import threading
import time
from .civet import Civet

DEFAULTS = dict(lower=21.0, upper=22.0, reduction=20.0, response=.25, recovery=2.0)


class PressureControl:
    def __init__(self, sensor=None, clock=time.monotonic, path=None):
        self.sensor = sensor or Civet()
        self.clock = clock
        self.path = Path(path) if path else Path(__file__).with_name('civet-pressure.json')
        self.lock = threading.RLock()
        self.settings = dict(DEFAULTS)
        self.enabled = False
        self.reduced = False
        self.fault = ''
        self.current = 1.0
        self.last = clock()
        self.window = None
        try:
            if self.path.exists(): self.settings = self.validate(json.loads(self.path.read_text()))
        except (ValueError, OSError, TypeError):
            pass

    @staticmethod
    def validate(data):
        result = dict(DEFAULTS)
        for key, lo, hi in [('lower',-100,500), ('upper',-100,500), ('reduction',0,100),
                            ('response',.02,10), ('recovery',.02,30)]:
            value = float(data.get(key, result[key]))
            if not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'{key} must be from {lo} to {hi}')
            result[key] = value
        if result['upper'] <= result['lower']: raise ValueError('B must be greater than A')
        return result

    def configure(self, settings, enabled):
        settings = self.validate(settings)
        with self.lock:
            if enabled and not self.sensor.snapshot()['fresh']:
                raise ValueError('Connect the Civet and wait for a fresh reading first')
            if self.fault and enabled:
                raise ValueError('Switch pressure control off and Apply before enabling it again')
            if not self.enabled or not enabled:
                self.reduced = False
                self.current = 1.0
            self.settings = settings
            self.enabled = bool(enabled)
            if not enabled: self.fault = ''
            self.last = self.clock()

    def target(self):
        with self.lock:
            if not self.enabled: return 1.0
            state = self.sensor.snapshot()
            if not state['fresh']:
                self.fault = 'Civet disconnected or readings stale. Output is held at zero.'
            if self.fault:
                self.current = 0.0
                return 0.0
            pressure = state['pressure_kpa']
            if pressure >= self.settings['upper']: self.reduced = True
            elif pressure <= self.settings['lower']: self.reduced = False
            return 1-self.settings['reduction']/100 if self.reduced else 1.0

    def gain(self):
        with self.lock:
            target = self.target()
            now = self.clock()
            dt = min(.1, max(0, now-self.last))
            self.last = now
            tau = self.settings['response' if target < self.current else 'recovery']
            self.current = target + (self.current-target)*math.exp(-dt/tau)
            return self.current

    def pcm16(self, frames, rate=44100, channels=2):
        with self.lock:
            if not self.enabled: return frames
            target = self.target()
            if self.fault: raise RuntimeError(self.fault)
            samples = array('h', frames)
            tau = self.settings['response' if target < self.current else 'recovery']
            decay = math.exp(-1/(rate*tau))
            current = self.current
            for i in range(0, len(samples), channels):
                current = target + (current-target)*decay
                for lane in range(channels): samples[i+lane] = int(samples[i+lane]*current)
            self.current = current
            return samples.tobytes()

    def tcode(self, message):
        """Called at the final socket send; authored V0 and all output paths are covered."""
        with self.lock:
            if not self.enabled: return message
            gain = self.gain()
            def scale(match):
                digits = match.group(1)
                return 'V0' + str(int(int(digits)*gain)).zfill(len(digits))
            # Existing sender emits whitespace-separated tokens. Strip any interval
            # on V0: smoothing is already applied here, not deferred at the receiver.
            result = re.sub(r'\bV0(\d+)(?:I\d+)?(?=\s|$)', scale, message, flags=re.I)
            if self.fault and not re.search(r'\bV0\d', result, re.I): result += ' V00000'
            return result

    def snapshot(self):
        with self.lock:
            return dict(enabled=self.enabled, reduced=self.reduced, fault=self.fault,
                        volume_factor=self.current, settings=dict(self.settings), sensor=self.sensor.snapshot())

    def show(self, parent, stop_output):
        import tkinter as tk
        from tkinter import ttk, messagebox
        if self.window is not None and self.window.winfo_exists():
            self.window.lift()
            return
        window = self.window = tk.Toplevel(parent)
        window.title('Civet pressure volume control')
        window.geometry('660x460')
        box = ttk.Frame(window, padding=16)
        box.pack(fill='both', expand=True)
        row = ttk.Frame(box); row.pack(fill='x')
        ttk.Button(row, text='Connect Civet', command=self.sensor.connect).pack(side='left')
        def disconnect():
            if self.enabled: stop_output()
            self.sensor.disconnect()
        ttk.Button(row, text='Disconnect', command=disconnect).pack(side='left', padx=8)
        status = ttk.Label(box, wraplength=620); status.pack(anchor='w', pady=10)
        entries = {}
        for key, label in [('lower','A · restore at kPa'), ('upper','B · reduce at kPa'),
                           ('reduction','Reduce volume by %'), ('response','Response seconds'), ('recovery','Recovery seconds')]:
            row = ttk.Frame(box); row.pack(fill='x', pady=2)
            ttk.Label(row, text=label, width=27).pack(side='left')
            entries[key] = tk.StringVar(value=f'{self.settings[key]:g}')
            ttk.Entry(row, textvariable=entries[key], width=12).pack(side='left')
        enabled = tk.BooleanVar(value=self.enabled)
        ttk.Checkbutton(box, text='Enable pressure reduction', variable=enabled).pack(anchor='w', pady=8)
        def apply():
            try:
                values = self.validate({k:v.get() for k,v in entries.items()})
                if self.enabled and not enabled.get(): stop_output()
                self.configure(values, enabled.get())
                self.path.write_text(json.dumps(values, indent=2), encoding='utf-8')
            except Exception as exc: messagebox.showerror('Pressure control', str(exc), parent=window)
        ttk.Button(box, text='Apply settings', command=apply).pack(anchor='w')
        ttk.Label(box, text='At B: reduce volume. Hold until A. A 20% reduction means 80% volume.\nStale readings latch output at zero. Switch off and Apply, reconnect, then re-enable.', wraplength=620).pack(anchor='w', pady=10)
        def refresh():
            if not window.winfo_exists(): return
            state = self.snapshot(); sensor = state['sensor']
            pressure = '—' if sensor['pressure_kpa'] is None else f"{sensor['pressure_kpa']:.2f} kPa"
            mode = 'OFF' if not state['enabled'] else ('REDUCED' if state['reduced'] else 'NORMAL')
            status.configure(text=f"{sensor['status']} · {pressure}\n{mode} · Output multiplier {state['volume_factor']*100:.0f}%\n{state['fault']}")
            window.after(200, refresh)
        refresh()
        # Size from the rendered controls so font/DPI scaling cannot hide Apply.
        window.update_idletasks()
        minimum_width = max(660, box.winfo_reqwidth())
        minimum_height = max(460, box.winfo_reqheight() + 32)
        window.minsize(minimum_width, minimum_height)
        window.geometry(f'{minimum_width}x{minimum_height}')

    def close(self):
        self.sensor.disconnect()
        if self.sensor.thread: self.sensor.thread.join(timeout=3)
