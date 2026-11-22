import os,socket,threading,unittest
from contextlib import ExitStack
from unittest.mock import patch,Mock
import tkinter as tk
from vector1a.app import VectorApp

class NavigationTests(unittest.TestCase):
 def setUp(self):
  self.guards=ExitStack()
  self.addCleanup(self.guards.close)
  self.root=tk.Tk();self.root.withdraw()
  self.addCleanup(lambda: NavigationTests.destroy_root(self))
  def blocked(*a,**k):raise AssertionError('External activity blocked during navigation test')
  for name in ('connect','connect_ex','bind','sendto'):self.guards.enter_context(patch.object(socket.socket,name,blocked))
  for name in ('start','join'):self.guards.enter_context(patch.object(threading.Thread,name))
  self.guards.enter_context(patch('subprocess.Popen',blocked))
  if hasattr(os,'startfile'):self.guards.enter_context(patch('os.startfile',blocked))
  self.guards.enter_context(patch('vector1a.app.load_settings',return_value={}))
  self.guards.enter_context(patch('vector1a.app.save_settings',side_effect=blocked))
  self.guards.enter_context(patch.object(VectorApp,'_save_settings'))
  self.guards.enter_context(patch('vector1a.app.FunscriptTimeline.request_media_poll'))
  self.actions={name:self.guards.enter_context(patch.object(VectorApp,name)) for name in ('resume','neutral','stop')}
  self.guards.enter_context(patch.object(self.root,'after',return_value='disabled'))
  self.app=VectorApp(self.root)
  self.root.geometry('980x720');self.root.deiconify();self.root.update()

 def destroy_root(self):
  try:self.root.destroy()
  except tk.TclError:pass

 def tearDown(self):
  try:self.app.close()
  finally:self.guards.close()

 def descendants(self,w):
  for child in w.winfo_children():yield child;yield from self.descendants(child)

 def test_fixed_controls_and_navigation_fit_smallest_window(self):
  header=self.app.navigation_header
  controls={str(w.cget('text')):w for w in self.descendants(header) if w.winfo_class()=='TButton'}
  for label,name in (('Resume ReStim','resume'),('Neutral ReStim','neutral'),('Stop all','stop')):
   controls[label].invoke();self.actions[name].assert_called_once()
  for size in ('980x720','1360x900'):
   self.root.geometry(size);self.root.update()
   for w in self.descendants(header):
    if w.winfo_class() in ('TButton','TMenubutton'):
     self.assertGreaterEqual(w.winfo_rootx(),self.root.winfo_rootx())
     self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
   self.app.main_canvas.yview_moveto(1.);self.root.update()
   self.assertLess(header.winfo_rooty()+header.winfo_height(),self.app.main_canvas.winfo_rooty()+2)
   self.assertTrue(controls['Stop all'].winfo_ismapped())

 def test_shortcuts_expand_scroll_and_leave_signals_alone(self):
  for title,button in self.app.section_shortcuts.items():
   button.invoke();self.root.update()
   section=self.app.sections[title]
   self.assertFalse(section.collapsed)
   self.assertGreaterEqual(section.winfo_rooty()+section.winfo_height(),self.app.main_canvas.winfo_rooty())
   self.assertLess(section.winfo_rooty(),self.app.main_canvas.winfo_rooty()+self.app.main_canvas.winfo_height())
  for action in self.actions.values():action.assert_not_called()
  actual={}
  for name,menu in self.app.navigation_menus.items():
   actual[name]=[menu.entrycget(i,'label') for i in range(menu.index('end')+1)]
  self.assertIn('Session startup',actual['Session'])
  self.assertIn('Semantic profiles',actual['Presets & tools'])
  self.assertIn('Connection log',actual['Connections'])
  self.assertIn('Setup guide',actual['Help'])
  self.assertIn('MFP input panel',actual['Connections'])
  self.assertIn('ReStim output panel',actual['Connections'])
  all_actions={label for values in actual.values() for label in values}
  self.assertTrue({'Setup guide','Rolling Variety','Presets A/B','Connection log','MFP axes','Session startup','Director','Script modifiers'} <= all_actions)

 def test_live_header_follows_applied_input_and_device_health(self):
  from vector1a.direct_player import HERESPHERE, MPC, DirectPlayerInput, PlayerFrame
  from vector1a.media_clock import MediaSnapshot

  app = self.app
  header = app.session_header
  app.playback_input.set(MPC)
  header.refresh("Stopped")
  self.assertIn("Active: MultiFunPlayer", header.playback.get())
  app.listener._run.set()
  app.listener._handle("L05000\n", "tcp")
  header.refresh("Running")
  self.assertIn("Receiving L0 (TCP)", header.playback.get())
  for source in (MPC, HERESPHERE):
   direct = app._direct_input = DirectPlayerInput(source, "localhost", 1)
   snapshot = MediaSnapshot(source, True, "paused", position_seconds=3., media_path="movie.mp4")
   direct.frame = PlayerFrame(snapshot, 10., None, "No matching funscript", 1)
   with patch("vector1a.session_header.time.monotonic", return_value=10.1):
    header.refresh("Running")
    self.assertIn(f"Active: {source} | Paused | No matching funscript", header.playback.get())
   with patch("vector1a.session_header.time.monotonic", return_value=14.):
    header.refresh("Running")
    self.assertIn("Stale player clock", header.playback.get())

  with patch.object(app.restim, "health", return_value={"connected": True, "tx_age": .1}):
   header.refresh("Running")
   self.assertIn("Connected", header.outputs["ReStim Primary"].get())
   self.assertIn("last write 0.1 s ago", header.outputs["ReStim Primary"].get())
  header.refresh("Running")
  self.assertIn("Disconnected", header.outputs["ReStim Primary"].get())

  app.handy.pending = ("stop", Mock())
  with patch.object(app.vacuglide, "state", wraps=app.vacuglide.state) as state:
   state.return_value = dict(state(), state="stopping", ownership="vector")
   header.refresh("Stopped")
   self.assertIn("awaiting confirmation", header.outputs["VacuGlide"].get())
   self.assertIn("awaiting acknowledgement", header.outputs["Handy"].get())
   state.return_value = dict(state.return_value, state="unknown", error="Stop unconfirmed")
   header.refresh("Stopped")
   self.assertIn("Device state unconfirmed", header.outputs["VacuGlide"].get())
   state.return_value = dict(state.return_value, state="stopped", stop_verified=True, error=None)
   header.refresh("Stopped")
   self.assertIn("stop confirmed", header.outputs["VacuGlide"].get())
  app.handy.pending = None
  app.listener._run.clear()
  for action in self.actions.values():action.assert_not_called()

 def test_deovr_uses_its_own_endpoint_in_the_playback_picker(self):
  from vector1a.direct_player import DEOVR, DirectPlayerInput

  app = self.app
  picker = next(w for w in self.descendants(app.navigation_header) if w.winfo_class() == "TCombobox")
  self.assertIn(DEOVR, tuple(picker.cget("values")))
  picker.set(DEOVR)
  app._show_playback_endpoint()
  self.assertEqual(str(app._playback_host.cget("textvariable")), str(app.direct_deovr_host))
  self.assertEqual(app._playback_port.get(), "23554")
  app.direct_deovr_host.set("192.0.2.7")
  with patch.object(DirectPlayerInput, "start") as start:
   app._apply_playback_input()
   start.assert_called_once()
  self.assertEqual(app._direct_input.source, DEOVR)
  self.assertEqual(app._direct_input.host, "192.0.2.7")
  self.assertEqual(app.direct_here_host.get(), "127.0.0.1")

 def test_load_button_uses_applied_multi_fun_player_timeline(self):
  with patch.object(self.app, "_timeline_browse") as browse:
   self.app.playback_input.set("HereSphere")
   button = next(w for w in self.descendants(self.app.navigation_header)
                 if w.winfo_class() == "TButton" and w.cget("text") == "Load funscript...")
   button.invoke()
   browse.assert_called_once()

 def test_direct_header_follows_script_association_seek_and_recovery(self):
  from dataclasses import replace
  from pathlib import Path
  from tempfile import TemporaryDirectory
  from vector1a.direct_player import HERESPHERE, MPC, DirectPlayerInput
  from vector1a.media_clock import MediaSnapshot

  with TemporaryDirectory() as folder:
   script = Path(folder) / "manual.funscript"
   script.write_text('{"actions":[{"at":0,"pos":0},{"at":10000,"pos":100}]}', encoding="utf-8")
   for source in (MPC, HERESPHERE):
    now = 10.
    direct = DirectPlayerInput(source, "localhost", 1, clock=lambda: now)
    movie = str(Path(folder) / "first.mp4")
    snapshot = MediaSnapshot(source, True, "playing", position_seconds=1., media_path=movie)
    direct._accept(snapshot)
    self.assertEqual(direct.session_status(now), ("Playing", "No matching funscript"))
    direct.load_manual(script, movie)
    self.assertEqual(direct.session_status(now), ("Playing", script.name))
    previous = direct.frame.revision
    now += .2
    direct._accept(replace(snapshot, position_seconds=5.))
    self.assertGreater(direct.frame.revision, previous)
    self.assertEqual(direct.session_status(now), ("Playing", script.name))
    direct._accept(replace(snapshot, state="paused", position_seconds=5.))
    self.assertEqual(direct.session_status(now), ("Paused", script.name))
    self.assertEqual(direct.session_status(now + 4.), ("Stale player clock", script.name))
    now += 4.
    direct._accept(replace(snapshot, position_seconds=5.5))
    self.assertEqual(direct.session_status(now), ("Playing", script.name))
    direct._accept(replace(snapshot, media_path=str(Path(folder) / "second.mp4")))
    self.assertEqual(direct.session_status(now), ("Playing", "No matching funscript"))

if __name__=='__main__':unittest.main()
