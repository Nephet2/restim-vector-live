import json
import unittest
from pathlib import Path
from dataclasses import FrozenInstanceError
from vector1a.output_config import freeze_curves
from baseline_capture import capture

class OutputSnapshotTests(unittest.TestCase):
 def test_curves_are_immutable_and_detached(self):
  source=[{'interpolation':'linear','points':[[0,0],[100,100]]}]
  frozen=freeze_curves(source)
  source[0]['points'][0][1]=40
  self.assertEqual(frozen[0]['points'][0],(0,0))
  with self.assertRaises(TypeError): frozen[0]['interpolation']='smooth'
  with self.assertRaises(TypeError): frozen[0]['points'][0][1]=20

 def test_real_worker_uses_no_tk_variables_and_matches_v85(self):
  root=Path(__file__).resolve().parents[1]
  expected=json.loads((Path(__file__).parent/'fixtures/v85_commands.json').read_text())
  actual=capture(root,worker_check=True)
  for scenario in expected:
   with self.subTest(scenario=scenario):self.assertEqual(actual[scenario],expected[scenario])

if __name__=='__main__':unittest.main()
