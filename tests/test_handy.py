"""Offline playback, wire-format, cancellation and interface regression tests."""
from concurrent.futures import Future
from contextlib import contextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vector1a.handy import HandyAPI, HandyOutput, HandyHTTPError
from vector1a.handy_control import HandyControl
from vector1a.handy_script import MotionScript, curated_scripts, from_vacuglide
from vector1a.vacuglide_script import Script, Event as SpeedEvent


class InlineWorker:
    def submit(self, action):
        future = Future()
        try:
            future.set_result(action())
        except Exception as exc:
            future.set_exception(exc)
        return future

    def shutdown(self, **kwargs):
        pass


class FakeAPI:
    def __init__(self, key="", api_key=""):
        self.version = 3 if api_key else 2
        self.calls = []
        self.offset = 0
        self.fail = None

    def connect(self, cancelled):
        self.calls.append(("connect", None))

    def call(self, path, body=None):
        self.calls.append((path, body))
        if self.fail == path:
            raise ValueError("Offline test failure")

    def stop(self):
        self.calls.append(("stop", None))

    def manual(self, low, high, velocity, cancelled, starting=False):
        self.calls.append(("native manual", (low, high, velocity, starting)))

    def check_manual(self, expected=True):
        self.calls.append(("manual state", expected))


@contextmanager
def output_fixture(v3=True):
    with patch("vector1a.handy.ThreadPoolExecutor", return_value=InlineWorker()):
        output = HandyOutput(FakeAPI)
    output.connect("test-device", "test-api" if v3 else "")
    output.poll()
    yield output
    output.close()


class ScriptTests(unittest.TestCase):
    def test_original_patterns_and_interpolation(self):
        scripts = curated_scripts()
        self.assertEqual(len(scripts), 5)
        script = scripts["Slow full strokes"]
        self.assertEqual(script.duration, 120)
        self.assertAlmostEqual(script.sample(1), .5)
        self.assertAlmostEqual(script.sample(2), 1)

    def test_invalid_and_inverted_funscripts(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "test.funscript"
            path.write_text(json.dumps({"inverted": True, "actions": [{"at": 0, "pos": 0}, {"at": 1000, "pos": 100}]}))
            script = MotionScript.load(path)
            self.assertEqual(script.sample(0), 1)
            self.assertEqual(script.sample(1), 0)
            path.write_text(json.dumps({"actions": [{"at": 1000, "pos": 0}, {"at": 0, "pos": 100}]}))
            with self.assertRaises(ValueError):
                MotionScript.load(path)
            path.write_text(json.dumps({"actions": [{"at": 0, "pos": 0}, {"at": 1000, "pos": float("nan")}]}))
            with self.assertRaises(ValueError):
                MotionScript.load(path)

    def test_speed_conversion_holds_and_ignores_valves(self):
        script = Script("Speed test", 2000, (SpeedEvent(0, "speed", 25), SpeedEvent(1000, "speed", 0),
                                                 SpeedEvent(0, "minus", duration_ms=500)))
        converted = from_vacuglide(script)
        self.assertAlmostEqual(converted.sample(.5), .5)
        self.assertAlmostEqual(converted.sample(1), 1)
        self.assertAlmostEqual(converted.sample(1.8), 1)
        self.assertIn("ignored", converted.note)


class ControlTests(unittest.TestCase):
    def test_precise_follow_poll_jitter_cannot_reverse_or_jump_target_clock(self):
        with output_fixture() as output:
            now = [10.]
            frame = {"playing": True, "position": 2., "source": "jitter MPC", "received_at": 10.,
                     "sample": lambda seconds: seconds / 100, "rate": 1., "precise": True}
            control = HandyControl(output, lambda: frame, clock=lambda: now[0])
            control.select("follow")
            control.start(preview=True)
            control.tick()
            previous = control.position
            jitter = (.08, -.4, .35, -.3, .4, -.1)
            for i in range(1, 121):
                now[0] = 10 + i * .1
                frame.update(position=2 + i * .1 + jitter[i % len(jitter)], received_at=now[0])
                control.tick()
                step = control.position - previous
                self.assertGreaterEqual(step, .095 - 1e-9)
                self.assertLessEqual(step, .105 + 1e-9)
                previous = control.position
            self.assertGreater(control.position, 13.9)
            stamps = [t for t, _ in control.history]
            self.assertTrue(all(b > a for a, b in zip(stamps, stamps[1:])))
            values = [value for _, value in control.history]
            self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))

    def test_follow_seek_clears_old_trace_and_does_not_slew_through_seek(self):
        with output_fixture() as output:
            now = [10.]
            frame = {"playing": True, "position": 2., "source": "video", "received_at": 10.,
                     "sample": lambda seconds: seconds / 100, "rate": 1., "precise": True}
            control = HandyControl(output, lambda: frame, clock=lambda: now[0])
            control.select("follow")
            control.start(preview=True)
            control.tick()
            now[0] += .1
            frame.update(position=20., received_at=now[0])
            control.tick()
            self.assertEqual(control.position, 20.)
            self.assertEqual(list(control.history), [(now[0], .2)])

    def test_mode_changes_resume_after_stop_and_operator_pause_cancels_handoff(self):
        with output_fixture() as output:
            control = HandyControl(output, lambda: None, clock=lambda: 10.)
            control.start()
            control.tick()
            control.select("manual")
            self.assertTrue(control._resume_pending)
            self.assertFalse(output.active)
            stop_ack = Future()
            output.pending = ("stop", stop_ack)
            before = len(output.api.calls)
            control.tick()
            self.assertEqual(len(output.api.calls), before)
            self.assertTrue(control._resume_pending)
            stop_ack.set_result(None)
            control.tick()
            self.assertTrue(control.playing)
            self.assertEqual(output.api.calls[-1][0], "native manual")
            control.select("script")
            control.pause()
            control.tick()
            self.assertFalse(control.running)
            self.assertFalse(output.active)

    def test_native_manual_on_api3_has_no_timed_refills(self):
        with output_fixture() as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(speed=8, low=20, high=50)
            control.start()
            for _ in range(60):
                control.tick()
                now[0] += .1
            self.assertFalse(any(path.startswith("hsp/") for path, _ in output.api.calls))
            self.assertEqual(len([1 for path, _ in output.api.calls if path == "native manual"]), 1)
            self.assertEqual(len(control.history), 0)

    def test_gradient_preserves_range_and_softens_turns(self):
        script = MotionScript("smooth", ((0., 0.), (1., 1.), (2., 0.)))
        for i in range(201):
            self.assertTrue(0 <= script.sample(i / 100, gradient=True) <= 1)
        epsilon = .001
        self.assertLess((1 - script.sample(1 - epsilon, gradient=True)) / epsilon, .01)
        self.assertLess((1 - script.sample(1 + epsilon, gradient=True)) / epsilon, .01)

    def test_inversion_offset_and_continuous_tempo_apply_before_range(self):
        with output_fixture() as output:
            control = HandyControl(output, lambda: None, clock=lambda: 10.)
            control.load(MotionScript("line", ((0., 0.), (10., 1.))))
            control.configure(low=20, high=60, tempo=.73, gradient=False, invert=True, offset=2)
            self.assertAlmostEqual(control.sample(), .52)
            self.assertAlmostEqual(control.sample(1), .2 + .4 * (1 - .273))
            control.configure(offset=-2)
            control.loop = False
            self.assertAlmostEqual(control.sample(), .6)
            for invalid in (float("nan"), 11):
                with self.assertRaises(ValueError):
                    control.configure(offset=invalid)

    def test_whole_second_player_clock_does_not_warp_stroke_timing(self):
        with output_fixture() as output:
            now = [10.]
            frame = {"playing": True, "position": 0., "source": "coarse MPC", "received_at": 10.,
                     "sample": lambda seconds: seconds / 10, "rate": 1., "precise": False}
            control = HandyControl(output, lambda: frame, clock=lambda: now[0])
            control.select("follow")
            control.start(preview=True)
            control.tick()
            for i in range(1, 151):
                now[0] = 10 + i * .02
                # A whole-second snapshot arrives every 300 ms.
                poll_time = (i // 15) * .3
                frame.update(position=int(poll_time) + i * .02 - poll_time, received_at=now[0])
                control.tick()
                self.assertAlmostEqual(control.position, i * .02)

    def test_direct_player_exposes_authored_positions_and_stops_when_paused(self):
        from vector1a.direct_player import DirectPlayerInput, PlayerFrame, MPC
        from vector1a.media_clock import MediaSnapshot
        from vector1a.timeline import FunscriptTimeline
        with TemporaryDirectory() as folder:
            path = Path(folder) / "movie.funscript"
            path.write_text(json.dumps({"actions": [{"at": 0, "pos": 0}, {"at": 10000, "pos": 100}]}))
            timeline = FunscriptTimeline()
            timeline.load(str(path))
            direct = DirectPlayerInput(MPC, "localhost", 13579)
            snapshot = MediaSnapshot(MPC, True, "playing", position_seconds=2., rate=1., media_path="movie.mp4")
            direct.frame = PlayerFrame(snapshot, 10., timeline, path.name, 1)
            frame = direct.handy_transport(10.2, "Linear")
            self.assertAlmostEqual(frame["position"], 2.2)
            self.assertAlmostEqual(frame["sample"](5), .5)
            self.assertEqual(frame["sample_gradient"](-2), 0.)
            self.assertEqual(frame["sample_gradient"](12), 1.)
            self.assertIsNone(direct.handy_transport(12, "Linear"))
            from dataclasses import replace
            direct.frame = replace(direct.frame, snapshot=replace(snapshot, state="paused"))
            self.assertIsNone(direct.handy_transport(10.2, "Linear"))

    def test_range_tempo_pause_seek_and_preview_without_connect(self):
        with output_fixture() as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.configure(low=20, high=60, tempo=.5)
            control.start(preview=True)
            now[0] += 2
            control.tick()
            self.assertAlmostEqual(control.position, 1)
            self.assertAlmostEqual(control.target, .4)
            self.assertFalse(output.active)
            control.pause()
            now[0] += 10
            control.tick()
            self.assertAlmostEqual(control.position, 1)
            control.seek(12)
            self.assertEqual(control.position, 12)
            with self.assertRaises(ValueError):
                control.configure(low=90, high=20)

    def test_manual_live_tempo_has_continuous_phase(self):
        with output_fixture() as output:
            now = [0.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.start(preview=True)
            now[0] = .7
            control.tick()
            before = control.sample()
            control.configure(tempo=2)
            self.assertAlmostEqual(control.sample(), before)
            control.configure(low=45, high=45)
            self.assertEqual(control.sample(1), .45)

    def test_source_pause_seek_and_freshness(self):
        with output_fixture() as output:
            now = [10.]
            frame = {"playing": True, "position": 2., "source": "video A", "received_at": 10.,
                     "sample": lambda seconds: .5, "rate": 1.}
            control = HandyControl(output, lambda: frame, clock=lambda: now[0])
            control.select("follow")
            control.start()
            control.tick()
            self.assertEqual(control.position, 2)
            output.poll()
            now[0] += .5
            frame.update(position=2.5, received_at=now[0])
            control.tick()
            self.assertEqual(control.position, 2.5)
            output.poll()
            frame.update(playing=False)
            control.tick()
            self.assertFalse(output.active)
            self.assertTrue(control.playing)  # waiting, not an operator pause
            output.poll()
            frame.update(playing=True, position=20.)
            control.tick()
            self.assertEqual(control.position, 20)
            self.assertTrue(output.active)
            output.poll()
            now[0] += 2
            control.tick()
            self.assertFalse(output.active)
            control.pause()
            frame.update(received_at=now[0])
            control.tick()
            self.assertFalse(output.active)  # operator pause never auto-resumes

    def test_non_loop_completion_stops(self):
        with output_fixture() as output:
            now = [0.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.loop = False
            control.start()
            now[0] = 121
            control.tick()
            self.assertFalse(control.playing)
            self.assertEqual(control.detail, "Finished")


class TransportTests(unittest.TestCase):
    def test_warm_timed_restart_uses_one_play_without_setup_or_prefill(self):
        from math import cos, pi
        with output_fixture() as output:
            output.api.rtt_ms = 900
            output.api.hsp_state = {"max_points": 2000}
            output.api.device_mode = 4
            output.stream_prepared = True
            output.stop()
            output.poll()
            output.start()
            self.assertTrue(output.warm_restart)
            before = len(output.api.calls)
            output.stream(lambda dt: (1 - cos(6 * pi * dt)) / 2, 100., revision="fresh after pause",
                          breakpoints=lambda a, b: [i / 6 for i in range(1, 23) if a < i / 6 < b])
            requests = output.api.calls[before:]
            self.assertEqual(len(requests), 1)
            path, body = requests[0]
            self.assertEqual(path, "hsp/play")
            self.assertEqual(body["start_time"], 0)
            self.assertTrue(body["add"]["flush"])
            self.assertGreater(body["add"]["points"][-1]["t"], 2300)

    def test_hamp_mode_invalidates_prepared_timed_restart(self):
        with output_fixture() as output:
            output.api.device_mode = 0
            output.stream_prepared = True
            output.start()
            self.assertFalse(output.warm_restart)
            output.stream(lambda dt: .5, 10.)
            paths = [path for path, _ in output.api.calls]
            self.assertIn("mode", paths)
            self.assertIn("hsp/setup", paths)
            self.assertNotIn("hsp/play", paths)

    def test_cancel_during_bulk_prefill_never_sends_late_play(self):
        with output_fixture() as output:
            output.api.rtt_ms = 900
            output.api.hsp_state = {"max_points": 2000}
            original = output.api.call
            def call(path, body=None):
                original(path, body)
                if path == "hsp/add":
                    output.cancelled.set()
            output.api.call = call
            control = HandyControl(output, lambda: None, clock=lambda: 10.)
            control.select("manual")
            control.configure(manual_native=False, cycles=3)
            control.start()
            control.tick()
            control.tick()
            self.assertTrue(any(path == "hsp/add" for path, _ in output.api.calls))
            self.assertFalse(any(path == "hsp/play" for path, _ in output.api.calls))

    def test_fast_gradient_prefills_real_capacity_before_playing_with_900ms_requests(self):
        now = [10.]
        class BufferedAPI(FakeAPI):
            def __init__(api):
                super().__init__(api_key="app")
                api.rtt_ms = 900
                api.hsp_state = {"max_points": 2000}
                api.points = []
                api.epoch = None
                api.prefilled = 0
                api.max_prefilled = 0
            def call(api, path, body=None):
                api.calls.append((path, body))
                now[0] += .9
                if path == "hsp/add":
                    if body["flush"]:
                        api.points = []
                    api.points.extend(body["points"])
                if path == "hsp/play":
                    if "add" in body:
                        api.points = list(body["add"]["points"])
                    api.prefilled = len(api.points)
                    api.max_prefilled = max(api.max_prefilled, api.prefilled)
                    api.epoch = body["server_time"] / 1000 - 1000 - body["start_time"] / 1000
                if api.epoch is not None and path in ("hsp/play", "hsp/add"):
                    current = (now[0] - api.epoch) * 1000
                    self.assertGreater(api.points[-1]["t"], current, "device ran out of timed motion")
        with output_fixture() as output, patch("vector1a.handy.monotonic", side_effect=lambda: now[0]), \
                patch("vector1a.handy.time", side_effect=lambda: now[0] + 1000):
            output.api = BufferedAPI()
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(manual_native=False, cycles=3, gradient=True)
            control.start()
            for i in range(80):
                if i == 20:
                    control.configure(low=20, high=80)
                elif i == 40:
                    control.configure(low=30, high=60)
                control.tick()
                now[0] += .1
            self.assertGreater(output.api.max_prefilled, 90)
            self.assertTrue(control.playing, control.detail)
            plays = [body for path, body in output.api.calls if path == "hsp/play"]
            self.assertEqual(len(plays), 3)
            self.assertTrue(all("add" in body and body["add"]["flush"] for body in plays[1:]))

    def test_gradient_live_range_edit_is_one_atomic_request_without_prefill(self):
        from math import cos, pi
        with output_fixture() as output:
            output.api.rtt_ms = 900
            output.api.hsp_state = {"max_points": 2000}
            output.start()
            output.stream_started = output.stream_prepared = True
            output.stream_revision = "old range"
            output.stream_end = 14.
            before = len(output.api.calls)
            output.stream(lambda dt: (1 - cos(6 * pi * dt)) / 2, 10., revision="new range",
                          breakpoints=lambda a, b: [i / 6 for i in range(1, 23) if a < i / 6 < b])
            requests = output.api.calls[before:]
            self.assertEqual(len(requests), 1)
            path, body = requests[0]
            self.assertEqual(path, "hsp/play")
            self.assertTrue(body["add"]["flush"])
            self.assertLessEqual(len(body["add"]["points"]), 90)
            self.assertGreater(body["add"]["points"][-1]["t"], 2300)
            self.assertLessEqual(output.edit_tolerance, .02)

    def test_device_global_range_is_read_without_widening_it(self):
        api = HandyAPI("device", "app")
        api.call = unittest.mock.Mock(return_value={"min": 0, "max": .56})
        limits = api.read_stroke()
        self.assertAlmostEqual(limits["max"], 56)
        api.call.assert_called_once_with("slider/stroke", method="GET")
        api.call.reset_mock()
        api.call.return_value = {"min": 0, "max": 1}
        api.reset_stroke()
        self.assertEqual(api.call.call_args_list[0].args, ("slider/stroke", {"min": 0, "max": 1}))
        self.assertEqual(api.global_stroke, {"min": 0, "max": 100})

    def test_device_range_cannot_change_during_motion(self):
        with output_fixture() as output:
            output.start()
            before = list(output.api.calls)
            with self.assertRaisesRegex(ValueError, "Pause Handy"):
                output.device_range(reset=True)
            self.assertEqual(before, output.api.calls)

    def test_turn_inside_former_refill_gap_is_transmitted_exactly(self):
        with output_fixture() as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.load(MotionScript("edge", ((0., 0.), (1.5, 0.), (1.51, 1.), (1.515, 0.), (4., 0.))))
            control.configure(gradient=False)
            control.start()
            control.tick()
            control.tick()
            previous = output.api.calls[-1][1]["add"]["points"][-1]
            self.assertEqual(previous["t"], 1500)
            self.assertAlmostEqual(output.stream_end, 11.5)
            now[0] = 10.5
            control.tick()
            path, body = output.api.calls[-1]
            self.assertEqual(path, "hsp/add")
            self.assertEqual(body["points"][0], {"t": 1510, "x": 100})
            self.assertIn({"t": 1515, "x": 0}, body["points"])

    def test_linear_stream_uses_events_and_gradient_adapts_with_bounded_error(self):
        from vector1a.handy import trajectory_points
        from bisect import bisect_right
        linear = trajectory_points(lambda t: t / 3, 0, 3, (1, 2))
        self.assertEqual([t for t, x in linear], [0, 1, 2, 3])
        curve = MotionScript("curve", ((0., 0.), (1., 1.), (2., 0.)))
        points = trajectory_points(lambda t: curve.sample(t, gradient=True), 0, 2, (1,))
        times = [t for t, _ in points]
        self.assertLess(len(points), 50)
        for i in range(1, 2000):
            t = i / 1000
            j = min(len(points) - 2, bisect_right(times, t) - 1)
            a, x = points[j]
            b, y = points[j + 1]
            actual = x + (y - x) * (t - a) / (b - a)
            self.assertAlmostEqual(actual, curve.sample(t, gradient=True), delta=.0051)

    def test_client_token_negotiates_bearer_only_on_readonly_connection_probe(self):
        from io import BytesIO
        from urllib.error import HTTPError
        api = HandyAPI("device-test", "client-token-test")
        requests = []
        def open_request(request, timeout=6):
            path = request.full_url.rsplit("/v3/", 1)[1]
            headers = {name.lower(): value for name, value in request.header_items()}
            requests.append((request.get_method(), path, headers))
            if path == "connected" and "x-api-key" in headers:
                raise HTTPError("unused", 401, "Unauthorized", {}, BytesIO(b'{"message":"Unauthenticated"}'))
            self.assertEqual(headers.get("authorization"), "Bearer client-token-test")
            self.assertNotIn("x-api-key", headers)
            data = {"connected": {"result": {"connected": True}},
                    "info": {"result": {"fw_version": "4.3.0", "fw_status": 0}},
                    "servertime": {"server_time": 1000000},
                    "mode": {"result": {"mode": 0}},
                    "slider/stroke": {"result": {"min": 0, "max": .56}},
                    "hamp/stop": {"result": {"play_state": 0}}}[path]
            return BytesIO(json.dumps(data).encode())
        with patch.object(api, "_open", side_effect=open_request):
            api.connect(Event())
        self.assertEqual(api.auth_scheme, "bearer")
        self.assertEqual([path for method, path, _ in requests].count("connected"), 2)
        self.assertNotIn("client-token-test", " ".join(api.trace))
        self.assertFalse(any("start" in path or "play" in path for _, path, _ in requests))

    def test_explicit_bearer_prefix_uses_authorization_header(self):
        api = HandyAPI("device-test", "  Bearer client-token-test  ")
        self.assertEqual(api.headers.get("Authorization"), "Bearer client-token-test")
        self.assertNotIn("X-Api-Key", api.headers)
        self.assertEqual(api.auth_scheme, "bearer")

    def test_malformed_credentials_are_rejected_without_echoing_values(self):
        for token in ("private-token\nnext-line", "private-token with-space", "Bearer private-token\rnext-line"):
            with self.subTest(kind="malformed token"):
                with self.assertRaises(ValueError) as raised:
                    HandyAPI("device-test", token)
                self.assertNotIn("private-token", str(raised.exception))

    def test_rejected_credentials_fail_before_device_control_and_explain_types(self):
        api = HandyAPI("device-test", "invalid-token-test")
        api.call = unittest.mock.Mock(side_effect=HandyHTTPError(401, "connected", "Unauthenticated"))
        with self.assertRaisesRegex(ValueError, "account sign-in token") as raised:
            api.connect(Event())
        self.assertEqual(api.call.call_count, 2)
        self.assertTrue(all(call.args == ("connected",) for call in api.call.call_args_list))
        self.assertNotIn("invalid-token-test", str(raised.exception))
        self.assertNotIn("invalid-token-test", " ".join(api.trace))

    def test_auth_failure_never_replays_motion_or_downgrades_to_v2(self):
        from io import BytesIO
        from urllib.error import HTTPError
        api = HandyAPI("device-test", "client-token-test")
        exc = HTTPError("unused", 401, "Unauthorized", {},
                        BytesIO(b'{"message":"expired client-token-test"}'))
        with patch.object(api, "_open", side_effect=exc) as open_request:
            with self.assertRaises(HandyHTTPError) as raised:
                api.call("hsp/play", {"start_time": 0})
        self.assertEqual(open_request.call_count, 1)
        self.assertEqual(api.version, 3)
        self.assertNotIn("client-token-test", str(raised.exception))

    def test_cancelled_connect_does_not_probe_alternate_authentication(self):
        api = HandyAPI("device-test", "client-token-test")
        cancelled = Event()
        cancelled.set()
        api.call = unittest.mock.Mock(side_effect=HandyHTTPError(401, "connected"))
        with self.assertRaises(HandyHTTPError):
            api.connect(cancelled)
        self.assertEqual(api.call.call_count, 1)

    def test_firmware4_legacy_follow_is_blocked_before_any_motion(self):
        with output_fixture(False) as output:
            output.api.info = {"firmware": "4.3.0+dcee7e58"}
            control = HandyControl(output, lambda: None)
            control.select("follow")
            with self.assertRaisesRegex(ValueError, "Application Key"):
                control.start()
            self.assertFalse(output.active)
            self.assertFalse(control.playing)
            self.assertEqual(output.api.calls, [("connect", None)])

    def test_manual_buffered_mode_uses_timed_points_not_native_speed(self):
        with output_fixture() as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(cycles=.5, low=20, high=60, manual_native=False)
            control.start()
            control.tick()  # prepare
            output.poll()
            control.tick()  # timed plan
            play = output.api.calls[-1]
            self.assertEqual(play[0], "hsp/play")
            self.assertFalse(any(path == "native manual" for path, _ in output.api.calls))
            points = play[1]["add"]["points"]
            for point in points:
                expected = control.sample(point["t"] / 1000) * 100
                self.assertAlmostEqual(point["x"], expected, delta=.51)

    def test_native_speed_is_not_scaled_by_range_and_no_fake_history(self):
        with output_fixture(False) as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(speed=10, low=40, high=60)
            control.start()
            control.tick()
            self.assertAlmostEqual(output.api.calls[-1][1][2], .1)
            self.assertEqual(len(control.history), 0)

    def test_hsp_handles_measured_900ms_rtt_without_overwriting_unplayed_points(self):
        now = [10.]
        class SlowAPI(FakeAPI):
            def __init__(self):
                super().__init__(api_key="test")
                self.rtt_ms = 900
                self.points = []
                self.epoch = None
                self.plays = 0
                self.setups = 0
            def call(api, path, body=None):
                api.calls.append((path, body))
                now[0] += .9
                if path == "hsp/setup":
                    api.setups += 1
                    api.points = []
                if path == "hsp/play":
                    api.plays += 1
                    api.epoch = body["server_time"] / 1000 - 1000
                    api.points = list(body["add"]["points"])
                elif path == "hsp/add":
                    api.points = (api.points + body["points"])[-100:]
                if path in ("hsp/add", "hsp/play"):
                    current = (now[0] - api.epoch) * 1000
                    self.assertLessEqual(api.points[0]["t"], current)
                    self.assertGreater(api.points[-1]["t"], current)
        with output_fixture() as output, patch("vector1a.handy.monotonic", side_effect=lambda: now[0]), \
                patch("vector1a.handy.time", side_effect=lambda: 1000 + now[0]):
            output.api = SlowAPI()
            output.start()
            output.stream(lambda dt: .5, now[0], revision=1)
            self.assertFalse(output.stream_started)
            output.poll()
            for i in range(100):
                output.stream(lambda dt: .5, now[0], revision=1 if i < 50 else 2)
                output.poll()
                self.assertTrue(output.active, output.error)
                self.assertLessEqual(len(output.point_stamps), 100)
                now[0] += .1
            self.assertEqual(output.api.setups, 1)
            self.assertEqual(output.api.plays, 2)  # single flushed replan for the edit

    def test_speed_only_adjustment_is_one_request_and_unchanged_values_send_none(self):
        api = HandyAPI("private-device")
        api.manual_interval = 0
        api.slide = {"min": 0, "max": 100}
        calls = []
        def call(path, body=None, method="PUT"):
            calls.append((path, body))
            return {"result": 0, "mode": 0}
        api.call = call
        api.manual(20, 70, .2, Event(), starting=True)
        calls.clear()
        api.manual(20, 70, .4, Event())
        self.assertEqual(calls, [("hamp/velocity", {"velocity": 40})])
        calls.clear()
        api.manual(20, 70, .4001, Event())
        self.assertEqual(calls, [])
        api.manual(25, 70, .4, Event())
        self.assertEqual(calls, [("slide", {"min": 25, "max": 70})])

    def test_reuses_https_connection_for_consecutive_requests(self):
        from io import BytesIO
        from unittest.mock import Mock
        api = HandyAPI("private-device")
        api._proxy = False
        connection = Mock()
        def response():
            result = BytesIO(b'{"result":0,"state":2}')
            result.status = 200
            return result
        connection.getresponse.side_effect = response
        with patch("vector1a.handy.HTTPSConnection", return_value=connection) as factory:
            api.check_manual()
            api.check_manual()
            factory.assert_called_once_with("www.handyfeeling.com", timeout=6)
            self.assertEqual(connection.request.call_count, 2)
            self.assertIsInstance(api.rtt_ms, int)
            api.close()
            connection.close.assert_called_once()

    def test_uncertain_motion_request_is_not_replayed(self):
        from http.client import RemoteDisconnected
        from unittest.mock import Mock
        api = HandyAPI("private-device")
        api._proxy = False
        connection = Mock()
        connection.getresponse.side_effect = RemoteDisconnected("closed")
        with patch("vector1a.handy.HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                api.call("hamp/velocity", {"velocity": 20})
        self.assertEqual(connection.request.call_count, 1)
        self.assertIsNone(api._connection)

    def test_control_edits_commit_before_any_new_device_command(self):
        with output_fixture(False) as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.start()
            control.tick()
            output.poll()
            count = len(output.api.calls)
            now[0] += .1
            control.configure(tempo=.5)
            control.configure(tempo=2)
            self.assertEqual(len(output.api.calls), count)
            control.tick()
            self.assertEqual(len(output.api.calls), count + 1)
            self.assertEqual(output.api.calls[-1][0], "native manual")
            self.assertAlmostEqual(output.api.calls[-1][1][2], .1, places=4)  # default 5% native speed, doubled

    def test_pending_adjustments_coalesce_without_half_second_job_wait(self):
        class DeferredWorker(InlineWorker):
            def __init__(self):
                self.jobs = []
            def submit(self, action):
                future = Future()
                self.jobs.append((future, action))
                return future
            def run_one(self):
                future, action = self.jobs.pop(0)
                future.set_result(action())
        with output_fixture(False) as output:
            worker = DeferredWorker()
            output.worker = worker
            output.start()
            output.manual(20, 60, 1, 1, 10.)
            output.manual(25, 60, 1, 1, 10.02)
            output.manual(30, 60, 1, 2, 10.03)
            self.assertEqual(len(worker.jobs), 1)
            worker.run_one()
            output.poll()
            output.manual(30, 60, 1, 2, 10.1)
            self.assertEqual(len(worker.jobs), 1)
            worker.run_one()
            output.poll()
            sent = [body for path, body in output.api.calls if path == "native manual"]
            self.assertEqual(len(sent), 2)
            self.assertEqual(sent[-1][:2], (30, 60))
            output.worker = InlineWorker()

    def test_native_stop_uses_cached_mode_without_status_roundtrip(self):
        api = HandyAPI("private-device")
        api.device_mode = 0
        api.call = unittest.mock.Mock(return_value={"result": 0})
        api.stop()
        api.call.assert_called_once_with("hamp/stop")

    def test_native_manual_dispatch_does_not_send_position_commands(self):
        with output_fixture(False) as output:
            now = [10.]
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(low=41, high=69, cycles=1)
            control.start()
            control.tick()
            self.assertEqual(output.api.calls[-1][0], "native manual")
            self.assertTrue(output.api.calls[-1][1][-1])
            initial_velocity = output.api.calls[-1][1][2]
            output.poll()
            now[0] += 1
            control.configure(tempo=2)
            now[0] += .6
            control.tick()
            self.assertAlmostEqual(output.api.calls[-1][1][2], initial_velocity * 2, places=3)
            self.assertFalse(any(path.startswith("hdsp") for path, _ in output.api.calls))
            control.pause()
            self.assertEqual(output.api.calls[-1][0], "stop")

    def test_native_hamp_units_range_before_start_and_restore(self):
        for version in (2, 3):
            with self.subTest(version=version):
                api = HandyAPI("private-device", "private-app" if version == 3 else "")
                api.slide = {"min": 10., "max": 90.}
                calls = []
                def call(path, body=None, method="PUT"):
                    calls.append((path, body))
                    return {"result": 0, "mode": 2} if path == "mode" and method == "GET" else {"result": 0}
                api.call = call
                api.manual(25, 75, .2, Event(), starting=True)
                if version == 2:
                    self.assertEqual(calls, [("mode", None), ("mode", {"mode": 0}), ("slide", {"min": 30, "max": 70}),
                        ("hamp/start", None), ("hamp/velocity", {"velocity": 20.})])
                    api.stop()
                    self.assertEqual(calls[-1], ("slide", {"min": 10., "max": 90.}))
                else:
                    self.assertEqual(calls, [("mode", None), ("mode", {"mode": 0}),
                        ("hamp/state", {"velocity": .2, "stroke": {"min": .25, "max": .75}}),
                        ("hamp/start", None)])
                    calls.clear()
                    api.manual(25, 75, .3, Event())
                    self.assertEqual(calls, [("hamp/state", {"velocity": .3})])

    def test_manual_cancel_and_collapsed_range_never_start(self):
        api = HandyAPI("private-device")
        api.slide = {"min": 0, "max": 100}
        api.call = unittest.mock.Mock(return_value={"result": 0})
        cancelled = Event()
        cancelled.set()
        api.manual(20, 60, .2, cancelled, starting=True)
        api.call.assert_not_called()
        api.manual(40, 40, .2, Event(), starting=True)
        self.assertNotIn("hamp/start", [call.args[0] for call in api.call.call_args_list])

    def test_v2_rounded_range_rejected_before_start(self):
        api = HandyAPI("private-device")
        api.slide = {"min": 0, "max": 100}
        api.call = unittest.mock.Mock(side_effect=lambda path, body=None, method="PUT": {"result": 1 if path == "slide" else 0})
        with self.assertRaisesRegex(ValueError, "adjusted"):
            api.manual(49, 50, .2, Event(), starting=True)
        self.assertNotIn("hamp/start", [call.args[0] for call in api.call.call_args_list])

    def test_v2_response_preserves_state_and_diagnostics_redact_keys(self):
        from io import BytesIO
        api = HandyAPI("private-device", "")
        self.assertEqual(api.base, "https://www.handyfeeling.com/api/handy/v2")
        with patch.object(api, "_open", return_value=BytesIO(b'{"result":0,"state":2}')):
            api.check_manual()
        self.assertNotIn("private-device", " ".join(api.trace))
        with patch.object(api, "_open", return_value=BytesIO(b'{"result":0,"state":1}')):
            with self.assertRaisesRegex(ValueError, "stopped"):
                api.check_manual()

    def test_firmware4_trace_range_is_encoded_as_inward_integers(self):
        api = HandyAPI("private-device")
        api.slide = {"min": 0, "max": 56}
        calls = []
        def call(path, body=None, method="PUT"):
            calls.append((method, path, body))
            return {"result": 0, "mode": 0}
        api.call = call
        api.manual(37.93, 51.15, .1234, Event(), starting=True)
        self.assertIn(("PUT", "slide", {"min": 22, "max": 28}), calls)
        self.assertIn(("PUT", "hamp/velocity", {"velocity": 12}), calls)
        self.assertNotIn(("PUT", "mode", {"mode": 0}), calls)
        self.assertLess(calls.index(("PUT", "slide", {"min": 22, "max": 28})),
                        calls.index(("PUT", "hamp/start", None)))

    def test_stop_does_not_reselect_existing_hamp_mode(self):
        api = HandyAPI("private-device")
        calls = []
        def call(path, body=None, method="PUT"):
            calls.append((method, path, body))
            return {"result": 0, "mode": 0}
        api.call = call
        api.stop()
        self.assertEqual(calls, [("GET", "mode", None), ("PUT", "hamp/stop", None)])

    def test_http_validation_explanation_is_preserved_without_keys(self):
        from io import BytesIO
        from urllib.error import HTTPError
        api = HandyAPI("private-device")
        exc = HTTPError("unused", 400, "Bad request", {},
                        BytesIO(b'{"error":{"message":"min must be integer, key=private-device"}}'))
        with patch.object(api, "_open", side_effect=exc):
            with self.assertRaisesRegex(ValueError, "min must be integer") as raised:
                api.call("slide", {"min": 21.2, "max": 28.6})
        self.assertNotIn("private-device", str(raised.exception))
        self.assertNotIn("private-device", " ".join(api.trace))

    def test_legacy_position_stream_serializes_integral_percentage(self):
        with output_fixture(False) as output:
            output.start()
            output.stream(lambda dt: .523456, 10)
            body = output.api.calls[-1][1]
            self.assertEqual(body["position"], 52)
            self.assertIs(type(body["position"]), int)

    def test_v2_wire_format_and_no_motion_backlog(self):
        with output_fixture(False) as output:
            output.start()
            output.stream(lambda dt: .75, 10)
            self.assertEqual(output.api.calls[-1], ("hdsp/xpt", {"position": 75., "duration": 340,
                                      "stopOnTarget": True, "immediateResponse": False}))
            count = len(output.api.calls)
            output.stream(lambda dt: .5, 10.1)
            self.assertEqual(len(output.api.calls), count)

    def test_hsp_finite_buffer_point_spacing_and_starvation(self):
        with output_fixture() as output:
            output.start()
            output.stream(lambda dt: .4, 10)
            output.poll()
            output.stream(lambda dt: .4, 10)
            play = output.api.calls[-1]
            self.assertEqual(play[0], "hsp/play")
            points = play[1]["add"]["points"]
            self.assertLessEqual(len(points), 100)
            self.assertTrue(all(p["x"] == 40 for p in points))
            self.assertEqual(len(points), 2)  # one continuous hold, not 75 repeated targets
            self.assertEqual(points[-1]["t"], 1500)
            self.assertFalse(play[1]["loop"])
            output.poll()
            output.stream(lambda dt: .6, 10.5)
            add = output.api.calls[-1]
            self.assertEqual(add[0], "hsp/add")
            self.assertGreater(add[1]["points"][0]["t"], points[-1]["t"])
            output.poll()
            output.stream(lambda dt: .2, 20)
            self.assertFalse(output.active)
            self.assertIn("buffer ran dry", output.error)
            self.assertEqual(output.api.calls[-1][0], "stop")

    def test_shallow_manual_strokes_keep_turns_without_quantized_stop_start_targets(self):
        from bisect import bisect_right
        with output_fixture() as output:
            now = [10.]
            output.api.rtt_ms = 900
            control = HandyControl(output, lambda: None, clock=lambda: now[0])
            control.select("manual")
            control.configure(low=37, high=51, cycles=.37, manual_native=False, gradient=False)
            control.start()
            control.tick()
            control.tick()
            points = output.api.calls[-1][1]["add"]["points"]
            self.assertLess(len(points), 9)
            self.assertTrue(any(p["x"] == 51 for p in points))
            times = [p["t"] / 1000 for p in points]
            self.assertIn(round(.5 / .37 * 1000), [p["t"] for p in points])
            for i in range(1, round(times[-1] * 100)):
                t = i / 100
                j = min(len(points) - 2, max(0, bisect_right(times, t) - 1))
                a, b = points[j:j + 2]
                actual = (a["x"] + (b["x"] - a["x"]) * (t - times[j]) / (times[j + 1] - times[j])) / 100
                self.assertAlmostEqual(actual, control.sample(t), delta=.006)

    def test_subsample_script_turn_is_preserved(self):
        with output_fixture() as output:
            control = HandyControl(output, lambda: None, clock=lambda: 10.)
            control.load(MotionScript("turn", ((0., 0.), (.013, 1.), (.025, 0.), (2., 0.))))
            control.start()
            control.tick()
            control.tick()
            points = output.api.calls[-1][1]["add"]["points"]
            self.assertIn({"t": 13, "x": 100}, points)
            self.assertIn({"t": 25, "x": 0}, points)

    def test_timed_stop_is_one_request(self):
        api = HandyAPI("device", "app")
        api.device_mode = 4
        api.call = unittest.mock.Mock(return_value={})
        api.stop()
        api.call.assert_called_once_with("hsp/stop")

    def test_live_edit_bypasses_refill_delay_and_replaces_buffer(self):
        with output_fixture() as output:
            output.start()
            output.stream(lambda dt: .4, 10., revision=1)
            output.poll()
            output.stream(lambda dt: .4, 10., revision=1)
            output.poll()
            output.stream(lambda dt: .6, 10.1, revision=2)
            path, body = output.api.calls[-1]
            self.assertEqual(path, "hsp/play")
            self.assertTrue(body["add"]["flush"])
            self.assertTrue(all(p["x"] == 60 for p in body["add"]["points"]))

    def test_follow_never_uses_pattern_matching_as_a_clock(self):
        from vector1a.app import VectorApp
        from unittest.mock import Mock
        app = SimpleNamespace(_direct_input=None, timeline=Mock())
        app.timeline.mfp_transport.return_value = None
        self.assertIsNone(VectorApp._handy_transport(app))
        app.timeline.position_seconds.assert_not_called()

    def test_failed_motion_stops_and_requires_explicit_reconnect(self):
        with output_fixture() as output:
            output.api.fail = "hsp/play"
            output.start()
            output.stream(lambda dt: .5, 10)
            output.poll()
            output.stream(lambda dt: .5, 10)
            output.poll()
            self.assertFalse(output.active)
            self.assertFalse(output.connected)
            self.assertEqual(output.api.calls[-1][0], "stop")
            with self.assertRaises(ValueError):
                output.start()

    def test_stop_during_setup_prevents_late_play(self):
        with output_fixture() as output:
            original = output.api.call
            def cancel_on_setup(path, body=None):
                result = original(path, body)
                if path == "hsp/setup":
                    output.cancelled.set()
                return result
            output.api.call = cancel_on_setup
            output.start()
            output.stream(lambda dt: .5, 10)
            self.assertNotIn("hsp/play", [p for p, b in output.api.calls])

    def test_http_errors_are_redacted_and_auth_version_is_explicit(self):
        from urllib.error import HTTPError
        api = HandyAPI("private-key", "private-api")
        self.assertEqual(api.version, 3)
        with patch.object(api, "_open", side_effect=HTTPError("private-key", 401, "private-api", {}, None)):
            with self.assertRaises(ValueError) as raised:
                api.call("info", method="GET")
        self.assertNotIn("private-", str(raised.exception))


class InterfaceTests(unittest.TestCase):
    def test_window_library_controls_and_close_do_not_move_device(self):
        import tkinter as tk
        from vector1a.handy_panel import HandyPanel
        with TemporaryDirectory() as folder, output_fixture() as output:
            root = tk.Tk()
            root.withdraw()
            try:
                app = SimpleNamespace(root=root, handy_control=HandyControl(output, lambda: None))
                with patch("vector1a.handy_panel.settings_path", return_value=Path(folder) / "settings.json"):
                    panel = HandyPanel(app)
                    self.assertEqual(str(panel.key_entry.cget("show")), "")
                    root.update()
                    self.assertEqual(len(panel.catalog), 5)
                    self.assertGreater(panel.canvas.winfo_height(), 80)
                    panel.selected.set(next(iter(panel.catalog)))
                    panel.load_selected()
                    panel.mode.set("manual")
                    panel.control.select("manual")
                    panel.control.configure(high=80)
                    panel.low.set(90)
                    panel.settings_changed("low")
                    self.assertEqual(panel.control.low, 80)
                    self.assertEqual(panel.control.high, 80)
                    panel.window.after_cancel(panel.job)
                    panel.refresh()
                    panel.range_control.handle = "low"
                    panel.range_control.apply(25)
                    self.assertEqual(panel.control.low, 25)
                    panel.range_control.handle = "high"
                    panel.range_control.nudge(-1)
                    self.assertEqual(panel.control.high, 79)
                    panel.preview()
                    panel.control.tick()
                    panel.window.after_cancel(panel.job)
                    panel.refresh()
                    self.assertTrue(panel.control.previewing)
                    panel.close()
                    self.assertFalse(panel.control.running)
                    self.assertEqual([p for p, b in output.api.calls], ["connect"])
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
