import tkinter as tk
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from vector1a.app import ENVELOPE_SETTING_AXES, VectorApp
from settings_scenarios import stub

SUFFIXES = ("enabled", "attack", "release", "jerk", "advance")


def envelope_fields():
    return [f"{name}_envelope_{suffix}" for name, _ in ENVELOPE_SETTING_AXES
            for suffix in SUFFIXES]


class EnvelopeSettingsFieldTests(unittest.TestCase):
    def test_axes_map_app_names_to_engine_axes(self):
        self.assertEqual(ENVELOPE_SETTING_AXES, (
            ("volume", "V0"), ("frequency", "C0"), ("pulse_frequency", "P0"),
            ("pulse_rise", "P3"), ("pulse_width", "P1")))

    def test_every_envelope_field_is_saved_once(self):
        fields = VectorApp.SETTINGS_FIELDS
        for name in envelope_fields():
            self.assertEqual(fields.count(name), 1, name)

    def test_saved_values_load_back_unchanged(self):
        document = {name: value for name, value in zip(
            envelope_fields(), [True, .1, .5, 100.0, "ma+attack"] * 5)}
        app = stub()
        with patch("vector1a.app.load_settings", return_value=document), \
                patch("vector1a.app.save_settings") as save:
            app._load_settings()
            app._save_settings()
        saved = save.call_args.args[0]
        self.assertEqual({name: saved[name] for name in document}, document)


class EnvelopeSettingsAppTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.guards = ExitStack()
        self.addCleanup(self.guards.close)
        for target in ("vector1a.app.XInputController.start",
                       "vector1a.app.VectorEngine.start",
                       "vector1a.app.FunscriptTimeline.request_media_poll",
                       "vector1a.app.save_settings"):
            self.guards.enter_context(patch(target))
        self.guards.enter_context(patch.object(self.root, "after", return_value="disabled"))
        self.guards.enter_context(patch("vector1a.app.load_settings", return_value={}))
        self.error = self.guards.enter_context(patch("vector1a.app.messagebox.showerror"))
        self.app = VectorApp(self.root)
        self.addCleanup(self.app.close)

    def test_defaults_are_off_and_engine_has_no_envelopes(self):
        self.assertEqual(self.app._envelope_settings(),
                         {axis: None for _, axis in ENVELOPE_SETTING_AXES})
        self.assertTrue(self.app.apply_config())
        self.assertEqual(self.app.engine.envelope_status(), {})

    def test_enabled_axis_reaches_engine_with_its_values(self):
        app = self.app
        app.volume_envelope_enabled.set(True)
        app.volume_envelope_attack.set(.1)
        app.volume_envelope_release.set(.5)
        app.volume_envelope_jerk.set(100.0)
        app.volume_envelope_advance.set("ma+attack")
        self.assertEqual(app._envelope_settings()["V0"], {
            "tau_attack": .1, "tau_release": .5, "jerk_limit": 100.0,
            "compensation": "ma+attack"})
        self.assertTrue(app.apply_config())
        status = app.engine.envelope_status()
        self.assertEqual(set(status), {"V0"})
        self.assertAlmostEqual(status["V0"]["advance_seconds"], .61)

    def test_zero_jerk_means_jerk_limit_off(self):
        app = self.app
        app.pulse_width_envelope_enabled.set(True)
        app.pulse_width_envelope_jerk.set(0.0)
        self.assertIsNone(app._envelope_settings()["P1"]["jerk_limit"])
        self.assertTrue(app.apply_config())
        self.assertEqual(app.engine.envelope_status()["P1"]["window_samples"], 1)

    def test_invalid_values_are_refused_like_other_settings(self):
        app = self.app
        app.volume_envelope_enabled.set(True)
        self.assertTrue(app.apply_config())
        before = app.engine.envelope_status()
        app.volume_envelope_release.set(3.0)              # Above the 2 s V0 cap.
        self.assertFalse(app.apply_config())
        self.error.assert_called_once()
        self.assertEqual(app.engine.envelope_status(), before)

    def test_resume_is_refused_when_envelope_values_are_invalid(self):
        app = self.app
        app.frequency_envelope_enabled.set(True)
        app.frequency_envelope_advance.set("release")
        app.resume()
        self.assertFalse(app.engine.control_state()["output_enabled"])


if __name__ == "__main__":
    unittest.main()
