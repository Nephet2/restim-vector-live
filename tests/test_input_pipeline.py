import json
import unittest
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from vector1a.input_pipeline import TempoController, InputPipeline
from tempo_scenarios import tempo_trace

class TempoTests(unittest.TestCase):
 def test_exact_prior_tempo_behavior(self):
  expected=json.loads((Path(__file__).parent/'fixtures/v85_tempo.json').read_text())
  actual=tempo_trace(TempoController)
  for scenario in expected:
   with self.subTest(scenario=scenario):self.assertEqual(actual[scenario],expected[scenario])

class InputTests(unittest.TestCase):
 def pipeline(self,active=False):
  order=[]
  engine=SimpleNamespace(receive_l0=lambda *a,**k:order.append(('engine',a,k)))
  timeline=SimpleNamespace(observe_live=lambda *a:order.append(('observe',a)))
  tempo=SimpleNamespace(transform=lambda value,now:order.append(('transform',value,now)) or value*.5)
  generated=SimpleNamespace(active=active,stroke_bounds=lambda now:(.2,.8))
  return InputPipeline(engine,timeline,generated,tempo),order

 def test_authored_observed_before_transform_and_interval_preserved(self):
  ctl,order=self.pipeline();ctl.receive_authored(.8,120,10.)
  self.assertEqual(order,[('observe',(.8,10.)),('transform',.8,10.),('engine',(.4,120,10.),{})])
  self.assertEqual(ctl.latest_authored_l0,.8)

 def test_generated_ownership_keeps_observation_but_blocks_authored_engine_input(self):
  ctl,order=self.pipeline(True);ctl.receive_authored(.8,120,10.)
  self.assertEqual(order,[('observe',(.8,10.))])
  ctl.generated_motion.active=False;ctl.receive_authored(.6,0,11.)
  self.assertEqual(order[-1],('engine',(.3,0,11.),{}))

 def test_generated_callback_keeps_stroke_bounds_and_timestamp(self):
  ctl,order=self.pipeline(True);ctl.receive_generated(.6,40,12.)
  self.assertEqual(order,[('transform',.6,12.),('engine',(.3,40,12.),{'stroke_bounds':(.2,.8)})])

 def test_exact_original_input_to_engine_sequence(self):
  from tempo_scenarios import input_trace
  expected=json.loads((Path(__file__).parent/'fixtures/v85_input.json').read_text())
  actual=input_trace(lambda engine,timeline,generated:InputPipeline(engine,timeline,generated,TempoController(timeline)))
  self.assertEqual(actual,expected)

 def test_callbacks_run_on_worker_without_ui_objects(self):
  ctl,order=self.pipeline();errors=[]
  def run():
   try:ctl.receive_authored(.8,10,10.);ctl.receive_generated(.6,20,11.)
   except BaseException as exc:errors.append(exc)
  worker=threading.Thread(target=run);worker.start();worker.join(2.)
  self.assertFalse(worker.is_alive());self.assertFalse(errors)
  self.assertEqual(len([x for x in order if x[0]=='engine']),2)

if __name__=='__main__':unittest.main()
