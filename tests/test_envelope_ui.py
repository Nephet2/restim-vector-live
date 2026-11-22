import tkinter as tk
import unittest
from contextlib import ExitStack
from tkinter import ttk
from unittest.mock import patch

from vector1a.app import ENVELOPE_SETTING_AXES, VectorApp, envelope_status_text


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class EnvelopeStatusTextTests(unittest.TestCase):
    def test_off(self):
        self.assertEqual(envelope_status_text(False, None), "Envelope off")

    def test_on_reports_advance_and_window(self):
        text = envelope_status_text(True, {"advance_seconds": .61, "window_samples": 18,
                                           "buffer_limited": False})
        self.assertEqual(text, "Envelope on · advance 0.61 s · jerk window 18 samples")

    def test_buffer_limit_and_replaced_pulse_timing_are_flagged(self):
        text = envelope_status_text(True, {"advance_seconds": .87, "window_samples": 30,
                                           "buffer_limited": True}, replaces_pulse_timing=True)
        self.assertIn("buffer limited: raise look-ahead", text)
        self.assertIn("replaces pulse smoothing and timing for this axis", text)

    def test_howl_pulse_replacement_is_stated_instead_of_envelope_on(self):
        text = envelope_status_text(True, {"advance_seconds": .01, "window_samples": 1,
                                           "buffer_limited": False},
                                    replaces_pulse_timing=True, howl_supplies_axis=True)
        self.assertEqual(text, "Envelope has no effect: Howl pulse supplies this axis")

    def test_jerk_off_is_named(self):
        text = envelope_status_text(True, {"advance_seconds": .01, "window_samples": 1,
                                           "buffer_limited": False})
        self.assertIn("jerk limit off", text)


class EnvelopeControlsTests(unittest.TestCase):
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
        self.guards.enter_context(patch("vector1a.app.messagebox.showerror"))
        self.app = VectorApp(self.root)
        self.addCleanup(self.app.close)
        self.toggles = {str(w.cget("variable")): w for w in descendants(self.root)
                        if w.winfo_class() == "TCheckbutton" and str(w.cget("text")) == "Envelope"}

    def test_one_envelope_toggle_per_axis_bound_to_its_setting(self):
        expected = {str(getattr(self.app, f"{name}_envelope_enabled"))
                    for name, _ in ENVELOPE_SETTING_AXES}
        self.assertEqual(set(self.toggles), expected)

    def test_every_setting_has_a_control(self):
        bound = {str(w.cget("textvariable")) for w in descendants(self.root)
                 if w.winfo_class() in ("TSpinbox", "TCombobox")}
        for name, _ in ENVELOPE_SETTING_AXES:
            for suffix in ("attack", "release", "jerk", "advance"):
                self.assertIn(str(getattr(self.app, f"{name}_envelope_{suffix}")), bound,
                              f"{name}_envelope_{suffix}")

    def test_advance_choices_are_the_engine_modes(self):
        combos = [w for w in descendants(self.root) if w.winfo_class() == "TCombobox"
                  and str(w.cget("textvariable")) == str(self.app.volume_envelope_advance)]
        self.assertEqual(len(combos), 1)
        self.assertEqual(tuple(combos[0].cget("values")), ("none", "ma", "ma+attack"))
        self.assertEqual(str(combos[0].cget("state")), "readonly")

    def test_ticking_a_toggle_applies_it_and_status_follows(self):
        toggle = self.toggles[str(self.app.pulse_rise_envelope_enabled)]
        status = self.app._envelope_status_vars["pulse_rise"]
        self.app._refresh_envelope_status()
        self.assertEqual(status.get(), "Envelope off")
        toggle.invoke()
        self.assertIn("P3", self.app.engine.envelope_status())
        self.app._refresh_envelope_status()
        self.assertTrue(status.get().startswith("Envelope on · advance"), status.get())
        # Pulse smoothing defaults to 5 s, so the replacement is spelled out.
        self.assertIn("replaces pulse smoothing and timing", status.get())
        toggle.invoke()
        self.assertNotIn("P3", self.app.engine.envelope_status())
        self.app._refresh_envelope_status()
        self.assertEqual(status.get(), "Envelope off")

    def test_howl_pulse_is_shown_on_p0_and_p1_only(self):
        app = self.app
        for name in ("pulse_frequency", "pulse_width", "pulse_rise"):
            self.toggles[str(getattr(app, f"{name}_envelope_enabled"))].invoke()
        app.four_phase_spatial_model.set("Howl Positional")
        app.howl_pulse.set(True)                    # Traces republish the output config.
        app._refresh_envelope_status()
        for name in ("pulse_frequency", "pulse_width"):
            self.assertEqual(app._envelope_status_vars[name].get(),
                             "Envelope has no effect: Howl pulse supplies this axis")
        self.assertTrue(app._envelope_status_vars["pulse_rise"].get().startswith("Envelope on"))
        # Howl pulse only replaces P0/P1 with a Howl spatial model.
        app.four_phase_spatial_model.set("Moving focus")
        app._refresh_envelope_status()
        self.assertTrue(app._envelope_status_vars["pulse_width"].get().startswith("Envelope on"))

    def test_volume_status_does_not_mention_pulse_timing(self):
        self.toggles[str(self.app.volume_envelope_enabled)].invoke()
        self.app._refresh_envelope_status()
        text = self.app._envelope_status_vars["volume"].get()
        self.assertTrue(text.startswith("Envelope on"), text)
        self.assertNotIn("pulse", text)


if __name__ == "__main__":
    unittest.main()
