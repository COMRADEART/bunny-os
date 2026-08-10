# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bunny Safe Mode: the smallest companion that is still a companion.

§19 lists what safe mode turns off — 3D, microphone, remote AI, desktop actions,
animation — and one thing it keeps: a local text interface with diagnostic
access. The list is short enough to state as data, and it is stated as data here
so that "what does safe mode do" has one answer that the window, the CLI and the
tests all read.

The design question is what safe mode is *for*, and the answer decides
everything else: **it exists to recover from a broken character package or
renderer**. A user whose 3D package started crashing the window has no way to
reach the setting that would change it, because reaching the setting needs the
window. Safe mode is the way in.

Two consequences:

**It is one-shot by default.** A safe mode that persisted would be a machine
that quietly stayed degraded after the problem was fixed. So the normal request
is "next launch only": the launcher consumes the flag, starts reduced, and the
launch after that is normal again. A user who wants it to stick says so, and
:attr:`SafeModeState.sticky` records that they did.

**It is set from outside the window.** The flag is a file. The recovery window
writes it, the CLI writes it, and — the case that matters — a launcher that has
just watched the window die three times writes it, so the fourth start is one
the user can actually use. That is §34's "reboot must not enter a permanent
crash loop", implemented as a file rather than as a hope.

Nothing here disables anything by itself. It records an intent; the launcher and
the runtime read :func:`safe_mode_environment` and act. A module that reached
into the renderer to switch it off would be a second place presentation is
decided.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from . import companion_state_root

__all__ = [
    "SAFE_MODE_FILE_NAME",
    "SAFE_MODE_RESTRICTIONS",
    "SafeModeState",
    "clear_safe_mode",
    "consume_safe_mode",
    "read_safe_mode",
    "request_safe_mode",
    "safe_mode_environment",
]

SAFE_MODE_FILE_NAME = "safe-mode.json"

_SCHEMA_VERSION = 1

#: What safe mode turns off, and the environment variable that turns it off.
#: The tuple is the specification: a reader who wants to know what safe mode
#: does reads this and is finished.
SAFE_MODE_RESTRICTIONS: tuple[tuple[str, str, str], ...] = (
    ("three-d", "BUNNY_COMPANION_DISABLE_3D", "3D rendering is off; the character is drawn in 2D or as text"),
    ("microphone", "BUNNY_COMPANION_DISABLE_MICROPHONE", "the microphone is not opened, and push-to-talk is unavailable"),
    ("remote-ai", "BUNNY_COMPANION_DISABLE_REMOTE", "no remote provider is contacted, whatever is configured"),
    ("desktop-actions", "BUNNY_COMPANION_DISABLE_DESKTOP_ACTIONS", "Bunny cannot act on the desktop"),
    ("animation", "BUNNY_COMPANION_MINIMAL_ANIMATION", "animation is reduced to the minimum"),
    ("voice", "BUNNY_COMPANION_DISABLE_VOICE", "spoken output is off; captions remain"),
)

#: What safe mode keeps. Stated because a list of removals reads as "nothing
#: works", and the point of safe mode is that something does.
SAFE_MODE_RETAINED: tuple[str, ...] = (
    "typed input and typed replies",
    "the task history that already exists",
    "settings, including character selection",
    "diagnostics and diagnostics export",
    "a local AI provider, when one is explicitly selected",
)

#: The maximum number of consecutive failed launches before the launcher turns
#: safe mode on by itself. Three, because two is a coincidence and four is a
#: user who has already given up.
FAILURE_THRESHOLD = 3


@dataclass(frozen=True)
class SafeModeState:
    """Whether the next companion launch is reduced, and why."""

    enabled: bool = False
    #: ``True`` when the user asked for it to persist. A one-shot request is
    #: consumed by the next launch; a sticky one is not.
    sticky: bool = False
    reason: str = ""
    #: Who asked: ``user``, ``recovery``, ``launcher`` or ``cli``. Carried
    #: because "safe mode turned itself on" and "I turned safe mode on" are
    #: different situations and the diagnostics page says which.
    origin: str = ""
    #: Consecutive failed launches the launcher has observed. Reset on a launch
    #: that reaches a visible window.
    consecutive_failures: int = 0

    @property
    def automatic(self) -> bool:
        return self.origin == "launcher"

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": _SCHEMA_VERSION,
            "enabled": self.enabled,
            "sticky": self.sticky,
            "reason": self.reason,
            "origin": self.origin,
            "consecutiveFailures": self.consecutive_failures,
            "automatic": self.automatic,
            "restrictions": [
                {"id": identifier, "variable": variable, "effect": effect}
                for identifier, variable, effect in SAFE_MODE_RESTRICTIONS
            ],
            "retained": list(SAFE_MODE_RETAINED),
        }

    @classmethod
    def from_json(cls, value: Mapping[str, Any]) -> "SafeModeState":
        def flag(key: str) -> bool:
            return bool(value.get(key)) is True

        reason = value.get("reason", "")
        origin = value.get("origin", "")
        failures = value.get("consecutiveFailures", 0)
        return cls(
            enabled=flag("enabled"),
            sticky=flag("sticky"),
            reason=reason if isinstance(reason, str) and len(reason) <= 512 else "",
            origin=origin if origin in ("user", "recovery", "launcher", "cli") else "",
            consecutive_failures=failures if isinstance(failures, int) and 0 <= failures <= 1000 else 0,
        )

    def lines(self) -> tuple[str, ...]:
        """Safe mode explained to somebody looking at it right now."""
        if not self.enabled:
            return ("Bunny starts normally.",)
        head = (
            "Bunny Safe Mode is on for the next start."
            if not self.sticky else "Bunny Safe Mode is on until you turn it off."
        )
        if self.automatic:
            head += (
                f" It was turned on automatically after {self.consecutive_failures} "
                "failed starts."
            )
        return (head, *(f"• {effect}" for _, _, effect in SAFE_MODE_RESTRICTIONS),
                "Still available:", *(f"• {item}" for item in SAFE_MODE_RETAINED))


def _path(root: Path | None = None) -> Path:
    return (root or companion_state_root()) / SAFE_MODE_FILE_NAME


def read_safe_mode(root: Path | None = None) -> SafeModeState:
    """The current state. An unreadable or absent file means "start normally".

    Deliberately fail-open. A corrupt safe-mode file that put a machine into
    safe mode for ever would be a worse failure than the one safe mode exists
    to recover from.
    """
    try:
        raw = _path(root).read_text(encoding="utf-8")
    except OSError:
        return SafeModeState()
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return SafeModeState()
    if not isinstance(value, Mapping) or value.get("schemaVersion") != _SCHEMA_VERSION:
        return SafeModeState()
    return SafeModeState.from_json(value)


def _write(state: SafeModeState, root: Path | None = None) -> SafeModeState:
    path = _path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_json(), indent=2, sort_keys=True) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=".safe-mode-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return state


def request_safe_mode(
    *,
    reason: str,
    origin: str = "user",
    sticky: bool = False,
    root: Path | None = None,
    consecutive_failures: int = 0,
) -> SafeModeState:
    """Ask for the next launch to be reduced."""
    if origin not in ("user", "recovery", "launcher", "cli"):
        raise ValueError(f"unknown safe-mode origin {origin!r}")
    return _write(SafeModeState(
        enabled=True, sticky=sticky, reason=str(reason)[:512], origin=origin,
        consecutive_failures=max(0, int(consecutive_failures)),
    ), root)


def clear_safe_mode(root: Path | None = None) -> SafeModeState:
    """Turn it off, including a sticky one, and forget the failure count."""
    return _write(SafeModeState(), root)


def consume_safe_mode(root: Path | None = None) -> SafeModeState:
    """Read the state and clear a one-shot request. Called by the launcher.

    Returns what this launch should do, *then* leaves the file describing what
    the next launch should do. A sticky request survives; a one-shot does not.
    """
    state = read_safe_mode(root)
    if state.enabled and not state.sticky:
        _write(SafeModeState(consecutive_failures=state.consecutive_failures), root)
    return state


def record_launch_outcome(*, succeeded: bool, root: Path | None = None) -> SafeModeState:
    """Count launches, and turn safe mode on when enough of them fail.

    This is the loop-breaker. A window that dies before it is visible increments
    the count; the third one arms safe mode for the next start, so the fourth
    start produces something the user can act on rather than a fourth crash.
    """
    state = read_safe_mode(root)
    if succeeded:
        if state.sticky and state.enabled:
            return _write(SafeModeState(
                enabled=True, sticky=True, reason=state.reason, origin=state.origin,
            ), root)
        return _write(SafeModeState(), root)
    failures = state.consecutive_failures + 1
    if failures >= FAILURE_THRESHOLD and not state.enabled:
        return _write(SafeModeState(
            enabled=True, sticky=False, origin="launcher",
            reason=(
                f"the companion window failed to start {failures} times in a row; "
                "safe mode is on for the next start so the problem can be reached"
            ),
            consecutive_failures=failures,
        ), root)
    return _write(SafeModeState(
        enabled=state.enabled, sticky=state.sticky, reason=state.reason,
        origin=state.origin, consecutive_failures=failures,
    ), root)


def safe_mode_environment(state: SafeModeState | None = None, root: Path | None = None) -> dict[str, str]:
    """The variables a reduced launch runs with. Empty when safe mode is off.

    An environment rather than a set of function calls, because the thing being
    reduced is a *child process* — the GTK window — and the launcher's only
    channel to it is the environment it starts it in.
    """
    state = read_safe_mode(root) if state is None else state
    if not state.enabled:
        return {}
    environment = {variable: "1" for _, variable, _ in SAFE_MODE_RESTRICTIONS}
    environment["BUNNY_COMPANION_SAFE_MODE"] = "1"
    return environment


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip() not in ("", "0", "false", "no")


def accessibility_from_environment(*, prefer_text_only: bool = False) -> Any:
    """Safe mode's variables as an :class:`AccessibilityPreferences`.

    The translation exists because safe mode's channel to the window is an
    *environment* — the window is a child process — while the window's language
    for "draw less" is the accessibility preferences it already honours. Making
    safe mode speak that language means it needs no renderer code of its own,
    which is the difference between one degradation path and two.

    ``BUNNY_COMPANION_DISABLE_3D`` maps to ``no_animation`` rather than to a 3D
    flag, because the ladder in :mod:`companion.presentation` has no "no 3D"
    input: the motion preferences degrade to ``static-image``, which is below
    both 3D rungs and below animated 2D. That is stronger than asked for and it
    is the right direction for a mode whose job is to start at all.
    """
    from ..presentation import AccessibilityPreferences

    disable_3d = _enabled("BUNNY_COMPANION_DISABLE_3D")
    minimal = _enabled("BUNNY_COMPANION_MINIMAL_ANIMATION")
    return AccessibilityPreferences(
        reduced_motion=minimal or disable_3d,
        no_animation=disable_3d,
        prefer_text_only=prefer_text_only or _enabled("BUNNY_COMPANION_TEXT_ONLY"),
    )


def service_overrides(state: SafeModeState | None = None, root: Path | None = None) -> dict[str, Any]:
    """What a reduced runtime is built with, as ``ServiceOptions`` keywords.

    The runtime reads the safe-mode *file* rather than the environment. It is
    started by systemd, not by the launcher, so there is no parent to inherit
    from; and the file is inside its own ``StateDirectory``, which is the one
    place it is guaranteed to be able to read.

    Every flag named here already existed as a supported way to build the
    service. Safe mode is a *combination* of them, not a new mechanism — which
    is why it can be trusted to leave a working runtime behind: each flag's
    off-state is already specified and already tested.
    """
    state = read_safe_mode(root) if state is None else state
    if not state.enabled:
        return {}
    return {
        # No microphone: the speech runtime is not built, so no device is opened
        # and push-to-talk answers "no speech-input runtime".
        "speech_enabled": False,
        # No desktop actions: the tools are absent from the allowlist, so a plan
        # naming one fails the way a plan naming shell.run does.
        "desktop_enabled": False,
        # No spoken output. Captions are produced regardless.
        "voice_enabled": False,
        # Providers stay built — §19 keeps "local provider only when explicitly
        # selected" — and the remote refusal is the configuration's job, below.
        "agents_enabled": True,
    }


def local_only_configuration(configuration: Any) -> Any:
    """The same configuration with every remote provider removed.

    Removed rather than disabled. A disabled remote provider is one flag away
    from being contacted and appears in the provider list as something that
    could be turned on; a machine in safe mode should have no remote provider to
    turn on. §19: *no remote AI*, which is a statement about what exists rather
    than about what is preferred.
    """
    providers = tuple(
        provider for provider in getattr(configuration, "providers", ())
        if not getattr(provider, "remote", False)
    )
    if len(providers) == len(getattr(configuration, "providers", ())):
        return configuration
    from dataclasses import replace

    return replace(configuration, providers=providers)

