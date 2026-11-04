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
  for label,name in (('START / RESUME','resume'),('Neutral','neutral'),('STOP','stop')):
   controls[label].invoke();self.actions[name].assert_called_once()
  for size in ('980x720','1360x900'):
   self.root.geometry(size);self.root.update()
   for w in self.descendants(header):
    if w.winfo_class() in ('TButton','TMenubutton'):
     self.assertGreaterEqual(w.winfo_rootx(),self.root.winfo_rootx())
     self.assertLessEqual(w.winfo_rootx()+w.winfo_width(),self.root.winfo_rootx()+self.root.winfo_width())
   self.app.main_canvas.yview_moveto(1.);self.root.update()
   self.assertLess(header.winfo_rooty()+header.winfo_height(),self.app.main_canvas.winfo_rooty()+2)
   self.assertTrue(controls['STOP'].winfo_ismapped())

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

if __name__=='__main__':unittest.main()
