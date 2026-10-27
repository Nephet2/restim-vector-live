import unittest
from vector1a.custom_spatial import make_preset, validate_curves, evaluate_curves
from vector1a.fourphase import _constrain_restim, map_electrode_order, SPATIAL_MODELS
from vector1a.spatial_curves_math import evaluate

class CustomCurveTests(unittest.TestCase):
 def test_presets_valid_and_constrained(self):
  self.assertIn('Custom',SPATIAL_MODELS)
  for name in ('Moving focus','Depth spread','Staggered','Equal values'):
   curves=validate_curves(make_preset(name))
   for n in range(101):
    raw=tuple(evaluate(c,n/100) for c in curves)
    result=evaluate_curves(curves,n/100)
    self.assertEqual(result,_constrain_restim(raw))
    self.assertTrue(all(0<=x<=1 for x in result))
 def test_shape_points_and_order(self):
  curves=validate_curves(make_preset('Moving focus'))
  for curve in curves:
   for x,y in curve['points']:self.assertAlmostEqual(evaluate(curve,x/100),y/100,places=6)
  value=evaluate_curves(curves,.3)
  self.assertEqual(map_electrode_order(value,'BACD'),(value[1],value[0],value[2],value[3]))
 def test_vector_profile_uses_curve_and_static_electrode_order(self):
  from vector1a.app import VectorApp
  class Var:
   def __init__(self,value): self.value=value
   def get(self): return self.value
  app=object.__new__(VectorApp);app.four_phase_spatial_model=Var('Custom')
  app.electrode_order=Var('BACD');app._custom_curves=make_preset('Moving focus')
  result,source,target,amount,kind=app._four_phase_profile(.37,1,70,.5,1)
  self.assertEqual(result,map_electrode_order(evaluate_curves(app._custom_curves,.37),'BACD'))
  self.assertEqual((source,target,amount,kind),('BACD','BACD',0.0,'custom'))
 def test_invalid_settings_rejected(self):
  with self.assertRaises(ValueError):validate_curves([])
  curves=make_preset('Moving focus');curves[0]['points'][1][0]=0
  with self.assertRaises(ValueError):validate_curves(curves)
  curves=make_preset('Moving focus');curves[2]['points'][1][1]=float('nan')
  with self.assertRaises(ValueError):validate_curves(curves)
 def test_edit_affects_only_new_curve(self):
  original=make_preset('Moving focus');edited=validate_curves(original)
  before=evaluate_curves(original,.5);edited[0]['points'][3][1]=13
  self.assertNotEqual(evaluate_curves(edited,.5),before)
  self.assertNotEqual(edited[0]['points'][3][1],original[0]['points'][3][1])

if __name__=='__main__':unittest.main()
