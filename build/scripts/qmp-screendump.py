#!/usr/bin/python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Photograph a running QEMU guest's screen, from outside it.

QMP's ``screendump`` reads the emulated framebuffer in the QEMU process. That
is the property this harness needs: it requires nothing of the guest — no
screenshot portal, no D-Bus, no cooperation from a compositor that may be the
thing that is broken — and it cannot be fooled by a session that believes it
drew something it did not. What it returns is what a monitor plugged into that
machine would show.

Written as its own program rather than a line of shell because QMP is a
handshake, not a request: the socket delivers a greeting, refuses every command
until ``qmp_capabilities`` is negotiated, and answers asynchronously with events
interleaved among the replies. `echo | socat` appears to work and silently
returns the greeting as though it were the result.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import time


class Qmp:
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
        document = {"execute": command}
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


def main() -> int:
    parser = argparse.ArgumentParser(prog="qmp-screendump")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--output")
    parser.add_argument("--powerdown", action="store_true",
                        help="request an ACPI shutdown instead of a screenshot")
    arguments = parser.parse_args()

    try:
        qmp = Qmp(arguments.socket)
    except (OSError, RuntimeError) as exc:
        print(f"qmp-screendump: cannot reach {arguments.socket}: {exc}", file=sys.stderr)
        return 3

    try:
        if arguments.powerdown:
            qmp.execute("system_powerdown")
            return 0
        if not arguments.output:
            print("qmp-screendump: --output is required for a screenshot", file=sys.stderr)
            return 2
        target = Path(arguments.output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        qmp.execute("screendump", filename=str(target))
        # screendump returns as soon as it has queued the write on some
        # versions, so the file is confirmed rather than assumed.
        for _ in range(50):
            if target.is_file() and target.stat().st_size > 0:
                print(f"{target} ({target.stat().st_size} bytes)")
                return 0
            time.sleep(0.2)
        print(f"qmp-screendump: {target} was never written", file=sys.stderr)
        return 4
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"qmp-screendump: {exc}", file=sys.stderr)
        return 5
    finally:
        qmp.close()


if __name__ == "__main__":
    raise SystemExit(main())
