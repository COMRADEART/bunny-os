# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""What every adapter returns, and what "this adapter works here" means.

An adapter answers two questions and they are kept apart on purpose.

:meth:`Adapter.probe` answers **can this machine do this at all**, and it is
allowed to be wrong in only one direction: it may report unavailable when the
thing would in fact have worked, and it may never report available when it would
not. §16 says availability is not inferred from installed binaries, and this is
where that rule is enforced — a probe looks for the *service answering*, not for
the file on disk.

:meth:`Adapter.perform` answers **did it happen**, and returns an
:class:`AdapterOutcome` that separates the acknowledgement from the observation.
An adapter that returned a boolean would force its caller to invent the
difference, and inventing it is how ``confirmed`` gets reported for a request
that was merely accepted.

``AdapterOutcome`` deliberately has no field for a backend object, a file
descriptor, a socket, a portal handle or a D-Bus proxy. §15 forbids those
reaching a tool output, and the cheapest way to keep that true is for them to
have nowhere to go: an adapter that wants to keep a handle keeps it privately,
and what leaves is a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from ..errors import DesktopUnavailable
from ..result import Observation

__all__ = [
    "Adapter",
    "AdapterOutcome",
    "Availability",
    "acknowledged",
    "failure",
    "unsupported_outcome",
    "verified",
]


@dataclass(frozen=True)
class Availability:
    """Whether one adapter can work here, and the sentence that says why not.

    ``mechanism`` records *how* it would work — which transport, which service.
    It is reported rather than hidden because "the notification went out through
    ``notify-send`` because the session bus had no daemon" is a fact a
    measurement and a bug report both need, and §17 draws the line at *hidden*
    fallback rather than at fallback.
    """

    available: bool
    mechanism: str = ""
    #: The service or interface that answered, or the one that did not.
    service: str = ""
    detail: str = ""

    def require(self, action_id: str) -> None:
        if not self.available:
            raise DesktopUnavailable(
                f"{action_id} cannot be performed here: {self.detail or 'the backend is unavailable'}"
            )

    def to_json(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "mechanism": self.mechanism,
            "service": self.service,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class AdapterOutcome:
    """What one backend call did, and what was observed about it.

    ``ok`` is the backend's own answer. ``observation`` is ours. They are
    separate because a backend returning success is an acknowledgement and
    nothing more, and the only thing that can turn an acknowledgement into a
    confirmation is a second look — which is what
    :attr:`Observation.verifies` records.
    """

    ok: bool
    observation: Observation
    #: What the adapter used, for the record and the measurement.
    mechanism: str = ""
    detail: str = ""
    #: Values the adapter read that the broker needs — a previous volume, a
    #: previous do-not-disturb state. Never user content.
    state: Mapping[str, Any] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "observation": self.observation.to_json(),
            "mechanism": self.mechanism,
            "detail": self.detail,
            "state": dict(self.state),
            "durationSeconds": round(self.duration_seconds, 6),
        }


def acknowledged(mechanism: str, detail: str = "", **state: Any) -> AdapterOutcome:
    """The backend took the request. Proves acceptance; proves nothing else."""
    return AdapterOutcome(
        ok=True,
        observation=Observation("acknowledgement", detail=detail or "the backend accepted the request"),
        mechanism=mechanism,
        detail=detail,
        state=state,
    )


def verified(
    mechanism: str,
    *,
    kind: str = "read-back",
    detail: str,
    matched: bool,
    observed_value: Any = None,
    **state: Any,
) -> AdapterOutcome:
    """Something was read back and compared. The only route to ``confirmed``."""
    return AdapterOutcome(
        ok=matched,
        observation=Observation(kind, detail=detail, matched=matched, observed_value=observed_value),
        mechanism=mechanism,
        detail=detail,
        state=state,
    )


def failure(mechanism: str, detail: str) -> AdapterOutcome:
    return AdapterOutcome(
        ok=False,
        observation=Observation("error", detail=detail),
        mechanism=mechanism,
        detail=detail,
    )


def unsupported_outcome(mechanism: str, detail: str) -> AdapterOutcome:
    """The environment exists and will not do this. Not a failure; a fact."""
    return AdapterOutcome(
        ok=False,
        observation=Observation("none", detail=detail),
        mechanism=mechanism,
        detail=detail,
        state={"unsupported": True},
    )


class Adapter(Protocol):
    """The whole adapter contract. Two methods, and no generic third."""

    #: The §7 name, matched against the descriptor table.
    adapter_id: str

    def probe(self) -> Availability:
        """Whether this machine can perform this adapter's operation."""


def _check_backends() -> None:
    """Descriptor backends and shipped adapters must name the same things."""
    from .. import catalogue
    from . import ADAPTER_IDS

    # A `backend` on a descriptor is the kebab-case form of an adapter name;
    # both lists are short and the mapping is checked rather than assumed so a
    # rename in one place cannot quietly orphan the other.
    expected = {
        "notification": "NotificationAdapter",
        "application-launch": "ApplicationLaunchAdapter",
        "application-present": "ApplicationPresentAdapter",
        "settings": "SettingsAdapter",
        "audio-control": "AudioControlAdapter",
        "clipboard": "ClipboardAdapter",
        "uri-open": "UriOpenAdapter",
        "file-reveal": "FileRevealAdapter",
    }
    missing = sorted(set(catalogue.BACKENDS) - set(expected))
    if missing:
        raise RuntimeError(f"descriptor backends {missing} have no adapter mapping")
    unknown = sorted(set(expected.values()) - set(ADAPTER_IDS))
    if unknown:
        raise RuntimeError(f"adapters {unknown} are mapped and not declared in ADAPTER_IDS")


_check_backends()
