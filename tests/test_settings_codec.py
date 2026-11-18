import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from vector1a.app import VectorApp
from vector1a.engine import PRIMARY_PULSE_AXES
from settings_scenarios import documents,stub

RESPONSE_FIELDS = {
    f"{axis}_{suffix}" for axis in PRIMARY_PULSE_AXES
    for suffix in ("damping", "offset_ms", "phase_degrees")
}
ADDED_SETTINGS = RESPONSE_FIELDS | {
    "direct_deovr_host", "direct_deovr_port", "direct_here_host", "direct_here_port",
    "direct_mpc_host", "direct_mpc_port", "preserve_stroke_range", "timeline_interpolation",
    "timing_variation_amount", "timing_variation_enabled", "timing_variation_group_multiplier",
    "timing_variation_style",
}

class SettingsCodecTests(unittest.TestCase):
 def test_exact_previous_load_and_save_documents(self):
  expected=json.loads((Path(__file__).parent/'fixtures/v85_settings.json').read_text())
  for name,document in documents().items():
   with self.subTest(scenario=name):
    app=stub()
    with patch('vector1a.app.load_settings',return_value=document),patch('vector1a.app.save_settings') as save:
     first=app._load_settings();app._save_settings()
    saved = save.call_args.args[0]
    self.assertEqual(saved.keys() - expected[name]['saved'].keys(), ADDED_SETTINGS)
    old_fields = {key: value for key, value in saved.items() if key not in ADDED_SETTINGS}
    self.assertEqual({'first_run':first,'saved':old_fields},expected[name])

 def test_response_settings_round_trip(self):
  response = {key: 0.5 if key.endswith("damping") else -10 for key in RESPONSE_FIELDS}
  app = stub()
  with patch('vector1a.app.load_settings', return_value=response), patch('vector1a.app.save_settings') as save:
   app._load_settings()
   app._save_settings()
  self.assertEqual({key: save.call_args.args[0][key] for key in response}, response)

 def test_decode_does_not_mutate_or_alias_input(self):
  document=documents()['all_profiles'];before=deepcopy(document)
  decoded=VectorApp._settings_codec().decode(document)
  decoded.state['_custom_curves'][0]['points'][0][1]=19
  self.assertEqual(document,before)
  legacy=documents()['legacy'];VectorApp._settings_codec().decode(legacy)
  self.assertNotIn('modifier_stroke_range',legacy)

 def test_saved_snapshot_is_detached_from_live_profiles(self):
  app=stub();document=documents()['all_profiles']
  with patch('vector1a.app.load_settings',return_value=document),patch('vector1a.app.save_settings') as save:
   app._load_settings();app._save_settings()
  written=save.call_args.args[0];before=deepcopy(written)
  app._custom_curves[0]['points'][0][1]=28
  app._preset_slots['A']['four_phase_volume_ceiling']=.2
  self.assertEqual(written,before)

 def test_duplicate_field_names_are_removed_without_changing_keys(self):
  codec=VectorApp._settings_codec()
  self.assertEqual(len(codec.fields),len(set(codec.fields)))
  self.assertEqual(set(codec.fields),set(VectorApp.SETTINGS_FIELDS))

if __name__=='__main__':unittest.main()
