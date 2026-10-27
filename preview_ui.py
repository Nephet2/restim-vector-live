"""Disconnected UI test launcher. No output transports or external apps permitted."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / 'dependencies')]
os.environ['LOCALAPPDATA'] = str(ROOT / 'profile')

from contextlib import ExitStack
from unittest.mock import patch
import socket
import tkinter as tk
from vector1a.app import VectorApp


def blocked(*args, **kwargs):
    raise PermissionError('UI preview: connections and external programs are disabled')


def main():
    with ExitStack() as guards:
        for method in ('connect', 'connect_ex', 'bind', 'sendto'):
            guards.enter_context(patch.object(socket.socket, method, blocked))
        guards.enter_context(patch('subprocess.Popen', blocked))
        if hasattr(os, 'startfile'):
            guards.enter_context(patch('os.startfile', blocked))
        for method in ('_auto_start_session', '_auto_start_director', 'show_setup_guide'):
            guards.enter_context(patch.object(VectorApp, method, lambda self: None))
        for target in ('vector1a.app.XInputController.start',
                       'vector1a.app.FunscriptTimeline.request_media_poll',
                       'vector1a.civet.Civet.connect'):
            guards.enter_context(patch(target))
        root = tk.Tk()
        app = VectorApp(root)
        root.title('Vector 1A - alpha82 Custom preview - UI ONLY / CONNECTIONS DISABLED')
        root.geometry('1360x900')
        if '--smoke-test' in sys.argv:
            root.after(300, app.show_custom_curves)
            root.after(1500, app.close)
        root.mainloop()


if __name__ == '__main__':
    main()
