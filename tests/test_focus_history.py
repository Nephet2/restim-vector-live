from vector1a.focus import FocusHistory


def test_focus_history_tracks_current_and_previous_dwell():
    h = FocusHistory("Top Full", now=10.0)
    assert h.snapshot(now=14.25) == {
        "current": "Top Full",
        "selected_for_seconds": 4.25,
        "previous": None,
        "previous_duration_seconds": 0.0,
    }
    h.select("Glans Focus", now=15.0)
    snap = h.snapshot(now=18.5)
    assert snap["current"] == "Glans Focus"
    assert snap["selected_for_seconds"] == 3.5
    assert snap["previous"] == "Top Full"
    assert snap["previous_duration_seconds"] == 5.0


def test_selecting_same_focus_does_not_reset_dwell():
    h = FocusHistory("Prostate Focus", now=20.0)
    h.select("Prostate Focus", now=30.0)
    assert h.snapshot(now=35.0)["selected_for_seconds"] == 15.0
