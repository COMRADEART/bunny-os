# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The one real backend: llama-server's LoRA surface, over loopback.

``llama-server`` is started by an operator with ``--lora`` (usually alongside
``--lora-init-without-apply``, so nothing is in effect until something asks).
It then exposes two calls:

* ``GET /lora-adapters`` — the adapters it was started with, each with an
  index, the path it was loaded from, and its current scale;
* ``POST /lora-adapters`` — a list of ``{"id": n, "scale": s}``, setting the
  scales of adapters it *already has*.

That second sentence is the security property this module is built around.
**The API takes an index, not a path.** There is no request this runtime can
make that causes a model server to open a file of the runtime's choosing. The
runtime can turn on something an operator already placed and started the server
with, and that is the whole of its power here. A backend where that was not
true would need reviewing on its own terms, which is why
:meth:`LlamaServerAdapterBackend.describe` reports the endpoint.

Matching is by **resolved path**. The runtime asks the server what it holds,
resolves each reported path, and looks for the validated artifact's adapter
file. A server holding an adapter at a different path is not holding this
adapter, whatever it is called: names are not identity, and the digest that was
checked was checked against a specific file.

Applying is followed by asking again. ``POST`` returning 200 is the server
saying it accepted a request; the scale reported by a subsequent ``GET`` is the
server saying what is actually in effect. Only the second is evidence, and
:attr:`~companion.models.inference.AdapterApplication.verified` carries which
one this is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from ..agents.wire import HttpTarget, WireError, WireSession
from .inference import (
    ADAPTER_NOT_PRELOADED,
    APPLIED,
    APPLY_REFUSED,
    BACKEND_UNAVAILABLE,
    RELEASED,
    VERIFY_FAILED,
    AdapterApplication,
    BackendStatus,
)

__all__ = ["LLAMA_SERVER_BACKEND_ID", "LlamaServerAdapterBackend", "default_target"]

LLAMA_SERVER_BACKEND_ID = "llama-server"

#: The format llama.cpp applies. A PEFT safetensors directory is not it — the
#: conversion is an export-side step and is deliberately not in the image.
_SUPPORTED_FORMATS: tuple[str, ...] = ("gguf",)

#: llama.cpp's own documented default port, not a choice this build made.
_DEFAULT_PORT = 8080

_LORA_PATH = "/lora-adapters"
_PROBE_TIMEOUT = 5.0
_APPLY_TIMEOUT = 30.0

#: A scale below this reads as "not in effect". llama.cpp stores a float; an
#: adapter at 0.0 is loaded and doing nothing, which is what release means.
_ACTIVE_SCALE_FLOOR = 1e-6


def default_target(port: int = _DEFAULT_PORT) -> HttpTarget:
    """Loopback only. :class:`HttpTarget` refuses anything else for a local kind."""
    return HttpTarget(scheme="http", host="127.0.0.1", port=port)


class LlamaServerAdapterBackend:
    """Applies a validated GGUF LoRA on a llama-server the operator started."""

    backend_id = LLAMA_SERVER_BACKEND_ID

    def __init__(
        self,
        target: HttpTarget | None = None,
        *,
        session: WireSession | None = None,
    ) -> None:
        self._target = target if target is not None else default_target()
        self._session = session if session is not None else WireSession()

    # -- reading -------------------------------------------------------- #

    def _adapters(self) -> tuple[list[dict[str, Any]], str]:
        """What the server holds, or an empty list and the reason it did not say."""
        try:
            status, document = self._session.request_json(
                self._target, "GET", _LORA_PATH, timeout=_PROBE_TIMEOUT
            )
        except WireError as error:
            return [], f"{self._target.locator}: {error}"
        if status != 200:
            return [], (
                f"{self._target.locator} answered {status} for {_LORA_PATH}; this "
                "server does not expose the LoRA surface"
            )
        if not isinstance(document, list):
            return [], f"{self._target.locator} returned {type(document).__name__} for {_LORA_PATH}"
        entries = [item for item in document if isinstance(item, dict)]
        return entries, ""

    def _base_model(self) -> tuple[str, int]:
        """The base weights the server loaded, as the server reports them.

        ``GET /v1/models`` names the file and, in its ``meta``, the parameter
        count. Both are the server's own statement about what it is running,
        which is what makes an adapter's compatibility checkable without anyone
        transcribing a path into a configuration file.
        """
        try:
            status, document = self._session.request_json(
                self._target, "GET", "/v1/models", timeout=_PROBE_TIMEOUT
            )
        except WireError:
            return "", 0
        if status != 200 or not isinstance(document, dict):
            return "", 0
        entries = document.get("data")
        if not isinstance(entries, list) or not entries:
            return "", 0
        first = entries[0] if isinstance(entries[0], dict) else {}
        path = str(first.get("id", ""))
        meta = first.get("meta")
        parameters = 0
        if isinstance(meta, dict):
            value = meta.get("n_params")
            if isinstance(value, int) and not isinstance(value, bool):
                parameters = value
        return path, parameters

    def describe(self) -> BackendStatus:
        entries, refusal = self._adapters()
        if refusal:
            return BackendStatus(
                backend_id=self.backend_id,
                available=False,
                detail=refusal,
                supported_formats=(),
                endpoint=self._target.locator,
            )
        loaded = ", ".join(str(item.get("path", "")) for item in entries) or "none"
        base_path, parameters = self._base_model()
        return BackendStatus(
            backend_id=self.backend_id,
            available=True,
            detail=f"{len(entries)} adapter(s) preloaded: {loaded}",
            supported_formats=_SUPPORTED_FORMATS,
            endpoint=self._target.locator,
            implementation="llama.cpp llama-server",
            base_model_path=base_path,
            base_model_parameters=parameters,
        )

    # -- matching ------------------------------------------------------- #

    @staticmethod
    def _index_for(entries: Sequence[dict[str, Any]], adapter_path: Path) -> int | None:
        """The server's index for exactly this file, matched by resolved path."""
        try:
            wanted = adapter_path.resolve()
        except OSError:  # pragma: no cover - resolve on a live file
            wanted = adapter_path
        for entry in entries:
            raw = str(entry.get("path", ""))
            if not raw:
                continue
            try:
                if Path(raw).resolve() == wanted:
                    identifier = entry.get("id")
                    return int(identifier) if isinstance(identifier, int) else None
            except OSError:  # pragma: no cover - a path the server named and we cannot stat
                continue
        return None

    def _scale_of(self, index: int) -> tuple[float | None, str]:
        entries, refusal = self._adapters()
        if refusal:
            return None, refusal
        for entry in entries:
            if entry.get("id") == index:
                value = entry.get("scale")
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    return float(value), ""
                return None, f"the server reported scale {value!r} for adapter {index}"
        return None, f"the server no longer holds adapter {index}"

    # -- writing -------------------------------------------------------- #

    def _set_scale(self, index: int, scale: float) -> str:
        try:
            status, _ = self._session.request_json(
                self._target, "POST", _LORA_PATH,
                body=[{"id": index, "scale": scale}],
                timeout=_APPLY_TIMEOUT,
            )
        except WireError as error:
            return f"{self._target.locator}: {error}"
        if status != 200:
            return f"{self._target.locator} answered {status} setting adapter {index} to {scale}"
        return ""

    def apply(self, model_id: str, adapter_path: Path, *, scale: float = 1.0) -> AdapterApplication:
        """Apply the adapter the server already holds at this path, then confirm."""
        entries, refusal = self._adapters()
        if refusal:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=BACKEND_UNAVAILABLE, detail=refusal, adapter_path=str(adapter_path),
            )

        index = self._index_for(entries, adapter_path)
        if index is None:
            held = ", ".join(str(item.get("path", "")) for item in entries) or "nothing"
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=ADAPTER_NOT_PRELOADED,
                detail=(
                    f"the server at {self._target.locator} was not started with this "
                    f"adapter. It holds: {held}. This runtime cannot ask a model server "
                    "to open a file — an operator starts the server with --lora, and "
                    "this turns it on."
                ),
                adapter_path=str(adapter_path),
            )

        problem = self._set_scale(index, scale)
        if problem:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=APPLY_REFUSED, detail=problem, adapter_path=str(adapter_path),
            )

        observed, why = self._scale_of(index)
        if observed is None:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=True, verified=False,
                code=VERIFY_FAILED,
                detail=f"the server accepted the request but its state could not be read back: {why}",
                adapter_path=str(adapter_path),
            )
        if abs(observed - scale) > 1e-6:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=True, verified=False,
                code=VERIFY_FAILED,
                detail=(
                    f"asked for scale {scale} and the server reports {observed}; a 200 is "
                    "the server accepting a request, not the adapter being in effect"
                ),
                scale=observed, adapter_path=str(adapter_path),
            )
        return AdapterApplication(
            backend_id=self.backend_id, model_id=model_id, applied=True, verified=True,
            code=APPLIED,
            detail=f"adapter {index} at {self._target.locator} is in effect at scale {observed}",
            scale=observed, adapter_path=str(adapter_path),
        )

    def release(self, model_id: str, adapter_path: Path | None = None) -> AdapterApplication:
        """Set every adapter this backend holds to zero, and confirm.

        Releases all of them rather than one: this build activates a single
        model at a time, and "the adapter I think is on is off" is a weaker
        statement than "nothing is on" when the two disagree.
        """
        entries, refusal = self._adapters()
        if refusal:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=BACKEND_UNAVAILABLE, detail=refusal,
            )
        problems: list[str] = []
        for entry in entries:
            identifier = entry.get("id")
            if not isinstance(identifier, int):
                continue
            problem = self._set_scale(identifier, 0.0)
            if problem:
                problems.append(problem)
        if problems:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=APPLY_REFUSED, detail="; ".join(problems),
            )
        after, why = self._adapters()
        if why:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=VERIFY_FAILED, detail=why,
            )
        still_on = [
            str(item.get("path", "")) for item in after
            if isinstance(item.get("scale"), (int, float))
            and float(item["scale"]) > _ACTIVE_SCALE_FLOOR
        ]
        if still_on:
            return AdapterApplication(
                backend_id=self.backend_id, model_id=model_id, applied=False, verified=False,
                code=VERIFY_FAILED,
                detail=f"adapters still in effect after release: {', '.join(still_on)}",
            )
        return AdapterApplication(
            backend_id=self.backend_id, model_id=model_id, applied=False, verified=True,
            code=RELEASED, detail=f"no adapter is in effect at {self._target.locator}",
        )
