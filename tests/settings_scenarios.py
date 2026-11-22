"""Synthetic, non-personal settings documents for compatibility checks."""
from copy import deepcopy
from types import SimpleNamespace
from vector1a.app import VectorApp
from vector1a.custom_spatial import make_preset
from vector1a.parameter_curves import default_curves

class Var:
 def __init__(self,value):self.value=value
 def get(self):return self.value
 def set(self,value):self.value=value

class Router:
 def __init__(self):self.axes={'P3'}
 def enabled_axes(self):return self.axes
 def set_enabled_axes(self,axes):self.axes={str(x).upper() for x in axes}

def stub(cls=VectorApp):
 app=object.__new__(cls)
 for name in set(app.SETTINGS_FIELDS)|{'director_texture','director_variation','director_top_focus','director_bottom_focus','director_primary_spatial','director_secondary_spatial','authored_routing_mode'}:
  setattr(app,name,Var('initial'))
 app._parameter_curves=default_curves();app._parameter_profiles={}
 app._custom_curves=make_preset('Moving focus');app._custom_profiles={};app._active_custom_profile_name=None
 app._preset_slots={'B':{'old':1}};app.axis_router=Router()
 for kind in ('texture','variation','top_focus','bottom_focus'):setattr(app,'_director_'+kind+'_profiles',{})
 return app

def documents():
 custom=make_preset('Depth spread');curves=default_curves()
 legacy={k:v for k,v in curves.items() if k not in ('primary_volume','prostate_volume')}
 return {
  'empty':{},
  'legacy':{'modifier_range_scale':.7,'parameter_response_curves':legacy,'parameter_response_profiles':{'Old':{'description':'legacy four curves','curves':legacy}}},
  'explicit_over_legacy':{'modifier_range_scale':.7,'modifier_stroke_range':.9,'first_run_complete':True},
  'all_profiles':{'custom_spatial_curves':custom,'custom_spatial_profiles':{'Spatial':{'description':'spatial','curves':custom}},'active_custom_profile':'Spatial',
   'parameter_response_curves':curves,'parameter_response_profiles':{'Response':{'description':'response','curves':curves}},
   'four_phase_presets':{'A':{'four_phase_volume_ceiling':.8},'B':{'electrode_order':'BACD'}},
   'director_texture_profiles':{'Smooth':{'frequency_ramp_level':.6},'unknown':{}},
   'director_variation_profiles':{'Wild':{'variety_enabled':True}},
   'director_top_focus_profiles':{'Root Focus':{'electrode_order':'ABCD'}},
   'director_bottom_focus_profiles':{'Anal Focus':{'prostate_rest_level':.4}},
   'director_texture':'Smooth','director_variation':'Wild','director_top_focus':'Root Focus','director_bottom_focus':'Anal Focus',
   'director_primary_spatial':'top_custom','director_secondary_spatial':'bottom_focus',
   'authored_axis_routes':['E1','P0'],'authored_routing_mode':'Auto authored ReStim set','first_run_complete':True,
   'restim_port':12355,'prostate_port':12350},
  'invalid_profiles':{'custom_spatial_curves':[],'parameter_response_curves':{},'parameter_response_profiles':{'bad':None},
   'custom_spatial_profiles':{'bad':{'curves':[]}},'active_custom_profile':'missing','four_phase_presets':{'A':None,'C':{}},
   'director_texture_profiles':{'Smooth':None,'unknown':{}},'director_variation_profiles':[],
   'authored_axis_routes':'bad','authored_routing_mode':'bad'},
  'unknown_fields':{'future_setting':{'nested':[1,2]},'first_run_complete':True},
 }
