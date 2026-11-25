import time
import unittest
from unittest.mock import patch

from test_navigation import NavigationTests
from vector1a.signal_quality_panel import SignalQualityPanel


class SignalQualityPopoutTests(unittest.TestCase):
    destroy_root = NavigationTests.destroy_root
    setUp = NavigationTests.setUp
    tearDown = NavigationTests.tearDown
    descendants = NavigationTests.descendants

    def pop_out_button(self):
        view = self.app.diagnostics_panel
        buttons = [w for w in self.descendants(view.notebook)
                   if w.winfo_class() == 'TButton' and str(w.cget('text')) == 'Pop out']
        self.assertEqual(len(buttons), 1)
        return buttons[0]

    def test_pop_out_opens_one_movable_window_with_its_own_panel(self):
        view = self.app.diagnostics_panel
        self.pop_out_button().invoke()
        self.root.update()
        window = view.popout_window
        self.assertTrue(window.winfo_exists())
        self.assertEqual(window.winfo_toplevel(), window)
        self.assertIn('Signal Quality', window.title())
        self.assertIsInstance(view.popout_panel, SignalQualityPanel)
        self.assertIsNot(view.popout_panel, view.signal_quality)
        self.assertEqual(window.resizable(), (True, True))
        # A second press brings the same window forward instead of opening another.
        self.pop_out_button().invoke()
        self.assertIs(view.popout_window, window)
        toplevels = [w for w in self.root.winfo_children() if w.winfo_class() == 'Toplevel'
                     and 'Signal Quality' in w.title()]
        self.assertEqual(len(toplevels), 1)

    def test_pop_out_starts_with_the_tab_selections(self):
        view = self.app.diagnostics_panel
        tab = view.signal_quality
        tab.endpoint.current(1)
        tab.span.current(2)
        tab.axis_checks['P0'].invoke()
        self.pop_out_button().invoke()
        self.root.update()
        out = view.popout_panel
        self.assertEqual(out.endpoint.get(), 'Prostate')
        self.assertEqual(out.span.get(), '30 s')
        self.assertEqual({a for a, v in out.axis_selected.items() if v.get()}, {'V0', 'P0'})

    def test_pop_out_updates_while_diagnostics_section_is_out_of_view(self):
        app = self.app
        view = app.diagnostics_panel
        self.pop_out_button().invoke()
        self.root.update()
        self.assertFalse(view.signal_quality.canvas.winfo_ismapped())
        now = time.monotonic()
        with patch.object(app.restim, 'tcode_history',
                          return_value=[(now - .2, 'V02500'), (now - .1, 'V04200')]):
            view.popout_panel.last_refresh = -float('inf')
            view.refresh()
        self.assertEqual(view.popout_panel.stats.set('V0', 'latest'), '42.00')
        self.assertTrue(view.popout_panel.plotted['V0'])
        app._save_settings.assert_not_called()
        for action in self.actions.values():
            action.assert_not_called()

    def test_keep_on_top_and_close_then_reopen(self):
        view = self.app.diagnostics_panel
        self.pop_out_button().invoke()
        self.root.update()
        window = view.popout_window
        self.assertFalse(bool(window.attributes('-topmost')))
        view.popout_on_top.set(True)
        view.apply_popout_on_top()
        self.assertTrue(bool(window.attributes('-topmost')))
        view.close_popout()
        self.assertIsNone(view.popout_window)
        self.assertIsNone(view.popout_panel)
        self.assertFalse(window.winfo_exists())
        view.refresh()                                   # No error once closed.
        self.pop_out_button().invoke()
        self.root.update()
        self.assertTrue(view.popout_window.winfo_exists())
        self.assertTrue(bool(view.popout_window.attributes('-topmost')))   # Choice kept.

    def test_window_close_button_uses_close_popout(self):
        view = self.app.diagnostics_panel
        self.pop_out_button().invoke()
        self.root.update()
        handler = view.popout_window.protocol('WM_DELETE_WINDOW')
        self.assertTrue(handler)
        view.popout_window.tk.call(handler)
        self.assertIsNone(view.popout_window)


if __name__ == '__main__':
    unittest.main()
