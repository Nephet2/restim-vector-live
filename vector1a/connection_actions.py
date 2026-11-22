"""Serialize UI connection commands without blocking Tk; newest pending wins."""
from __future__ import annotations
import threading
from typing import Callable


class ConnectionActions:
    def __init__(self, client, status: Callable[[str], None], name: str):
        self.client = client
        self.status = status
        self._condition = threading.Condition()
        self._pending = None
        self._closed = False
        self._worker = threading.Thread(target=self._run, name=f'restim-control-{name}', daemon=True)
        self._worker.start()

    def submit(self, action: str, host: str = '', port: int = 0) -> None:
        if action not in ('connect', 'disconnect'):
            raise ValueError('Unknown connection action')
        with self._condition:
            if self._closed:
                return
            self._pending = (action, host, port)
            self._condition.notify()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._pending = None
            self._condition.notify_all()
        # Do not wait for a connection timeout on the Tk thread.

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closed:
                    self._condition.wait()
                if self._closed:
                    return
                action, host, port = self._pending
                self._pending = None
            try:
                if action == 'connect':
                    self.client.connect(host, port)
                else:
                    self.client.disconnect()
            except OSError as exc:
                self.status(f'Connection failed; background retry active: {exc}')
