"""Offline UI inspection harness. All device/network/process operations blocked."""
import sys, socket, threading, subprocess, tkinter as tk
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from vector1a.app import VectorApp
from vector1a.sequence_ui import show_sequences as show_passages

def blocked(*a,**kw): raise AssertionError("External operation blocked in UI preview")
with ExitStack() as stack:
 for method in ('connect','connect_ex','bind','sendto'):
  stack.enter_context(patch.object(socket.socket,method,blocked))
 stack.enter_context(patch('subprocess.Popen',blocked))
 stack.enter_context(patch.object(threading.Thread,'start'))
 stack.enter_context(patch.object(threading.Thread,'join'))
 stack.enter_context(patch('vector1a.app.load_settings',return_value={}))
 stack.enter_context(patch('vector1a.app.save_settings'))
 for method in ('_auto_start_session','_auto_start_director','show_setup_guide','_save_settings'):
  stack.enter_context(patch.object(VectorApp,method))
 stack.enter_context(patch('vector1a.app.FunscriptTimeline.request_media_poll'))
 root=tk.Tk(); root.withdraw(); app=VectorApp(root)
 app.show_director_semantic_window(); app._director_semantic_window.withdraw()
 show_passages(app); root.update()
 window=app._sequence_window
 print('READY: passage window',window.winfo_width(),window.winfo_height(),flush=True)
 root.after(int(sys.argv[1])*1000 if len(sys.argv)>1 else 180000,app.close)
 root.mainloop()
