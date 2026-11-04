"""Behavior contract captured from the untouched Desktop v85 source."""
import json
from pathlib import Path
import unittest
from baseline_capture import capture

class CommandBaselineTests(unittest.TestCase):
 def test_exact_v85_command_and_scheduler_baseline(self):
  root=Path(__file__).resolve().parents[1]
  expected=json.loads((Path(__file__).parent/'fixtures/v85_commands.json').read_text(encoding='utf-8'))
  actual=capture(root)
  self.assertEqual(set(actual),set(expected))
  for scenario in expected:
   with self.subTest(scenario=scenario):
    self.assertEqual(actual[scenario],expected[scenario])

if __name__=='__main__': unittest.main()
