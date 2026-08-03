"""Core shell state shared by every V3 shell component.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class VisualMode(str, Enum):
    """The two approved visual experiences, carried forward from V2."""

    REGULAR = "regular"
    CHARACTER = "character"


class LayoutMode(str, Enum):
    COMFORTABLE = "comfortable"
    COMPACT = "compact"


class BackendState(str, Enum):
    """Whether a control has a real backend behind it.

    ``UNAVAILABLE`` is displayed as "Unavailable in experimental shell". There
    is deliberately no ``MOCK`` state: a control either reflects a real backend
    or says it cannot.
    """

    CONNECTED = "connected"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PrivacyIndicator:
    """An indicator that must stay visible for as long as it is active.

    Privacy indicators are the one class of shell element that no mode, layout
    or overlay may hide. Character Mode does not obscure them, FocusMode does
    not suppress them, and CompactLayout does not collapse them into an
    overflow menu.
    """

    key: str
    label: str
    active: bool = False

    def must_be_visible(self) -> bool:
        return self.active


PRIVACY_INDICATORS = ("microphone", "camera", "screen-capture", "location")


@dataclass
class ShellState:
    """The state every component renders from.

    Components never invent state. A field that no backend has set keeps its
    declared default and the surface says so.
    """

    visual_mode: VisualMode = VisualMode.REGULAR
    layout_mode: LayoutMode = LayoutMode.COMFORTABLE
    focus_mode: bool = False
    reduced_motion: bool = False
    high_contrast: bool = False
    bunny_enabled: bool = True
    local_only: bool = False
    do_not_disturb: bool = False
    active_workspace: int = 0
    workspace_count: int = 4
    indicators: dict[str, PrivacyIndicator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for key in PRIVACY_INDICATORS:
            self.indicators.setdefault(
                key, PrivacyIndicator(key=key, label=key.replace("-", " ").title())
            )

    @property
    def character_mode(self) -> bool:
        return self.visual_mode is VisualMode.CHARACTER

    def set_indicator(self, key: str, active: bool) -> None:
        if key not in self.indicators:
            raise KeyError(f"unknown privacy indicator: {key}")
        current = self.indicators[key]
        self.indicators[key] = PrivacyIndicator(current.key, current.label, active)

    def active_privacy_indicators(self) -> list[PrivacyIndicator]:
        return [indicator for indicator in self.indicators.values() if indicator.active]

    def animation_duration_ms(self, requested: int) -> int:
        """Reduced motion means no animation, not a quick one."""

        return 0 if self.reduced_motion else requested
