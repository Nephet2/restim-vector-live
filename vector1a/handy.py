"""Serialized Handy cloud transport. One request job at a time; no motion backlog."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from http.client import HTTPSConnection, HTTPException
from io import BytesIO
import json
from math import ceil, floor, isfinite
from threading import Event
from time import monotonic, time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, getproxies, urlopen


class HandyHTTPError(ValueError):
    def __init__(self, status, path, explanation=""):
        self.status = status
        suffix = f": {explanation}" if explanation else ""
        super().__init__(f"Handy HTTP {status} on /{path}{suffix}")


def trajectory_points(sample, start, end, knots=(), tolerance=.005):
    """Preserve authored events; subdivide curves at half a percent error.

    Linear segments need no sampling grid. Check quarter-points as well as
    midpoints so symmetric S curves do not alias into straight lines.
    """
    times = sorted({start, end, *(t for t in knots if start < t < end)})
    result = [(start, sample(start))]
    def segment(a, x, b, y, depth=0):
        checks = [(a + (b - a) * f, f) for f in (.25, .5, .75)]
        error = max(abs(sample(t) - (x + (y - x) * f)) for t, f in checks)
        if error > tolerance and b - a > .002 and depth < 16:
            mid = (a + b) / 2
            value = sample(mid)
            segment(a, x, mid, value, depth + 1)
            segment(mid, value, b, y, depth + 1)
        else:
            result.append((b, y))
    for a, b in zip(times, times[1:]):
        segment(a, sample(a), b, sample(b))
    return result


class HandyAPI:
    def __init__(self, key, api_key=""):
        api_key = api_key.strip()
        self.version = 3 if api_key else 2
        self.headers = {"Content-Type": "application/json", "X-Connection-Key": key}
        self.auth_scheme = "none"
        if api_key:
            if api_key.lower().startswith("bearer "):
                self.headers["Authorization"] = "Bearer " + api_key.split(None, 1)[1].strip()
                self.auth_scheme = "bearer"
            else:
                self.headers["X-Api-Key"] = api_key
                self.auth_scheme = "api_key"
        # Reject malformed copied headers before http.client can include their
        # value in an exception message. Never echo credential text to the UI.
        values = [key]
        if api_key:
            values.append(self.headers.get("X-Api-Key") or self.headers["Authorization"][7:])
        if any(not value or any(ord(char) <= 32 or ord(char) >= 127 for char in value) for value in values):
            raise ValueError("Paste only the Handy credential values, without spaces or line breaks.")
        self.base = ("https://www.handyfeeling.com/api/handy/v2" if self.version == 2
                     else "https://www.handyfeeling.com/api/handy-rest/v3")
        self.offset = 0
        self.info = {}
        self.trace = deque(maxlen=50)
        self.slide = None
        self.hsp_state = {}
        self.global_stroke = None
        self.manual_slide_changed = False
        self._connection = None
        self._proxy = bool(getproxies().get("https"))
        self._manual_stroke = None
        self._manual_velocity = None
        self._manual_next_at = 0.
        self.manual_interval = .3
        self.device_mode = None
        self.rtt_ms = None

    def close(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _open(self, request, timeout=6):
        """Reuse one TLS session on the serialized device worker.

        Keep configured system proxies working via urllib. Never replay a
        failed motion request: the device may already have acted on it.
        """
        if self._proxy:
            return urlopen(request, timeout=timeout)
        target = urlsplit(request.full_url)
        if self._connection is None:
            self._connection = HTTPSConnection(target.hostname, timeout=timeout)
        try:
            self._connection.request(request.get_method(), target.path,
                                     body=request.data, headers=dict(request.header_items()))
            response = self._connection.getresponse()
            if response.status >= 300:
                data = response.read()
                raise HTTPError(request.full_url, response.status, response.reason,
                                response.headers, BytesIO(data))
            return response
        except HTTPError:
            raise
        except (OSError, HTTPException):
            self.close()
            raise

    def call(self, path, body=None, method="PUT"):
        # Never record request headers or connection/API keys.
        self.trace.append(f"{method} /{path} {json.dumps(body) if body is not None else ''}")
        data = None if body is None else json.dumps(body, allow_nan=False).encode()
        sent = monotonic()
        try:
            with self._open(Request(f"{self.base}/{path}", data, self.headers, method=method), timeout=6) as response:
                value = json.load(response)
        except HTTPError as exc:
            explanation = ""
            try:
                payload = json.loads(exc.read(4096))
                error = payload.get("error", payload) if isinstance(payload, dict) else {}
                if isinstance(error, dict):
                    explanation = str(error.get("message") or error.get("name") or "")
                    if not explanation and error.get("errors"):
                        explanation = json.dumps(error["errors"])
                elif isinstance(error, str):
                    explanation = error
                # Some validation responses use details rather than message.
                if not explanation and isinstance(payload, dict):
                    explanation = str(payload.get("message") or payload.get("details") or "")
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            secrets = [self.headers.get(name) for name in ("X-Connection-Key", "X-Api-Key", "Authorization")]
            authorization = self.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                secrets.append(authorization.split(None, 1)[1])
            for secret in secrets:
                if secret:
                    explanation = explanation.replace(secret, "[redacted]")
            explanation = " ".join(explanation.split())[:700]
            suffix = f": {explanation}" if explanation else ""
            self.trace.append(f"HTTP {exc.code}{suffix}")
            raise HandyHTTPError(exc.code, path, explanation) from None
        except (URLError, TimeoutError, OSError, HTTPException):
            self.close()
            self.trace.append("Network timeout/unavailable")
            raise ValueError("Handy connection timed out or is unavailable.") from None
        if not isinstance(value, dict) or value.get("error"):
            error = value.get("error", {}) if isinstance(value, dict) else {}
            code = error.get("code", "unknown") if isinstance(error, dict) else "unknown"
            self.trace.append(f"Device error {code}")
            raise ValueError(f"Handy rejected the command (code {code}). Check Online mode and firmware.")
        if isinstance(value.get("result"), (int, float)) and value["result"] < 0:
            self.trace.append(f"Rejected: result={value['result']}")
            raise ValueError("Handy did not accept the command.")
        # v2 puts state/velocity/firmware alongside its numeric result code.
        # Only v3 wraps the actual response data inside result.
        result = value.get("result", value) if self.version == 3 else value
        self.rtt_ms = round((monotonic() - sent) * 1000)
        if path == "mode":
            self.device_mode = body.get("mode") if method == "PUT" and body else (
                result.get("mode") if isinstance(result, dict) else result)
        if path.startswith("hsp/") and isinstance(result, dict):
            self.hsp_state = dict(result)
        if path == "info":
            self.trace.append(f"Device info received ({self.rtt_ms} ms)")
        else:
            self.trace.append(f"Reply ({self.rtt_ms} ms) " + json.dumps(result))
        return result

    def connect(self, cancelled):
        try:
            status = self.call("connected", method="GET")
        except HandyHTTPError as exc:
            if self.version != 3 or exc.status != 401 or cancelled.is_set():
                raise
            # Authentication negotiation is limited to this read-only probe.
            # Never replay a start/position/stop command to guess credentials.
            if self.auth_scheme == "api_key":
                credential = self.headers.pop("X-Api-Key")
                self.headers["Authorization"] = "Bearer " + credential
                self.auth_scheme = "bearer"
            else:
                credential = self.headers.pop("Authorization").split(None, 1)[1]
                self.headers["X-Api-Key"] = credential
                self.auth_scheme = "api_key"
            self.trace.append(f"Authentication probe: trying {self.auth_scheme} (credential hidden)")
            try:
                status = self.call("connected", method="GET")
            except HandyHTTPError as alternate:
                if alternate.status != 401:
                    raise
                raise ValueError("Handy rejected this credential as both an API key and a bearer token (401). "
                                 "Use a Handy Application Key or an unexpired client API token; "
                                 "the account sign-in token is a different credential. "
                                 "Keep the short device key in Connection key.") from None
        connected = status.get("connected") if isinstance(status, dict) else status
        if connected is not True:
            raise ValueError("Handy is offline. Put it in Online mode and check the connection key.")
        if cancelled.is_set():
            return
        info = self.call("info", method="GET")
        if isinstance(info, dict):
            self.info = {"firmware": info.get("fw_version", info.get("fwVersion", "unknown")),
                         "model": info.get("hw_model_name", info.get("model", "unknown"))}
        if isinstance(info, dict) and (info.get("fw_status", info.get("fwStatus")) == 2):
            raise ValueError("Handy firmware update required.")
        if cancelled.is_set():
            return
        if self.version == 3:
            begin = time() * 1000
            server = self.call("servertime", method="GET")
            end = time() * 1000
            stamp = server.get("server_time", server.get("servertime")) if isinstance(server, dict) else server
            if not isinstance(stamp, (int, float)):
                raise ValueError("Handy returned an invalid server clock.")
            self.offset = stamp - (begin + end) / 2
        if not cancelled.is_set():
            self.stop()
        if self.version == 3 and not cancelled.is_set():
            self.read_stroke()
        if self.version == 2 and not cancelled.is_set():
            slide = self.call("slide", method="GET")
            if not isinstance(slide, dict) or not all(isinstance(slide.get(k), (int, float))
                    and isfinite(slide[k]) for k in ("min", "max")) or not 0 <= slide['min'] < slide['max'] <= 100:
                raise ValueError("Handy returned an invalid stroke zone.")
            self.slide = {"min": slide["min"], "max": slide["max"]}
            self.info["original_stroke_zone"] = dict(self.slide)
            self.global_stroke = dict(self.slide)

    def read_stroke(self):
        value = self.call("slider/stroke" if self.version == 3 else "slide", method="GET")
        scale = 100 if self.version == 3 else 1
        if (not isinstance(value, dict) or not all(isinstance(value.get(k), (int, float))
                and isfinite(value[k]) for k in ("min", "max"))
                or not 0 <= value["min"] < value["max"] <= 100 / scale):
            raise ValueError("Handy returned invalid device stroke limits.")
        self.global_stroke = {k: value[k] * scale for k in ("min", "max")}
        if self.version == 2:
            self.slide = dict(self.global_stroke)
        return dict(self.global_stroke)

    def reset_stroke(self):
        self.call("slider/stroke" if self.version == 3 else "slide",
                  {"min": 0, "max": 1 if self.version == 3 else 100})
        self.read_stroke()

    def stop(self):
        if self.version == 3 and self.device_mode == 4:
            # Stop the active stream in one request, without mode queries or
            # a mode transition ahead of the actual stop.
            self.call("hsp/stop")
            return
        # Switching into HAMP stops any HSP/HDSP trajectory as well.
        if self.device_mode != 0:
            self.ensure_mode(0)
        self.call("hamp/stop")
        self._manual_stroke = self._manual_velocity = None
        if self.version == 2 and self.manual_slide_changed and self.slide is not None:
            self.call("slide", self.slide)
            self.manual_slide_changed = False

    def ensure_mode(self, mode, cancelled=None):
        if cancelled is not None and cancelled.is_set():
            return
        current = self.call("mode", method="GET")
        value = current.get("mode") if isinstance(current, dict) else current
        if value != mode and not (cancelled is not None and cancelled.is_set()):
            self.call("mode", {"mode": mode})

    def manual(self, low, high, velocity, cancelled, starting=False):
        """Native alternating movement, with version-specific percentage units."""
        def call(path, body=None):
            delay = max(0., self._manual_next_at - monotonic())
            if delay and cancelled.wait(delay):
                return
            if not cancelled.is_set():
                self._manual_next_at = monotonic() + self.manual_interval
                return self.call(path, body)
        if starting:
            self.ensure_mode(0, cancelled)
            self._manual_stroke = self._manual_velocity = None
        if high - low < .01 or velocity <= 0:
            call("hamp/stop")
            return
        if self.version == 2:
            if self.slide is None:
                raise ValueError("Reconnect Handy to read its stroke zone before manual playback.")
            bottom, top = self.slide["min"], self.slide["max"]
            # The firmware-4 legacy adapter rejected fractional /slide values
            # in the real device trace. Round inwards, never widen the range.
            stroke = {"min": ceil(round(bottom + (top - bottom) * low / 100, 8)),
                      "max": floor(round(bottom + (top - bottom) * high / 100, 8))}
            if stroke["min"] >= stroke["max"]:
                raise ValueError("The selected range is too narrow for whole-percentage legacy control.")
            if stroke != self._manual_stroke:
                self.manual_slide_changed = True
                reply = call("slide", stroke)
                if reply is not None and reply.get("result", 0) != 0:
                    # Firmware may round a too-small zone outwards. Do not start
                    # motion outside the operator's selected endpoints.
                    raise ValueError("Handy adjusted the requested stroke zone; increase the range and try again.")
                if not cancelled.is_set():
                    self._manual_stroke = stroke
            if starting:
                call("hamp/start")
            speed = round(velocity * 100)
            if speed != self._manual_velocity:
                call("hamp/velocity", {"velocity": speed})
                if not cancelled.is_set():
                    self._manual_velocity = speed
        else:
            stroke = {"min": low / 100, "max": high / 100}
            if velocity != self._manual_velocity or stroke != self._manual_stroke:
                body = {}
                if velocity != self._manual_velocity:
                    body["velocity"] = velocity
                if stroke != self._manual_stroke:
                    body["stroke"] = stroke
                call("hamp/state", body)
                if not cancelled.is_set():
                    self._manual_stroke, self._manual_velocity = stroke, velocity
            if starting:
                call("hamp/start")

    def check_manual(self, expected=True):
        state = self.call("hamp/state", method="GET")
        value = state.get("play_state" if self.version == 3 else "state") if isinstance(state, dict) else None
        if expected and value != (1 if self.version == 3 else 2):
            raise ValueError("Handy reports manual motion stopped. Check the device and its stroke zone.")


class HandyOutput:
    def __init__(self, api_factory=HandyAPI):
        self.api_factory = api_factory
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="handy")
        self.api = None
        self.pending = None
        self.connected = False
        self.error = ""
        self.detail = "Disconnected"
        self.cancelled = Event()
        self.active = False
        self.stream_started = False
        self.stream_epoch = 0.
        self.stream_end = 0.
        self.index = 0
        self.next_send = 0.
        self.closed = False
        self.manual_settings = None
        self.backend = ""
        self.manual_check_at = 0.
        self.stream_prepared = False
        self.stream_revision = None
        self.point_stamps = deque()
        self.buffer_window = 1.5
        self.last_vertex = None
        self.edit_tolerance = .005
        self.warm_restart = False

    def device_range(self, reset=False):
        self.poll()
        if not self.connected or self.active or self.pending:
            raise ValueError("Pause Handy and wait for stop confirmation before reading or changing device limits.")
        self._submit("limits", self.api.reset_stroke if reset else self.api.read_stroke)

    def _submit(self, kind, action):
        if self.pending is not None:
            raise ValueError("Wait for the Handy command to finish.")
        self.pending = kind, self.worker.submit(action)

    def poll(self):
        if self.pending is None or not self.pending[1].done():
            return
        kind, future = self.pending
        self.pending = None
        try:
            future.result()
            if kind == "connect" and not self.cancelled.is_set():
                self.connected = True
                self.detail = "Connected • stopped"
            elif kind == "stop":
                self.detail = "Stop confirmed"
            elif kind == "limits":
                self.detail = "Device stroke limits updated; stopped"
            elif kind == "motion" and not self.cancelled.is_set():
                self.detail = f"{self.backend} • commands acknowledged"
            elif kind == "prepare" and not self.cancelled.is_set():
                self.stream_prepared = True
                self.detail = "HSP ready • preparing timed points"
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, ValueError) else "Handy command failed."
            self.detail = self.error
            self.active = False
            self.connected = False
            self.stream_prepared = False
            self.cancelled.set()
            # On any motion error, best-effort stop is next, never another move.
            if kind in ("motion", "prepare") and self.api:
                self.pending = "stop", self.worker.submit(self.api.stop)

    def connect(self, key, api_key=""):
        if not key.strip():
            raise ValueError("Enter the Handy connection key.")
        if self.closed:
            raise ValueError("Handy output is closed.")
        if self.pending:
            raise ValueError("Wait for the current Handy command.")
        previous = self.api
        self.api = self.api_factory(key.strip(), api_key.strip())
        self.stream_prepared = False
        self.warm_restart = False
        self.cancelled = Event()
        self.error = ""
        self.detail = "Connecting…"
        def connect():
            if previous is not None and hasattr(previous, "close"):
                previous.close()
            self.api.connect(self.cancelled)
        self._submit("connect", connect)

    def start(self):
        self.poll()
        if not self.connected or self.pending:
            raise ValueError("Connect Handy and wait for stop confirmation first.")
        self.cancelled = Event()
        self.active = True
        # HSP stop leaves its session prepared. Rebuild current targets in one
        # play command; do not repeat mode/setup or initial multi-batch prefill.
        # A new connection or switching to HAMP invalidates this fast path.
        self.warm_restart = (self.stream_prepared and self.api.version == 3
                             and getattr(self.api, "device_mode", None) == 4)
        self.stream_started = False
        self.stream_prepared = self.warm_restart
        self.stream_revision = None
        self.point_stamps.clear()
        self.manual_settings = None
        self.manual_check_at = 0.
        self.next_send = 0
        self.error = ""

    def stop(self):
        self.active = False
        self.stream_started = False
        self.cancelled.set()
        self.detail = "Stopping…"
        if self.api is None:
            self.detail = "Disconnected"
            return None
        if self.pending is not None and self.pending[0] == "stop":
            return self.pending[1]
        # Only one existing job can precede this stop. Its cancel token prevents
        # subsequent commands in that job (including a late play after setup).
        future = self.worker.submit(self.api.stop)
        self.pending = "stop", future
        return future

    def validate_position_mode(self):
        firmware = str(getattr(self.api, "info", {}).get("firmware", ""))
        if self.api is not None and self.api.version == 2 and firmware.startswith("4."):
            raise ValueError("Timed playback on this firmware-4 Handy requires buffered HSP. "
                             "Enter your Handy Application Key in the API key field and reconnect. "
                             "The legacy position path has been disabled after its incorrect physical movement.")

    def stream(self, sampler, now, revision=None, breakpoints=None):
        """sampler(dt) returns a bounded 0..1 position dt seconds from now."""
        self.poll()
        if not self.active or not self.connected or self.pending:
            return
        if now < self.next_send and revision == self.stream_revision:
            return
        api, cancelled = self.api, self.cancelled
        try:
            self.validate_position_mode()
        except ValueError as exc:
            self.error = str(exc)
            self.stop()
            return
        self.backend = "HDSP position stream" if api.version == 2 else "HSP buffered stream"
        starting = not self.stream_started
        if api.version == 3 and not self.stream_prepared:
            self.backend = "HSP preparing"
            def prepare():
                if not cancelled.is_set():
                    api.call("mode", {"mode": 4})
                if not cancelled.is_set():
                    api.call("hsp/setup")
            self._submit("prepare", prepare)
            return
        replacing = api.version == 3 and revision != self.stream_revision
        if api.version == 3 and not starting and not replacing and now >= self.stream_end - .06:
            self.error = "Handy buffer ran dry. Playback paused; press Resume to resynchronise."
            self.stop()
            return
        if api.version == 2:
            target = round(max(0, min(100, sampler(.34) * 100)))
            def send():
                if starting and not cancelled.is_set():
                    api.call("mode", {"mode": 2})
                if not cancelled.is_set():
                    api.call("hdsp/xpt", {"position": target, "duration": 340, "stopOnTarget": True,
                                          "immediateResponse": False})
            self.next_send = now + .34
        else:
            # Build points only AFTER mode/setup have completed. At a 900 ms
            # RTT the former 1.5 s plan could expire during initialization.
            # Respect the reported device capacity and each request's point
            # limit. Fast curves may need several batches before playback.
            rtt = max(0., (getattr(api, "rtt_ms", None) or 0) / 1000)
            if starting or replacing:
                self.buffer_window = max(1.5, min(12., rtt * 3 + 1))
                self.stream_epoch = now
                self.stream_end = now
                self.index = 0
                self.point_stamps.clear()
                self.last_vertex = None
            guard = max(.2, rtt / 2)
            while self.point_stamps and self.point_stamps[0] < now - guard:
                self.point_stamps.popleft()
            capacity = getattr(api, "hsp_state", {}).get("max_points", 100)
            capacity = min(10000, max(100, int(capacity))) if isinstance(capacity, (int, float)) and isfinite(capacity) else 100
            slots = capacity - len(self.point_stamps)
            if slots <= 0:
                return
            stamp = self.stream_end
            end = now + self.buffer_window
            if stamp >= end:
                return
            knots = [now + delta for delta in breakpoints(stamp - now, end - now)] if breakpoints else []
            previous = self.last_vertex
            def sample(at):
                if previous is not None and at == previous[0]:
                    return previous[1]
                return max(0, min(1, sampler(at - now)))
            vertices = trajectory_points(sample, stamp, end, knots)
            quick_restart = starting and self.warm_restart
            if (replacing and not starting) or quick_restart:
                # Refill and initial prebuffer are different from a live edit.
                # Never flush a playing stream and then send several batches
                # before play: that creates a visible motor pause on each edit.
                # Keep enough time for the next two request deliveries. Only
                # exceptionally dense curves need a coarser edit approximation.
                self.edit_tolerance = .005
                minimum_end = now + min(self.buffer_window, rtt * 2 + .5)
                while (len(vertices) > 90 and vertices[89][0] < minimum_end
                       and self.edit_tolerance < .02):
                    self.edit_tolerance *= 2
                    vertices = trajectory_points(sample, stamp, end, knots, tolerance=self.edit_tolerance)
            bulk_start = starting and not quick_restart and len(vertices) > 90 and capacity > 100
            if bulk_start:
                # Plan for the expected completion of prefill, rather than
                # creating a plan that is already old when playback begins.
                batches = ceil(len(vertices) / 90)
                for _ in range(3):
                    epoch = now + batches * rtt
                    end = epoch + self.buffer_window
                    knots = [now + delta for delta in breakpoints(epoch - now, end - now)] if breakpoints else []
                    vertices = trajectory_points(lambda at: max(0, min(1, sampler(at - now))), epoch, end, knots)
                    vertices = vertices[:capacity]
                    required = ceil(len(vertices) / 90)
                    if required == batches:
                        break
                    batches = required
                self.stream_epoch = epoch
            if previous is not None:
                vertices = vertices[1:]
            vertices = vertices[:slots if bulk_start else min(90, slots)]
            # Quantise time once, coalescing sub-millisecond events rather
            # than sending duplicate timestamps that the device cannot play.
            encoded = {}
            old_time = round((previous[0] - self.stream_epoch) * 1000) if previous else -1
            for stamp, x in vertices:
                t = max(0, round((stamp - self.stream_epoch) * 1000))
                if t > old_time:
                    encoded[t] = (stamp, round(x * 100))
            points = [{"t": t, "x": value[1]} for t, value in encoded.items()]
            vertices = [(value[0], value[1] / 100) for value in encoded.values()]
            if not points:
                return
            self.point_stamps.extend(stamp for stamp, _ in vertices)
            self.stream_end = vertices[-1][0]
            self.last_vertex = (self.stream_end, points[-1]["x"] / 100)
            self.index += len(points)
            if bulk_start:
                self.detail = f"Prefilling {len(points)} timed points before playback"
            add = {"points": points, "tail_point_stream_index": self.index, "flush": starting or replacing}
            epoch = self.stream_epoch
            def send():
                def call(path, body=None):
                    if not cancelled.is_set():
                        return api.call(path, body)
                if bulk_start:
                    base_index = self.index - len(points)
                    for at in range(0, len(points), 90):
                        chunk = points[at:at + 90]
                        call("hsp/add", {"points": chunk, "tail_point_stream_index": base_index + at + len(chunk),
                                         "flush": at == 0})
                        if cancelled.is_set():
                            return
                    if cancelled.wait(max(0., epoch - monotonic())):
                        return
                    call("hsp/play", {"start_time": max(0, round((monotonic() - epoch) * 1000)),
                         "server_time": round(time() * 1000 + api.offset), "playback_rate": 1,
                         "pause_on_starving": False, "loop": False})
                elif starting or replacing:
                    call("hsp/play", {"start_time": 0, "server_time": round(time() * 1000 + api.offset +
                         (epoch - monotonic()) * 1000), "playback_rate": 1,
                         "pause_on_starving": False, "loop": False, "add": add})
                else:
                    call("hsp/add", add)
            self.next_send = now + .5
            self.stream_revision = revision
        self.stream_started = True
        self.warm_restart = False
        self._submit("motion", send)

    def manual(self, low, high, speed_percent, tempo, now):
        self.poll()
        if not self.active or not self.connected or self.pending or now < self.next_send:
            return
        # HAMP exposes native speed, not a reliable cycles/second clock.
        velocity = min(1., max(0., speed_percent * tempo / 100))
        settings = round(low, 2), round(high, 2), round(velocity, 4)
        api, cancelled = self.api, self.cancelled
        starting = self.manual_settings is None or ((self.manual_settings[1] - self.manual_settings[0] < .01
                    or self.manual_settings[2] <= 0) and high - low >= .01 and velocity > 0)
        self.backend = "HAMP native manual"
        if settings != self.manual_settings:
            self._submit("motion", lambda: api.manual(*settings, cancelled, starting=starting))
            self.manual_settings = settings
            # The API rate-limits actual changed fields; no additional half-
            # second job delay before sending the newest slider values.
            self.next_send = now
            self.manual_check_at = now + 5.
        elif now >= self.manual_check_at:
            self._submit("motion", lambda: None if cancelled.is_set() else api.check_manual(high - low >= .01 and velocity > 0))
            self.next_send = now
            self.manual_check_at = now + 5.

    def diagnostics(self):
        api = self.api
        if api is None:
            return "Handy has not been connected."
        return "\n".join([f"Handy API v{api.version}", f"Endpoint: {getattr(api, 'base', 'test')}",
                          f"Authentication: {getattr(api, 'auth_scheme', 'test')} (credential hidden)",
                          f"Backend: {self.backend or 'Stopped'}", f"Device: {json.dumps(getattr(api, 'info', {}))}",
                          f"HTTP: {'system proxy' if getattr(api, '_proxy', False) else 'persistent HTTPS connection'}",
                          f"Last request round trip: {getattr(api, 'rtt_ms', None)} ms",
                          f"Last edit curve tolerance: {self.edit_tolerance * 100:g}% (before wire rounding)",
                          f"Device stroke limits (%): {json.dumps(getattr(api, 'global_stroke', None))}",
                          f"Status: {self.detail}", f"Error: {self.error or 'none'}",
                          f"Last HSP state: {json.dumps(getattr(api, 'hsp_state', {}))}",
                          "", "Recent commands (keys excluded):",
                          *list(getattr(api, "trace", ()))])

    def close(self, stop=True):
        self.closed = True
        future = self.stop() if stop else None
        if self.api is not None and hasattr(self.api, "close"):
            self.worker.submit(self.api.close)
        self.worker.shutdown(wait=False)
        return future
