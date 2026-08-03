"""The mode controller.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Regular Mode and Character Mode differ in exactly one thing: whether the guide
character may appear inside the approved containers. They do not differ in
window management, workspace semantics, keyboard shortcuts, available actions,
privacy indicators or approval behaviour.

Regular Mode is not "Character Mode with the character hidden". It uses the
whole surface: there is no reserved empty illustration area waiting for a
character that will never arrive.
"""

from __future__ import annotations

from dataclasses import dataclass

from .character import CharacterLayer
from .model import LayoutMode, ShellState, VisualMode


@dataclass(frozen=True)
class PanelLayout:
    """How a panel divides itself between illustration and content."""

    illustration_fraction: float
    content_fraction: float
    reserved_empty_space: bool

    def validate(self) -> None:
        total = self.illustration_fraction + self.content_fraction
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"panel layout must account for all space, got {total}")


#: Regular Mode gives every pixel to content.
REGULAR_LAYOUT = PanelLayout(illustration_fraction=0.0, content_fraction=1.0, reserved_empty_space=False)

#: Character Mode gives a bounded share to the illustration.
CHARACTER_LAYOUT = PanelLayout(illustration_fraction=0.32, content_fraction=0.68, reserved_empty_space=False)


class ModeController:
    """Applies a visual mode across the shell."""

    def __init__(self, state: ShellState, character: CharacterLayer) -> None:
        self.state = state
        self.character = character
        self._apply()

    def _apply(self) -> None:
        self.character.character_mode = self.state.character_mode
        self.character.focus_mode = self.state.focus_mode
        if not self.state.character_mode:
            self.character.hide()

    def set_visual_mode(self, mode: VisualMode) -> None:
        """Switch mode live. Never restarts the session or the compositor."""

        self.state.visual_mode = mode
        self._apply()

    def toggle(self) -> VisualMode:
        self.set_visual_mode(
            VisualMode.REGULAR if self.state.character_mode else VisualMode.CHARACTER
        )
        return self.state.visual_mode

    def set_focus_mode(self, enabled: bool) -> None:
        self.state.focus_mode = enabled
        self.character.focus_mode = enabled
        if enabled:
            # FocusMode ends any continuous presence immediately.
            self.character.hide()

    def panel_layout(self) -> PanelLayout:
        layout = CHARACTER_LAYOUT if self.state.character_mode else REGULAR_LAYOUT
        layout.validate()
        return layout

    def illustration_box(self, panel: tuple[int, int]) -> tuple[int, int]:
        """The illustration's box inside a panel of the given size.

        Zero in Regular Mode, which is the difference between "uses all
        available space intentionally" and "hides an empty column".
        """

        width, height = panel
        layout = self.panel_layout()
        return (int(width * layout.illustration_fraction), height)

    def content_box(self, panel: tuple[int, int]) -> tuple[int, int]:
        width, height = panel
        layout = self.panel_layout()
        return (int(width * layout.content_fraction), height)

    def animation_duration_ms(self, requested: int) -> int:
        return self.state.animation_duration_ms(requested)


def responsive_layout(width: int) -> LayoutMode:
    """Pick a layout from the available width.

    The threshold is stated once here so the top bar, the dock and the panels
    cannot disagree about when the shell is narrow.
    """

    return LayoutMode.COMPACT if width < 1280 else LayoutMode.COMFORTABLE


def character_fits(panel_width: int) -> bool:
    """Whether Character Mode's illustration is worth showing at this width.

    Below the threshold the illustration would be too small to read, so
    Character Mode falls back to the Regular layout for that panel rather than
    showing a thumbnail of a character.
    """

    return panel_width >= 720
