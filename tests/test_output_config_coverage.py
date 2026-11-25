"""Every OutputConfig field follows its setting as soon as the setting changes."""
from dataclasses import fields
import unittest

from test_navigation import NavigationTests
from vector1a.output_config import OutputConfig

# Fields that are not a Tk setting of the same name.
NOT_TK_SETTINGS = {"custom_curves", "variety_started"}


class OutputConfigCoverageTests(unittest.TestCase):
    destroy_root = NavigationTests.destroy_root
    setUp = NavigationTests.setUp
    tearDown = NavigationTests.tearDown

    def settings(self):
        return [f.name for f in fields(OutputConfig) if f.name not in NOT_TK_SETTINGS]

    def test_every_setting_republishes_the_output_config_when_written(self):
        unpublished = []
        for name in self.settings():
            variable = getattr(self.app, name)
            self.app._output_config = None
            variable.set(variable.get())
            if self.app._output_config is None:
                unpublished.append(name)
        self.assertEqual(unpublished, [])

    def test_published_values_follow_the_settings(self):
        wrong = {}
        for name in self.settings():
            variable = getattr(self.app, name)
            value = variable.get()
            if isinstance(value, bool):
                new = not value
            elif isinstance(value, float):
                new = round(value + 0.05, 6)
            else:
                continue
            variable.set(new)
            published = getattr(self.app._output_config, name)
            if published != new:
                wrong[name] = (new, published)
        self.assertEqual(wrong, {})


if __name__ == "__main__":
    unittest.main()
