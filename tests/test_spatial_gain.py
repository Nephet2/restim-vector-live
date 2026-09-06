from vector1a.spatial_gain import SpatialGainController, apply_gain


def test_gain_steps_are_bounded_and_cumulative():
    g = SpatialGainController(now=0.0)
    assert g.step(+1, step=.10, minimum=.50, maximum=1.50, now=1.0) == 1.10
    assert round(g.step(+1, step=.10, minimum=.50, maximum=1.50, now=2.0), 6) == 1.20
    for i in range(10):
        g.step(+1, step=.10, minimum=.50, maximum=1.50, now=3.0+i)
    assert g.target == 1.50


def test_gain_restore_and_history():
    g = SpatialGainController(now=0.0)
    g.set_target(1.2, minimum=.5, maximum=1.5, now=5.0)
    assert g.previous_target == 1.0
    assert g.previous_duration == 5.0
    g.restore(minimum=.5, maximum=1.5, now=9.0)
    assert g.target == 1.0
    assert g.previous_target == 1.2
    assert g.previous_duration == 4.0


def test_gain_ramps_smoothly():
    g = SpatialGainController(now=0.0)
    g.set_target(1.2, minimum=.5, maximum=1.5, now=0.0)
    assert round(g.update(ramp_per_second=.20, now=.5), 3) == 1.1
    assert round(g.update(ramp_per_second=.20, now=1.0), 3) == 1.2


def test_apply_gain_clamps_final_volume():
    assert apply_gain(.7, 1.1) == .77
    assert apply_gain(.9, 1.5) == 1.0
    assert apply_gain(.4, .5) == .2
