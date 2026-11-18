import unittest
from dataclasses import replace, asdict
from vector1a.engine import VectorEngine, OutputSample
from vector1a.motion import MotionMode, SegmentState

def frame(t=0,span=.3,mode=MotionMode.TOP_LEFT_BOTTOM_RIGHT):
    return OutputSample(1,t,t+2,.7,.7,80,.9,.8,.85,mode,.6,.5,.4,.3,.2,.8,.65,
                        source_stroke_span=span)

class RangePreservationTests(unittest.TestCase):
    def test_default_off_is_exact_passthrough(self):
        e=VectorEngine(lambda s:None)
        s=frame()
        self.assertIs(e._range_preserved_sample(s),s)
        self.assertFalse(e.range_preservation_snapshot()['enabled'])

    def test_geometry_only_and_smooth_on_off(self):
        e=VectorEngine(lambda s:None);e.set_range_preservation(True)
        scales=[]
        for i in range(151):
            s=frame(i*.02);out=e._range_preserved_sample(s)
            before,after=asdict(s),asdict(out)
            for axis in ('alpha','beta'):before.pop(axis);after.pop(axis)
            self.assertEqual(before,after)
            scales.append(e.range_preservation_snapshot()['scale'])
        self.assertAlmostEqual(scales[-1],.3)
        self.assertLessEqual(max(abs(b-a) for a,b in zip(scales,scales[1:])),.01000001)
        e.set_range_preservation(False)
        for i in range(151,302):e._range_preserved_sample(frame(i*.02))
        self.assertAlmostEqual(e.range_preservation_snapshot()['scale'],1)
        s=frame(7);self.assertIs(e._range_preserved_sample(s),s)

    def test_mode4_is_never_scaled_and_full_strokes_unchanged(self):
        e=VectorEngine(lambda s:None);e.set_range_preservation(True)
        for i in range(100):
            s=frame(i*.02,.2,MotionMode.RESTIM_ORIGINAL)
            self.assertIs(e._range_preserved_sample(s),s)
        for i in range(100,200):
            s=frame(i*.02,1)
            self.assertIs(e._range_preserved_sample(s),s)

    def test_unknown_range_does_not_collapse(self):
        e=VectorEngine(lambda s:None);e.set_range_preservation(True)
        for i in range(100):self.assertIsInstance(e._range_preserved_sample(frame(i*.02,None)),OutputSample)
        self.assertEqual(e.range_preservation_snapshot()['scale'],1)
        self.assertIn('waiting',e.range_preservation_snapshot()['source'])

    def test_reversal_repairs_span_in_queued_sample(self):
        e=VectorEngine(lambda s:None)
        s=frame(.2,None);e._queue=[(s.due_at,1,s)]
        e._rewrite_completed_stroke(SegmentState(1,0,.4,.3,.7,80))
        self.assertAlmostEqual(e._queue[0][2].source_stroke_span,.4)
        self.assertEqual(e._queue[0][2].volume,s.volume)

    def test_sampled_udp_uses_whole_completed_stroke(self):
        e=VectorEngine(lambda s:None,clock=lambda:0);e.resume();e.set_range_preservation(True)
        # Many tiny updates span .2 -> .8; the inferred completed stroke is .6,
        # not the .02 difference of one UDP update.
        e._last_input_position=.2;e._stroke_start_position=.2
        for i in range(1,32):
            value=.2+.02*i if i<=30 else .78
            e.receive_l0(value,received_at=i*.02);e._calculate_and_queue(i*.02)
        self.assertAlmostEqual(e._queue[5][2].source_stroke_span,.6)
        e._calculate_and_queue(.64)
        self.assertAlmostEqual(e._queue[-1][2].source_stroke_span,.6)

    def test_known_bounds_and_release_path(self):
        sent=[];e=VectorEngine(sent.append,clock=lambda:3);e.resume()
        e.set_range_preservation(True)
        e.receive_l0(.7,received_at=0,stroke_bounds=(.3,.7))
        e._calculate_and_queue(.02)
        self.assertAlmostEqual(e._queue[0][2].source_stroke_span,.4)
        e._rewrite_completed_stroke(SegmentState(1,0,.1,.5,.6,80))
        self.assertAlmostEqual(e._queue[0][2].source_stroke_span,.4)
        e._release_due(3)
        self.assertEqual(len(sent),1)
        self.assertEqual(e.diagnostics().alpha,sent[0].alpha)

if __name__=='__main__':unittest.main()
