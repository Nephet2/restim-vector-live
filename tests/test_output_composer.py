import json
import unittest
from pathlib import Path
from baseline_capture import capture

class OutputComposerTests(unittest.TestCase):
 def test_extended_pre_extraction_behavior_on_real_worker(self):
  root=Path(__file__).resolve().parents[1]
  expected=json.loads((Path(__file__).parent/'fixtures/v85_composer_extended.json').read_text())
  actual=capture(root,worker_check=True,extended=True)
  self.assertEqual(set(actual),set(expected))
  for scenario in expected:
   with self.subTest(scenario=scenario):self.assertEqual(actual[scenario],expected[scenario])

if __name__=='__main__':unittest.main()
