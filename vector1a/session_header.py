"""Live session overview built from local playback and output state."""
import time
import tkinter as tk
from tkinter import ttk

from .direct_player import DEOVR, HERESPHERE, MFP, MPC
from .handy_control import MODES as HANDY_MODES
from .timeline import FunscriptTimeline


def mfp_session_status(feed, timeline):
    if not feed["running"]:
        clock = "Listener stopped"
    elif feed["last_l0_age"] is None:
        clock = "Listening for L0"
    elif feed["last_l0_age"] >= 2.0:
        clock = f"L0 quiet for {feed['last_l0_age']:.1f} s"
    else:
        clock = f"Receiving L0 ({feed['last_transport']})"
    mode = timeline["clock_source"]
    if mode in (FunscriptTimeline.CLOCK_AUTO, FunscriptTimeline.CLOCK_MPC, FunscriptTimeline.CLOCK_VLC):
        health = timeline["media_clock_health"]
        player = timeline["media_player"] or "Player"
        if player == "MPC":
            player = MPC
        elif not timeline["media_connected"]:
            player = "Player"
        age = timeline["media_sample_age_seconds"]
        if timeline["media_connected"] and (health == "stale" or (age is not None and age >= 3.0)):
            clock += f" / {player} clock stale"
        elif timeline["media_connected"] and health in ("live", "checking", "paused", "idle"):
            clock += f" / {player} {health}"
        else:
            clock += " / waiting for timeline clock"
    elif mode == FunscriptTimeline.CLOCK_MANUAL:
        clock += " / manual preview clock"
    elif timeline["loaded"]:
        clock += " / estimated timeline"
    return clock, timeline["file"] or "No local funscript loaded"


def restim_session_status(health, engine_state, input_ready, generated):
    connection = "Connected" if health["connected"] else "Disconnected"
    request = "Waiting for input" if not input_ready and engine_state in ("Running", "Buffering") else f"Engine {engine_state.lower()}"
    if generated and engine_state in ("Running", "Buffering"):
        request += " (generated)"
    age = health["tx_age"]
    write = f"last write {age:.1f} s ago" if age is not None else "no socket writes"
    return " | ".join((connection, request, write))


def handy_session_status(control):
    output = control.output
    source = HANDY_MODES[control.mode]
    pending = output.pending[0] if output.pending else None
    if pending == "stop":
        state = "Stop requested; awaiting acknowledgement"
    elif pending == "connect":
        state = "Connecting"
    elif output.error:
        state = "Device error; see Handy Interface"
    elif control.previewing:
        state = "Preview only"
    elif not output.connected:
        state = "Disconnected"
    elif control.playing:
        if control._waiting:
            state = "Waiting for playback clock"
        elif pending == "prepare" or (not control.native_manual and not output.stream_started):
            state = "Preparing timed motion"
        elif pending == "motion":
            state = "Motion command pending"
        else:
            state = output.detail
    else:
        state = "Stop acknowledged" if output.detail == "Stop confirmed" else control.detail
    return f"{source} | {state}"


def vacu_session_status(control, state):
    source = control.source_name
    phase = state["state"]
    speed = state["confirmed_speed_percent"]
    if phase == "stopping" or control.stopping:
        detail = "Stop requested; awaiting confirmation"
    elif phase == "unknown" or control.error or state["error"]:
        detail = "Device state unconfirmed; see VacuGlide Interface"
    elif phase == "connecting":
        detail = "Taking control"
    elif state["ownership"] != "vector":
        detail = "Disconnected"
    elif control.playing:
        detail = f"Target {control.target:.0f}%"
        if speed is not None:
            detail += f" | device reported {speed:g}%"
    elif state["stop_verified"]:
        detail = "Paused; stop confirmed"
    elif phase == "running":
        detail = "Running"
        if speed is not None:
            detail += f" | device reported {speed:g}%"
    else:
        detail = "Connected; idle"
    return f"{source} | {detail}"


class SessionHeader:
    def __init__(self, parent, app, outputs):
        self.app = app
        body = ttk.Frame(parent)
        body.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        body.columnconfigure((0, 1), weight=1, uniform="output_status")
        source = ttk.Frame(body)
        source.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(source, text="Playback input").pack(side="left")
        input_box = ttk.Combobox(source, textvariable=app.playback_input, values=(MFP, MPC, HERESPHERE, DEOVR),
                                 state="readonly", width=16)
        input_box.pack(side="left", padx=5)
        input_box.bind("<<ComboboxSelected>>", app._show_playback_endpoint)
        ttk.Button(source, text="Use input", command=app._apply_playback_input).pack(side="left", padx=(0, 10))
        ttk.Label(source, text="Player address").pack(side="left")
        app._playback_host = ttk.Entry(source, width=16)
        app._playback_host.pack(side="left", padx=5)
        ttk.Label(source, text="Port").pack(side="left")
        app._playback_port = ttk.Spinbox(source, from_=1, to=65535, width=7)
        app._playback_port.pack(side="left", padx=5)
        app._show_playback_endpoint()
        ttk.Button(source, text="Load funscript...", command=app._load_playback_script).pack(side="left", padx=5)

        self.playback = tk.StringVar(master=parent)
        ttk.Label(body, textvariable=self.playback, width=1, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(2, 5))
        self.outputs = {}
        for index, (name, open_settings) in enumerate(outputs):
            row, column = divmod(index, 2)
            line = ttk.Frame(body)
            line.grid(row=row + 2, column=column, sticky="ew", padx=(0, 6))
            ttk.Button(line, text=name, command=open_settings, width=15).pack(side="left")
            value = self.outputs[name] = tk.StringVar(master=parent)
            ttk.Label(line, textvariable=value, width=1, anchor="w").pack(
                side="left", fill="x", expand=True, padx=6)
        self.refresh(app.engine.diagnostics().state)

    def refresh(self, engine_state):
        app = self.app
        direct = app._direct_input
        if direct is None:
            source = MFP
            clock, script = mfp_session_status(app.listener.health(), app.timeline.metadata())
        else:
            source = direct.source
            clock, script = direct.session_status(time.monotonic())
        self._set(self.playback, f"Active: {source} | {clock} | {script}")
        generated = direct is None and app.generated_motion.active
        for name, client in (("ReStim Primary", app.restim), ("ReStim Prostate", app.prostate_restim)):
            value = restim_session_status(client.health(), engine_state, app._input_ready, generated)
            self._set(self.outputs[name], value)
        self._set(self.outputs["Handy"], handy_session_status(app.handy_control))
        self._set(self.outputs["VacuGlide"], vacu_session_status(app.vacuglide_control, app.vacuglide.state()))

    @staticmethod
    def _set(variable, value):
        if variable.get() != value:
            variable.set(value)
