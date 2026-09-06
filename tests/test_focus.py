from vector1a.focus import apply_top_focus, top_focus_weights, apply_bottom_focus, bottom_focus_window


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
