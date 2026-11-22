import unittest, math
from dataclasses import replace
from vector1a.engine import VectorEngine
from vector1a.motion import MotionMode,SegmentState
from vector1a.timing_variation import warp,STYLES,GROUP_PATTERN,group_style
from test_range_preservation import frame

def replay(enabled,delay=2,style='Stroke groups'):
    now=[0.];sent=[]
    e=VectorEngine(sent.append,clock=lambda:now[0],lookahead_seconds=delay)
    e.mode=MotionMode.TOP_LEFT_BOTTOM_RIGHT
    e._last_input_position=0.;e._stroke_start_position=0.
    e.configure_timing_variation(enabled,style,.65);e.resume()
    for i in range(1,501):
        now[0]=i*.02
        p=(i%50)/25 if i%50<=25 else 2-(i%50)/25
        e.receive_l0(p,received_at=now[0]);e.step(now[0])
    now[0]=13.;e._release_due(now[0])
    return e,sent

class TimingTests(unittest.TestCase):
    def test_numeric_group_multiplier_expands_existing_pattern(self):
        for n in (1,2,3,4,32):
            expected=[style for style in GROUP_PATTERN for _ in range(n)]
            self.assertEqual([group_style(i,n) for i in range(1,8*n+1)],expected)
            self.assertEqual(group_style(8*n+1,n),'Linear')
        e=VectorEngine(lambda s:None)
        e.configure_timing_variation(True,'Stroke groups',.65,3)
        self.assertEqual(e.timing_variation_snapshot()['group_multiplier'],3)
        for bad in (0,33,1.5,float('inf'),float('nan')):
            with self.assertRaises(ValueError):e.configure_timing_variation(True,'Stroke groups',.65,bad)

    def test_warps_lock_endpoints_and_are_monotonic_bounded(self):
        for style in STYLES[1:]:
            self.assertEqual(warp(0,style)[0],0)
            self.assertEqual(warp(1,style)[0],1)
            values=[warp(i/1000,style) for i in range(1001)]
            self.assertTrue(all(0<=q<=1 and 0<=v<=2 for q,v in values))
            self.assertTrue(all(a[0]<=b[0] for a,b in zip(values,values[1:])))

    def test_disabled_exact_passthrough(self):
        e=VectorEngine(lambda s:None)
        s=frame();self.assertIs(e.timing_variation.apply(e,s),s)

    def test_live_queue_changes_primary_pulses_without_retiming_or_volume_change(self):
        base,bs=replay(False);active,ss=replay(True)
        self.assertEqual(len(bs),len(ss))
        changed=0
        for b,s in zip(bs,ss):
            self.assertEqual((b.sequence,b.calculated_at,b.due_at,b.raw_l0,b.output_l0,b.volume,
                              b.frequency,b.pulse_rise_time,b.alpha_prostate,b.beta_prostate,b.volume_prostate),
                             (s.sequence,s.calculated_at,s.due_at,s.raw_l0,s.output_l0,s.volume,
                              s.frequency,s.pulse_rise_time,s.alpha_prostate,s.beta_prostate,s.volume_prostate))
            if s.secondary_pulse_frequency is not None:
                self.assertEqual(s.secondary_pulse_frequency,b.pulse_frequency)
                self.assertEqual(s.secondary_pulse_width,b.pulse_width)
            self.assertTrue(active.pulse_frequency_min<=s.pulse_frequency<=active.pulse_frequency_max)
            self.assertTrue(active.pulse_width_min<=s.pulse_width<=active.pulse_width_max)
            changed+=abs(b.pulse_frequency-s.pulse_frequency)>.01
        self.assertGreater(changed,80)
        self.assertGreater(max(abs(a.pulse_width-b.pulse_width) for a,b in zip(bs,ss)),.03)
        self.assertGreater(active.timing_variation.frames,100)

    def test_insufficient_lookahead_bypasses_incomplete_strokes(self):
        base,bs=replay(False,delay=.05)
        active,ss=replay(True,delay=.05,style='Accelerate')
        self.assertEqual([(s.alpha,s.beta,s.pulse_frequency,s.pulse_width) for s in bs],
                         [(s.alpha,s.beta,s.pulse_frequency,s.pulse_width) for s in ss])
        self.assertEqual(active.timing_variation.frames,0)

    def test_switch_off_restores_exact_baseline_at_stroke_boundaries(self):
        e=VectorEngine(lambda s:None)
        e.configure_timing_variation(True,'Accelerate',.65)
        for j in range(6):
            stroke=SegmentState(j+1,j,j+1,0,1,80)
            s=replace(frame(j+.02),timing_stroke=stroke)
            e.timing_variation.apply(e,s)
        e.configure_timing_variation(False,'Accelerate',.65)
        for j in range(6,12):
            stroke=SegmentState(j+1,j,j+1,0,1,80)
            s=replace(frame(j+.02),timing_stroke=stroke)
            out=e.timing_variation.apply(e,s)
        self.assertEqual(e.timing_variation.strength,0)
        self.assertIs(out,s)
        self.assertEqual(e.timing_variation.status,'OFF')

    def test_amount_zero_and_invalid_input(self):
        e=VectorEngine(lambda s:None)
        with self.assertRaises(ValueError):e.configure_timing_variation(True,'bad',.5)
        with self.assertRaises(ValueError):e.configure_timing_variation(True,'Accelerate',float('nan'))
        e.configure_timing_variation(True,'Accelerate',0)
        s=replace(frame(.02),timing_stroke=SegmentState(1,0,1,0,1))
        self.assertIs(e.timing_variation.apply(e,s),s)

if __name__=='__main__':unittest.main()
