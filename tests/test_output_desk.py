from concurrent.futures import Future
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import json
import tkinter as tk
import unittest

from test_handy import output_fixture
from vector1a.handy_control import HandyControl
from vector1a.handy_script import MotionScript
from vector1a.output_desk import IntensitySource, OutputDesk
from vector1a.output_panel import OutputPanel
from vector1a.vacuglide_control import VacuGlideControl


class VacuumOutput:
    def __init__(self):
        self.calls = []
        self.lease = None
        self.values = dict(state="stopped", ownership="vector", confirmed_speed_percent=0,
                           max_speed_percent=80, error=None, valves={"plus": False, "minus": False},
                           stop_revision=0, stop_verified=True, director_min_speed_percent=0,
                           director_max_speed_percent=70)
    def state(self):
        return {**self.values, "valves": dict(self.values["valves"])}
    def receipt(self):
        f = Future(); f.set_result((200, {"ok": True, **self.state()})); return f
    def reserve_timeline(self, **kwargs):
        self.lease = object(); return self.lease, None
    def owns_timeline(self, lease):
        return self.lease is lease and lease is not None
    def cancel_timeline(self, lease):
        self.lease = None
    def command(self, action, speed, timeline=None):
        assert self.owns_timeline(timeline)
        assert 0 <= speed <= self.values["max_speed_percent"]
        self.calls.append((action, speed))
        self.values.update(state="running", confirmed_speed_percent=speed)
        return self.receipt()
    def motor_rest(self, lease):
        assert self.owns_timeline(lease)
        self.values.update(state="stopped", confirmed_speed_percent=0)
        return self.receipt()
    def valve(self, lease, kind, opened):
        assert self.owns_timeline(lease)
        self.calls.append((kind, opened))
        self.values["valves"][kind] = opened
        return self.receipt()
    def stop(self, release=False):
        self.calls.append(("stop", None))
        self.values.update(state="stopped", confirmed_speed_percent=0,
                           stop_revision=self.values["stop_revision"] + 1,
                           valves={"plus": False, "minus": False})
        self.lease = None
        return self.receipt()


class SourceTests(unittest.TestCase):
    def test_vacuglide_json_uses_authored_intensity_without_replaying_valves(self):
        from vector1a.vacuglide_script import Script, Event
        with TemporaryDirectory() as folder:
            path = Path(folder) / "intensity.json"
            Script("intensity", 2000, (Event(0, "speed", 40), Event(0, "plus", duration_ms=1000))).save(path)
            source = IntensitySource(lambda: None, clock=lambda: 10.)
            source.select("script")
            source.load(path)
            source.start()
            frame = source.frame()
            self.assertAlmostEqual(frame["l0"], .4)
            self.assertIn("authored intensity", frame["label"])
            self.assertNotIn("plus", frame)
            source.invert = True
            self.assertAlmostEqual(source.frame()["l0"], .6)

    def test_position_velocity_inversion_offset_and_paused_source(self):
        now = [10.]
        frame = {"playing": True, "position": 2., "received_at": 10., "source": "movie", "rate": 1,
                 "sample": lambda t: max(0, min(1, t / 10))}
        source = IntensitySource(lambda: frame, clock=lambda: now[0])
        source.position_mode = True
        source.offset = 1
        source.start()
        self.assertAlmostEqual(source.frame()["l0"], .3)
        source.invert = True
        self.assertAlmostEqual(source.frame()["l0"], .7)
        source.invert = False
        source.position_mode = False
        self.assertAlmostEqual(source.frame()["l0"], .1 / 6)
        source.invert = True
        self.assertAlmostEqual(source.frame()["l0"], 1 - .1 / 6)
        frame["playing"] = False
        self.assertFalse(source.frame()["playing"])
        self.assertEqual(source.frame()["l0"], 0)

    def test_manual_uses_trim_level_and_live_source_switch_keeps_preview(self):
        source = IntensitySource(lambda: None)
        source.select("manual")
        source.invert = True
        source.start()
        self.assertEqual(source.frame()["l0"], 1)
        source.select("script")
        self.assertTrue(source.control.previewing)
        source.control.load(MotionScript("test", ((0., .25), (10., .25))))
        source.position_mode = True
        self.assertAlmostEqual(source.frame()["l0"], .75)
        source.pause()
        self.assertEqual(source.frame()["l0"], 0)


class DeskTests(unittest.TestCase):
    def make(self, output):
        self.now = 10.
        self.voutput = VacuumOutput()
        self.vacu = VacuGlideControl(self.voutput, lambda: None, clock=lambda: self.now)
        self.handy = HandyControl(output, lambda: None, clock=lambda: self.now)
        self.handy.select("manual")
        self.app = SimpleNamespace(handy_control=self.handy, vacuglide_control=self.vacu, _handy_transport=lambda: None)
        self.desk = OutputDesk(self.app, clock=lambda: self.now)
        self.desk.select_mapped_intensity("manual")
        return self.desk

    def test_shared_resume_and_pause_respect_link_selection(self):
        with output_fixture() as output:
            desk = self.make(output)
            desk.linked["vacu"] = False
            desk.resume()
            self.assertTrue(self.handy.playing)
            self.assertFalse(self.vacu.playing)
            desk.resume(["vacu"])
            self.vacu.tick()
            self.assertTrue(self.vacu.playing)
            self.assertEqual(self.voutput.calls[-1], ("start", 70.))
            desk.pause()
            self.assertFalse(self.handy.playing)
            self.assertTrue(self.vacu.playing)
            self.assertIn("VacuGlide is unlinked", desk.message)
            desk.pause(["vacu"])
            self.assertFalse(self.vacu.playing)

    def test_preflight_does_not_start_handy_if_linked_vacuum_is_disconnected(self):
        with output_fixture() as output:
            desk = self.make(output)
            self.voutput.values["max_speed_percent"] = None
            with self.assertRaisesRegex(ValueError, "Connect"):
                desk.resume()
            self.assertFalse(self.handy.playing)
            self.assertFalse(output.active)

    def test_pending_resume_is_cancelled_by_global_stop_revision(self):
        with output_fixture() as output:
            desk = self.make(output)
            f = Future()
            self.vacu._pending = ("stop", f)
            desk.resume(["vacu"])
            self.assertTrue(desk.pending_vacu)
            self.voutput.stop()
            desk.tick()
            self.assertFalse(desk.pending_vacu)
            self.assertFalse(self.vacu.playing)

    def test_resume_keeps_the_selected_editor_source(self):
        with output_fixture() as output:
            desk = self.make(output)
            self.vacu.select("manual", None)
            self.vacu.manual_speed = 35
            desk.resume(["vacu"])
            self.vacu.tick()
            desk.resume(["vacu"])
            self.assertEqual(self.voutput.calls, [("start", 35)])
            self.assertEqual(self.vacu.mode, "manual")
            self.assertFalse(desk.source.active)
            with self.assertRaisesRegex(ValueError, "Pause"):
                desk.select_mapped_intensity("manual")
            desk.pause(["vacu"])
            self.vacu.tick()
            desk.select_mapped_intensity("manual")
            self.assertFalse(self.vacu.playing)
            self.assertFalse(desk.source.active)

    def test_resume_after_failed_stop_is_cancelled(self):
        with output_fixture() as output:
            desk = self.make(output)
            future = Future()
            self.vacu._pending = ("stop", future)
            desk.resume(["vacu"])
            future.set_result((502, {"ok": False}))
            self.vacu.tick()
            desk.tick()
            self.assertFalse(desk.pending_vacu)
            self.assertFalse(self.vacu.playing)
            self.assertIn("stop was not confirmed", desk.message)

    def test_resume_after_confirmed_stop_honours_source_selection(self):
        with output_fixture() as output:
            desk = self.make(output)
            future = Future()
            self.vacu._pending = ("stop", future)
            desk.resume(["vacu"])
            future.set_result((200, {"ok": True}))
            self.vacu.tick()
            desk.tick()
            self.assertFalse(desk.pending_vacu)
            self.assertTrue(self.vacu.playing)
            self.assertTrue(desk.source.active)
            desk.pause(["vacu"])
            self.vacu.tick()
            future = Future()
            self.vacu._pending = ("stop", future)
            desk.resume(["vacu"])
            self.vacu.select("manual", None)
            future.set_result((200, {"ok": True}))
            self.vacu.tick()
            desk.tick()
            self.assertFalse(desk.pending_vacu)
            self.assertFalse(self.vacu.playing)

    def test_vacuum_mapping_respects_trim_and_valve_buttons(self):
        with output_fixture() as output:
            desk = self.make(output)
            self.vacu.set_trim(35)
            desk.resume(["vacu"])
            self.vacu.tick()
            self.assertEqual(self.voutput.calls[-1], ("start", 35.))
            self.vacu.stroke("plus")
            for _ in range(3):
                self.vacu.tick()
            self.assertIn(("plus", True), self.voutput.calls)
            self.now += 1.1
            for _ in range(3):
                self.vacu.tick()
            self.assertIn(("plus", False), self.voutput.calls)
            desk.pause(["vacu"])

    def test_existing_interface_can_take_back_source(self):
        with output_fixture() as output:
            desk = self.make(output)
            desk.resume(["vacu"])
            self.vacu.select("manual", None)
            desk.tick()
            self.assertIsNone(self.vacu.mapped_source)
            self.assertFalse(desk.source.active)

    def test_invalid_source_stops_vacuum_and_does_not_invert_missing_input(self):
        with output_fixture() as output:
            desk = self.make(output)
            desk.resume(["vacu"])
            self.vacu.tick()
            with patch.object(desk.source, "frame", return_value={"playing": True, "l0": float("nan")}):
                self.vacu.tick()
            self.assertFalse(self.vacu.playing)
            self.assertEqual(self.voutput.calls[-1][0], "stop")

    def test_global_stop_cancels_pending_shared_resume(self):
        from vector1a.app import VectorApp
        from unittest.mock import Mock
        with output_fixture() as output:
            desk = self.make(output)
            desk.pending_vacu = True
            # Exercise the integration hook without invoking ReStim setup.
            app = SimpleNamespace(output_desk=desk, handy_control=Mock(), vacuglide=Mock(),
                                  engine=Mock(), _reset_four_phase_group_delay=Mock(),
                                  _mute_output=Mock(), _four_phase_live_lock=__import__('threading').Lock(),
                                  _input_lock=__import__('threading').Lock(), passage=Mock(),
                                  event_engine=Mock(), generated_motion=Mock(), output_composer=Mock(),
                                  electrode_order=SimpleNamespace(get=lambda: "ABCD"))
            VectorApp.stop(app)
            self.assertFalse(desk.pending_vacu)
            self.assertFalse(desk.source.active)
            app.handy_control.stop.assert_called_once()
            app.vacuglide.stop.assert_called_once()

    def test_window_builds_and_closing_pauses_both_without_external_activity(self):
        with output_fixture() as output, TemporaryDirectory() as folder:
            desk = self.make(output)
            root = tk.Tk(); root.withdraw()
            self.app.root = root
            self.app.output_desk = desk
            self.app.stop = lambda: desk.pause(["handy", "vacu"])
            try:
                with patch("vector1a.output_panel.settings_path", return_value=Path(folder) / "settings.json"):
                    panel = OutputPanel(self.app)
                    root.update()
                    self.assertEqual(panel.hmode.get(), "manual")
                    self.assertTrue(panel.links["handy"].get())
                    self.assertTrue(panel.links["vacu"].get())
                    panel.close()
                    self.assertFalse(self.handy.running)
                    self.assertFalse(self.vacu.playing)
            finally:
                root.destroy()

    def test_vacu_source_and_linked_pause_agree_across_both_windows(self):
        from vector1a.vacuglide_editor import Editor

        def find_button(parent, label):
            for child in parent.winfo_children():
                if "text" in child.keys() and child.cget("text") == label and hasattr(child, "invoke"):
                    return child
                found = find_button(child, label)
                if found is not None:
                    return found
            return None

        with output_fixture() as output, TemporaryDirectory() as folder:
            desk = self.make(output)
            root = tk.Tk()
            root.withdraw()
            self.app.root = root
            self.app.output_desk = desk
            self.app.stop = lambda: None
            try:
                with patch("vector1a.output_panel.settings_path", return_value=Path(folder) / "settings.json"), patch(
                        "vector1a.vacuglide_editor.load_token", return_value=""):
                    editor = Editor(root, self.voutput, self.app)
                    combined = OutputPanel(self.app)
                    linked_pause = find_button(combined.window, "Pause linked")
                    choose_funscript = find_button(combined.frames["vacu"], "Funscript")

                    editor.source_buttons["script"].invoke()
                    combined.refresh_vacu_source()
                    self.assertEqual(editor.selected_source.get(), "script")
                    self.assertEqual(combined.vmode.get(), "")
                    editor.play_live_button.invoke()
                    self.vacu.tick()
                    self.assertTrue(self.vacu.playing)
                    self.assertEqual(self.voutput.state()["state"], "running")

                    linked_pause.invoke()
                    for _ in range(3):
                        self.vacu.tick()
                        desk.tick()
                    self.assertFalse(self.vacu.playing)
                    self.assertEqual(self.voutput.state()["confirmed_speed_percent"], 0)
                    self.assertEqual(self.voutput.calls[-1], ("stop", None))
                    self.assertIn("Handy and VacuGlide", desk.message)

                    choose_funscript.invoke()
                    editor.refresh_source_selection()
                    self.assertEqual(combined.vmode.get(), "follow")
                    self.assertTrue(editor.mapped_source_indicator.instate(["selected"]))
                    self.assertFalse(editor.source_buttons["script"].instate(["selected"]))
                    self.assertEqual(editor.mapped_source_indicator.cget("text"), "Mapped Funscript")
                    self.assertFalse(self.vacu.playing)

                    editor.source_buttons["script"].invoke()
                    combined.refresh_vacu_source()
                    self.assertEqual(combined.vmode.get(), "")
                    self.assertTrue(editor.source_buttons["script"].instate(["selected"]))
                    combined.close()
                    editor.close()
            finally:
                root.destroy()

    def test_handy_windows_only_commit_the_edited_field(self):
        from vector1a.handy_panel import HandyPanel
        with output_fixture() as output, TemporaryDirectory() as folder:
            self.make(output)
            root = tk.Tk()
            root.withdraw()
            self.app.root = root
            self.app.output_desk = self.desk
            self.app.stop = lambda: None
            try:
                with patch("vector1a.output_panel.settings_path", return_value=Path(folder) / "settings.json"), patch(
                        "vector1a.handy_panel.settings_path", return_value=Path(folder) / "settings.json"):
                    combined = OutputPanel(self.app)
                    device = HandyPanel(self.app)
                    device.tempo.set(1.5)
                    device.settings_changed("tempo")
                    combined.hinvert.set(True)
                    combined.change_handy("invert", combined.hinvert)
                    self.assertEqual(self.handy.tempo, 1.5)
                    combined.window.after_cancel(combined.job)
                    combined.refresh()
                    self.assertEqual(combined.htempo.get(), 1.5)
                    combined.set_tempo(.5)
                    device.gradient.set(False)
                    device.settings_changed("gradient")
                    self.assertEqual(self.handy.tempo, .5)
                    self.assertTrue(self.handy.invert)
                    device.window.after_cancel(device.job)
                    device.refresh()
                    self.assertEqual(device.tempo.get(), .5)
                    self.assertTrue(device.invert.get())
                    combined.close()
                    device.close()
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
