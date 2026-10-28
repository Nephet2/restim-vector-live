import math
import tkinter as tk
from types import SimpleNamespace

import pytest

from vector1a.engine import VectorEngine
from vector1a.motion import MotionMode, MotionParameters
from vector1a.output_ranges import scale_response, unit_range
from vector1a.range_bar import RangeBar


def configured_engine(**kwargs):
    engine = VectorEngine(lambda sample: None, clock=lambda: 10.)
    engine.configure(rate_hz=50, lookahead_seconds=.05, volume=.7,
                     mode=MotionMode.CIRCULAR, params=MotionParameters(), **kwargs)
    return engine


def test_range_math_endpoints_fixed_value_and_invalid_settings():
    assert [scale_response(v,.2,.8) for v in (0,.5,1)] == pytest.approx([.2,.5,.8])
    assert scale_response(-2,.2,.8) == .2
    assert scale_response(2,.2,.8) == .8
    assert scale_response(.2,.6,.6) == .6
    assert unit_range(2,-1) == (0.,1.)
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError):
            unit_range(bad,1)


def test_generator_ranges_bound_primary_secondary_and_carrier():
    engine = configured_engine(volume_response_min=.2, volume_response_max=.8,
                               frequency_min=.3, frequency_max=.6)
    for time in (10.,20.):
        for speed in (0.,1.,35.,100.):
            assert .7*.2 <= engine._calculate_volume(time,speed) <= .7*.8
            assert .7*.2 <= engine._calculate_prostate_volume(time,speed) <= .7*.8
            assert .3 <= engine._calculate_frequency(time,speed) <= .6
    engine.volume_response_min = engine.volume_response_max = .4
    engine.frequency_min = engine.frequency_max = .55
    assert engine._calculate_volume(10.,90.) == pytest.approx(.28)
    assert engine._calculate_prostate_volume(10.,90.) == pytest.approx(.28)
    assert engine._calculate_frequency(10.,90.) == .55
    engine.volume = 0
    assert engine._calculate_volume(10.,90.) == 0
    assert engine._calculate_prostate_volume(10.,90.) == 0


def test_default_ranges_preserve_generator_behaviour():
    engine = configured_engine(dynamic_volume=False)
    assert engine._calculate_volume(10.,100.) == .7
    assert engine._calculate_frequency(10.,100.) == 1.
    assert engine._calculate_frequency(20.,100.) == .5
    engine.dynamic_volume = True
    assert engine._calculate_volume(20.,0.) == pytest.approx(.7*19/20*.4)


def test_stop_and_neutral_do_not_use_running_volume_floor():
    engine = configured_engine(volume_response_min=.8,volume_response_max=.9)
    engine.resume()
    engine.neutral()
    assert engine.diagnostics().state == "Neutral"
    assert engine.diagnostics().output_volume == 0
    engine.stop()
    assert engine.diagnostics().state == "Stopped"
    assert engine.diagnostics().output_volume == 0


@pytest.fixture(scope="module")
def ui_root():
    root = tk.Tk()
    root.geometry("700x120")
    yield root
    root.destroy()


def test_drag_keyboard_and_equal_handles(ui_root):
    low, high = tk.DoubleVar(ui_root,value=.2), tk.DoubleVar(ui_root,value=.8)
    changed=[]
    bar=RangeBar(ui_root,minimum_var=low,maximum_var=high,command=lambda:changed.append((low.get(),high.get())))
    bar.pack()
    ui_root.update()
    bar.set(.2,.8,.5)
    assert bar.winfo_reqheight() <= 26  # 24px content plus existing border.
    bar.event_generate("<Button-1>",x=round(bar._x(.2)),y=5)
    bar.event_generate("<B1-Motion>",x=round(bar._x(.4)),y=5)
    bar.event_generate("<ButtonRelease-1>",x=round(bar._x(.4)),y=5)
    ui_root.update()
    assert low.get() == pytest.approx(.4,abs=.002)
    assert high.get() == .8
    bar._move(1.)
    assert low.get() == .8  # Dragging never crosses the other bound.
    low.set(.5);high.set(.5)
    ui_root.update()
    bar.event_generate("<Button-1>",x=round(bar._x(.5)),y=bar._height-3)
    bar.event_generate("<B1-Motion>",x=round(bar._x(.7)),y=bar._height-3)
    bar.event_generate("<ButtonRelease-1>",x=round(bar._x(.7)),y=bar._height-3)
    ui_root.update()
    assert low.get() == .5
    assert high.get() == pytest.approx(.7,abs=.002)
    bar._select("minimum");bar._nudge(-.01)
    ui_root.update()
    assert low.get() == .49
    assert changed
    # All drawn thumb/track geometry stays within the existing bar height.
    for item in bar.find_all():
        coords=bar.coords(item)
        assert all(0 <= y <= bar._height for y in coords[1::2])


def test_spinbox_edits_redraw_without_rewriting_input(ui_root):
    low, high = tk.DoubleVar(ui_root,value=.2), tk.DoubleVar(ui_root,value=.8)
    changed=[]
    bar=RangeBar(ui_root,minimum_var=low,maximum_var=high,command=lambda:changed.append(True))
    bar.pack();ui_root.update()
    low.set(.35);high.set(.65);ui_root.update()
    assert (bar._minimum,bar._maximum)==(.35,.65)
    assert changed
    changed.clear()
    ui_root.setvar(low._name, "")
    ui_root.update()
    assert changed == []
    low.set(.25);ui_root.update()
    assert bar._minimum == .25


def test_full_app_load_save_and_compact_bar_layout():
    from contextlib import ExitStack
    from unittest.mock import patch
    from vector1a.app import VectorApp
    saved = {"volume_response_min": .15, "volume_response_max": .75,
             "frequency_min": .2, "frequency_max": .9,
             "pulse_frequency_min": .25, "pulse_frequency_max": .85}
    root = tk.Tk()
    app = None
    with ExitStack() as guards:
        guards.enter_context(patch.object(root, "after", return_value="disabled"))
        guards.enter_context(patch("vector1a.app.load_settings", return_value=saved))
        save = guards.enter_context(patch("vector1a.app.save_settings"))
        guards.enter_context(patch("vector1a.app.XInputController.start"))
        guards.enter_context(patch("vector1a.app.VectorEngine.start"))
        guards.enter_context(patch("vector1a.app.FunscriptTimeline.request_media_poll"))
        try:
            app = VectorApp(root)
            for name in ("Frequency", "Pulse frequency", "Pulse rise time", "Pulse width"):
                app.sections[name].collapsed = False
                app.sections[name]._render()
            bars = [app.volume_response_bar, app.frequency_bar, app.pulse_frequency_bar,
                    app.pulse_rise_bar, app.pulse_width_bar]
            for width in (1360,1920):
                root.geometry(f"{width}x1000")
                root.update()
                for bar in bars:
                    assert bar.winfo_height() <= 22
                    assert bar.winfo_width() == 522
                    parent = bar.master
                    assert bar.winfo_x()+bar.winfo_width() <= parent.winfo_width()
            assert app.volume_response_bar.master.winfo_height() <= 120
            # A short window can reach diagnostics, with toolbar staying visible.
            root.geometry("1360x720")
            for name, section in app.sections.items():
                if name != "Commissioning controls":
                    section.collapsed = False
                    section._render()
            root.update()
            assert app.main_scrollbar.winfo_ismapped()
            assert app.main_canvas.yview()[1] < 1.
            app.main_canvas.event_generate("<MouseWheel>", delta=-120)
            root.update()
            assert app.main_canvas.yview()[0] > 0.
            app.main_canvas.yview_moveto(1.)
            root.update()
            diagnostics = app.sections["Live diagnostics"]
            canvas_bottom = app.main_canvas.winfo_rooty()+app.main_canvas.winfo_height()
            assert diagnostics.winfo_rooty()+diagnostics.winfo_height() <= canvas_bottom+24
            assert app.main_canvas.winfo_rooty() > root.winfo_rooty()
            # Resizing and collapsing update the scroll region.
            before = app.main_canvas.bbox("all")[3]
            diagnostics.collapsed = True
            diagnostics._render()
            root.update()
            assert app.main_canvas.bbox("all")[3] < before
            app.apply_config()
            assert app.engine.volume_response_min == .15
            assert app.engine.volume_response_max == .75
            assert app.engine.frequency_min == .2
            assert app.engine.frequency_max == .9
            assert app.engine.pulse_frequency_min == .25
            assert app.engine.pulse_frequency_max == .85
            app._save_settings()
            values = save.call_args.args[0]
            for name,value in saved.items():
                assert values[name] == value
        finally:
            if app is not None:
                app.close()
            else:
                root.destroy()


def test_matching_respects_idle_floor_response_ceiling_and_attack():
    from vector1a.output_ranges import match_volume_response
    engine = configured_engine(volume_rest_level=.4)
    floor = engine.volume_rest_response()
    assert floor == pytest.approx(.38)
    assert match_volume_response(.983, .71, floor) == .71
    assert match_volume_response(.38, 0., floor) == .38
    assert match_volume_response(.5, 1., floor) == .5  # Return-ramp ceiling.
    assert match_volume_response(0., 1., floor) == 0.
    engine.volume_response_min, engine.volume_response_max = .2, .8
    assert engine.volume_rest_response() == pytest.approx(.428)
    assert match_volume_response(.8, 0., engine.volume_rest_response()) == pytest.approx(.428)


def test_actual_primary_and_prostate_commands_and_relocated_control():
    from contextlib import ExitStack
    from unittest.mock import patch
    from vector1a.app import VectorApp
    from vector1a.engine import OutputSample
    from vector1a.howl_conversion import Frame
    root = tk.Tk()
    app = None
    with ExitStack() as guards:
        guards.enter_context(patch.object(root, "after", return_value="disabled"))
        guards.enter_context(patch("vector1a.app.load_settings", return_value={}))
        guards.enter_context(patch("vector1a.app.save_settings"))
        guards.enter_context(patch("vector1a.app.XInputController.start"))
        guards.enter_context(patch("vector1a.app.VectorEngine.start"))
        guards.enter_context(patch("vector1a.app.FunscriptTimeline.request_media_poll"))
        try:
            app = VectorApp(root)
            primary = guards.enter_context(patch.object(app.restim, "send_primary"))
            prostate = guards.enter_context(patch.object(app.prostate_restim, "send_prostate"))
            for sender in (app.restim_sender, app.prostate_sender):
                guards.enter_context(patch.object(sender, "submit", side_effect=lambda fn, **kw: fn()))
            app.four_phase_volume_ceiling.set(1.)
            app.match_spatial_intensity.set(True)
            app.four_phase_reversal_emphasis.set(False)
            app.apply_config()
            guards.enter_context(patch.object(app._howl_converter, "sample",
                return_value=Frame((1.,1.,1.,1.), 0., .5, 0.)))
            idle = app.engine._calculate_volume(app.engine._last_input_time+1., 0.)
            bottom = app.engine._calculate_prostate_volume(app.engine._last_input_time+1., 0.)
            sample = OutputSample(1, 10., 10., .5, .5, 0., .5, .5, idle,
                MotionMode.CIRCULAR, .5, .5, .5, .5, .5, .5, bottom)
            app._send_sample(sample)
            assert primary.call_args.args[3] == pytest.approx(.38)
            assert prostate.call_args.args[2] == pytest.approx(bottom)
            assert app._outgoing_volumes == pytest.approx((.38,bottom))
            from dataclasses import replace
            app.match_spatial_intensity.set(False)
            app.four_phase_volume_ceiling.set(.85)
            app._send_sample(replace(sample, volume=.7*.3928))
            assert primary.call_args.args[3] == pytest.approx(.33388)
            app.match_spatial_intensity.set(True)
            app.four_phase_volume_ceiling.set(1.)
            # Authored V0 remains an explicit override and is reflected in readout.
            guards.enter_context(patch.object(app.axis_router, "snapshot", return_value={"V0":.22}))
            app._send_sample(sample)
            assert primary.call_args.kwargs["overrides"]["V0"] == .22
            assert app._outgoing_volumes[0] == .22
            # One checkbox, in Volume response, with unchanged persisted setting.
            def descendants(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from descendants(child)
            controls=[w for w in descendants(root)
                      if w.winfo_class()=="TCheckbutton" and
                      str(w.cget("text"))=="Match intensity across spatial modes"]
            assert len(controls)==1
            assert controls[0].master == app.volume_response_bar.master
            app.neutral()
            assert app._outgoing_volumes == (.7,.7)
            app.stop()
            assert app._outgoing_volumes == (0.,0.)
        finally:
            if app is not None:
                app.close()
            else:
                root.destroy()
