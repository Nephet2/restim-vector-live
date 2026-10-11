from vector1a.focus import (BottomFocusTransition, apply_top_focus, top_focus_weights,
                            apply_bottom_focus, apply_bottom_focus_window, bottom_focus_window)


def test_top_focus_preserves_neutral():
    assert apply_top_focus((.5,.5,.5,.5), "Glans Focus") == (.5,.5,.5,.5)


def test_top_nominal_ceiling_leaves_headroom():
    values = apply_top_focus((1,1,1,1), "Glans Focus", nominal_ceiling=.65)
    assert values[0] < 1.0
    assert values[0] > values[1] > values[2] > values[3]
    assert round(values[0], 4) == .9225


def test_root_focus_moves_peak_to_e4():
    values = apply_top_focus((1,1,1,1), "Root Focus", nominal_ceiling=.65)
    assert values[3] == max(values)
    assert values[0] == min(values)


def test_top_sweep_peak_moves_with_path():
    assert top_focus_weights("Top Sweep", 0.0)[0] == 1.30
    assert top_focus_weights("Top Sweep", 1.0)[3] == 1.30


def test_prostate_focus_remaps_alpha_to_upper_half():
    assert apply_bottom_focus(0.0, "Prostate Focus") == .5
    assert apply_bottom_focus(.5, "Prostate Focus") == .75
    assert apply_bottom_focus(1.0, "Prostate Focus") == 1.0


def test_bottom_focus_strength_can_fade_to_original():
    assert apply_bottom_focus(.25, "Prostate Focus", strength=0.0) == .25
    assert bottom_focus_window("Anal Focus") == (.25,.75)


def test_bottom_focus_transition_preserves_continuity_then_reaches_target():
    transition = BottomFocusTransition("Bottom Full", now=10.0)
    before = apply_bottom_focus_window(0.1, transition.window(now=10.0))
    transition.select("Prostate Focus", duration=1.0, now=10.0)
    at_change = apply_bottom_focus_window(0.1, transition.window(now=10.0))
    halfway = apply_bottom_focus_window(0.1, transition.window(now=10.5))
    complete = apply_bottom_focus_window(0.1, transition.window(now=11.0))
    assert at_change == before
    assert before < halfway < complete
    assert complete == apply_bottom_focus(0.1, "Prostate Focus")


def test_bottom_focus_transition_retargets_from_current_effective_window():
    transition = BottomFocusTransition("Bottom Full", now=20.0)
    transition.select("Prostate Focus", duration=1.0, now=20.0)
    current = transition.window(now=20.4)
    transition.select("Perineum Focus", duration=1.0, now=20.4)
    assert transition.window(now=20.4) == current
    assert transition.window(now=21.4) == bottom_focus_window("Perineum Focus")


def test_top_focus_150_percent_exaggerates_peak_without_clipping_at_default_headroom():
    weights = top_focus_weights("Glans Focus", strength=1.5)
    assert round(weights[0], 3) == 1.45
    values = apply_top_focus((1,1,1,1), "Glans Focus", nominal_ceiling=.65, strength=1.5)
    assert round(values[0], 5) == .97125
    assert values[0] < 1.0


def test_top_focus_175_percent_stays_below_ceiling_at_default_headroom():
    values = apply_top_focus((1,1,1,1), "Glans Focus", nominal_ceiling=.65, strength=1.75)
    assert round(values[0], 6) == .995625
    assert values[0] < 1.0
