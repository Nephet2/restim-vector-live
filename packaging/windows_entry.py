"""Entry point for the portable Windows executable."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


def smoke_test(report_path: str) -> None:
    """Exercise packaged imports, Tk and event data without opening connections."""
    import tkinter as tk
    from tkinter import ttk
    import bleak
    from vector1a import __version__
    from vector1a.antialias_canvas import ANTIALIAS_AVAILABLE
    assert ANTIALIAS_AVAILABLE, "Pillow preview support is missing"
    from vector1a.app import VectorApp
    from vector1a.events import load_definitions
    root = tk.Tk()
    root.withdraw()
    try:
        ttk.Label(root, text="Vector packaging check")
        root.update_idletasks()
        definitions, _ = load_definitions()
        assert definitions, "No bundled event definitions"
        assert callable(VectorApp), "Application import failed"
        report = {"version": __version__, "tk": tk.TkVersion,
                  "events": len(definitions), "bleak": bleak.__name__,
                  "frozen": bool(getattr(sys, "frozen", False)), "ok": True}
        Path(report_path).write_text(json.dumps(report), encoding="utf-8")
    finally:
        root.destroy()


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        # Never read or write the user's normal profile during a packaging test.
        with tempfile.TemporaryDirectory() as profile:
            os.environ["LOCALAPPDATA"] = profile
            smoke_test(sys.argv[2])
        return

    folder = Path(sys.executable).resolve().parent
    os.environ["LOCALAPPDATA"] = str(folder / "profile")
    logs = folder / "profile" / "Vector1A" / "logs"
    try:
        logs.mkdir(parents=True, exist_ok=True)
        log = (logs / "vector-console.log").open("a", encoding="utf-8", buffering=1)
    except OSError:
        from tkinter import messagebox
        messagebox.showerror("Vector 1A", "Extract Vector to a writable folder before running it.")
        return
    sys.stdout = sys.stderr = log
    try:
        from datetime import datetime
        from vector1a import __version__
        print(f"\n{datetime.now().isoformat(timespec='seconds')} Vector {__version__} starting")
        from vector1a.app import main as app_main
        app_main()
    except Exception:
        traceback.print_exc()
        from tkinter import messagebox
        messagebox.showerror("Vector 1A", f"Vector could not start. Details are in:\n{logs / 'vector-console.log'}")
        raise
    finally:
        log.flush()


if __name__ == "__main__":
    main()
