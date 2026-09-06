"""Bounded RFC 6455 text receiver for MFP's local T-code output.

Only the input transport lives here; timing and axis routing remain in MFPListener.
No extensions or subprotocols are negotiated.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import socket
import struct
import time
from typing import Callable


class WebSocketInput:
    MAX_HEADER = 8192
    MAX_MESSAGE = 65536

    def __init__(self, sock: socket.socket, running: Callable[[], bool], initial: bytes):
        self.sock = sock
        self.running = running
        self.buffer = bytearray(initial)

    def _read(self, size: int, deadline: float | None = None) -> bytes:
        while len(self.buffer) < size:
            if not self.running():
                raise EOFError
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("WebSocket handshake timed out")
            try:
                data = self.sock.recv(min(4096, size - len(self.buffer)))
            except socket.timeout:
                continue
            if not data:
                raise EOFError
            self.buffer.extend(data)
        data = bytes(self.buffer[:size])
        del self.buffer[:size]
        return data

    def handshake(self) -> bool:
        deadline = time.monotonic() + 3.0
        header = bytearray()
        try:
            while not header.endswith(b"\r\n\r\n"):
                if len(header) >= self.MAX_HEADER:
                    raise ValueError("Header too large")
                header.extend(self._read(1, deadline))
            lines = header.decode("ascii").split("\r\n")
            method, path, version = lines[0].split()
            if method != "GET" or path not in ("/", "/ws", "/tcode") or version != "HTTP/1.1":
                raise ValueError("Unsupported WebSocket endpoint")
            fields = {}
            for line in lines[1:]:
                if line:
                    name, value = line.split(":", 1)
                    name = name.strip().lower()
                    if name in fields:
                        raise ValueError("Duplicate header")
                    fields[name] = value.strip()
            if (fields.get("upgrade", "").lower() != "websocket"
                    or "upgrade" not in fields.get("connection", "").lower().replace(" ", "").split(",")
                    or fields.get("sec-websocket-version") != "13"
                    or not fields.get("host")):
                raise ValueError("Invalid upgrade")
            key = fields.get("sec-websocket-key", "")
            if len(base64.b64decode(key, validate=True)) != 16:
                raise ValueError("Invalid key")
        except (ValueError, UnicodeError, binascii.Error, TimeoutError):
            self.sock.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            return False
        accept = base64.b64encode(hashlib.sha1(
            (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest())
        self.sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                          b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
        return True

    def _send_control(self, opcode: int, payload: bytes) -> None:
        self.sock.sendall(bytes((0x80 | opcode, len(payload))) + payload)

    def _close(self, code: int) -> None:
        self._send_control(8, struct.pack("!H", code))
        # Give the close frame a chance to reach Windows clients even when the
        # rejected frame has unread bytes. Never drain indefinitely.
        self.sock.shutdown(socket.SHUT_WR)
        deadline = time.monotonic() + .2
        remaining = self.MAX_MESSAGE + 14
        self.sock.settimeout(.05)
        while self.running() and remaining > 0 and time.monotonic() < deadline:
            try:
                data = self.sock.recv(min(4096, remaining))
            except socket.timeout:
                continue
            if not data:
                break
            remaining -= len(data)

    def receive(self, on_text: Callable[[str], None]) -> None:
        message = bytearray()
        fragmented = False
        while self.running():
            first, second = self._read(2)
            final, opcode = bool(first & 0x80), first & 0x0f
            length = second & 0x7f
            control = opcode >= 8
            if first & 0x70 or not second & 0x80 or opcode not in (0, 1, 2, 8, 9, 10):
                self._close(1002)
                return
            if control and (not final or length > 125):
                self._close(1002)
                return
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
                if length < 126:
                    self._close(1002)
                    return
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
                if length < 65536 or length >> 63:
                    self._close(1002)
                    return
            if length > self.MAX_MESSAGE or (not control and len(message) + length > self.MAX_MESSAGE):
                self._close(1009)
                return
            mask = self._read(4)
            payload = bytes(value ^ mask[i % 4] for i, value in enumerate(self._read(length)))
            if opcode == 8:
                if len(payload) == 1:
                    self._close(1002)
                    return
                if payload:
                    code = struct.unpack("!H", payload[:2])[0]
                    if code not in (1000, 1001, 1002, 1003, 1007, 1008, 1009, 1010, 1011, 1012, 1013, 1014) and not 3000 <= code <= 4999:
                        self._close(1002)
                        return
                    try:
                        payload[2:].decode("utf-8")
                    except UnicodeError:
                        self._close(1007)
                        return
                self._send_control(8, payload)
                return
            if opcode == 9:
                self._send_control(10, payload)
                continue
            if opcode == 10:
                continue
            if opcode == 2:
                self._close(1003)
                return
            if (opcode == 0 and not fragmented) or (opcode == 1 and fragmented):
                self._close(1002)
                return
            message.extend(payload)
            if final:
                try:
                    text = message.decode("utf-8")
                except UnicodeError:
                    self._close(1007)
                    return
                on_text(text)
                message.clear()
                fragmented = False
            else:
                fragmented = True
