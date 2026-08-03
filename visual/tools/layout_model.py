"""Pure layout constraints used by deterministic Visual V1 baseline tests."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Viewport:
    physical_width: int
    physical_height: int
    scale: float = 1.0

    @property
    def width(self) -> int:
        return int(self.physical_width / self.scale)

    @property
    def height(self) -> int:
        return int(self.physical_height / self.scale)


def surface_bounds(viewport: Viewport, mode: str = "normal") -> dict[str, tuple[int, int]]:
    if mode not in {"normal", "compact", "focus"}:
        raise ValueError("unknown layout mode")
    compact = mode == "compact"
    assistant_width = min(390 if compact else 430, int(viewport.width * (0.32 if compact else 0.36)))
    approval_width = min(450 if compact else 500, int(viewport.width * (0.38 if compact else 0.42)))
    overview_width = min(310 if compact else 360, int(viewport.width * (0.24 if compact else 0.28)))
    palette_width = min(600 if compact else 680, viewport.width - 48)
    return {
        "assistant": (assistant_width, viewport.height - 72),
        "approval": (approval_width, min(680, viewport.height - 100)),
        "overview": (overview_width, min(640, viewport.height - 112)),
        "palette": (palette_width, min(640, viewport.height - 72)),
        "dock": (min(620, viewport.width - 48), 64 if not compact else 52),
    }


SUPPORTED_VIEWPORTS = (
    Viewport(1366, 768), Viewport(1920, 1080), Viewport(2560, 1440),
    Viewport(3840, 2160, 2.0),
)
