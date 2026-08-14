# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Offline by default, and the one narrow way that changes.

A training corpus is the most private object in Bunny OS. It is assembled from
the things a person actually asked their computer to do, in their words, about
their files. Everything in this module exists so that no part of the training
path can send it anywhere without somebody having said so, out loud, for that
invocation.

The mechanism is deliberately not "we do not call requests". Libraries in this
space phone home for reasons their authors consider helpful: a tokenizer checks
for a newer revision, a hub client reports an anonymous usage ping, a config
loader silently re-downloads a file it already has. None of that goes through
code written here, so a rule about this package's own source would not bind it.

Instead :meth:`NetworkPolicy.environment` produces the environment that turns
those off at the library level — ``HF_HUB_OFFLINE``, ``TRANSFORMERS_OFFLINE``,
``HF_HUB_DISABLE_TELEMETRY``, ``DISABLE_TELEMETRY``, ``DO_NOT_TRACK`` — and the
backend applies it around everything it does. When a download *is* approved, the
offline flags come off for exactly that operation and go back on afterwards; the
telemetry flags never come off at all.

Uploading has no policy field, no flag and no code path. Not a disabled one:
there is nowhere in this package that pushes a model, and
``tests/model_studio/test_isolation.py`` greps the source to keep it that way.
Publishing an adapter is a separate, deliberate act with a separate tool, and
the reason it is not here is that "the training subsystem can upload, it just
does not by default" is one configuration mistake away from the thing this whole
module is for.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from typing import Any, Iterator, Mapping

from .errors import NetworkRefused

__all__ = [
    "OFFLINE",
    "NetworkPolicy",
    "applied",
    "refuse_upload",
]


@dataclass(frozen=True)
class NetworkPolicy:
    """What this invocation is allowed to reach.

    One field, because there is exactly one legitimate reason for this
    subsystem to use the network: fetching a base model the machine does not
    have. Every other network use — dataset fetching, telemetry, publishing,
    remote training — is absent rather than disabled.
    """

    #: Whether a base model may be downloaded. Granted per invocation, from the
    #: command line, by the person running it.
    allow_model_download: bool = False
    #: Why it was granted, for the provenance record.
    reason: str = ""

    def require_download(self, what: str) -> None:
        """Raise unless this invocation was allowed to fetch ``what``."""
        if not self.allow_model_download:
            raise NetworkRefused(
                f"{what} is not present locally and this run has no network approval. "
                "Nothing is downloaded implicitly. Re-run with --allow-model-download "
                "to approve fetching the base model, or point model.base at a local "
                "directory."
            )

    def environment(self) -> dict[str, str]:
        """The environment variables that hold this policy at the library level."""
        values = {
            # Never lifted, under any policy. Telemetry about a private corpus
            # is the thing with no acceptable version.
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        }
        if not self.allow_model_download:
            values["HF_HUB_OFFLINE"] = "1"
            values["TRANSFORMERS_OFFLINE"] = "1"
        return values

    def to_json(self) -> dict[str, Any]:
        return {
            "allowModelDownload": self.allow_model_download,
            "reason": self.reason,
            "allowUpload": False,
            "environment": self.environment(),
        }


#: The default. Named, so that code and reports can say which policy was in
#: force rather than describing it.
OFFLINE = NetworkPolicy()


@contextmanager
def applied(policy: NetworkPolicy, environment: Mapping[str, str] | None = None) -> Iterator[None]:
    """Apply ``policy`` to the process environment for the duration of a block.

    Restores exactly what was there before, including deleting variables that
    were not set. A training run that approved a download must not leave the
    process able to make another one after it returns.
    """
    target = os.environ if environment is None else environment
    previous: dict[str, str | None] = {}
    values = policy.environment()
    for key, value in values.items():
        previous[key] = target.get(key)  # type: ignore[union-attr]
        target[key] = value  # type: ignore[index]
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                target.pop(key, None)  # type: ignore[union-attr]
            else:
                target[key] = value  # type: ignore[index]


def refuse_upload(destination: str = "") -> None:
    """The function every "can we publish this?" caller finds instead of an uploader.

    It always raises. It exists so that the absence of an upload path is a
    *stated* absence with a place to read about it, rather than a thing someone
    concludes is an oversight and helpfully fixes.
    """
    where = f" to {destination}" if destination else ""
    raise NetworkRefused(
        f"Bunny Model Studio does not publish adapters{where}. Publishing a model trained "
        "on a personal corpus is a separate, deliberate act; it is not a mode of the "
        "training subsystem, because a training subsystem that can publish is one "
        "configuration mistake away from publishing."
    )
