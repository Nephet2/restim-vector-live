from collections import deque

from vector1a.app import VectorApp


class _Flag:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Events:
    def __init__(self, accepted=True):
        self.accepted = accepted
        self.calls = []

    def schedule_trigger(self, event, params, activate_at):
        self.calls.append((event, params, activate_at))
        return self.accepted


def _app(enabled=True):
    app = object.__new__(VectorApp)
    app.director_events_enabled = _Flag(enabled)
    app.event_engine = _Events()
    app._director_event_history = deque(maxlen=12)
    return app


def test_director_event_requires_operator_opt_in():
    status, response = _app(False)._trigger_director_event({"event": "mcb_tease"})
    assert status == 409
    assert response["ok"] is False


def test_director_event_rejects_unknown_recipe_and_unbounded_duration():
    app = _app()
    assert app._trigger_director_event({"event": "mcb_extract"})[0] == 400
    assert app._trigger_director_event({"event": "mcb_tease", "duration_seconds": 31})[0] == 400


def test_director_event_uses_curated_params_and_records_acceptance():
    app = _app()
    status, response = app._trigger_director_event(
        {"event": "mcb_tease", "duration_seconds": 8})
    assert status == 202
    assert response["accepted"] is True
    event, params, _activate_at = app.event_engine.calls[0]
    assert event == "mcb_tease"
    assert params == {"tease_amplitude": 0.08, "duration_ms": 8000}
    assert app._director_event_history[-1]["event"] == "mcb_tease"
