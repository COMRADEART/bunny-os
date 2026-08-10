# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Every GPU object this renderer creates, with an owner and a destructor.

§20 asks for a resource to have an owner, a creation point, a destruction point,
an estimated size and a health state. A ledger is the only way to answer the
question the §34 gates actually ask — "did a hundred renderer lifecycles leak a
texture?" — because the GL API has no way to enumerate what a process owns. A
counter incremented next to each ``glGen*`` would answer it too, right up until
someone adds a twelfth allocation site and forgets; this class *is* the
allocation site, so there is nothing to forget.

Two design points worth stating.

**Deletion is idempotent and survives a lost context.** When a context is gone,
the names in it are already invalid; calling ``glDeleteTextures`` on them is
harmless but pointless, and the ledger must still reach zero or every subsequent
leak check compares against a poisoned baseline. :meth:`GpuResources.release`
takes ``context_lost`` and drops the names without calling the driver.

**Replacement is bounded, not instantaneous.** §20 requires the old model to be
unloaded before the new one is active "beyond bounded overlap". The overlap here
is exactly one model: :meth:`GpuResources.begin_replacement` opens a second
owner, and the old owner is released the moment the new one has uploaded, so the
peak is two models rather than a growing set.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable

from .errors import RendererContextError

#: The kinds this ledger knows. Closed: a new kind means a new deleter, and a
#: kind without one would leak silently.
RESOURCE_KINDS: tuple[str, ...] = (
    "vertex-buffer",
    "index-buffer",
    "vertex-array",
    "texture",
    "morph-texture",
    "skin-uniform",
    "shader-program",
    "framebuffer",
    "renderbuffer",
)

_DELETERS: dict[str, tuple[str, str]] = {
    "vertex-buffer": ("glDeleteBuffers", "buffers"),
    "index-buffer": ("glDeleteBuffers", "buffers"),
    "vertex-array": ("glDeleteVertexArrays", "arrays"),
    "texture": ("glDeleteTextures", "textures"),
    "morph-texture": ("glDeleteTextures", "textures"),
    "framebuffer": ("glDeleteFramebuffers", "framebuffers"),
    "renderbuffer": ("glDeleteRenderbuffers", "renderbuffers"),
}


@dataclass
class GpuResource:
    """One named GL object. ``name`` is the driver's handle, not a label."""

    kind: str
    name: int
    owner: str
    created_at: float
    created_by: str
    estimated_bytes: int
    health: str = "live"
    released_at: float | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "name": self.name,
            "owner": self.owner,
            "createdBy": self.created_by,
            "createdAt": round(self.created_at, 6),
            "estimatedBytes": self.estimated_bytes,
            "health": self.health,
            "releasedAt": None if self.released_at is None else round(self.released_at, 6),
        }


class GpuResources:
    """The ledger. Nothing in the renderer allocates a GL object except here."""

    def __init__(self, gl: Any, *, clock: Callable[[], float] | None = None) -> None:
        self.gl = gl
        self._clock = clock or time.monotonic
        self._live: dict[tuple[str, int], GpuResource] = {}
        self._released: list[GpuResource] = []
        self.peak_bytes = 0
        self.created_total = 0
        self.released_total = 0
        self.leak_suspicions: list[str] = []
        #: Bounded history: a long-running client must not grow a ledger.
        self.history_limit = 512

    # -- allocation --------------------------------------------------------

    def record(
        self, kind: str, name: int, *, owner: str, created_by: str, estimated_bytes: int
    ) -> GpuResource:
        if kind not in RESOURCE_KINDS:
            raise ValueError(f"unknown GPU resource kind: {kind}")
        if not name:
            raise RendererContextError(f"{created_by} returned GL object name 0")
        key = (kind, int(name))
        if key in self._live:
            # Two owners for one driver handle means one of them will delete it
            # while the other still draws with it.
            raise RendererContextError(f"{kind} {name} is already recorded as live")
        resource = GpuResource(
            kind=kind, name=int(name), owner=str(owner), created_at=self._clock(),
            created_by=str(created_by), estimated_bytes=max(0, int(estimated_bytes)),
        )
        self._live[key] = resource
        self.created_total += 1
        self.peak_bytes = max(self.peak_bytes, self.estimated_bytes)
        return resource

    def buffers(self, count: int, *, kind: str, owner: str, created_by: str, estimated_bytes: int) -> list[int]:
        names = self.gl.gen("glGenBuffers", count)
        self.gl.check(created_by)
        per_object = estimated_bytes // max(1, count)
        for name in names:
            self.record(kind, name, owner=owner, created_by=created_by, estimated_bytes=per_object)
        return names

    def vertex_arrays(self, count: int, *, owner: str, created_by: str) -> list[int]:
        names = self.gl.gen("glGenVertexArrays", count)
        self.gl.check(created_by)
        for name in names:
            self.record("vertex-array", name, owner=owner, created_by=created_by, estimated_bytes=0)
        return names

    def textures(self, count: int, *, kind: str = "texture", owner: str, created_by: str, estimated_bytes: int) -> list[int]:
        names = self.gl.gen("glGenTextures", count)
        self.gl.check(created_by)
        per_object = estimated_bytes // max(1, count)
        for name in names:
            self.record(kind, name, owner=owner, created_by=created_by, estimated_bytes=per_object)
        return names

    def program(self, name: int, *, owner: str, created_by: str) -> int:
        self.record("shader-program", name, owner=owner, created_by=created_by, estimated_bytes=0)
        return name

    def framebuffers(self, count: int, *, owner: str, created_by: str) -> list[int]:
        names = self.gl.gen("glGenFramebuffers", count)
        self.gl.check(created_by)
        for name in names:
            self.record("framebuffer", name, owner=owner, created_by=created_by, estimated_bytes=0)
        return names

    def renderbuffers(self, count: int, *, owner: str, created_by: str, estimated_bytes: int) -> list[int]:
        names = self.gl.gen("glGenRenderbuffers", count)
        self.gl.check(created_by)
        for name in names:
            self.record(
                "renderbuffer", name, owner=owner, created_by=created_by,
                estimated_bytes=estimated_bytes // max(1, count),
            )
        return names

    # -- release -----------------------------------------------------------

    def release(self, *, owner: str | None = None, context_lost: bool = False) -> int:
        """Delete everything (or everything one owner holds). Returns the count.

        Never raises. A release path that can throw is a release path that stops
        halfway and leaves the rest of the ledger live — which is precisely the
        leak it exists to prevent.
        """
        targets = [
            resource for resource in self._live.values()
            if owner is None or resource.owner == owner
        ]
        if not targets:
            return 0
        by_kind: dict[str, list[int]] = {}
        for resource in targets:
            by_kind.setdefault(resource.kind, []).append(resource.name)
        if not context_lost:
            for kind, names in by_kind.items():
                if kind == "shader-program":
                    for name in names:
                        try:
                            self.gl.glDeleteProgram(name)
                        except Exception as exc:  # noqa: BLE001 - see docstring
                            self.leak_suspicions.append(f"glDeleteProgram({name}): {exc}")
                    continue
                deleter = _DELETERS[kind][0]
                try:
                    self.gl.delete(deleter, names)
                except Exception as exc:  # noqa: BLE001 - see docstring
                    self.leak_suspicions.append(f"{deleter}: {exc}")
            try:
                self.gl.drain_errors()
            except Exception:  # noqa: BLE001
                pass
        now = self._clock()
        for resource in targets:
            resource.health = "released-context-lost" if context_lost else "released"
            resource.released_at = now
            self._live.pop((resource.kind, resource.name), None)
            self._released.append(resource)
            self.released_total += 1
        if len(self._released) > self.history_limit:
            del self._released[: len(self._released) - self.history_limit]
        return len(targets)

    def begin_replacement(self, *, previous_owner: str, new_owner: str) -> None:
        """Open the bounded overlap §20 permits: one old model, one new one."""
        owners = {resource.owner for resource in self._live.values()}
        extra = owners.difference({previous_owner, new_owner})
        if extra:
            raise RendererContextError(
                "a model replacement began with unexpected owners still live: "
                + ", ".join(sorted(extra))
            )

    # -- reporting ---------------------------------------------------------

    @property
    def live_count(self) -> int:
        return len(self._live)

    @property
    def estimated_bytes(self) -> int:
        return sum(resource.estimated_bytes for resource in self._live.values())

    def counts(self) -> dict[str, int]:
        result = {kind: 0 for kind in RESOURCE_KINDS}
        for resource in self._live.values():
            result[resource.kind] += 1
        return result

    def owners(self) -> tuple[str, ...]:
        return tuple(sorted({resource.owner for resource in self._live.values()}))

    def to_json(self) -> dict[str, Any]:
        counts = self.counts()
        return {
            "live": self.live_count,
            "counts": counts,
            "textures": counts["texture"] + counts["morph-texture"],
            "buffers": counts["vertex-buffer"] + counts["index-buffer"],
            "vertexArrays": counts["vertex-array"],
            "programs": counts["shader-program"],
            "framebuffers": counts["framebuffer"],
            "renderbuffers": counts["renderbuffer"],
            "estimatedBytes": self.estimated_bytes,
            "peakBytes": self.peak_bytes,
            "createdTotal": self.created_total,
            "releasedTotal": self.released_total,
            "owners": list(self.owners()),
            "leakSuspicions": list(self.leak_suspicions),
        }


__all__ = ["GpuResource", "GpuResources", "RESOURCE_KINDS"]
