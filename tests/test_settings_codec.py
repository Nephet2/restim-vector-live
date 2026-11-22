import json
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from vector1a.app import VectorApp
from settings_scenarios import documents,stub

class SettingsCodecTests(unittest.TestCase):
 def test_exact_previous_load_and_save_documents(self):
  expected=json.loads((Path(__file__).parent/'fixtures/v85_settings.json').read_text())
  for name,document in documents().items():
   with self.subTest(scenario=name):
    app=stub()
    with patch('vector1a.app.load_settings',return_value=document),patch('vector1a.app.save_settings') as save:
     first=app._load_settings();app._save_settings()
    self.assertEqual({'first_run':first,'saved':save.call_args.args[0]},expected[name])

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
