from types import SimpleNamespace
from unittest.mock import Mock, patch
from vector1a.custom_spatial import CurveEditor, make_preset


def test_idle_editor_skips_redraw_and_invalidates_for_visible_changes():
    editor=object.__new__(CurveEditor)
    editor.app=SimpleNamespace(_four_phase_send_last_l0=.5,_custom_curves=make_preset('Moving focus'))
    editor.yaw=-24;editor.pitch=25
    editor.plots=[Mock() for _ in range(4)];editor.three=Mock()
    for c in (*editor.plots,editor.three):
        c.winfo_width.return_value=300;c.winfo_height.return_value=150
    editor.draw_3d=Mock()
    with patch('vector1a.custom_spatial.painter',side_effect=lambda c:c),patch('vector1a.custom_spatial.present'):
        editor.draw();assert editor.draw_3d.call_count==1
        editor.draw();assert editor.draw_3d.call_count==1
        editor.app._four_phase_send_last_l0=.6;editor.draw();assert editor.draw_3d.call_count==2
        editor.app._custom_curves[0]['points'][1][1]=20;editor.draw();assert editor.draw_3d.call_count==3
        editor.plots[0].winfo_width.return_value=400;editor.draw();assert editor.draw_3d.call_count==4
        editor.yaw=0;editor.draw();assert editor.draw_3d.call_count==5
