# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""A QMP client, shared by the screenshot and input harnesses.

Written as its own module rather than a line of shell because QMP is a
handshake, not a request: the socket delivers a greeting, refuses every command
until ``qmp_capabilities`` is negotiated, and answers asynchronously with events
interleaved among the replies. ``echo | socat`` appears to work and silently
returns the greeting as though it were the result.

Two programs need it now — ``qmp-screendump.py`` photographs the framebuffer and
``qmp-input.py`` injects pointer and key events — and a second copy of a
protocol handshake is a second thing to get subtly wrong.
"""

from __future__ import annotations

import json
import socket
import time


class Qmp:
    """One QMP connection, with capabilities already negotiated."""

    def __init__(self, path: str, timeout: float = 30.0) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.settimeout(timeout)
        self._socket.connect(path)
        self._buffer = b""
        greeting = self._read()
        if "QMP" not in greeting:
            raise RuntimeError(f"not a QMP socket: {greeting}")
        self.execute("qmp_capabilities")

    def _read(self) -> dict:
        """One JSON document. QMP frames by newline and interleaves events."""
        while b"\n" not in self._buffer:
            chunk = self._socket.recv(65536)
            if not chunk:
                raise RuntimeError("the QMP socket closed")
            self._buffer += chunk
        line, _, self._buffer = self._buffer.partition(b"\n")
        return json.loads(line.decode("utf-8"))

    def execute(self, command: str, **arguments) -> dict:
        document: dict = {"execute": command}
        if arguments:
            document["arguments"] = arguments
        self._socket.sendall((json.dumps(document) + "\n").encode("utf-8"))
        # Skip events until the reply arrives. An event is not an answer, and
        # treating the first document as one is how a screendump gets reported
        # as successful because a VNC client happened to connect.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            message = self._read()
            if "event" in message:
                continue
            if "error" in message:
                raise RuntimeError(f"{command} refused: {message['error']}")
            return message
        raise TimeoutError(f"{command} produced no reply")

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass
