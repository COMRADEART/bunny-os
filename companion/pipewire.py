# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Facts read out of a ``pw-dump`` graph, in one place.

Both PipeWire backends — the recorder in :mod:`companion.speech.capture` and
the player in :mod:`companion.voice.audio` — need to know which device the
session treats as its default. Both asked a node for ``node.default``, and
that property does not exist: PipeWire keeps the default in a *metadata*
object, not on the node.

The consequence was not a wrong label. Every device came back
``default=False``, so device selection fell through to "the first non-monitor
entry in graph order", and on a machine with more than one source that is
whichever node the daemon happened to create first. Measured on a Bunny OS
guest with a line-in and a microphone: capture ran against the line-in, which
delivers no frames, and the interaction ended with "the input device was
lost" — a true statement about the wrong device.

So it is parsed once, here, and the two backends share it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

__all__ = ["default_node_name", "DEFAULT_SOURCE_KEYS", "DEFAULT_SINK_KEYS"]

#: In preference order. The ``configured`` key is the choice a person made;
#: the unqualified key can be a routing decision the session manager took on
#: its own, which is still better than an arbitrary node but is second.
DEFAULT_SOURCE_KEYS = ("default.configured.audio.source", "default.audio.source")
DEFAULT_SINK_KEYS = ("default.configured.audio.sink", "default.audio.sink")


def default_node_name(graph: Sequence[Any], keys: Sequence[str]) -> str:
    """The ``node.name`` the graph's default metadata points at, or ``""``.

    ``keys`` is in preference order; the first one present wins. A graph with
    no metadata object, no matching key, or a value in a shape this does not
    recognise yields ``""``, which every caller treats as "no default was
    expressed" rather than as an error — a machine with one microphone has
    never needed one.
    """
    found: dict[str, str] = {}
    for node in graph:
        if not isinstance(node, Mapping):
            continue
        props = node.get("props")
        if not isinstance(props, Mapping) or props.get("metadata.name") != "default":
            continue
        entries = node.get("metadata")
        if not isinstance(entries, Sequence):
            continue
        for entry in entries:
            if not isinstance(entry, Mapping):
                continue
            key = entry.get("key")
            if not isinstance(key, str) or key not in keys:
                continue
            value = entry.get("value")
            # `{"name": "..."}` is what PipeWire writes; a bare string is
            # accepted because it costs nothing and a future daemon may.
            name = value.get("name") if isinstance(value, Mapping) else value
            if isinstance(name, str) and name.strip():
                found.setdefault(key, name.strip())
    for key in keys:
        if key in found:
            return found[key]
    return ""
