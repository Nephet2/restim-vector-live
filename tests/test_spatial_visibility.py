import copy,unittest
from test_navigation import NavigationTests

class SpatialVisibilityTests(unittest.TestCase):
 destroy_root=NavigationTests.destroy_root
 setUp=NavigationTests.setUp
 tearDown=NavigationTests.tearDown
 descendants=NavigationTests.descendants

 def control(self,variable):
  for w in self.descendants(self.app.sections['Four-phase primary motion'].body):
   try:
    if str(w.cget('textvariable'))==str(variable):return w
   except Exception:pass
  self.fail('Control not found')

 def test_each_model_shows_only_its_spatial_controls(self):
  app=self.app;ui=app.spatial_visibility
  for model in ('Moving focus','Depth spread','Howl Positional','Howl Dynamic','Custom','Moving focus'):
   app.four_phase_spatial_model.set(model);self.root.update()
   self.assertEqual(bool(self.control(app.four_phase_crossover_width).grid_info()),model=='Moving focus')
   self.assertEqual(bool(self.control(app.four_phase_return_depth).grid_info()),model=='Moving focus')
   self.assertEqual(bool(self.control(app.four_phase_group_delay_ms).grid_info()),model=='Moving focus')
   self.assertEqual(bool(self.control(app.four_phase_tip_retention).grid_info()),model=='Depth spread')
   self.assertEqual(bool(self.control(app.four_phase_full_depth_capture).grid_info()),model=='Depth spread')
   self.assertEqual(ui.custom_button.winfo_manager()=='pack',model=='Custom')
   self.assertEqual(bool(ui.howl_panel.grid_info()),model.startswith('Howl '))
   self.assertIn('three-phase alpha/beta',ui.note.cget('text'))

 def test_visible_panel_widgets_fit_smallest_window(self):
  app=self.app;panel=app.sections['Four-phase primary motion'].body
  app.section_shortcuts['Four-phase primary motion'].invoke()
  for model in ('Moving focus','Depth spread','Custom','Howl Positional','Howl Dynamic'):
   app.four_phase_spatial_model.set(model);app._refresh();self.root.update()
   for widget in panel.winfo_children():
    if widget.grid_info():
     with self.subTest(model=model,widget=widget.winfo_class()):
      self.assertLessEqual(widget.winfo_x()+widget.winfo_width(),panel.winfo_width()+2)

 def test_matching_keeps_amplitude_controls_and_pulse_ownership_clear(self):
  app=self.app;ui=app.spatial_visibility
  app.four_phase_spatial_model.set('Custom');app.match_spatial_intensity.set(True)
  self.assertTrue(ui.howl_panel.grid_info())
  self.assertTrue(self.control(app.howl_sigma).grid_info())
  self.assertFalse(self.control(app.howl_width).grid_info())
  self.assertFalse(self.control(app.howl_freq_min).grid_info())
  app.four_phase_spatial_model.set('Howl Dynamic');app.howl_pulse.set(True)
  self.assertTrue(self.control(app.howl_pan).grid_info())
  self.assertFalse(self.control(app.howl_width).grid_info())
  self.assertTrue(self.control(app.howl_freq_min).grid_info())
  app.howl_pulse.set(False)
  self.assertFalse(self.control(app.howl_freq_min).grid_info())

 def test_visibility_retains_values_and_never_saves_or_changes_output_state(self):
  app=self.app
  before={name:getattr(app,name).get() for name in set(app.SETTINGS_FIELDS)}
  curves=copy.deepcopy(app._custom_curves)
  for model in ('Depth spread','Custom','Howl Dynamic','Moving focus'):
   app.four_phase_spatial_model.set(model)
  after={name:getattr(app,name).get() for name in set(app.SETTINGS_FIELDS)}
  before.pop('four_phase_spatial_model');after.pop('four_phase_spatial_model')
  self.assertEqual(before,after);self.assertEqual(curves,app._custom_curves)
  app._save_settings.assert_not_called()
  for action in self.actions.values():action.assert_not_called()

if __name__=='__main__':unittest.main()
