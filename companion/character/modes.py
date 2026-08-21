# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The three renderer modes a person chooses between, and what each one costs.

The capability ladder in :mod:`companion.character.adaptation` answers "how much
may this machine draw". It has five rungs and it is not a menu: nobody chooses
``lightweight-3d``, the machine falls to it. This module answers the other
question — "which of the three companions did the user ask for" — and the two
are deliberately separate values.

They were briefly one. Collapsing them looks tempting because both end in a
renderer, and it fails on the first machine that degrades: a user who chose 3D
and whose GPU context is lost would have had their *choice* rewritten to 2D by
the degradation, and when the context came back nothing would have restored it.
The mode is what the person asked for and only a person changes it; the rung is
what the machine can currently honour. Degradation moves the rung.

**Pre-rendered is the default, and it is a frame player.** The renderer behind
it — :class:`companion.character.animated_renderer.Animated2DRenderer` — plays
validated PNG frame sequences with alpha out of the character package. It
decodes no geometry, holds no GL objects, and when the companion is idle the
quiescence policy in :mod:`companion.character.quiescence` stops it advancing at
all.

It is the default because it is the cheapest thing to *run*, which is a narrower
claim than "the cheapest", and the difference is measured rather than assumed.
``scripts/renderer_mode_measure.py`` on the reference host puts a pre-rendered
frame at 0.0023 ms of compute against 0.22 ms for the interactive renderer —
roughly two orders of magnitude, because one indexes a list where the other
solves for a pose. It loses the other half of the comparison: it holds every
decoded frame, 468 KB against the interactive renderer's 36 KB for the same
package. On the hardware this phase is aimed at, CPU wakeups cost battery and
half a megabyte does not, so the trade is deliberate — but it is a trade, and
the mode that wins on memory is the other one.

**Interactive 2D is a real-time renderer, not a heavier frame player.** It
computes pose rather than looking it up, which buys reaction and continuous
transitions and costs arithmetic per frame. It sits on the same rung as
pre-rendered because it draws the same kind of surface; it is a different
*renderer*, not a different allowance.

**3D is unchanged and stays opt-in.** Nothing here lowers what the 3D renderer
can do. It is simply no longer what a machine picks on its own.

The ordering below is the fallback chain §15 asks for, and it is expressed as
data for the same reason the task lifecycle is: a chain assembled from ``if``
branches at three call sites is a chain that can disagree with itself.
"""

from __future__ import annotations

from enum import Enum
from typing import Mapping

from .adaptation import Presentation

__all__ = [
    "DEFAULT_MODE",
    "MODE_CEILINGS",
    "MODE_RENDERERS",
    "PERFORMANCE_FRAME_CAPS",
    "PRERENDERED_RENDERER",
    "RenderMode",
    "ceiling_for_mode",
    "mode_from_settings",
    "performance_cap",
    "renderer_chain",
]


class RenderMode(str, Enum):
    """What the user chose. Three values, because §2 offers three."""

    PRERENDERED = "prerendered"
    INTERACTIVE_2D = "2d"
    THREE_D = "3d"


#: The mode a machine has when nobody has said otherwise.
#:
#: §3 of the phase brief, and the one line in this module that changes what an
#: existing machine draws. Before it, :data:`companion.character.policy.
#: POLICY_LADDER` started at ``full-3d`` and any machine that could hold a GL
#: context booted into the 3D companion.
DEFAULT_MODE = RenderMode.PRERENDERED

#: The highest capability rung each mode is allowed to reach.
#:
#: A *ceiling*, never a floor. Choosing 3D on a machine with no GPU does not
#: produce 3D; it produces the highest thing below it that works, and the
#: degradation ladder already knows how to find that. This is why there is no
#: "force 3D" anywhere in the settings surface — a preference that could break
#: the window is not a preference, it is a fault waiting for a bug report.
MODE_CEILINGS: Mapping[RenderMode, Presentation] = {
    RenderMode.PRERENDERED: Presentation.ANIMATED_2D,
    RenderMode.INTERACTIVE_2D: Presentation.ANIMATED_2D,
    RenderMode.THREE_D: Presentation.FULL_3D,
}

#: The renderer name that serves the pre-rendered mode. Named once, because it
#: is also the last rung of every fallback chain and the two must not drift.
PRERENDERED_RENDERER = "animated-2d"

#: The renderer that *is* each mode, before any fallback.
MODE_RENDERERS: Mapping[RenderMode, str] = {
    RenderMode.PRERENDERED: PRERENDERED_RENDERER,
    RenderMode.INTERACTIVE_2D: "interactive-2d",
    RenderMode.THREE_D: "full-3d",
}

#: §15's fallback, per mode, for the 2D rung: which renderer to try and in what
#: order when the one above it will not start.
#:
#: Every chain ends at :data:`PRERENDERED_RENDERER` because the frame player is
#: the renderer with the fewest ways to fail — it needs no GL context, no shader
#: compilation and no geometry, only decoded images the package validator has
#: already proven decodable. Below it the capability ladder takes over with
#: static-image and then text-only, which is where a chain that has run out of
#: renderers belongs.
_TWO_D_CHAINS: Mapping[RenderMode, tuple[str, ...]] = {
    RenderMode.PRERENDERED: (PRERENDERED_RENDERER,),
    RenderMode.INTERACTIVE_2D: ("interactive-2d", PRERENDERED_RENDERER),
    # A 3D user who has fallen to the 2D rung gets the interactive renderer
    # first: they asked for a companion that reacts, and interactive-2d is the
    # closest surviving thing to that. §15 draws exactly this chain.
    RenderMode.THREE_D: ("interactive-2d", PRERENDERED_RENDERER),
}


#: §10's performance setting, as a frame-rate ceiling.
#:
#: A ceiling on *effort* and never on which renderer runs. A user who chose 3D
#: and set performance to ``low`` gets 3D at 15 fps, not a silent demotion to
#: 2D — the two settings answer different questions and a performance control
#: that changed the companion out from under someone would be answering the
#: wrong one.
#:
#: ``automatic`` is absent on purpose rather than mapped to 60: it means "do not
#: add a ceiling", and the degradation ladder's own caps — thermal, CPU
#: pressure, battery, accessibility — still apply underneath every value here.
PERFORMANCE_FRAME_CAPS: Mapping[str, int] = {
    "low": 15,
    "balanced": 30,
    "high": 60,
}


def performance_cap(performance: str) -> int | None:
    """The frame-rate ceiling for a performance setting, or ``None`` for none."""
    return PERFORMANCE_FRAME_CAPS.get(str(performance or "").strip().casefold())


def ceiling_for_mode(mode: RenderMode) -> Presentation:
    """The capability rung this mode may reach at most."""
    return MODE_CEILINGS[mode]


def renderer_chain(mode: RenderMode, presentation: Presentation) -> tuple[str, ...]:
    """Which renderers may serve ``presentation``, best first, for this mode.

    Only the 2D rung has a choice to make — it is the one rung two renderers can
    serve. Every other rung has exactly one implementation, so its "chain" is a
    single name and the caller needs no special case for it.
    """
    if presentation is Presentation.ANIMATED_2D:
        return _TWO_D_CHAINS[mode]
    if presentation in (Presentation.FULL_3D, Presentation.LIGHTWEIGHT_3D):
        return (presentation.value,)
    if presentation is Presentation.STATIC_IMAGE:
        return (Presentation.STATIC_IMAGE.value,)
    return ()


def mode_from_settings(value: str | None, *, three_d: str = "auto") -> RenderMode:
    """Read a mode out of settings, tolerating the vocabulary that came before.

    ``three_d`` is the older ``auto``/``off`` preference. It is still honoured
    as a *veto* and never as a request: a machine whose settings say
    ``threeD: off`` cannot land in 3D mode however ``renderMode`` reads. That
    direction is deliberate — the old setting could only ever restrict, so
    letting it restrict is the reading that cannot surprise anyone who set it.

    An unreadable or unknown mode is the default rather than an error. Settings
    are read on the start-up path of the thing that draws the companion, and a
    typo in a file should cost a person the pre-rendered companion, not the
    companion.
    """
    try:
        mode = RenderMode(str(value or "").strip().casefold())
    except ValueError:
        mode = DEFAULT_MODE
    if mode is RenderMode.THREE_D and three_d == "off":
        return RenderMode.INTERACTIVE_2D
    return mode
