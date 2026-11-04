import queue,unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from test_navigation import NavigationTests
from vector1a.director import DirectorRequest

class SemanticTempoTests(unittest.TestCase):
 setUp=NavigationTests.setUp
 tearDown=NavigationTests.tearDown
 descendants=NavigationTests.descendants

 def timeline(self,band='moderate'):
  fake=SimpleNamespace(loaded=True,position_seconds=lambda:4.,sample_position=lambda position:.4,
                       snapshot=lambda:{'now':{'energy_band':band}})
  self.app.timeline=fake;self.app.tempo.timeline=fake

 def test_three_scales_and_restore_preserves_other_modifiers(self):
  app=self.app;self.timeline()
  app.modifier_stroke_range.set(.6);app.modifier_position_bias.set(.1)
  with patch('time.monotonic',return_value=10.):
   for scale in (.5,2.):
    result=app._start_director_tempo_window(scale,15.)
    self.assertEqual(result['scale'],scale);self.assertEqual(app.tempo.scale,scale)
   app.timeline.loaded=False
   result=app._start_director_tempo_window(1.,0.)
  self.assertTrue(result['restored_authored_tempo']);self.assertEqual(app.tempo.scale,1.)
  self.assertEqual(app.modifier_stroke_range.get(),.6)
  self.assertEqual(app.modifier_position_bias.get(),.1)
  self.assertEqual(app._director_capabilities()['commands']['modifier']['tempo_scales'],[.5,1.,2.])

 def test_existing_timeline_duration_and_high_energy_limits(self):
  app=self.app
  with self.assertRaises(ValueError):app._start_director_tempo_window(.5,15.)
  self.timeline('challenging')
  with self.assertRaisesRegex(ValueError,'limited'):app._start_director_tempo_window(2.,30.)
  with self.assertRaises(ValueError):app._start_director_tempo_window(.5,17.)
  with self.assertRaises(ValueError):app._start_director_tempo_window(3.,15.)
  app._start_director_tempo_window(2.,15.)

 def test_semantic_api_restores_without_a_duration(self):
  app=self.app;self.timeline()
  app._start_director_tempo_window(.5,15.)
  req=DirectorRequest('POST','/v1/semantic/tempo',{'scale':1.})
  app.director_bridge=SimpleNamespace(get_nowait=Mock(side_effect=[req,queue.Empty()]))
  app._drain_director_requests()
  self.assertEqual(req.status,200)
  self.assertEqual(req.response['tempo']['scale'],1.)
  self.assertEqual(app.tempo.scale,1.)

 def test_semantic_window_buttons_and_scroll_region(self):
  app=self.app;app.show_director_semantic_window();self.root.update()
  window=app._director_semantic_window
  controls={str(w.cget('text')):w for w in self.descendants(window) if w.winfo_class()=='TButton'}
  self.timeline()
  app.modifier_tempo_duration_seconds.set(15.)
  for label,scale in (('0.5× · slower',.5),('1× · authored',1.),('2× · faster',2.)):
   controls[label].invoke();self.assertEqual(app.tempo.scale,scale)
  window.geometry('900x600');self.root.update()
  self.assertGreater(window.semantic_canvas.bbox('all')[3],window.semantic_canvas.winfo_height())
  window.semantic_canvas.yview_moveto(1.);self.root.update()
  self.assertGreater(window.semantic_canvas.yview()[0],0.)

class SemanticTempoHTTPTests(unittest.TestCase):
 def test_semantic_tempo_http_route(self):
  from test_director import _post_round_trip
  result=_post_round_trip('/v1/semantic/tempo',{'scale':1.})
  self.assertEqual(result['scale'],1.)

if __name__=='__main__':unittest.main()
