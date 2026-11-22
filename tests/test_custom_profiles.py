import copy
import json
import queue
import unittest
from unittest.mock import Mock
from vector1a.app import VectorApp
from vector1a.custom_spatial import make_preset, validate_curves, validated_profiles
from vector1a.director import DirectorRequest
from vector1a.parameter_curves import default_curves

class Var:
 def __init__(self,value):self.value=value
 def get(self):return self.value
 def set(self,value):self.value=value

def stub():
 app=object.__new__(VectorApp);app._custom_curves=make_preset('Moving focus');app._custom_profiles={};app._custom_curve_editor=None
 app._parameter_profiles={}
 app._parameter_curves=default_curves()
 app.four_phase_spatial_model=Var('Moving focus');app.director_primary_spatial=Var('top_moving_focus')
 app._save_settings=Mock();app.apply_config=Mock();return app

class ProfileTests(unittest.TestCase):
 def test_save_description_and_load_are_independent_copies(self):
  app=stub();before=copy.deepcopy(app._custom_curves)
  self.assertEqual(app.save_custom_profile(' My profile ','Gentle sweep'),'My profile')
  app._custom_curves[0]['points'][1][1]=12
  self.assertEqual(app._custom_profiles['My profile']['curves'],before)
  app.update_custom_profile_description('My profile','Wide and slow')
  self.assertEqual(app._custom_profiles['My profile']['curves'],before)
  app.apply_custom_profile('My profile')
  self.assertEqual(app._custom_curves,before);self.assertEqual(app.four_phase_spatial_model.get(),'Custom')
  self.assertEqual(app.active_custom_profile()['description'],'Wide and slow')
  app._custom_curves[0]['points'][1][1]=14
  self.assertIsNone(app.active_custom_profile())
 def test_round_trip_validation_and_invalid_data(self):
  app=stub();app.save_custom_profile('A','description')
  saved=json.loads(json.dumps(app._custom_profiles));saved['bad']={'description':'x','curves':[]}
  self.assertEqual(validated_profiles(saved),app._custom_profiles)
  with self.assertRaises(ValueError):app.save_custom_profile('','x')
  with self.assertRaises(ValueError):app.save_custom_profile('x','z'*501)
 def test_profiles_survive_settings_round_trip(self):
  from unittest.mock import patch
  app=stub()
  for field in app.SETTINGS_FIELDS:setattr(app,field,Var(None))
  app.four_phase_spatial_model=Var('Custom');app.director_primary_spatial=Var('top_custom')
  for field in ('director_texture','director_variation','director_top_focus','director_bottom_focus','director_secondary_spatial'):
   setattr(app,field,Var(''))
  app._preset_slots={};app.axis_router=Mock();app.axis_router.enabled_axes.return_value=set()
  app.authored_routing_mode=Var('Manual selected axes')
  for kind in ('texture','variation','top_focus','bottom_focus'):setattr(app,'_director_'+kind+'_profiles',{})
  app._custom_profiles={};app._custom_curves=make_preset('Depth spread');app._active_custom_profile_name=None
  del app._save_settings
  with patch('vector1a.app.save_settings') as save:
   app.save_custom_profile('Depth','Description survives')
   written=json.loads(json.dumps(save.call_args.args[0]))
  restored=stub()
  for field in restored.SETTINGS_FIELDS:setattr(restored,field,Var(None))
  restored.axis_router=Mock();restored._preset_slots={}
  for field in ('director_texture','director_variation','director_top_focus','director_bottom_focus','director_primary_spatial','director_secondary_spatial','authored_routing_mode'):
   setattr(restored,field,Var(''))
  with patch('vector1a.app.load_settings',return_value=written):restored._load_settings()
  self.assertEqual(restored._custom_profiles['Depth']['description'],'Description survives')
  self.assertEqual(restored._custom_curves,app._custom_curves)
  self.assertEqual(restored._active_custom_profile_name,'Depth')
 def test_semantic_request_applies_existing_profile_only(self):
  app=stub();app.save_custom_profile('Wave','Full sweep');app._custom_curves=make_preset('Equal values')
  def request(body):
   req=DirectorRequest('POST','/v1/semantic/primary-spatial',body)
   app.director_bridge=Mock();app.director_bridge.get_nowait.side_effect=[req,queue.Empty()]
   app._drain_director_requests();self.assertTrue(req.completed.is_set());return req
  missing=request({'primary_spatial':'top_custom','custom_profile':'missing'})
  self.assertEqual(missing.status,404);self.assertEqual(app.four_phase_spatial_model.get(),'Moving focus')
  invalid=request({'primary_spatial':'top_depth_spread','custom_profile':'Wave'})
  self.assertEqual(invalid.status,400)
  ok=request({'primary_spatial':'top_custom','custom_profile':'Wave'})
  self.assertEqual(ok.status,200);self.assertEqual(app.active_custom_profile()['name'],'Wave')
  self.assertEqual(app._custom_curves,make_preset('Moving focus'))

if __name__=='__main__':unittest.main()
