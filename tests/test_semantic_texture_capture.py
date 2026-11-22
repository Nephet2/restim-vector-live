import copy
import unittest
from unittest.mock import patch
from test_navigation import NavigationTests
from vector1a.app import VectorApp

SAVE_SETTINGS = VectorApp._save_settings


class SemanticCaptureTests(unittest.TestCase):
    setUp = NavigationTests.setUp
    tearDown = NavigationTests.tearDown
    descendants = NavigationTests.descendants

    def checkbox(self, variable):
        matches = []
        for widget in self.descendants(self.app.content):
            if widget.winfo_class() == "TCheckbutton" and str(widget.cget("variable")) == str(variable):
                matches.append(widget)
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_texture_capture_save_reload_apply_restores_actual_controls(self):
        app = self.app
        expected = {
            "frequency_min": .23, "frequency_max": .74,
            "pulse_frequency_min": .31, "pulse_frequency_max": .68,
            "pulse_rise_min": .12, "pulse_rise_max": .43,
            "pulse_width_min": .26, "pulse_width_max": .79,
            "four_phase_reversal_window": .35, "four_phase_reversal_strength": .25,
            "motion_rising_volume_multiplier": .83, "motion_falling_volume_multiplier": .96,
        }
        for name, value in expected.items():
            getattr(app, name).set(value)
        for name in ("four_phase_reversal_emphasis", "four_phase_stroke_phase_texture"):
            variable = getattr(app, name)
            variable.set(False)
            self.checkbox(variable).invoke()
            expected[name] = True
        app._capture_director_profile("texture", "Smooth")
        captured = app._director_texture_profiles["Smooth"]
        for name, value in expected.items():
            self.assertEqual(captured[name], value, name)
        with patch("vector1a.app.save_settings") as save:
            SAVE_SETTINGS(app)
        document = copy.deepcopy(save.call_args.args[0])
        app._director_texture_profiles.clear()
        with patch("vector1a.app.load_settings", return_value=document):
            app._load_settings()
        for name, value in expected.items():
            getattr(app, name).set(False if isinstance(value, bool) else .5)
        app._apply_director_profile("texture", "Smooth")
        for name, value in expected.items():
            self.assertEqual(getattr(app, name).get(), value, name)
        self.assertEqual(app.engine.frequency_min, .23)
        self.assertEqual(app.engine.frequency_max, .74)
        self.assertEqual(app._active_director_profile("texture"), "Smooth")
        app.frequency_min.set(.24)
        self.assertEqual(app._active_director_profile("texture"), "Custom")
        # False checkboxes must also be captured and restored explicitly.
        for name in ("four_phase_reversal_emphasis", "four_phase_stroke_phase_texture"):
            self.checkbox(getattr(app, name)).invoke()
        app._capture_director_profile("texture", "Rough")
        app.four_phase_reversal_emphasis.set(True)
        app.four_phase_stroke_phase_texture.set(True)
        app._apply_director_profile("texture", "Rough")
        self.assertFalse(app.four_phase_reversal_emphasis.get())
        self.assertFalse(app.four_phase_stroke_phase_texture.get())

    def test_variation_checkboxes_restore_independently_from_texture(self):
        app = self.app
        for name in ("jitter_enabled", "speed_linked_variation"):
            variable = getattr(app, name)
            variable.set(False)
            self.checkbox(variable).invoke()
        app._capture_director_profile("variation", "Lively")
        app.jitter_enabled.set(False)
        app.speed_linked_variation.set(False)
        app.four_phase_reversal_emphasis.set(True)
        app._apply_director_profile("variation", "Lively")
        self.assertTrue(app.jitter_enabled.get())
        self.assertTrue(app.speed_linked_variation.get())
        self.assertTrue(app.four_phase_reversal_emphasis.get())

    def test_old_sparse_texture_leaves_previously_uncaptured_values_alone(self):
        app = self.app
        app._director_texture_profiles["Normal"] = {"pulse_width_min": .32,
            "four_phase_reversal_emphasis": False, "four_phase_stroke_phase_texture": True}
        app.frequency_min.set(.18)
        app.frequency_max.set(.81)
        app.motion_rising_volume_multiplier.set(.89)
        app.motion_falling_volume_multiplier.set(.93)
        app._apply_director_profile("texture", "Normal")
        self.assertEqual(app.frequency_min.get(), .18)
        self.assertEqual(app.frequency_max.get(), .81)
        self.assertEqual(app.motion_rising_volume_multiplier.get(), .89)
        self.assertEqual(app.motion_falling_volume_multiplier.get(), .93)
        self.assertEqual(app.pulse_width_min.get(), .32)
        self.assertFalse(app.four_phase_reversal_emphasis.get())
        self.assertTrue(app.four_phase_stroke_phase_texture.get())
