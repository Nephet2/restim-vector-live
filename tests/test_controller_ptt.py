from vector1a.controller import (
    controller_snapshot, LEFT_SHOULDER, DPAD_UP, DPAD_LEFT
)


def test_lb_alone_is_ptt_candidate():
    state = controller_snapshot(LEFT_SHOULDER, True)
    assert state["lb_pressed"] is True
    assert state["ptt_candidate"] is True
    assert state["lb_dpad_active"] is False


def test_lb_dpad_is_vector_gesture_not_ptt():
    state = controller_snapshot(LEFT_SHOULDER | DPAD_UP, True)
    assert state["ptt_candidate"] is False
    assert state["lb_dpad_active"] is True
    assert state["dpad"]["up"] is True


def test_release_clears_ptt_candidate():
    state = controller_snapshot(0, True)
    assert state["lb_pressed"] is False
    assert state["ptt_candidate"] is False

def test_disconnected_forces_buttons_clear():
    state = controller_snapshot(LEFT_SHOULDER | DPAD_LEFT, False)
    assert state["buttons"] == 0
    assert state["connected"] is False
