import unittest
from test_navigation import NavigationTests

class ResponsePanelTests(unittest.TestCase):
 destroy_root=NavigationTests.destroy_root
 setUp=NavigationTests.setUp
 tearDown=NavigationTests.tearDown
 descendants=NavigationTests.descendants

 def test_stages_and_unique_base_volume_control(self):
  app=self.app;panel=app.sections['Volume response'].body
  labels=[str(w.cget('text')) for w in self.descendants(panel) if w.winfo_class()=='TLabel']
  for stage in ('1 · Generated response','2 · Output levels','3 · Composed command'):
   self.assertIn(stage,labels)
  controls=[]
  for w in self.descendants(app.content):
   if w.winfo_class()=='TSpinbox' and str(w.cget('textvariable'))==str(app.volume):controls.append(w)
  self.assertEqual(len(controls),1)
  self.assertIs(controls[0].master,panel)
  self.assertEqual(app.response_curves_button.grid_info()['row'],app.volume_response_bar.grid_info()['row'])
  self.assertLess(app.response_curves_button.grid_info()['column'],app.volume_response_bar.grid_info()['column'])
  self.assertEqual(app.volume_response_bar._minimum_var,app.volume_response_min)
  self.assertEqual(app.volume_response_bar._maximum_var,app.volume_response_max)

 def test_response_panel_fits_small_and_large_windows(self):
  app=self.app;panel=app.sections['Volume response'].body
  for size in ('980x720','1360x900'):
   self.root.geometry(size);app.section_shortcuts['Volume response'].invoke();self.root.update()
   for widget in panel.winfo_children():
    with self.subTest(size=size,widget=widget.winfo_class()):
     self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),panel.winfo_width()+2)
   self.assertLessEqual(panel.winfo_height(),340)
  for action in self.actions.values():action.assert_not_called()

if __name__=='__main__':unittest.main()
