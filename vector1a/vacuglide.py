"""Native, operator-armed VacuGlide output."""
from concurrent.futures import Future, ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
from time import monotonic, sleep
from threading import RLock
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .settings import settings_path


CLUSTERS = frozenset(
    f"{region}.autoblowapi.com" for region in (
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "ca-central-1", "ap-southeast-2", "eu-west-2", "eu-central-1",
    )
)


VALVE_FIELDS = {"minus": "strokeMinusValve", "plus": "strokePlusValve"}


def output_error(action, exc):
    if isinstance(exc, HTTPError):
        reason = f"Autoblow HTTP {exc.code}"
        if exc.code == 429:
            reason += " (rate limited)"
    elif isinstance(exc, TimeoutError):
        reason = "device request timed out"
    elif isinstance(exc, OSError):
        reason = "device connection failed"
    else:
        reason = str(exc) if type(exc) is ValueError else "invalid device response"
    return f"{action}: {reason.rstrip('.')}."


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class VacuGlideAPI:
    def __init__(self, token):
        self._token = token
        self._host = None
        self._opener = build_opener(NoRedirect())

    def _request(self, host, path, method="GET", payload=None):
        headers = {"x-device-token": self._token}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(f"https://{host}/vacuglide/{path}", data, headers, method=method)
        with self._opener.open(request, timeout=2.5) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict):
            raise ValueError("Invalid device reply")
        return result

    def connect(self):
        info = self._request("latency.autoblowapi.com", "connected")
        if info.get("connected") is not True or info.get("deviceType") != "vacuglide":
            raise ValueError("VacuGlide is offline or token belongs to another device")
        host = info.get("cluster")
        if not isinstance(host, str) or host not in CLUSTERS:
            raise ValueError("Unknown VacuGlide cluster")
        self._host = host

    def set_speed(self, speed):
        return self._request(self._host, "target-speed", "PUT", {"targetSpeed": speed})

    def set_valve(self, kind, opened):
        return self._request(self._host, f"valve/stroke-{kind}", "PUT", {"valveState": opened})

    def state(self):
        return self._request(self._host, "state")

    def stop(self):
        # Re-resolve once if the device has reconnected to a different cluster.
        try:
            return self._request(self._host, "target-speed/stop", "PUT")
        except OSError as exc:
            if isinstance(exc, HTTPError) and exc.code == 429:
                raise
            self.connect()
            return self._request(self._host, "target-speed/stop", "PUT")


def percent(value):
    if type(value) not in (int, float) or not 0 < value <= 100:
        raise ValueError("Speed must be greater than 0 and at most 100 percent")
    return float(value)


class VacuGlideOutput:
    """Serialize cloud writes. Stop clears ownership only after a device receipt."""
    def __init__(self, api_factory=VacuGlideAPI):
        self._api_factory = api_factory
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vacuglide")
        self._lock = RLock()
        self._api = None
        self._cap = None
        self._phase = "released"
        self._speed = None
        self._error = None
        self._motion = None
        self._stop = None
        self._release_requested = False
        self._stop_revision = 0
        self._stop_verified = False
        self._stop_reported_mode = None
        self._timeline = None
        self._timeline_source = None
        self._valve_cleanup = False
        self._valves = dict.fromkeys(VALVE_FIELDS)
        self._range_path = settings_path().with_name("vacuglide-director-range.json")
        self._director_range = self._load_director_range()

    @staticmethod
    def _validate_director_range(low, high):
        if (type(low) not in (int, float) or type(high) not in (int, float)
                or not 0 <= low <= high <= 100):
            raise ValueError("Gwendolyn's minimum and maximum must be between 0% and 100%.")
        return float(low), float(high)

    def _load_director_range(self):
        try:
            low, high = json.loads(self._range_path.read_text(encoding="utf-8"))
            return self._validate_director_range(low, high)
        except (OSError, ValueError, TypeError):
            return 0.0, 25.0

    def save_director_range(self, low, high):
        bounds = self._validate_director_range(low, high)
        with self._lock:
            self._range_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._range_path.parent, delete=False) as file:
                file.write(json.dumps(bounds).encode("utf-8"))
                temporary = Path(file.name)
            try:
                temporary.replace(self._range_path)
            finally:
                temporary.unlink(missing_ok=True)
            self._director_range = bounds

    def director_command(self, action, speed=None):
        if action == "stop":
            return self.stop()
        if action not in ("start", "speed"):
            raise ValueError("Use start, speed, or stop")
        if type(speed) in (int, float) and speed == 0:
            return self.stop()
        speed = percent(speed)
        with self._lock:
            low, high = self._director_range
            if self._timeline is not None:
                raise ValueError("Use the Script Editor's speed trim during live script playback.")
            speed = min(high, max(low, speed))
            return self.command(action, speed) if speed > 0 else self.stop()

    def state(self):
        with self._lock:
            return {
                "ownership": "vector" if self._api is not None else "released",
                "state": self._phase,
                "confirmed_speed_percent": self._speed,
                "max_speed_percent": self._cap,
                "error": self._error,
                "valves": self._valves.copy(),
                "control_source": self._timeline_source,
                "stop_revision": self._stop_revision,
                "stop_verified": self._stop_verified,
                "stop_reported_mode": self._stop_reported_mode,
                "director_min_speed_percent": self._director_range[0],
                "director_max_speed_percent": self._director_range[1],
            }

    def _set(self, phase, speed=None, error=None):
        with self._lock:
            self._phase, self._speed, self._error = phase, speed, error
            if phase != "stopped":
                self._stop_verified = False

    def _busy(self):
        return any(job is not None and not job.done() for job in (self._motion, self._stop))

    def arm(self, token, cap):
        token = token.strip()
        if not token or not token.isascii() or not token.isprintable() or " " in token:
            raise ValueError("Enter the VacuGlide device token")
        cap = percent(cap)
        with self._lock:
            if self._api is not None or self._busy():
                raise ValueError("Release Vector control before claiming the device again")
            api = self._api_factory(token)
            self._cap = cap
            self._set("connecting")
            self._motion = self._worker.submit(self._claim, api)
            return self._motion

    def _claim(self, api):
        try:
            api.connect()
        except (OSError, ValueError):
            with self._lock:
                self._cap = None
                self._set("released", error="VacuGlide connection failed. Check the token and Online mode.")
            return 502, {"ok": False, **self.state()}
        with self._lock:
            self._api = api
        return self._halt()

    def reserve_timeline(self, valves=False, *, source="Saved script"):
        with self._lock:
            if self._timeline is not None:
                raise ValueError(f"VacuGlide is controlled by {self._timeline_source}. Stop that source first.")
            if self._api is None or self._phase != "stopped" or self._busy():
                raise ValueError("Claim the VacuGlide in Vector and wait for a confirmed stop before starting a script.")
            self._timeline = object()
            self._timeline_source = source
            if valves:
                self._valve_cleanup = True
                self._valves = dict.fromkeys(VALVE_FIELDS)
            return self._timeline, self._cap

    def owns_timeline(self, reservation):
        with self._lock:
            return reservation is not None and reservation is self._timeline

    def cancel_timeline(self, reservation):
        with self._lock:
            if reservation is not None and reservation is self._timeline:
                self._timeline = None
                self._timeline_source = None

    def command(self, action, speed=None, *, timeline=None):
        if action == "stop":
            return self.stop()
        if action not in ("start", "speed"):
            raise ValueError("Use start, speed, or stop")
        speed = percent(speed)
        with self._lock:
            if timeline is not self._timeline:
                raise ValueError("VacuGlide output is reserved by the script editor or the script has stopped.")
            required = "stopped" if action == "start" else "running"
            if self._busy() or self._api is None or self._phase != required:
                raise ValueError(f"VacuGlide must be owned by Vector and {required}")
            speed = min(speed, self._cap)
            self._set("applying")
            self._motion = self._worker.submit(self._drive, speed)
            return self._motion

    def valve(self, timeline, kind, opened, *, deadline=None):
        if kind not in VALVE_FIELDS or type(opened) is not bool:
            raise ValueError("Use Stroke Plus or Stroke Minus with an open or close state.")
        with self._lock:
            if not self.owns_timeline(timeline) or not self._valve_cleanup or self._busy():
                raise ValueError("The live valve track is unavailable.")
            self._motion = self._worker.submit(self._set_valve, kind, opened, deadline, timeline)
            return self._motion

    def _set_valve(self, kind, opened, deadline=None, timeline=None):
        if opened and (not self.owns_timeline(timeline) or self.state()["state"] == "stopping"
                       or (deadline is not None and monotonic() >= deadline)):
            return 200, {"ok": True, "skipped": True, **self.state()}
        try:
            receipt = self._api.set_valve(kind, opened)
            if receipt.get(VALVE_FIELDS[kind]) is not opened:
                raise ValueError("Unexpected valve receipt")
        except (OSError, ValueError) as exc:
            with self._lock:
                self._valves[kind] = None
                self._error = output_error(f"Stroke {kind} {'open' if opened else 'close'}", exc)
            return 502, {"ok": False, **self.state()}
        with self._lock:
            self._valves[kind] = opened
        return 200, {"ok": True, **self.state()}

    def motor_rest(self, timeline):
        with self._lock:
            if not self.owns_timeline(timeline) or self._busy():
                raise ValueError("The live speed track is unavailable.")
            self._set("stopping")
            self._motion = self._worker.submit(self._halt)
            return self._motion

    def _drive(self, speed):
        try:
            receipt = self._api.set_speed(speed)
            raw_speed = receipt.get("targetSpeed")
            confirmed = 0.0 if type(raw_speed) in (float, int) and raw_speed == 0 else percent(raw_speed)
            mode = receipt.get("operationalMode")
            if mode != "TARGET_SPEED_PLAYING":
                if isinstance(mode, str) and len(mode) <= 40 and mode.isascii() and mode.replace("_", "").isalnum():
                    raise ValueError(f"device reported {mode} instead of target-speed playback")
                raise ValueError("device did not report target-speed playback")
            if confirmed > self._cap:
                raise ValueError(f"reported {confirmed:g}% above the {self._cap:g}% claim cap")
        except (OSError, ValueError) as exc:
            reason = output_error(f"Set speed to {speed:g}%", exc)
            with self._lock:
                self._set("stopping")
            self._halt()
            with self._lock:
                if self._phase != "stopped" and self._error:
                    reason += f" {self._error}"
                self._error = reason
            return 502, {"ok": False, **self.state()}
        with self._lock:
            if self._stop is None or self._stop.done():
                self._set("running", confirmed)
                return 200, {"ok": True, **self.state()}
            return 409, {"ok": False, **self.state(), "error": "A stop superseded this speed request"}

    def stop(self, release=False, *, timeline=None, keep_timeline=False):
        with self._lock:
            if timeline is not None and timeline is not self._timeline:
                if self._stop is not None:
                    return self._stop
                future = Future()
                future.set_result((409, {"ok": False, **self.state()}))
                return future
            if timeline is None:
                self._stop_revision += 1
            if not keep_timeline or timeline is None:
                self._timeline = None
                self._timeline_source = None
            self._release_requested |= release
            if self._stop is not None and not self._stop.done():
                return self._stop
            if self._api is None and not self._busy():
                self._release_requested = False
                future = Future()
                future.set_result((200, {"ok": True, **self.state()}))
                return future
            self._set("stopping")
            self._stop = self._worker.submit(self._stop_owned)
            return self._stop

    def _stop_owned(self):
        code, receipt = self._halt(publish=False)
        with self._lock:
            close_valves = self._valve_cleanup
            # Close a valve last known open first. A failed close never skips the other valve.
            order = sorted(VALVE_FIELDS, key=lambda kind: self._valves[kind] is not True)
        if close_valves:
            closures = [self._set_valve(kind, False)[1] for kind in order]
        else:
            closures = []
        if code == 200 and self._api is not None and all(reply["ok"] for reply in closures):
            code, receipt = self._verify_stopped()
        with self._lock:
            valve_errors = [reply["error"] for reply in closures if not reply["ok"]]
            if valve_errors:
                problems = " ".join(valve_errors)
                self._set("unknown", error=f"Valve closure unconfirmed. {problems} Use the VacuGlide's physical power control.")
                code, receipt = 502, {"ok": False}
            elif code != 200:
                self._set("unknown", error=receipt.get("error"))
            else:
                self._error = None
                if self._timeline is None:
                    self._valve_cleanup = False
            release = self._release_requested
            self._release_requested = False
            if release and receipt["ok"]:
                self._api, self._cap = None, None
                self._set("released")
            return code, {"ok": receipt["ok"], **self.state()}

    def _verify_stopped(self):
        """Read playback independently of the stop command acknowledgement."""
        mode = None
        try:
            for attempt in range(2):
                if attempt:
                    sleep(0.2)
                value = self._api.state().get("operationalMode")
                mode = value if isinstance(value, str) else None
                if mode != "TARGET_SPEED_PAUSED":
                    raise ValueError("Device readback is not paused")
        except (OSError, ValueError):
            with self._lock:
                self._stop_reported_mode = mode
                label = (f" Device reported {mode}." if mode and mode.isascii()
                         and mode.replace("_", "").isalnum() and len(mode) <= 40 else "")
                self._set("unknown", error=f"Stop readback unconfirmed.{label}")
                return 502, {"ok": False, **self.state()}
        with self._lock:
            self._stop_reported_mode = mode
            self._stop_verified = True
            self._set("stopped", 0.0)
            return 200, {"ok": True, **self.state()}

    def _halt(self, *, publish=True):
        if self._api is not None:
            try:
                receipt = self._api.stop()
                if receipt.get("operationalMode") != "TARGET_SPEED_PAUSED":
                    raise ValueError("Unexpected stop receipt")
            except (OSError, ValueError):
                self._set("unknown", error="Stop command unconfirmed.")
                return 502, {"ok": False, **self.state()}
            if publish:
                return self._verify_stopped()
        return 200, {"ok": True, **self.state()}

    def close(self):
        self._worker.shutdown(wait=False)
