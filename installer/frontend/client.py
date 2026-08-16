# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The unprivileged half: how the setup surface asks the backend for things.

Every request this sends is one the backend re-checks. That is not politeness —
it is the reason the surface can be wrong without a disk being harmed. In
particular the confirmation phrase is sent as typed and compared *there*, against
a phrase re-derived from the disk in the validated plan, so the client cannot
compute a phrase that would pass for a disk it did not select.

## Absent, not broken

`connect` returns ``None`` when there is no backend rather than raising. A
development workstation has no installer socket, and setup must still start there
— §26's argument, generalised: the person should get a window that explains,
never a session with nothing in it. The surface renders a failure screen saying
it cannot write to a disk, which is true and is better than a traceback.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import socket
import time
from typing import Any, Mapping

from installer.backend.server import SOCKET_PATH

__all__ = ["BackendClient", "InstallerRefused", "connect"]

#: Written by the unit that starts the backend, readable only by the live user.
TOKEN_PATH = Path("/run/bunny-installer/session-token")


class InstallerRefused(RuntimeError):
    """The backend refused, and said why. Nothing was written."""

    def __init__(self, message: str, *, kind: str = "invalid") -> None:
        super().__init__(message)
        self.kind = kind


class BackendClient:
    def __init__(self, connection: socket.socket, token: str, *,
                 installation_id: str | None = None) -> None:
        self._connection = connection
        self._token = token
        self._buffer = b""
        self.installation_id = installation_id or "install-" + secrets.token_hex(8)

    def call(self, operation: str, **params: Any) -> Mapping[str, Any]:
        return self._call(operation, params)

    def _call(self, operation: str, params: Mapping[str, Any], *,
              secret_values: Mapping[str, str] | None = None,
              timeout: float | None = 30.0) -> Mapping[str, Any]:
        """One request, one response line.

        ``secret_values`` never rides the JSON protocol — the protocol refuses
        any request whose params carry a secret-named field, by design. The
        values travel as a sealed memfd passed over the socket with
        ``SCM_RIGHTS``, keyed by the ``installer-secret:`` references the plan
        carries, so what the protocol logs and audits contains references and
        never material.
        """
        request = {
            "schemaVersion": 1,
            "requestId": "req-" + secrets.token_hex(8),
            "installationId": self.installation_id,
            "operation": operation,
            "nonce": secrets.token_urlsafe(24),
            # The backend refuses a request more than 60 seconds old, so this is
            # generated per call rather than per session.
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "params": dict(params),
            "sessionToken": self._token,
        }
        data = json.dumps(request).encode("utf-8") + b"\n"
        previous_timeout = self._connection.gettimeout()
        self._connection.settimeout(timeout)
        try:
            if secret_values:
                payload = json.dumps(dict(secret_values)).encode("utf-8")
                descriptor = os.memfd_create("bunny-installer-secrets")
                try:
                    os.write(descriptor, payload)
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    socket.send_fds(self._connection, [data], [descriptor])
                finally:
                    os.close(descriptor)
            else:
                self._connection.sendall(data)
            while b"\n" not in self._buffer:
                chunk = self._connection.recv(65536)
                if not chunk:
                    raise InstallerRefused("the installer backend closed the connection",
                                           kind="unavailable")
                self._buffer += chunk
        finally:
            self._connection.settimeout(previous_timeout)
        line, self._buffer = self._buffer.split(b"\n", 1)
        response = json.loads(line.decode("utf-8"))
        if "error" in response:
            error = response["error"]
            raise InstallerRefused(str(error.get("message", "refused")),
                                   kind=str(error.get("kind", "invalid")))
        return response.get("result", {})

    # -- the operations the surface uses ---------------------------------

    def initialize(self) -> Mapping[str, Any]:
        return self.call("installer.initialize")

    def probe(self) -> Mapping[str, Any]:
        return self.call("installer.probe")

    def validate(self, plan: Mapping[str, Any]) -> Mapping[str, Any]:
        return self.call("installer.plan.validate", plan=dict(plan))

    def start(self, *, acknowledgement: str, second_confirmation: bool,
              recovery_key_confirmed: bool,
              passphrase_secret_ref: str | None = None,
              secret_values: Mapping[str, str] | None = None,
              setup_choices: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        """Ask for the installation to begin, and wait for it to end.

        ``acknowledgement`` is the phrase the person typed, verbatim. This client
        does not check it and could not usefully: the comparison that matters
        happens in `storage.safety.assert_confirmed`, on the other side, against
        the disk in the plan the backend itself validated.

        ``secret_values`` maps the plan's ``installer-secret:`` references to
        their material; see :meth:`_call` for how it travels. The call blocks
        for the whole installation — the backend serves one conversation and
        the write it performs is the response — so it carries no timeout.
        """
        params: dict[str, Any] = {
            "acknowledgement": acknowledgement,
            "secondConfirmation": second_confirmation,
            "recoveryKeyConfirmed": recovery_key_confirmed,
        }
        if passphrase_secret_ref:
            params["passphraseSecretRef"] = passphrase_secret_ref
        if setup_choices is not None:
            # §45: the full non-secret choices record travels with the
            # request, so the backend can place it on the installed system.
            # The protocol's secret-shape refusal applies to it like any
            # other param.
            params["setupChoices"] = dict(setup_choices)
        return self._call("installer.install.start", params,
                          secret_values=secret_values, timeout=None)

    def status(self) -> Mapping[str, Any]:
        return self.call("installer.install.status")

    def close(self) -> None:
        try:
            self._connection.close()
        except OSError:
            pass


def connect(*, path: Path = SOCKET_PATH, token_path: Path = TOKEN_PATH,
            wait_seconds: float = 30.0) -> BackendClient | None:
    """A client, or ``None`` when this machine has no installer backend.

    **Waits, briefly.** The backend is a system service and the surface is a
    session autostart, and there is no ordering between "the socket is listening"
    and "the desktop starts autostarting things" that either side can rely on —
    the unit is `Before=gdm.service`, which orders the *start*, not the readiness.
    A single attempt that lost that race would leave setup permanently convinced
    the machine has no installer, showing "no disks found" on a machine with a
    disk, for the rest of the session. Nothing retries it, because nothing was
    told it failed.

    Thirty seconds, then `None` — which is the honest answer for a workstation
    with no backend at all, and the surface has a screen that says so.
    """
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while True:
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if token:
            try:
                connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                connection.settimeout(120)
                connection.connect(str(path))
                return BackendClient(connection, token)
            except OSError:
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.5)
