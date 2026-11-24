"""An open dropdown must not stop the live display (reported against alpha91).

Opening a ttk dropdown moves Tk focus to its internal "popdown" list, which
has no Python widget.  On Python 3.10 (the report) tkinter's focus_get() then
raises KeyError('popdown'); newer Pythons may return a value instead.  The
tests post a real dropdown and make focus_get() raise exactly as on 3.10, so
they check the behaviour on every Python version.
"""
import unittest
from tkinter import Misc, ttk
from unittest.mock import patch

from test_navigation import NavigationTests


def focus_get_as_on_python_310(self, *args, **kwargs):
    raise KeyError('popdown')


class DropdownFocusTests(unittest.TestCase):
    destroy_root = NavigationTests.destroy_root
    setUp = NavigationTests.setUp
    descendants = NavigationTests.descendants

    def tearDown(self):
        combo = getattr(self, 'posted', None)
        if combo is not None:
            try:
                combo.tk.call('ttk::combobox::Unpost', combo)
            except Exception:
                pass
        NavigationTests.tearDown(self)

    def open_dropdown(self):
        """Post a real combobox list, which moves focus into Tk's popdown."""
        combo = next(w for w in self.descendants(self.app.root)
                     if isinstance(w, ttk.Combobox) and w.winfo_ismapped())
        combo.tk.call('ttk::combobox::Post', combo)
        self.posted = combo
        self.root.update()
        self.assertIn('popdown', str(self.root.tk.call('focus')))   # As in the report.
        patcher = patch.object(Misc, 'focus_get', focus_get_as_on_python_310)
        patcher.start()
        self.addCleanup(patcher.stop)
        return combo

    def test_range_bars_draw_while_a_dropdown_is_open(self):
        self.open_dropdown()
        app = self.app
        for bar in (app.volume_response_bar, app.frequency_bar, app.pulse_frequency_bar,
                    app.pulse_rise_bar, app.pulse_width_bar):
            bar.set_live_value(0.4, 0.6)
            self.assertTrue(bar.find_withtag('live_target'))

    def test_refresh_completes_while_a_dropdown_is_open(self):
        self.open_dropdown()
        app = self.app
        app.root.after.reset_mock()
        app._refresh()
        app.root.after.assert_called_with(100, app._refresh)

    def test_range_bar_still_marks_its_own_keyboard_focus(self):
        bar = self.app.volume_response_bar
        bar.focus_force()
        self.root.update()
        bar.set_live_value(0.5)
        outlines = [bar.itemcget(item, 'outline') for item in bar.find_all()
                    if bar.type(item) == 'rectangle']
        self.assertIn('#1769aa', outlines)            # Focused handle highlight.

    def test_refresh_reschedules_even_if_a_step_fails(self):
        app = self.app
        app.root.after.reset_mock()

        def broken():
            raise RuntimeError('display step failed')
        app.diagnostics_panel.refresh = broken
        with self.assertRaises(RuntimeError):        # Still reported, not hidden...
            app._refresh()
        app.root.after.assert_called_with(100, app._refresh)   # ...but the loop goes on.


if __name__ == '__main__':
    unittest.main()
