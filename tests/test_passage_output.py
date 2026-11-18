"""Wire-format regression across generated/authored/event/pressure output paths."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from baseline_capture import capture


class PassageOutputTests(unittest.TestCase):
    def test_final_factor_covers_all_volume_paths_and_preserves_other_axes(self):
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads((root/'tests/fixtures/v85_commands.json').read_text())
        with patch('vector1a.passage.PassageController.factors_now', return_value=(.5, .25)):
            actual = capture(root, worker_check=True)
        for scenario, before in baseline.items():
            if 'primary' not in before:
                self.assertEqual(actual[scenario], before)
                continue
            for lane, factor in (('primary', .5), ('prostate', .25)):
                for b, a in zip(before[lane], actual[scenario][lane]):
                    old = {v[:2]: int(v[2:]) for v in b.split()}
                    new = {v[:2]: int(v[2:]) for v in a.split()}
                    with self.subTest(scenario=scenario, lane=lane):
                        self.assertEqual(set(old), set(new))
                        for key in old:
                            if key == 'V0':
                                self.assertLessEqual(new[key], old[key])
                                self.assertAlmostEqual(new[key], old[key]*factor, delta=1)
                            else:
                                self.assertEqual(new[key], old[key])


if __name__ == '__main__': unittest.main()
