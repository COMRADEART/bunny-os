# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The llama-server backend, against a server whose behaviour is known exactly.

A real ``llama-server`` is the right thing to test against and the wrong thing
to require of every test run, so this suite stands up a small HTTP server on
loopback that speaks the two calls the backend uses and can be told to
misbehave. The heavy slice runs the same code against the real one.

The case worth having is ``test_a_server_that_accepts_and_ignores``: a 200 to
``POST`` with no change to the reported scale. That is what a bridge which
trusted status codes would have called success, and it is the reason
:meth:`~companion.models.llama_server.LlamaServerAdapterBackend.apply` asks
again before saying yes.
"""

from __future__ import annotations

import json
from pathlib import Path
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from companion.agents.wire import HttpTarget
from companion.models.inference import (
    ADAPTER_NOT_PRELOADED,
    APPLIED,
    BACKEND_UNAVAILABLE,
    RELEASED,
    VERIFY_FAILED,
)
from companion.models.llama_server import LlamaServerAdapterBackend


class _State:
    """What the fake server holds. Shared with the test that drives it."""

    def __init__(self) -> None:
        self.adapters: list[dict] = []
        self.accept_but_ignore = False
        self.refuse_post = False
        self.posts: list[list] = []


class _Handler(BaseHTTPRequestHandler):
    state: _State

    def log_message(self, *args) -> None:  # noqa: D102 - silence the test server
        return

    def _send(self, status: int, document) -> None:
        payload = json.dumps(document).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        if self.path == "/lora-adapters":
            self._send(200, self.state.adapters)
        else:
            self._send(404, {"error": "no"})

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8")) if length else []
        self.state.posts.append(body)
        if self.state.refuse_post:
            self._send(500, {"error": "refused"})
            return
        if not self.state.accept_but_ignore:
            for change in body:
                for entry in self.state.adapters:
                    if entry["id"] == change.get("id"):
                        entry["scale"] = float(change.get("scale", 0.0))
        self._send(200, {"ok": True})


class LlamaBackend(unittest.TestCase):
    def setUp(self) -> None:
        self.state = _State()
        handler = type("Handler", (_Handler,), {"state": self.state})
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.target = HttpTarget(scheme="http", host="127.0.0.1", port=self.server.server_port)
        self.backend = LlamaServerAdapterBackend(self.target)
        self.adapter = Path(__file__).resolve()  # any real, resolvable path

    def _preload(self, scale: float = 0.0) -> None:
        self.state.adapters = [{"id": 0, "path": str(self.adapter), "scale": scale}]

    def test_it_describes_a_server_that_holds_an_adapter(self) -> None:
        self._preload()
        status = self.backend.describe()
        self.assertTrue(status.available)
        self.assertEqual(status.supported_formats, ("gguf",))
        self.assertIn("llama", status.implementation.lower())

    def test_a_server_that_is_not_there_is_a_result_not_a_raise(self) -> None:
        backend = LlamaServerAdapterBackend(
            HttpTarget(scheme="http", host="127.0.0.1", port=9)
        )
        status = backend.describe()
        self.assertFalse(status.available)
        self.assertTrue(status.detail)
        outcome = backend.apply("demo", self.adapter)
        self.assertEqual(outcome.code, BACKEND_UNAVAILABLE)
        self.assertFalse(outcome.active)

    def test_applying_sets_the_scale_and_confirms_it(self) -> None:
        self._preload()
        outcome = self.backend.apply("demo", self.adapter)
        self.assertTrue(outcome.active)
        self.assertEqual(outcome.code, APPLIED)
        self.assertEqual(outcome.scale, 1.0)
        self.assertEqual(self.state.posts, [[{"id": 0, "scale": 1.0}]])

    def test_a_server_that_accepts_and_ignores_is_not_success(self) -> None:
        """200 is the server accepting a request, not the adapter being on."""
        self._preload()
        self.state.accept_but_ignore = True
        outcome = self.backend.apply("demo", self.adapter)
        self.assertFalse(outcome.active)
        self.assertTrue(outcome.applied, "the request was accepted")
        self.assertFalse(outcome.verified, "and it did not take")
        self.assertEqual(outcome.code, VERIFY_FAILED)

    def test_an_adapter_the_server_does_not_hold(self) -> None:
        self._preload()
        outcome = self.backend.apply("demo", self.adapter.parent / "not-loaded.gguf")
        self.assertFalse(outcome.active)
        self.assertEqual(outcome.code, ADAPTER_NOT_PRELOADED)
        self.assertIn("--lora", outcome.detail)
        self.assertEqual(self.state.posts, [], "nothing was asked of the server")

    def test_the_runtime_cannot_make_the_server_open_a_file(self) -> None:
        """The structural property: the API takes an index, not a path.

        Every POST this backend sends names an id the server already reported.
        There is no request it can construct that points the server at a new
        file, which is why an artifact cannot smuggle a path into a model server.
        """
        self._preload()
        self.backend.apply("demo", self.adapter)
        self.backend.release("demo")
        for body in self.state.posts:
            for change in body:
                self.assertEqual(set(change), {"id", "scale"})
                self.assertIn(change["id"], {entry["id"] for entry in self.state.adapters})

    def test_releasing_sets_everything_to_zero_and_confirms(self) -> None:
        self._preload(scale=1.0)
        outcome = self.backend.release("demo")
        self.assertTrue(outcome.verified)
        self.assertFalse(outcome.applied)
        self.assertEqual(outcome.code, RELEASED)
        self.assertEqual(self.state.adapters[0]["scale"], 0.0)

    def test_a_release_the_server_ignores_is_reported(self) -> None:
        self._preload(scale=1.0)
        self.state.accept_but_ignore = True
        outcome = self.backend.release("demo")
        self.assertFalse(outcome.verified)
        self.assertEqual(outcome.code, VERIFY_FAILED)
        self.assertIn("still in effect", outcome.detail)

    def test_a_refused_post_is_reported(self) -> None:
        self._preload()
        self.state.refuse_post = True
        outcome = self.backend.apply("demo", self.adapter)
        self.assertFalse(outcome.active)
        self.assertIn(outcome.code, {"APPLY_REFUSED", VERIFY_FAILED})

    def test_matching_is_by_resolved_path_not_by_name(self) -> None:
        self.state.adapters = [
            {"id": 0, "path": str(self.adapter.parent / "other.gguf"), "scale": 0.0},
            {"id": 1, "path": str(self.adapter), "scale": 0.0},
        ]
        outcome = self.backend.apply("demo", self.adapter)
        self.assertTrue(outcome.active)
        self.assertEqual(self.state.posts[0][0]["id"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
