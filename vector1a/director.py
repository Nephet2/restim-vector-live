from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Empty, Queue
from typing import Any
from urllib.parse import urlparse


@dataclass
class DirectorRequest:
    method: str
    path: str
    body: dict[str, Any]
    completed: threading.Event = field(default_factory=threading.Event)
    status: int = 500
    response: dict[str, Any] = field(default_factory=lambda: {"ok": False, "error": "not processed"})


class DirectorBridge:
    """Thread-safe handoff between the HTTP listener and Vector's Tk/UI thread."""

    def __init__(self) -> None:
        self._requests: Queue[DirectorRequest] = Queue()

    def submit(self, method: str, path: str, body: dict[str, Any], timeout: float = 2.0
               ) -> tuple[int, dict[str, Any]]:
        request = DirectorRequest(method=method, path=path, body=body)
        self._requests.put(request)
        if not request.completed.wait(timeout):
            return 503, {"ok": False, "error": "Vector UI did not answer in time"}
        return request.status, request.response

    def get_nowait(self) -> DirectorRequest:
        return self._requests.get_nowait()


class _DirectorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, bridge: DirectorBridge):
        super().__init__(address, handler)
        self.bridge = bridge


class _Handler(BaseHTTPRequestHandler):
    server_version = "VectorDirector/0.9"

    def log_message(self, _format: str, *_args) -> None:
        return

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin", "")
        if origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            return {}
        if length > 65536:
            raise ValueError("request body too large")
        raw = self.rfile.read(length)
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object")
        return parsed

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        self.send_response(204)
        if origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/v1/state", "/v1/capabilities", "/v1/controller"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        status, payload = self.server.bridge.submit("GET", path, {})  # type: ignore[attr-defined]
        self._send(status, payload)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in (
                "/v1/preset", "/v1/rolling-variety", "/v1/neutral", "/v1/stop", "/v1/resume",
                "/v1/semantic/texture", "/v1/semantic/primary-spatial",
                "/v1/semantic/secondary-spatial", "/v1/semantic/variation",
                "/v1/semantic/top-focus", "/v1/semantic/bottom-focus",
                "/v1/spatial-gain/top", "/v1/spatial-gain/bottom",
                "/v1/generated-motion/plan", "/v1/generated-motion/hold",
                "/v1/generated-motion/resume", "/v1/generated-motion/authored",
                "/v1/modifier/target", "/v1/modifier/stroke-range", "/v1/modifier/tempo", "/v1/modifier/restore"):
            self._send(404, {"ok": False, "error": "not found"})
            return
        try:
            body = self._body()
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send(400, {"ok": False, "error": str(exc)})
            return
        status, payload = self.server.bridge.submit("POST", path, body)  # type: ignore[attr-defined]
        self._send(status, payload)


class DirectorServer:
    """Small loopback-only HTTP server. Vector itself remains AI-independent."""

    LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

    def __init__(self, bridge: DirectorBridge):
        self.bridge = bridge
        self._server: _DirectorHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._server is not None and self._thread is not None and self._thread.is_alive()

    @property
    def address(self) -> tuple[str, int] | None:
        if self._server is None:
            return None
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self, host: str = "127.0.0.1", port: int = 11436) -> tuple[str, int]:
        if host not in self.LOOPBACK_HOSTS:
            raise ValueError("Director API is loopback-only in this release")
        if self.running:
            assert self.address is not None
            return self.address
        server = _DirectorHTTPServer((host, int(port)), _Handler, self.bridge)
        thread = threading.Thread(target=server.serve_forever, name="vector-director-http", daemon=True)
        self._server, self._thread = server, thread
        thread.start()
        assert self.address is not None
        return self.address

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
