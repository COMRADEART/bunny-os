"""GTK 4 layer-shell runtime for the Bunny shell components.

BUNNY WAYLAND SHELL EXPERIMENT — NOT RELEASE QUALIFIED — DO NOT USE AS THE
DEFAULT SESSION.

Every piece of Bunny chrome is an ordinary Wayland client on
``wlr-layer-shell-v1``. Nothing here is drawn by the compositor, which is what
gives the chrome an accessibility implementation at all — see
``visual-v3/ACCESSIBILITY_MODEL.md``.

The component specifications below are importable without GTK, so the layout,
keyboard and focus policy can be tested on any platform. Only :func:`run`
requires a Wayland session.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Edge(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    TOP = "top"
    BOTTOM = "bottom"


class LayerName(str, Enum):
    BACKGROUND = "background"
    BOTTOM = "bottom"
    TOP = "top"
    OVERLAY = "overlay"


class KeyboardMode(str, Enum):
    """How a surface may take the keyboard.

    ``NONE`` is the default and the safe one. ``EXCLUSIVE`` is reserved for
    surfaces the user deliberately opened and is typing into.
    """

    NONE = "none"
    ON_DEMAND = "on-demand"
    EXCLUSIVE = "exclusive"


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    namespace: str
    layer: LayerName
    anchors: tuple[Edge, ...]
    keyboard: KeyboardMode
    exclusive_zone: int = 0
    width: int = 0
    height: int = 0
    #: Whether this surface may ever contain the guide character.
    character_permitted: bool = False
    #: Whether this surface handles authentication input.
    authentication_surface: bool = False


#: The complete set of Bunny chrome components.
#:
#: ``character_permitted`` encodes the V2 character policy directly in the
#: surface table: the top bar, the dock, the overview and the lock screen can
#: never host the character because no code reads a flag that is False here.
COMPONENTS: dict[str, ComponentSpec] = {
    "top-bar": ComponentSpec(
        name="top-bar",
        namespace="bunny-top-bar",
        layer=LayerName.TOP,
        anchors=(Edge.LEFT, Edge.RIGHT, Edge.TOP),
        keyboard=KeyboardMode.NONE,
        exclusive_zone=32,
        height=32,
    ),
    "dock": ComponentSpec(
        name="dock",
        namespace="bunny-dock",
        layer=LayerName.TOP,
        anchors=(Edge.LEFT, Edge.RIGHT, Edge.BOTTOM),
        keyboard=KeyboardMode.NONE,
        exclusive_zone=64,
        height=64,
    ),
    "launcher": ComponentSpec(
        name="launcher",
        namespace="bunny-launcher",
        layer=LayerName.OVERLAY,
        anchors=(),
        keyboard=KeyboardMode.EXCLUSIVE,
        width=880,
        height=600,
    ),
    "command-palette": ComponentSpec(
        name="command-palette",
        namespace="bunny-command-palette",
        layer=LayerName.OVERLAY,
        anchors=(Edge.TOP,),
        keyboard=KeyboardMode.EXCLUSIVE,
        width=720,
        height=420,
    ),
    "quick-settings": ComponentSpec(
        name="quick-settings",
        namespace="bunny-quick-settings",
        layer=LayerName.OVERLAY,
        anchors=(Edge.TOP, Edge.RIGHT),
        keyboard=KeyboardMode.ON_DEMAND,
        width=380,
        height=520,
    ),
    "notification-center": ComponentSpec(
        name="notification-center",
        namespace="bunny-notification-center",
        layer=LayerName.TOP,
        anchors=(Edge.TOP, Edge.RIGHT),
        keyboard=KeyboardMode.ON_DEMAND,
        width=420,
        height=760,
    ),
    "assistant-panel": ComponentSpec(
        name="assistant-panel",
        namespace="bunny-assistant",
        layer=LayerName.TOP,
        anchors=(Edge.TOP, Edge.RIGHT, Edge.BOTTOM),
        keyboard=KeyboardMode.ON_DEMAND,
        width=460,
        character_permitted=True,
    ),
    "approval-panel": ComponentSpec(
        name="approval-panel",
        namespace="bunny-approval",
        layer=LayerName.OVERLAY,
        anchors=(),
        keyboard=KeyboardMode.EXCLUSIVE,
        width=640,
        height=520,
        character_permitted=True,
    ),
    "overview": ComponentSpec(
        name="overview",
        namespace="bunny-overview",
        layer=LayerName.TOP,
        anchors=(Edge.LEFT, Edge.RIGHT, Edge.TOP, Edge.BOTTOM),
        keyboard=KeyboardMode.EXCLUSIVE,
    ),
    "lock-screen": ComponentSpec(
        name="lock-screen",
        # The lock screen is NOT a layer surface. It uses ext-session-lock-v1,
        # which is a separate, privileged surface role the compositor treats as
        # the only thing on screen. A layer surface could be covered by another
        # layer surface; a lock surface cannot.
        namespace="bunny-lock-screen",
        layer=LayerName.OVERLAY,
        anchors=(Edge.LEFT, Edge.RIGHT, Edge.TOP, Edge.BOTTOM),
        keyboard=KeyboardMode.EXCLUSIVE,
        authentication_surface=True,
    ),
}


def spec(name: str) -> ComponentSpec:
    if name not in COMPONENTS:
        raise KeyError(f"unknown shell component: {name}")
    return COMPONENTS[name]


def character_permitted(component: str) -> bool:
    """Whether the guide character may appear inside a component.

    Refuses on an unknown component rather than defaulting to permitted.
    """

    if component not in COMPONENTS:
        return False
    candidate = COMPONENTS[component]
    if candidate.authentication_surface:
        return False
    return candidate.character_permitted


def reserves_space(component: str) -> bool:
    """Whether the component takes an exclusive zone from the work area."""

    return COMPONENTS[component].exclusive_zone > 0


# --------------------------------------------------------------------------
# GTK runtime. Imported lazily so the specifications above stay testable
# without a display.
# --------------------------------------------------------------------------


def _require_gtk():
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk, Gtk4LayerShell

    return Gtk, Gtk4LayerShell


def apply_layer_shell(window, component: str) -> None:
    """Turn a GTK window into the layer surface its specification describes."""

    _, layer_shell = _require_gtk()
    definition = spec(component)

    layer_shell.init_for_window(window)
    layer_shell.set_namespace(window, definition.namespace)
    layer_shell.set_layer(
        window,
        {
            LayerName.BACKGROUND: layer_shell.Layer.BACKGROUND,
            LayerName.BOTTOM: layer_shell.Layer.BOTTOM,
            LayerName.TOP: layer_shell.Layer.TOP,
            LayerName.OVERLAY: layer_shell.Layer.OVERLAY,
        }[definition.layer],
    )
    edges = {
        Edge.LEFT: layer_shell.Edge.LEFT,
        Edge.RIGHT: layer_shell.Edge.RIGHT,
        Edge.TOP: layer_shell.Edge.TOP,
        Edge.BOTTOM: layer_shell.Edge.BOTTOM,
    }
    for edge, native in edges.items():
        layer_shell.set_anchor(window, native, edge in definition.anchors)
    if definition.exclusive_zone:
        layer_shell.set_exclusive_zone(window, definition.exclusive_zone)
    layer_shell.set_keyboard_mode(
        window,
        {
            KeyboardMode.NONE: layer_shell.KeyboardMode.NONE,
            KeyboardMode.ON_DEMAND: layer_shell.KeyboardMode.ON_DEMAND,
            KeyboardMode.EXCLUSIVE: layer_shell.KeyboardMode.EXCLUSIVE,
        }[definition.keyboard],
    )
    if definition.width or definition.height:
        window.set_default_size(definition.width or -1, definition.height or -1)
