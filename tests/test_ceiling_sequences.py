import unittest
from dataclasses import replace
from vector1a.passage_sequence import SequencePlan
from vector1a.passage import PassageController
from vector1a.engine import VectorEngine, OutputSample
from vector1a.motion import MotionMode
from vector1a.output_composer import OutputComposer
from test_passage import Clock


class CeilingSequenceTests(unittest.TestCase):
    def test_visible_readback_tracks_controller_instead_of_preview(self):
        from vector1a.sequence_ui import controller_display
        clock=Clock();controller=PassageController(clock)
        self.assertEqual(controller_display(controller.snapshot())[0],'NO ACTIVE SEQUENCE')
        controller.apply(SequencePlan.validated({'label':'Red light / green light','steps':[
            {'preset':'tease_return'},{'preset':'build_release'}]},.85))
        cue,_,status=controller_display(controller.snapshot())
        self.assertEqual(cue,'RED LIGHT');self.assertIn('02:20 remaining',status)
        controller.hold();clock.advance(controller,10)
        cue,_,status=controller_display(controller.snapshot())
        self.assertEqual(cue,'RED LIGHT — HELD');self.assertIn('02:20 remaining',status)
        controller.resume();clock.advance(controller,70)
        cue,_,status=controller_display(controller.snapshot())
        self.assertEqual(cue,'GREEN LIGHT');self.assertIn('Step 2',status)
        self.assertIn('01:10 remaining',status)
        clock.advance(controller,70)
        cue,_,status=controller_display(controller.snapshot())
        self.assertEqual(cue,'COMPLETED');self.assertIn('00:00 remaining',status)
        controller.reset()
        self.assertEqual(controller_display(controller.snapshot())[0],'NO ACTIVE SEQUENCE')

    def test_visible_readback_marks_waiting_clock(self):
        from vector1a.sequence_ui import controller_display
        cue,_,status=controller_display({'active':True,'phase':'tease',
            'sequence':{'game_phase':'red_light','step_index':0},
            'reason':'waiting for media clock','remaining_seconds':60})
        self.assertEqual(cue,'RED LIGHT — PAUSED / WAITING')
        self.assertIn('waiting for media clock',status)

    def test_85_to_100_to_85_and_tease_return(self):
        p=SequencePlan.validated({'steps':[{'preset':'build_release','out_seconds':10,'hold_seconds':10,'return_seconds':10},
                                          {'preset':'tease_return','out_seconds':10,'hold_seconds':10,'return_seconds':10}]},.85)
        for t,expected in ((0,.85),(10,1),(20,1),(30,.85),(40,.85*.65),(50,.85*.65),(60,.85)):
            with self.subTest(t=t):self.assertAlmostEqual(p.at(t)[1]*.85,expected)
        self.assertEqual(p.at(60)[0],'complete')

    def test_runtime_build_exceeds_baseline_without_exceeding_full_scale(self):
        clock=Clock();c=PassageController(clock)
        p=SequencePlan.validated({'steps':[{'preset':'build_release','out_seconds':10,'hold_seconds':10,'return_seconds':10}]},.85)
        c.apply(p)
        for _ in range(1000):
            clock.advance(c,.02)
            self.assertLessEqual(c.factors_now()[0]*.85,1+1e-9)
            self.assertEqual(c.factors_now()[1],1)
        self.assertAlmostEqual(c.factors_now()[0]*.85,1)
        clock.advance(c,15)
        self.assertEqual(c.factors_now(),(1,1))
        self.assertAlmostEqual(c.snapshot()['nominal_ceiling'],.85)
        self.assertFalse(c.snapshot()['active'])
        self.assertTrue(c.snapshot()['completed'])
        self.assertEqual(c.snapshot()['remaining_seconds'],0)

    def test_sequence_replacement_and_restore_do_not_clip_amplified_factor(self):
        clock=Clock();c=PassageController(clock)
        c.apply(SequencePlan.validated({'steps':[{'preset':'build_release','out_seconds':10,'hold_seconds':40,'return_seconds':10}]},.85))
        clock.advance(c,20);old=c.factors_now()[0];self.assertGreater(old,1)
        c.restore();self.assertEqual(c.factors_now()[0],old)
        clock.advance(c,.02);self.assertLess(abs(old-c.factors_now()[0]),.01)
        clock.advance(c,10);self.assertEqual(c.factors_now(),(1,1))

    def test_invalid_levels_and_sequence_bounds(self):
        for body,baseline in (({'steps':[{'preset':'build_release','level':1.1}]},.85),
                              ({'steps':[{'preset':'build_release','level':.7}]},.85),
                              ({'steps':[{'preset':'tease_return','level':.9}]},.85),
                              ({'steps':[{'preset':'tease_return','out_seconds':float('nan')}]},.85),
                              ({'steps':[{'preset':'build_release'}]},0),({'steps':[]},.85),
                              ({'steps':[{'preset':'build_release'}]*17},.85)):
            with self.subTest(body=body),self.assertRaises(ValueError):SequencePlan.validated(body,baseline)

    def test_game_cues_advance_and_end_with_sequence(self):
        p=SequencePlan.validated({'label':'Red light / green light','steps':[
            {'preset':'tease_return'},{'preset':'build_release'},{'preset':'build_release'},{'preset':'tease_return'}]},.85)
        self.assertEqual(p.detail_at(0)['game_phase'],'red_light')
        self.assertEqual(p.detail_at(70)['game_phase'],'green_light')
        self.assertEqual(p.detail_at(140)['game_phase'],'green_light')
        self.assertEqual(p.detail_at(210)['game_phase'],'red_light')
        self.assertEqual(p.duration,280)
        self.assertIsNone(p.detail_at(280)['game_phase'])

    def test_mode_switch_preserves_queue_and_response_configuration(self):
        e=VectorEngine(lambda sample:None,clock=lambda:10)
        e._queue=[(12,1,'queued')];e._state='Running';e.volume=.71
        before=(e.volume,e.pulse_frequency_min,e.pulse_width_max)
        e.set_motion_mode(MotionMode.RESTIM_ORIGINAL)
        self.assertEqual(e._queue,[(12,1,'queued')]);self.assertEqual(e._state,'Running')
        self.assertEqual(before,(e.volume,e.pulse_frequency_min,e.pulse_width_max))

    def test_spatial_transition_is_continuous_and_preserves_volume(self):
        c=OutputComposer(None,None,None,None,None,None)
        old=OutputSample(1,0,0,.2,.2,50,.2,.3,.85,MotionMode.CIRCULAR,.4,.5,.6,.7,.2,.3,.4)
        self.assertEqual(c._blend_motion(old),old)
        new=replace(old,mode=MotionMode.RESTIM_ORIGINAL,alpha=.9,beta=.8,due_at=1)
        first=c._blend_motion(new)
        self.assertEqual((first.alpha,first.beta),(.2,.3));self.assertEqual(first.volume,.85)
        middle=c._blend_motion(replace(new,due_at=2))
        self.assertAlmostEqual(middle.alpha,.55);self.assertAlmostEqual(middle.beta,.55)
        final=c._blend_motion(replace(new,due_at=3))
        self.assertAlmostEqual(final.alpha,.9);self.assertAlmostEqual(final.beta,.8);self.assertEqual(final.volume,.85)

    def test_sequence_preview_and_apply_use_primary_ceiling_in_api(self):
        from types import SimpleNamespace
        from test_passage_api import PassageAPITests
        fixture=PassageAPITests();fixture.setUp()
        fixture.app.four_phase_volume_ceiling=SimpleNamespace(get=lambda:.85)
        body={'steps':[{'preset':'build_release'}]}
        preview=fixture.request('sequence-preview',body)
        self.assertEqual(preview.status,200);self.assertEqual(preview.response['baseline'],.85)
        self.assertFalse(fixture.app.passage.snapshot()['active'])
        result=fixture.request('sequence',body)
        self.assertEqual(result.status,200)
        self.assertEqual(result.response['passage']['plan']['baseline'],.85)
        # Derived through the passage plan, so allow float rounding (~1e-13).
        self.assertAlmostEqual(result.response['passage']['nominal_ceiling'],.85,places=9)

    def test_motion_mode_api_leaves_queue_and_volume_settings_unchanged(self):
        from types import SimpleNamespace
        from test_passage_api import PassageAPITests
        from vector1a.director import DirectorRequest
        fixture=PassageAPITests();fixture.setUp()
        app=fixture.app;app.engine=VectorEngine(lambda sample:None)
        app.engine._queue=[(12,1,'queued')];app.mode=SimpleNamespace(set=lambda value:None)
        app.apply_config=lambda:None
        old_volume=app.engine.volume
        request=DirectorRequest('POST','/v1/motion-mode',{'mode':MotionMode.RESTIM_ORIGINAL.value})
        app.director_bridge._requests.put(request);app._drain_director_requests()
        self.assertEqual(request.status,200);self.assertEqual(app.engine._queue,[(12,1,'queued')])
        self.assertEqual(app.engine.volume,old_volume)


if __name__=='__main__':unittest.main()
