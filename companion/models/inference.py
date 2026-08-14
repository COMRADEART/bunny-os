# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What "load an adapter" means in a runtime that loads no weights.

Bunny's inference is out-of-process. Every provider in :mod:`companion.agents`
is a client — loopback HTTP to a model server, or one allowlisted subprocess —
and the image packages no inference runtime at all. So the obvious reading of
"adapter loading abstraction", a class that opens safetensors and merges
tensors, would mean putting a tensor library and a model loader inside the
Companion's process. That is a large new dependency, a large new attack
surface, and a duplicate of work the model server already does properly.

What this package does instead is narrower and, at the trust boundary, stronger:

``describe()``
    what this backend is and which adapter formats it declares it can apply.
    A backend that cannot apply anything says so, and the registry refuses to
    activate artifacts nothing can use rather than failing at first inference.
``apply(artifact)``
    ask the backend to apply an already-validated adapter, then **ask again**
    and confirm it took. An application that cannot be confirmed is not an
    application; :attr:`AdapterApplication.verified` is a separate field from
    :attr:`~AdapterApplication.applied` for exactly that reason.
``release()``
    unapply, and confirm that too.

The structural property worth noticing is in what ``apply`` *cannot* do. The
llama-server backend can only address adapters the server was already started
with; its API takes an index into a preloaded list, not a path. So there is no
call in this package that causes a model server to open a file of the runtime's
choosing — the runtime can turn on something an operator already put there, and
that is all. A backend where that is not true would need to be reviewed on its
own terms, which is why :meth:`AdapterCapableBackend.describe` reports the
endpoint it speaks to.

Nothing here decides whether an adapter *should* be applied. That is
:mod:`companion.models.validation`, and the registry runs it first.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ADAPTER_NOT_PRELOADED",
    "APPLIED",
    "APPLY_REFUSED",
    "AdapterApplication",
    "AdapterCapableBackend",
    "BACKEND_UNAVAILABLE",
    "BackendStatus",
    "FORMAT_UNSUPPORTED",
    "NullAdapterBackend",
    "RELEASED",
    "VERIFY_FAILED",
]

APPLIED = "APPLIED"
RELEASED = "RELEASED"
BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
FORMAT_UNSUPPORTED = "FORMAT_UNSUPPORTED"
ADAPTER_NOT_PRELOADED = "ADAPTER_NOT_PRELOADED"
APPLY_REFUSED = "APPLY_REFUSED"
VERIFY_FAILED = "VERIFY_FAILED"


@dataclass(frozen=True)
class BackendStatus:
    """Whether a backend is here, and what it says it can do."""

    backend_id: str
    available: bool
    detail: str = ""
    supported_formats: tuple[str, ...] = ()
    endpoint: str = ""
    #: What the backend reports it is, when it will say. Never inferred.
    implementation: str = ""
    #: The base weights the backend has loaded, as it reports them. This is how
    #: the runtime learns what an adapter would be applied *to* without anyone
    #: having to type it: the backend knows, and asking it is better evidence
    #: than a configuration file that could be out of step with the server.
    base_model_path: str = ""
    #: The parameter count the backend reports for those weights, when it does.
    base_model_parameters: int = 0

    def to_json(self) -> dict[str, Any]:
        return {
            "backendId": self.backend_id,
            "available": self.available,
            "detail": self.detail,
            "supportedFormats": list(self.supported_formats),
            "endpoint": self.endpoint,
            "implementation": self.implementation,
            "baseModelPath": self.base_model_path,
            "baseModelParameters": self.base_model_parameters,
        }


@dataclass(frozen=True)
class AdapterApplication:
    """The outcome of asking a backend to apply or release an adapter.

    ``applied`` is what the backend was asked to do and did not refuse.
    ``verified`` is whether asking it afterwards confirmed the state. Only both
    together mean a model is active: a backend that accepts a request and then
    reports the adapter at scale zero has not applied anything, and a bridge
    that reported success on the strength of a 200 would have shipped a model
    the user believes is running.
    """

    backend_id: str
    model_id: str
    applied: bool
    verified: bool
    code: str
    detail: str
    scale: float = 0.0
    adapter_path: str = ""

    @property
    def active(self) -> bool:
        return self.applied and self.verified

    def to_json(self) -> dict[str, Any]:
        return {
            "backendId": self.backend_id,
            "modelId": self.model_id,
            "applied": self.applied,
            "verified": self.verified,
            "active": self.active,
            "code": self.code,
            "detail": self.detail,
            "scale": self.scale,
            "adapterPath": self.adapter_path,
        }


@runtime_checkable
class AdapterCapableBackend(Protocol):
    """The whole surface the registry needs from an inference backend."""

    @property
    def backend_id(self) -> str: ...

    def describe(self) -> BackendStatus:
        """What this backend is and can do. Absence is a result, never a raise."""
        ...

    def apply(self, model_id: str, adapter_path: Path, *, scale: float = 1.0) -> AdapterApplication:
        """Apply a validated adapter, then confirm it took."""
        ...

    def release(self, model_id: str) -> AdapterApplication:
        """Unapply, and confirm that too."""
        ...


class NullAdapterBackend:
    """The honest default: a backend that applies nothing and says so.

    This is what the registry gets on a machine with no model server, and it is
    a real object rather than ``None`` so that every caller takes the same path
    and the reason ends up in the same field. A registry holding this backend
    lists artifacts, validates them, and refuses to activate any of them —
    which is the correct behaviour for a Bunny image as it ships, because no
    image ships an inference runtime.
    """

    backend_id = "none"

    def __init__(self, detail: str = "no inference backend is configured on this machine") -> None:
        self._detail = detail

    def describe(self) -> BackendStatus:
        return BackendStatus(
            backend_id=self.backend_id,
            available=False,
            detail=self._detail,
            supported_formats=(),
        )

    def apply(self, model_id: str, adapter_path: Path, *, scale: float = 1.0) -> AdapterApplication:
        return AdapterApplication(
            backend_id=self.backend_id,
            model_id=model_id,
            applied=False,
            verified=False,
            code=BACKEND_UNAVAILABLE,
            detail=self._detail,
            adapter_path=str(adapter_path),
        )

    def release(self, model_id: str) -> AdapterApplication:
        return AdapterApplication(
            backend_id=self.backend_id,
            model_id=model_id,
            applied=False,
            verified=True,
            code=RELEASED,
            detail="nothing was applied, so nothing needed releasing",
        )
