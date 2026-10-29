from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace
import tkinter as tk

import pytest

from vector1a.engine import VectorEngine
from vector1a.parameter_curves import default_curves, validate_parameter_curves, shape_output, PARAMETERS
from vector1a.spatial_curves_math import preset, evaluate


def test_curve_validation_copy_and_shape_bounds():
    curves = default_curves()
    copied = validate_parameter_curves(curves)
    curves['frequency']['points'][0][1] = 50
    assert copied['frequency']['points'][0][1] == 0
    with pytest.raises(ValueError): validate_parameter_curves({})
    for value in (0.2, 0.31, 0.8):
        assert shape_output(copied['frequency'], value, .2, .8)[0] == value
    for shape in ('bell','valley','triangle','falling'):
        for i in range(101):
            output, drive = shape_output(preset(shape), .2+.6*i/100, .2, .8)
            assert .2-1e-12 <= output <= .8+1e-12
            assert 0 <= drive <= 1
    assert shape_output(preset('falling'), .4, .4, .4) == (.4, 0.)


def test_straight_curves_preserve_existing_calculations_exactly():
    # The old arithmetic remains explicit, including the legacy width clamp.
    engine = VectorEngine(lambda sample:None, clock=lambda:10.)
    engine.volume_ramp_up_seconds = 0
    for speed in (0.,.3,1.,20.,60.,100.):
        for value in (0.,.3,.7,1.):
            engine._last_input_time = 10.
            normalized = speed/100
            expected = (engine.frequency_ramp_level*(engine.frequency_ramp_speed_ratio-1)+normalized)/engine.frequency_ramp_speed_ratio
            assert engine._calculate_frequency(10.,speed) == expected
            combined=(normalized*(engine.pulse_frequency_ratio-1)+value)/engine.pulse_frequency_ratio
            if not (speed>.5 and value>1e-6): combined*=engine.volume_rest_level
            expected=engine.pulse_frequency_min+combined*(engine.pulse_frequency_max-engine.pulse_frequency_min)
            assert engine._calculate_pulse_frequency(10.,speed,value) == expected
            combined=((1-engine.frequency_ramp_level)*(engine.pulse_rise_ratio-1)+1-normalized)/engine.pulse_rise_ratio
            expected=engine.pulse_rise_min+combined*(engine.pulse_rise_max-engine.pulse_rise_min)
            assert engine._calculate_pulse_rise_time(speed) == expected
            limited=min(engine.pulse_width_max,max(engine.pulse_width_min,1-value))
            combined=(normalized*(engine.pulse_width_ratio-1)+limited)/engine.pulse_width_ratio
            if speed<=.5:combined*=engine.volume_rest_level
            expected=min(engine.pulse_width_max,max(engine.pulse_width_min,combined))
            assert engine._calculate_pulse_width(10.,speed,value) == expected


def test_each_curve_shapes_its_own_axis_and_fixed_bounds():
    engine = VectorEngine(lambda sample:None,clock=lambda:10.)
    curves=default_curves()
    for key,*_ in PARAMETERS:curves[key]={'points':[[0,25],[100,25]],'interpolation':'smooth'}
    engine.set_parameter_curves(curves)
    expected=[.25, engine.pulse_frequency_min+.25*(engine.pulse_frequency_max-engine.pulse_frequency_min),
              engine.pulse_rise_min+.25*(engine.pulse_rise_max-engine.pulse_rise_min),
              engine.pulse_width_min+.25*(engine.pulse_width_max-engine.pulse_width_min)]
    values=[engine._calculate_frequency(10.,80.),engine._calculate_pulse_frequency(10.,80.,.8),
            engine._calculate_pulse_rise_time(80.),engine._calculate_pulse_width(10.,80.,.8)]
    assert values==pytest.approx(expected)
    assert len(engine.parameter_curve_snapshot())==4
    engine.pulse_width_min=engine.pulse_width_max=.4
    assert engine._calculate_pulse_width(10.,80.,.8)==.4
    with pytest.raises(ValueError):engine.set_parameter_curves({})
    assert engine.parameter_curves==validate_parameter_curves(curves)


def test_editor_live_add_drag_remove_restore_and_settings():
    from vector1a.app import VectorApp
    root=tk.Tk()
    app=None
    with ExitStack() as guards:
        guards.enter_context(patch.object(root,'after',return_value='disabled'))
        guards.enter_context(patch('vector1a.app.load_settings',return_value={}))
        save=guards.enter_context(patch('vector1a.app.save_settings'))
        guards.enter_context(patch('vector1a.app.XInputController.start'))
        guards.enter_context(patch('vector1a.app.VectorEngine.start'))
        guards.enter_context(patch('vector1a.app.FunscriptTimeline.request_media_poll'))
        try:
            app=VectorApp(root)
            app.show_parameter_curves()
            editor=app._parameter_curve_editor
            root.update()
            assert len(editor.plots)==6
            for width,height in ((1120,740),(1360,850)):
                editor.window.geometry(f'{width}x{height}')
                root.update()
                assert editor.footer.winfo_rooty()+editor.footer.winfo_height() <= editor.window.winfo_rooty()+editor.window.winfo_height()
                assert editor.three.winfo_height()>100
                assert all(c.winfo_height()>80 for c in editor.plots.values())

            # One discoverable button shares the response bar's existing row.
            button=app.response_curves_button
            assert button.master is app.volume_response_bar.master
            assert button.grid_info()['row']==app.volume_response_bar.grid_info()['row']
            assert int(button.grid_info()['column'])<int(app.volume_response_bar.grid_info()['column'])
            assert button.winfo_x()+button.winfo_width()<=980
            assert app.match_spatial_intensity.get() is False
            assert app.speed_linked_variation.get() is False
            editor.focus_parameter('pulse_width')
            root.update()
            assert editor.graph_canvas.yview()[0]>0
            assert editor.cards['pulse_width'].winfo_rooty() < editor.graph_canvas.winfo_rooty()+editor.graph_canvas.winfo_height()
            editor.focus_parameter('primary_volume')
            root.update()
            assert editor.graph_canvas.yview()[0]==0
            # Profiles are independent copies of all six shapes, and load live.
            editor.profile_name.set('My response')
            editor.profile_description.set('Gentle four-parameter response')
            editor.save_profile()
            saved_profile=validate_parameter_curves(app._parameter_profiles['My response']['curves'])
            editor.draft['frequency']['points'][0][1]=60
            editor.changed()
            assert app._parameter_profiles['My response']['curves']==saved_profile
            editor.profile_choice.set('My response')
            editor.load_profile()
            assert app.engine.parameter_curves==saved_profile
            assert app.frequency_min.get()==0. and app.frequency_max.get()==1.
            editor.profile_description.set('Updated description')
            editor.update_description()
            assert app._parameter_profiles['My response']['description']=='Updated description'
            editor.save()
            assert save.call_args.args[0]['parameter_response_profiles']==app._parameter_profiles
            # Real mouse events rotate the composite, without changing the curves.
            before=editor.composite.yaw,editor.composite.pitch
            editor.three.event_generate('<ButtonPress-1>',x=50,y=50)
            editor.three.event_generate('<B1-Motion>',x=110,y=80)
            root.update()
            assert (editor.composite.yaw,editor.composite.pitch)!=before
            assert app.engine.parameter_curves==saved_profile
            editor.composite.reset()
            assert (editor.composite.yaw,editor.composite.pitch)==(-28.,25.)

            for key,*_ in PARAMETERS:
                canvas=editor.plots[key]
                x,y=editor.coords(key,50,25)
                editor.add(SimpleNamespace(x=x,y=y),key)
                assert len(app.engine.parameter_curves[key]['points'])==3
                assert evaluate(app.engine.parameter_curves[key],.5)==pytest.approx(.25,abs=.005)
                canvas.event_generate('<ButtonPress-1>',x=round(x),y=round(y))
                nx,ny=editor.coords(key,60,80)
                canvas.event_generate('<B1-Motion>',x=round(nx),y=round(ny))
                canvas.event_generate('<ButtonRelease-1>',x=round(nx),y=round(ny))
                root.update()
                assert app.engine.parameter_curves[key]['points'][1][1]==pytest.approx(80,abs=1)
                moved=app.engine.parameter_curves[key]['points'][1]
                nx,ny=editor.coords(key,*moved)
                editor.remove(SimpleNamespace(x=nx,y=ny),key)
                assert len(app.engine.parameter_curves[key]['points'])==2
                # Endpoint X cannot move or be removed; its Y remains editable.
                x,y=editor.coords(key,0,0)
                editor.press(SimpleNamespace(x=x,y=y),key)
                nx,ny=editor.coords(key,40,35)
                editor.move(SimpleNamespace(x=nx,y=ny),key)
                editor.release()
                assert app.engine.parameter_curves[key]['points'][0][0]==0
                x,y=editor.coords(key,0,35)
                editor.remove(SimpleNamespace(x=x,y=y),key)
                assert len(app.engine.parameter_curves[key]['points'])==2
            editor.save()
            assert save.call_args.args[0]['parameter_response_curves']==app.engine.parameter_curves
            editor.discard()
            assert app.engine.parameter_curves==default_curves()
            editor.close()
            assert app._parameter_curve_editor is None
            # No secondary editor instance and no Apply button.
            app.show_parameter_curves();editor=app._parameter_curve_editor
            same=editor
            app.show_parameter_curves()
            assert app._parameter_curve_editor is same
            def children(widget):
                for child in widget.winfo_children():
                    yield child
                    yield from children(child)
            assert not any(w.winfo_class()=='TButton' and 'Apply' in w.cget('text') for w in children(editor.window))
            editor.close()
        finally:
            if app:app.close()
            else:root.destroy()


def test_parameter_profile_validation_roundtrip_and_invalid_entries():
    import json
    from vector1a.parameter_curves import validate_parameter_profile, validated_parameter_profiles
    name, profile=validate_parameter_profile(' Example ', ' Description ', default_curves())
    assert name=='Example' and profile['description']=='Description'
    saved=json.loads(json.dumps({name:profile}))
    saved['Broken']={'curves':{}}
    saved['Bad type']=None
    assert validated_parameter_profiles(saved)=={name:profile}
    for bad in ('','x'*81,None):
        with pytest.raises(ValueError):validate_parameter_profile(bad,'',default_curves())
    with pytest.raises(ValueError):validate_parameter_profile('A','x'*501,default_curves())


def test_composite_projection_rotations_fit_the_viewport():
    import math
    from vector1a.parameter_curve_3d import ParameterCurveComposite
    view=ParameterCurveComposite.__new__(ParameterCurveComposite)
    for yaw in (-180.,-28.,0.,90.,179.):
        for pitch in (10.,25.,75.):
            view.yaw,view.pitch=yaw,pitch
            for w,h in ((320,240),(450,500)):
                point=view.projector(w,h)
                for x in (0.,.5,1.):
                    for y in (0.,1.):
                        for lane in range(len(PARAMETERS)):
                            px,py,depth=point(x,y,lane)
                            assert all(math.isfinite(v) for v in (px,py,depth))
                            assert 0<=px<=w and 0<=py<=h


def test_volume_curves_are_independent_and_zero_volume_stays_zero():
    engine=VectorEngine(lambda sample:None,clock=lambda:10.)
    engine.volume_ramp_up_seconds=0
    curves=default_curves()
    curves['primary_volume']={'points':[[0,20],[100,20]],'interpolation':'linear'}
    curves['prostate_volume']={'points':[[0,80],[100,80]],'interpolation':'smooth'}
    engine.set_parameter_curves(curves)
    assert engine._calculate_volume(10.,80.)==pytest.approx(engine.volume*.2)
    assert engine._calculate_prostate_volume(10.,80.)==pytest.approx(engine.volume*.8)
    current=engine.parameter_curve_snapshot()['primary_volume']
    assert engine.volume_rest_response()==pytest.approx(.2)
    assert engine.parameter_curve_snapshot()['primary_volume']==current
    engine.volume=0
    assert engine._calculate_volume(10.,80.)==0
    assert engine._calculate_prostate_volume(10.,80.)==0


def test_legacy_four_curve_profiles_add_neutral_volumes():
    from vector1a.parameter_curves import validated_parameter_profiles
    curves=default_curves()
    del curves['primary_volume'];del curves['prostate_volume']
    curves['frequency']=preset('bell','smooth')
    migrated=validate_parameter_curves(curves)
    assert migrated['frequency']==curves['frequency']
    assert migrated['primary_volume']==default_curves()['primary_volume']
    profile=validated_parameter_profiles({'Old':{'description':'Legacy', 'curves':curves}})['Old']
    assert profile['curves']==migrated
    bad=dict(curves);bad['primary_volume']=default_curves()['primary_volume']
    with pytest.raises(ValueError):validate_parameter_curves(bad)


def test_volume_matching_uses_the_shaped_idle_floor():
    from vector1a.output_ranges import match_volume_response
    engine=VectorEngine(lambda sample:None,clock=lambda:10.)
    curves=default_curves()
    curves['primary_volume']={'points':[[0,20],[100,20]],'interpolation':'linear'}
    engine.set_parameter_curves(curves)
    idle=engine._calculate_volume(11.,0.)/engine.volume
    assert match_volume_response(idle,0.,engine.volume_rest_response())==pytest.approx(.2)
    engine.resume();engine.stop()
    assert engine.diagnostics().output_volume==0
