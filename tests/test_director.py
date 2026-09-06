import json
import threading
import time
import urllib.request

from vector1a.director import DirectorBridge, DirectorServer


def _serve_one(bridge, expected_path, response):
    deadline = time.time() + 2.0
    while time.time() < deadline:
        try:
            req = bridge.get_nowait()
        except Exception:
            time.sleep(0.01)
            continue
        assert req.path == expected_path
        req.status = 200
        req.response = response
        req.completed.set()
        return
    raise AssertionError("no director request received")


def test_director_server_state_round_trip():
    bridge = DirectorBridge()
    server = DirectorServer(bridge)
    host, port = server.start("127.0.0.1", 0)
    worker = threading.Thread(target=_serve_one, args=(bridge, "/v1/state", {"ok": True, "running": True}))
    worker.start()
    with urllib.request.urlopen(f"http://{host}:{port}/v1/state", timeout=2) as response:
        payload = json.loads(response.read())
    worker.join(timeout=2)
    server.stop()
    assert payload == {"ok": True, "running": True}


def test_director_server_post_preset_json():
    bridge = DirectorBridge()
    server = DirectorServer(bridge)
    host, port = server.start("127.0.0.1", 0)

    def responder():
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                req = bridge.get_nowait()
            except Exception:
                time.sleep(0.01)
                continue
            assert req.path == "/v1/preset"
            assert req.body == {"preset": "B"}
            req.status = 202
            req.response = {"ok": True, "preset": "B"}
            req.completed.set()
            return
        raise AssertionError("no director request received")

    worker = threading.Thread(target=responder)
    worker.start()
    request = urllib.request.Request(
        f"http://{host}:{port}/v1/preset",
        data=json.dumps({"preset": "B"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        payload = json.loads(response.read())
    worker.join(timeout=2)
    server.stop()
    assert payload == {"ok": True, "preset": "B"}


def test_director_server_rejects_non_loopback_bind():
    bridge = DirectorBridge()
    server = DirectorServer(bridge)
    try:
        server.start("0.0.0.0", 11436)
    except ValueError as exc:
        assert "loopback-only" in str(exc)
    else:
        server.stop()
        raise AssertionError("non-loopback bind unexpectedly allowed")


def _post_round_trip(path, body):
    bridge = DirectorBridge()
    server = DirectorServer(bridge)
    host, port = server.start("127.0.0.1", 0)

    def responder():
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                req = bridge.get_nowait()
            except Exception:
                time.sleep(0.01)
                continue
            assert req.path == path
            assert req.body == body
            req.status = 200
            req.response = {"ok": True, **body}
            req.completed.set()
            return
        raise AssertionError("no director request received")

    worker = threading.Thread(target=responder)
    worker.start()
    request = urllib.request.Request(
        f"http://{host}:{port}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        payload = json.loads(response.read())
    worker.join(timeout=2)
    server.stop()
    return payload


def test_director_server_post_semantic_texture():
    assert _post_round_trip("/v1/semantic/texture", {"texture": "Smooth"})["texture"] == "Smooth"


def test_director_server_post_primary_spatial():
    payload = _post_round_trip(
        "/v1/semantic/primary-spatial", {"primary_spatial": "top_depth_spread"})
    assert payload["primary_spatial"] == "top_depth_spread"


def test_director_server_post_secondary_spatial():
    payload = _post_round_trip(
        "/v1/semantic/secondary-spatial", {"secondary_spatial": "bottom_focus"})
    assert payload["secondary_spatial"] == "bottom_focus"


def test_director_server_post_semantic_variation():
    assert _post_round_trip("/v1/semantic/variation", {"variation": "Lively"})["variation"] == "Lively"


def test_director_server_post_top_focus():
    payload = _post_round_trip(
        "/v1/semantic/top-focus", {"top_focus": "Glans Focus"})
    assert payload["top_focus"] == "Glans Focus"


def test_director_server_post_bottom_focus():
    payload = _post_round_trip(
        "/v1/semantic/bottom-focus", {"bottom_focus": "Prostate Focus"})
    assert payload["bottom_focus"] == "Prostate Focus"


def test_director_server_controller_round_trip():
    bridge = DirectorBridge()
    server = DirectorServer(bridge)
    host, port = server.start("127.0.0.1", 0)
    expected = {"ok": True, "connected": True, "lb_pressed": True, "ptt_candidate": True}
    worker = threading.Thread(target=_serve_one, args=(bridge, "/v1/controller", expected))
    worker.start()
    with urllib.request.urlopen(f"http://{host}:{port}/v1/controller", timeout=2) as response:
        payload = json.loads(response.read())
    worker.join(timeout=2)
    server.stop()
    assert payload == expected


def test_director_server_post_stop():
    payload = _post_round_trip("/v1/stop", {})
    assert payload["ok"] is True


def test_director_server_post_resume():
    payload = _post_round_trip("/v1/resume", {})
    assert payload["ok"] is True


def test_director_server_post_modifier_target():
    payload = _post_round_trip("/v1/modifier/target", {"preset": "base_prostate_focused"})
    assert payload["preset"] == "base_prostate_focused"


def test_director_server_post_modifier_tempo():
    payload = _post_round_trip("/v1/modifier/tempo", {"scale": 2.0, "duration_seconds": 15})
    assert payload["scale"] == 2.0
    assert payload["duration_seconds"] == 15


def test_director_server_post_modifier_restore():
    payload = _post_round_trip("/v1/modifier/restore", {})
    assert payload["ok"] is True


def test_director_server_post_modifier_stroke_range():
    payload = _post_round_trip("/v1/modifier/stroke-range", {"action": "narrower"})
    assert payload["action"] == "narrower"


def test_director_server_post_custom_event():
    payload = _post_round_trip(
        "/v1/event/trigger", {"event": "mcb_tease", "duration_seconds": 8})
    assert payload["event"] == "mcb_tease"


def test_director_server_post_cancel_events():
    assert _post_round_trip("/v1/event/cancel", {})["ok"] is True
