from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable


DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
START, LEFT_SHOULDER, RIGHT_SHOULDER = 0x0010, 0x0100, 0x0200
A, B, X, Y = 0x1000, 0x2000, 0x4000, 0x8000


def controller_snapshot(buttons: int, connected: bool) -> dict[str, object]:
    """Compact physical-controller state for the loopback Director/PTT bridge."""
    buttons = int(buttons) if connected else 0
    lb = bool(buttons & LEFT_SHOULDER)
    dpad = {
        "up": bool(buttons & DPAD_UP),
        "down": bool(buttons & DPAD_DOWN),
        "left": bool(buttons & DPAD_LEFT),
        "right": bool(buttons & DPAD_RIGHT),
    }
    dpad_any = any(dpad.values())
    return {
        "connected": bool(connected),
        "buttons": buttons,
        "lb_pressed": lb,
        "dpad": dpad,
        "lb_dpad_active": lb and dpad_any,
        "ptt_candidate": lb and not dpad_any,
    }


class _Gamepad(ctypes.Structure):
    _fields_ = [("buttons", wintypes.WORD), ("left_trigger", ctypes.c_ubyte),
                ("right_trigger", ctypes.c_ubyte), ("thumb_lx", ctypes.c_short),
                ("thumb_ly", ctypes.c_short), ("thumb_rx", ctypes.c_short),
                ("thumb_ry", ctypes.c_short)]


class _State(ctypes.Structure):
    _fields_ = [("packet", wintypes.DWORD), ("gamepad", _Gamepad)]


class XInputController:
    """Edge-triggered Xbox input independent of foreground-window focus."""

    def __init__(self, on_buttons: Callable[[int], None], on_status: Callable[[str], None],
                 on_state: Callable[[int, bool], None] | None = None):
        self.on_buttons, self.on_status, self.on_state = on_buttons, on_status, on_state
        self._run = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._get_state = self._load()

    @staticmethod
    def _load():
        for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
            try:
                function = ctypes.WinDLL(name).XInputGetState
                function.argtypes = (wintypes.DWORD, ctypes.POINTER(_State))
                function.restype = wintypes.DWORD
                return function
            except (OSError, AttributeError):
                pass
        return None

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._run.set()
        self._thread = threading.Thread(target=self._loop, name="vector-xinput", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._run.clear()
        if self._thread:
            self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        previous = 0
        last_status = None
        last_state: tuple[bool, int] | None = None
        while self._run.is_set():
            state = _State()
            connected = self._get_state is not None and self._get_state(0, ctypes.byref(state)) == 0
            self._connected = connected
            status = "Xbox controller connected" if connected else "Xbox controller not detected"
            if status != last_status:
                self.on_status(status)
                last_status = status
            buttons = state.gamepad.buttons if connected else 0
            state_key = (connected, int(buttons))
            if state_key != last_state and self.on_state is not None:
                self.on_state(int(buttons), bool(connected))
                last_state = state_key
            pressed = buttons & ~previous
            if pressed:
                # Include held modifier state with newly pressed buttons.
                self.on_buttons(pressed | (buttons & LEFT_SHOULDER))
            previous = buttons
            time.sleep(0.04)
