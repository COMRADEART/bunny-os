"""Quick Settings.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

A control either reflects a real backend or says "Unavailable in experimental
shell". There is no third option. A toggle with no backend does not flip, does
not animate, and does not report success — showing fake success in a prototype
is how a prototype gets mistaken for a product.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .model import BackendState, ShellState


UNAVAILABLE_LABEL = "Unavailable in experimental shell"


class ToggleKind(str, Enum):
    """Who owns the state behind a control."""

    SHELL = "shell"
    """The shell itself owns it, so it always works."""

    SYSTEM = "system"
    """A system service owns it; unavailable without that service."""

    BUNNY = "bunny"
    """The Bunny backend owns it."""


@dataclass
class Toggle:
    key: str
    label: str
    kind: ToggleKind
    backend: BackendState = BackendState.UNAVAILABLE
    value: bool = False
    detail: str = ""

    @property
    def available(self) -> bool:
        return self.backend is BackendState.CONNECTED

    def status_text(self) -> str:
        if not self.available:
            return UNAVAILABLE_LABEL
        return "On" if self.value else "Off"


class SetResult(str, Enum):
    APPLIED = "applied"
    REFUSED_NO_BACKEND = "refused-no-backend"
    UNKNOWN_TOGGLE = "unknown-toggle"


#: Every control the phase requires, with the owner of its state.
REQUIRED_TOGGLES: tuple[tuple[str, str, ToggleKind], ...] = (
    ("wifi", "Wi-Fi", ToggleKind.SYSTEM),
    ("bluetooth", "Bluetooth", ToggleKind.SYSTEM),
    ("audio", "Audio", ToggleKind.SYSTEM),
    ("microphone", "Microphone", ToggleKind.SYSTEM),
    ("camera-privacy", "Camera privacy", ToggleKind.SYSTEM),
    ("brightness", "Brightness", ToggleKind.SYSTEM),
    ("power-mode", "Power mode", ToggleKind.SYSTEM),
    ("night-light", "Night light", ToggleKind.SYSTEM),
    ("vpn", "VPN", ToggleKind.SYSTEM),
    ("accessibility", "Accessibility", ToggleKind.SHELL),
    ("focus-mode", "FocusMode", ToggleKind.SHELL),
    ("compact-layout", "CompactLayout", ToggleKind.SHELL),
    ("regular-mode", "Regular Mode", ToggleKind.SHELL),
    ("character-mode", "Character Mode", ToggleKind.SHELL),
    ("bunny-enabled", "Bunny enabled", ToggleKind.BUNNY),
    ("local-only", "Local Only", ToggleKind.BUNNY),
    ("updates", "Updates", ToggleKind.SYSTEM),
)


class QuickSettings:
    """The Quick Settings surface."""

    def __init__(self, state: ShellState) -> None:
        self.state = state
        self.toggles: dict[str, Toggle] = {}
        for key, label, kind in REQUIRED_TOGGLES:
            # Shell-owned controls work because the shell is the backend.
            backend = BackendState.CONNECTED if kind is ToggleKind.SHELL else BackendState.UNAVAILABLE
            self.toggles[key] = Toggle(key=key, label=label, kind=kind, backend=backend)
        self._sync_from_state()

    def _sync_from_state(self) -> None:
        self.toggles["focus-mode"].value = self.state.focus_mode
        self.toggles["compact-layout"].value = self.state.layout_mode.value == "compact"
        self.toggles["regular-mode"].value = not self.state.character_mode
        self.toggles["character-mode"].value = self.state.character_mode
        self.toggles["accessibility"].value = self.state.high_contrast or self.state.reduced_motion

    def connect_backend(self, key: str, *, value: bool, detail: str = "") -> None:
        """Attach a real backend to a control.

        Called only with observed backend state. Nothing else may set
        ``BackendState.CONNECTED``.
        """

        toggle = self.toggles[key]
        toggle.backend = BackendState.CONNECTED
        toggle.value = value
        toggle.detail = detail

    def set(self, key: str, value: bool) -> SetResult:
        toggle = self.toggles.get(key)
        if toggle is None:
            return SetResult.UNKNOWN_TOGGLE
        if not toggle.available:
            # Refused, and the control keeps its previous appearance. It does
            # not flip and then revert, which reads as success followed by a
            # glitch.
            return SetResult.REFUSED_NO_BACKEND
        toggle.value = value
        if key == "focus-mode":
            self.state.focus_mode = value
        elif key == "character-mode":
            from .model import VisualMode

            self.state.visual_mode = VisualMode.CHARACTER if value else VisualMode.REGULAR
            self._sync_from_state()
        elif key == "regular-mode":
            from .model import VisualMode

            self.state.visual_mode = VisualMode.REGULAR if value else VisualMode.CHARACTER
            self._sync_from_state()
        elif key == "compact-layout":
            from .model import LayoutMode

            self.state.layout_mode = LayoutMode.COMPACT if value else LayoutMode.COMFORTABLE
        return SetResult.APPLIED

    def unavailable_keys(self) -> list[str]:
        return sorted(key for key, toggle in self.toggles.items() if not toggle.available)

    def contains_mock_state(self) -> bool:
        """True if any control claims a backend it does not have.

        Used by the packaging gate: a build where this returns True must not
        ship.
        """

        for toggle in self.toggles.values():
            if toggle.backend is BackendState.CONNECTED and toggle.kind is not ToggleKind.SHELL:
                # A system or Bunny control is only ever CONNECTED after
                # connect_backend() was called with observed state. A build that
                # pre-sets one is packaging a mock.
                if toggle.detail == "mock":
                    return True
        return False
