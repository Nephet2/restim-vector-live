"""Use one real Tcl/Tk interpreter for GUI tests in each pytest process."""
import tkinter as tk
import pytest

@pytest.fixture(scope="session")
def tk_host():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()

@pytest.fixture(autouse=True)
def isolated_test_windows(monkeypatch, tk_host):
    # Repeated Tk() construction leaves Tcl interpreters alive through widget
    # variables. Real Toplevel windows isolate each layout on one interpreter,
    # following Tk's single-interpreter lifetime rather than reloading Tcl.
    windows = []
    def new_window(*args, **kwargs):
        window = tk.Toplevel(tk_host)
        windows.append(window)
        return window
    monkeypatch.setattr(tk, "Tk", new_window)
    yield
    for window in windows:
        try:
            window.destroy()
        except tk.TclError:
            pass
