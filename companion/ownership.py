# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which account may own a file this process is willing to trust.

Two places refuse to read a file owned by a third party: the speech model
loader, because a model is data a native parser walks, and the desktop entry
reader, because an entry names a program that will be started. Both asked the
same question — "is the owner root, or us?" — and both got the wrong answer on
a real Bunny OS system, for a reason that is invisible on a developer's host.

``bunny-companion.service`` is a *user* service with ``ProtectSystem=strict``
and ``ProtectHome=read-only``. An unprivileged user manager cannot build those
mount namespaces without a user namespace, so systemd gives the unit one, and
its map is a single entry::

    $ cat /proc/$(pgrep -f bunny-companion-service)/uid_map
          1000       1000          1

Only uid 1000 is mapped. Every file owned by real root — which is every file in
``/usr``, including the speech model and every ``.desktop`` file the image
ships — is therefore reported to that process as the kernel's overflow uid,
65534. The ownership rule read that as "a third party owns this" and refused.

The measured effect was total and silent: on the shipped image the microphone
button was permanently disabled with "Voice recognition needs repair before it
can be used", and nothing in the suite noticed, because outside the namespace —
which is where every test, probe and developer shell runs — the same files are
owned by uid 0 and the rule passes.

So the rule is stated here once, and it accepts the overflow uid *only* when
this process is in a user namespace that does not map root. That condition is
what makes it safe rather than a loosening:

* Inside such a namespace, no principal can create or modify a file owned by an
  unmapped uid. Only uid 1000 is writable-as, so a file the namespace reports as
  65534 is one that nothing inside it can have written.
* Outside a namespace, 65534 is the ordinary ``nobody`` account and is still
  refused, exactly as before.

Both callers additionally refuse anything group- or other-writable, which is
the other half of the property and is unchanged.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["trusted_owner_ids", "owner_is_trusted"]

#: Where the kernel publishes the uid it substitutes for an unmapped owner.
_OVERFLOW_UID_PATH = Path("/proc/sys/kernel/overflowuid")
_DEFAULT_OVERFLOW_UID = 65534
_UID_MAP_PATH = Path("/proc/self/uid_map")


def _overflow_uid() -> int:
    try:
        return int(_OVERFLOW_UID_PATH.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return _DEFAULT_OVERFLOW_UID


def _root_is_unmapped() -> bool:
    """True when this process is in a user namespace that does not map uid 0.

    The initial namespace maps the whole range (``0 0 4294967295``), so this is
    False there and the overflow uid stays untrusted. A missing or unreadable
    ``uid_map`` is treated as "root is mapped": refusing is the safe direction
    when the question cannot be answered.
    """
    try:
        text = _UID_MAP_PATH.read_text(encoding="ascii")
    except OSError:
        return False
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 3:
            continue
        try:
            inside, _outside, count = (int(field) for field in fields)
        except ValueError:
            continue
        if inside <= 0 < inside + count:
            return False
    return True


def trusted_owner_ids() -> frozenset[int]:
    """The uids a file may be owned by and still be read by this process."""
    if not hasattr(os, "getuid"):
        return frozenset()
    trusted = {0, os.getuid()}
    if _root_is_unmapped():
        trusted.add(_overflow_uid())
    return frozenset(trusted)


def owner_is_trusted(uid: int) -> bool:
    return uid in trusted_owner_ids()
