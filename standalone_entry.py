"""Folder-local source entry point; normal operation has full output support."""
from pathlib import Path
import os
import platform
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
# The attached Windows source ZIP includes a verified CPython 3.13 x64 wheel.
# A checkout or another Python version can use its separately installed Pillow.
if sys.version_info[:2] == (3, 13) and platform.machine().lower() in ('amd64', 'x86_64'):
    deps = ROOT / 'dependencies'
    if deps.is_dir():
        sys.path.insert(0, str(deps))
os.environ['LOCALAPPDATA'] = str(ROOT / 'profile')


def main():
    if '--smoke-test' in sys.argv:
        from contextlib import ExitStack
        from unittest.mock import patch
        import tkinter as tk
        from vector1a.app import VectorApp
        with ExitStack() as guards:
            guards.enter_context(patch('vector1a.app.load_settings', return_value={}))
            guards.enter_context(patch('vector1a.app.save_settings'))
            for method in ('_auto_start_session', '_auto_start_director', 'show_setup_guide'):
                guards.enter_context(patch.object(VectorApp, method, lambda self: None))
            for target in ('XInputController.start', 'VectorEngine.start', 'FunscriptTimeline.request_media_poll'):
                guards.enter_context(patch('vector1a.app.' + target))
            root = tk.Tk()
            app = VectorApp(root)
            root.after(300, app.show_custom_curves)
            root.after(1200, app.close)
            root.mainloop()
        return
    from vector1a.app import main as app_main
    app_main()


if __name__ == '__main__':
    main()
