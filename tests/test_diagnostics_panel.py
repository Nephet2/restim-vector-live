import unittest
from unittest.mock import patch
from vector1a.diagnostics_panel import age,transport_text
from test_navigation import NavigationTests

class TransportFormatTests(unittest.TestCase):
 def test_no_write_is_never_and_failures_stay_separate(self):
  text=transport_text({'connected':True,'send_count':0,'tx_age':None,'send_failures':2},
      {'alive':True,'pending':False,'dropped':3,'stale':1,'failures':2})
  self.assertIn('Socket: connected',text)
  self.assertIn('Last socket write: never',text)
  self.assertIn('Failures: socket 2; sender 2',text)
  self.assertIn('Superseded frames: 3; expired: 1',text)
  self.assertEqual(age(.125),'0.12 s ago')

class DiagnosticsPanelTests(unittest.TestCase):
 destroy_root=NavigationTests.destroy_root
 setUp=NavigationTests.setUp
 tearDown=NavigationTests.tearDown
 descendants=NavigationTests.descendants

 def test_read_only_health_is_separate_from_configured_addresses(self):
  app=self.app;view=app.diagnostics_panel
  app.restim_port.set(12355)
  before=app.engine.control_state()
  with patch.object(app.restim,'health',return_value={'connected':False,'send_count':12,'tx_age':.25,'send_failures':2}):
   view.refresh()
  self.assertIn('Configured: 127.0.0.1:12355',view.stage_vars['primary_address'].get())
  self.assertIn('Socket: disconnected',view.stage_vars['primary'].get())
  self.assertIn('Successful socket writes: 12',view.stage_vars['primary'].get())
  self.assertIn('No MFP L0 received',view.stage_vars['source'].get())
  self.assertEqual(app.engine.control_state(),before)
  app._save_settings.assert_not_called()
  for action in self.actions.values():action.assert_not_called()

 def test_both_tabs_remain_accessible_at_minimum_width(self):
  app=self.app;view=app.diagnostics_panel
  app.section_shortcuts['Live diagnostics'].invoke();app._refresh();self.root.update()
  self.assertEqual([view.notebook.tab(tab,'text') for tab in view.notebook.tabs()],['Signal path','Calculated samples'])
  for size in ('980x720','1360x900'):
   self.root.geometry(size);self.root.update()
   for tab in view.notebook.tabs():
    view.notebook.select(tab);self.root.update()
    for widget in (view.notebook,view.overview,view.samples):
     self.assertLessEqual(widget.winfo_width(),app.sections['Live diagnostics'].body.winfo_width()+2)
  labels=[str(w.cget('text')) for w in self.descendants(view.samples) if w.winfo_class()=='TLabel']
  self.assertIn('Generated Primary alpha',labels)
  self.assertIn('Generated Prostate alpha',labels)

if __name__=='__main__':unittest.main()
