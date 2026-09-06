from vector1a.modifier import ModifierValues, interpolate, transform_segment
from vector1a.motion import SegmentState


def seg(a, b):
    return SegmentState(1, 0.0, 1.0, a, b)


def test_neutral_returns_original_object():
    original = seg(0.2, 0.8)
    assert transform_segment(original, ModifierValues()) is original


def test_stroke_range_compresses_around_neutral():
    out = transform_segment(seg(0.2, 0.8), ModifierValues(stroke_range=0.5))
    assert abs(out.start_position - 0.35) < 1e-9
    assert abs(out.end_position - 0.65) < 1e-9


def test_range_and_bias_are_clamped_to_restim_unit_interval():
    out = transform_segment(seg(0.0, 1.0), ModifierValues(stroke_range=1.5, position_bias=0.25))
    assert out.start_position == 0.0
    assert out.end_position == 1.0


def test_smoothing_is_deterministic_and_bounded():
    out = transform_segment(seg(0.25, 0.75), ModifierValues(smoothing=1.0))
    assert 0.0 <= out.start_position <= 1.0
    assert 0.0 <= out.end_position <= 1.0
    assert abs(out.start_position - 0.15625) < 1e-9
    assert abs(out.end_position - 0.84375) < 1e-9


def test_interpolation_uses_single_range_control():
    a = ModifierValues(stroke_range=1.0, position_bias=0.0, smoothing=0.0)
    b = ModifierValues(stroke_range=1.4, position_bias=-0.2, smoothing=1.0)
    mid = interpolate(a, b, 0.5)
    assert abs(mid.stroke_range - 1.2) < 1e-9
    assert abs(mid.position_bias + 0.1) < 1e-9
    assert abs(mid.smoothing - 0.5) < 1e-9


def test_alpha70_extended_targeting_bounds():
    low = ModifierValues(stroke_range=0.1, position_bias=-0.9).bounded()
    high = ModifierValues(stroke_range=9.0, position_bias=0.9).bounded()
    assert low.stroke_range == 0.3
    assert low.position_bias == -0.35
    assert high.stroke_range == 1.5
    assert high.position_bias == 0.35


def test_tight_targeting_remains_bounded():
    out = transform_segment(seg(0.0, 1.0), ModifierValues(stroke_range=0.3, position_bias=-0.35))
    assert out.start_position == 0.0
    assert abs(out.end_position - 0.30) < 1e-9
