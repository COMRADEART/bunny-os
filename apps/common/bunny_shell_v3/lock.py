"""Lock screen policy and the authentication boundary.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

The compositor never validates a password and never sees one. The lock client
collects the secret and hands it to an isolated helper that talks to PAM; the
helper answers with a boolean and nothing else. Everything below exists to keep
that boundary intact even when things go wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LockState(str, Enum):
    UNLOCKED = "unlocked"
    LOCKING_INCOMPLETE = "locking-incomplete"
    LOCKED = "locked"
    LOCKED_CLIENT_GONE = "locked-client-gone"

    @property
    def desktop_visible(self) -> bool:
        return self is LockState.UNLOCKED


class AuthResult(str, Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    HELPER_UNAVAILABLE = "helper-unavailable"


#: Everything the lock screen must offer.
REQUIRED_LOCK_FEATURES = (
    "password-authentication",
    "keyboard-layout",
    "accessibility-controls",
    "power-actions",
    "clock",
    "notifications-hidden-by-default",
    "network-state",
    "unlock-failure-messages",
)


@dataclass
class LockScreenPolicy:
    """What the lock screen shows and what it refuses to show."""

    notifications_hidden_by_default: bool = True
    character_permitted: bool = False
    power_actions: tuple[str, ...] = ("suspend", "restart", "power-off")
    accessibility_controls: tuple[str, ...] = (
        "high-contrast",
        "large-text",
        "screen-reader",
        "on-screen-keyboard",
    )

    def may_show_notification_content(self, unlocked: bool) -> bool:
        if not unlocked and self.notifications_hidden_by_default:
            return False
        return True

    def may_show_character(self) -> bool:
        """Never. The lock screen is an authentication surface."""

        return False


@dataclass
class SessionLock:
    """Lock lifecycle, covering every active output.

    Mirrors ``compositor/bunny-shell/src/session.rs`` so the same behaviour is
    testable from the Python suite and from the Rust suite.
    """

    state: LockState = LockState.UNLOCKED
    required_outputs: set[str] = field(default_factory=set)
    covered_outputs: set[str] = field(default_factory=set)
    failed_attempts: int = 0

    def set_outputs(self, names) -> None:
        self.required_outputs = set(names)
        self.covered_outputs &= self.required_outputs
        self._refresh()

    def lock(self) -> None:
        self.covered_outputs.clear()
        self.state = LockState.LOCKING_INCOMPLETE
        self._refresh()

    def surface_attached(self, output: str) -> None:
        if self.state is LockState.UNLOCKED:
            return
        if output in self.required_outputs:
            self.covered_outputs.add(output)
        self._refresh()

    def output_added(self, output: str) -> None:
        self.required_outputs.add(output)
        self._refresh()

    def output_removed(self, output: str) -> None:
        self.required_outputs.discard(output)
        self.covered_outputs.discard(output)
        self._refresh()

    def client_lost(self) -> None:
        if self.state is not LockState.UNLOCKED:
            self.state = LockState.LOCKED_CLIENT_GONE

    def uncovered(self) -> list[str]:
        return sorted(self.required_outputs - self.covered_outputs)

    def may_present_desktop(self, output: str) -> bool:
        _ = output
        return self.state.desktop_visible

    def unlock(self, result: AuthResult) -> bool:
        if result is not AuthResult.SUCCESS:
            self.failed_attempts += 1
            return False
        if self.state is LockState.LOCKED_CLIENT_GONE:
            # The client that could prove authentication is gone.
            return False
        self.state = LockState.UNLOCKED
        self.covered_outputs.clear()
        self.failed_attempts = 0
        return True

    def _refresh(self) -> None:
        if self.state in (LockState.UNLOCKED, LockState.LOCKED_CLIENT_GONE):
            return
        self.state = (
            LockState.LOCKED
            if self.required_outputs and not self.uncovered()
            else LockState.LOCKING_INCOMPLETE
        )


class AuthenticationHelper:
    """The boundary between the lock client and PAM.

    This class deliberately has no method that returns, stores or logs a
    secret. ``authenticate`` takes the secret, uses it, and returns a boolean.
    """

    #: Set by the real helper to the PAM service name. There is no default that
    #: would let a misconfigured helper authenticate against nothing.
    service: str | None = None

    def __init__(self, service: str | None = None) -> None:
        self.service = service
        self.attempts = 0

    def authenticate(self, username: str, secret: str) -> AuthResult:
        """Validate a secret through PAM.

        V3 does not implement the PAM conversation; it defines the boundary and
        returns HELPER_UNAVAILABLE so nothing can mistake an unimplemented
        helper for a successful authentication.
        """

        self.attempts += 1
        # Never retained, never logged, never returned.
        del secret
        if not self.service or not username:
            return AuthResult.HELPER_UNAVAILABLE
        return AuthResult.HELPER_UNAVAILABLE

    def __repr__(self) -> str:
        # Explicit: a default repr on a subclass holding a secret field would
        # leak it into a traceback.
        return f"AuthenticationHelper(service={self.service!r}, attempts={self.attempts})"


def redact(line: str) -> str:
    """Redact a line that mentions a credential field."""

    lowered = line.lower()
    for needle in ("password", "passphrase", "secret", "token", "credential", "keyring"):
        if needle in lowered:
            return "[redacted: line referenced a credential field]"
    return line
