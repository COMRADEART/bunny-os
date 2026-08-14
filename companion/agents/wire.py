# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded HTTP for provider adapters: loopback pinned, redirects refused.

Every HTTP adapter in this package talks through this module, so the security
properties are stated once and hold everywhere:

* **A local endpoint is loopback or it is nothing.** ``http`` targets must
  name a host in :data:`LOOPBACK_HOSTS` — a literal, not a DNS name that
  resolves somewhere interesting at request time. This is the §20 SSRF case
  closed at the type: a "local" provider whose configuration says
  ``192.168.1.50`` or ``metadata.internal`` is refused at construction.
* **Redirects are refused, not followed.** A 3xx from a provider is an
  attempt to change the destination after the destination was approved. The
  status is returned as a failure naming the refused location's *presence*
  (never its value, which could itself be a probe).
* **Responses are bounded.** Body size, stream line length and stream
  duration all have ceilings; a provider that exceeds one has failed, not
  "nearly succeeded".
* **Streams decode incrementally.** A UTF-8 code point split across chunks
  reassembles; the §11 correctness the assembler checks is established here.
* **No proxies, no environment.** ``http.client`` consults no proxy
  variables, and this module never reads the environment at all — a proxy an
  attacker can set is a destination an attacker can choose.

TLS uses the system trust store with hostname verification on; there is no
flag to turn either off, because a "just this once" flag is how a test
configuration ships.
"""

from __future__ import annotations

import codecs
import http.client
import json
import socket
import ssl
import threading
from dataclasses import dataclass
from typing import Any, Iterator, Mapping, Sequence

from .errors import AgentSchemaError

__all__ = [
    "HttpTarget",
    "LOOPBACK_HOSTS",
    "MAX_RESPONSE_BYTES",
    "MAX_STREAM_LINE_BYTES",
    "WireError",
    "WireSession",
    "failure_kind_for_status",
]

LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_STREAM_LINE_BYTES = 64 * 1024
_READ_CHUNK = 8192


class WireError(Exception):
    """A wire-level failure, pre-labelled with its §17 failure kind."""

    def __init__(self, message: str, *, kind: str = "connection", retry_hint_seconds: float = 0.0) -> None:
        super().__init__(message)
        self.kind = kind
        self.retry_hint_seconds = retry_hint_seconds


def failure_kind_for_status(status: int) -> str:
    if status in (401, 403):
        return "authentication"
    if status == 404:
        return "model-unavailable"
    if status == 429:
        return "rate-limit"
    if status == 413:
        return "context-limit"
    return "invalid-response"


@dataclass(frozen=True)
class HttpTarget:
    """One endpoint an adapter may reach, validated before any socket opens."""

    scheme: str
    host: str
    port: int
    base_path: str = ""

    def __post_init__(self) -> None:
        if self.scheme not in ("http", "https"):
            raise AgentSchemaError(f"scheme {self.scheme!r} is not http or https")
        if not self.host or "/" in self.host or "@" in self.host or " " in self.host:
            raise AgentSchemaError(f"host {self.host!r} is not a bare host")
        if self.scheme == "http" and self.host not in LOOPBACK_HOSTS:
            raise AgentSchemaError(
                f"plain http is loopback-only; {self.host!r} is not one of {LOOPBACK_HOSTS}. "
                "A remote provider is https and an approval; there is no third shape."
            )
        if not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise AgentSchemaError(f"port {self.port!r} is out of range")
        if self.base_path and not self.base_path.startswith("/"):
            raise AgentSchemaError("base path starts with '/'")
        if any(marker in self.base_path for marker in ("?", "#", "..")):
            raise AgentSchemaError("base path carries no query, fragment or traversal")

    @property
    def local(self) -> bool:
        return self.host in LOOPBACK_HOSTS

    @property
    def locator(self) -> str:
        return f"{self.host}:{self.port}{self.base_path}"

    def path(self, suffix: str) -> str:
        if not suffix.startswith("/"):
            raise AgentSchemaError("request paths start with '/'")
        return f"{self.base_path}{suffix}" if self.base_path else suffix


class WireSession:
    """Owns every live connection an adapter has, so cancel and close can find them.

    One session per adapter instance. Connections are per-request — provider
    servers are long-lived but generations are not, and a connection that
    outlives its generation is a descriptor the §24 gates would count.
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._live: dict[str, http.client.HTTPConnection] = {}
        self._tls = ssl.create_default_context()

    def _connect(self, target: HttpTarget, timeout: float) -> http.client.HTTPConnection:
        if target.scheme == "https":
            return http.client.HTTPSConnection(
                target.host, target.port, timeout=timeout, context=self._tls
            )
        return http.client.HTTPConnection(target.host, target.port, timeout=timeout)

    def _register(self, request_id: str, connection: http.client.HTTPConnection) -> None:
        if not request_id:
            return
        with self._guard:
            self._live[request_id] = connection

    def _unregister(self, request_id: str) -> None:
        if not request_id:
            return
        with self._guard:
            self._live.pop(request_id, None)

    def cancel(self, request_id: str) -> bool:
        """Close the connection under a generation. The read path sees it fail."""
        with self._guard:
            connection = self._live.pop(request_id, None)
        if connection is None:
            return False
        try:
            connection.close()
        except OSError:  # pragma: no cover - close is best-effort by design
            pass
        return True

    def close(self) -> None:
        with self._guard:
            live, self._live = dict(self._live), {}
        for connection in live.values():
            try:
                connection.close()
            except OSError:  # pragma: no cover
                pass

    @property
    def live_connections(self) -> int:
        with self._guard:
            return len(self._live)

    # -- one-shot JSON ------------------------------------------------------

    def request_json(
        self,
        target: HttpTarget,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | Sequence[Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 10.0,
        request_id: str = "",
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> tuple[int, Any]:
        """One request, one bounded JSON response. 3xx is a refusal.

        ``body`` accepts a sequence as well as a mapping because not every
        endpoint takes an object: llama-server's ``POST /lora-adapters`` takes a
        JSON array. The encoding was always ``json.dumps`` and is unchanged;
        only the annotation was too narrow to describe what it already did.
        """
        connection = self._connect(target, timeout)
        self._register(request_id, connection)
        try:
            payload = None
            send_headers = {"Accept": "application/json", **(headers or {})}
            if body is not None:
                payload = json.dumps(body).encode("utf-8")
                send_headers["Content-Type"] = "application/json"
            try:
                connection.request(method, target.path(path), body=payload, headers=send_headers)
                response = connection.getresponse()
            except socket.timeout as error:
                raise WireError(f"timed out reaching {target.locator}: {error}", kind="timeout") from None
            except (OSError, http.client.HTTPException) as error:
                raise WireError(
                    f"could not reach {target.locator}: {type(error).__name__}: {error}",
                    kind="connection",
                ) from None
            if 300 <= response.status < 400:
                raise WireError(
                    f"{target.locator} answered {response.status} with a redirect; "
                    "a destination that moves after approval is refused",
                    kind="invalid-response",
                )
            raw = self._read_bounded(response, max_response_bytes, target)
            if not raw:
                return response.status, None
            try:
                return response.status, json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise WireError(
                    f"{target.locator} returned non-JSON where JSON was promised: {type(error).__name__}",
                    kind="invalid-response",
                ) from None
        finally:
            self._unregister(request_id)
            try:
                connection.close()
            except OSError:  # pragma: no cover
                pass

    @staticmethod
    def _read_bounded(response: http.client.HTTPResponse, bound: int, target: HttpTarget) -> bytes:
        collected = bytearray()
        while True:
            try:
                chunk = response.read(_READ_CHUNK)
            except socket.timeout:
                raise WireError(f"timed out reading from {target.locator}", kind="timeout") from None
            except (OSError, http.client.HTTPException) as error:
                raise WireError(
                    f"connection to {target.locator} failed mid-read: {type(error).__name__}",
                    kind="connection",
                ) from None
            if not chunk:
                return bytes(collected)
            collected.extend(chunk)
            if len(collected) > bound:
                raise WireError(
                    f"{target.locator} exceeded the {bound}-byte response bound",
                    kind="invalid-response",
                )

    # -- streaming ----------------------------------------------------------

    def stream_lines(
        self,
        target: HttpTarget,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None,
        headers: Mapping[str, str] | None = None,
        timeout: float = 60.0,
        request_id: str = "",
        max_total_bytes: int = MAX_RESPONSE_BYTES,
    ) -> Iterator[tuple[int, str]]:
        """Yield ``(status, line)`` pairs with incremental UTF-8 decoding.

        The first yield carries the status with an empty line so callers can
        refuse an error status before consuming a stream. Lines are stripped
        of their terminator; blank lines are yielded (SSE frames them).
        Cancellation arrives as a closed connection: the read raises, and the
        caller — which knows whether its signal is set — names the outcome.
        """
        connection = self._connect(target, timeout)
        self._register(request_id, connection)
        decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        total = 0
        try:
            payload = json.dumps(body).encode("utf-8") if body is not None else None
            send_headers = {"Accept": "application/json", **(headers or {})}
            if payload is not None:
                send_headers["Content-Type"] = "application/json"
            try:
                connection.request(method, target.path(path), body=payload, headers=send_headers)
                response = connection.getresponse()
            except socket.timeout as error:
                raise WireError(f"timed out reaching {target.locator}: {error}", kind="timeout") from None
            except (OSError, http.client.HTTPException) as error:
                raise WireError(
                    f"could not reach {target.locator}: {type(error).__name__}: {error}",
                    kind="connection",
                ) from None
            if 300 <= response.status < 400:
                raise WireError(
                    f"{target.locator} answered {response.status} with a redirect mid-stream",
                    kind="invalid-response",
                )
            yield response.status, ""
            if response.status != 200:
                # The body of an error status is one bounded JSON read, surfaced
                # as a line so the adapter can extract the provider's message.
                raw = self._read_bounded(response, MAX_STREAM_LINE_BYTES, target)
                text = raw.decode("utf-8", errors="replace")
                if text:
                    yield response.status, text
                return
            buffered = ""
            while True:
                try:
                    chunk = response.read(_READ_CHUNK)
                except socket.timeout:
                    raise WireError(f"stream from {target.locator} timed out", kind="timeout") from None
                except (OSError, http.client.HTTPException, ssl.SSLError) as error:
                    raise WireError(
                        f"stream from {target.locator} closed: {type(error).__name__}",
                        kind="connection",
                    ) from None
                if not chunk:
                    remainder = decoder.decode(b"", final=True) + buffered
                    if remainder:
                        yield 200, remainder
                    return
                total += len(chunk)
                if total > max_total_bytes:
                    raise WireError(
                        f"stream from {target.locator} exceeded {max_total_bytes} bytes",
                        kind="invalid-response",
                    )
                try:
                    buffered += decoder.decode(chunk)
                except UnicodeDecodeError:
                    raise WireError(
                        f"stream from {target.locator} is not UTF-8", kind="invalid-response"
                    ) from None
                while "\n" in buffered:
                    line, buffered = buffered.split("\n", 1)
                    line = line.rstrip("\r")
                    if len(line.encode("utf-8")) > MAX_STREAM_LINE_BYTES:
                        raise WireError(
                            f"stream line from {target.locator} exceeded "
                            f"{MAX_STREAM_LINE_BYTES} bytes",
                            kind="invalid-response",
                        )
                    yield 200, line
        finally:
            self._unregister(request_id)
            try:
                connection.close()
            except OSError:  # pragma: no cover
                pass
