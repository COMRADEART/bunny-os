# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Where a capsule's own things live, and what "clear this app's data" deletes.

Seven directories, and the split between them is what makes the Settings buttons
mean something. "Clear temporary data", "reset the app" and "delete the app's
data" are three different requests, and a layout with one directory would make
all three the same button::

    <root>/<identity>/
        manifest.json     what this capsule is: permissions, limits, backend
        state.json        lifecycle state and launch history
        data/             the application's own persistent data      [reset, delete]
        config/           the application's own settings             [reset, delete]
        cache/            regenerable                                [clear, reset, delete]
        tmp/              discarded on every stop                    [clear, reset, delete]
        runtime/          sockets and pid-like files; discarded on stop
        exports/          artefacts produced for the user, staged for approval
        inbox/            files the user granted, materialised for the capsule

``clear temporary data`` removes ``cache`` and ``tmp``.
``reset`` removes ``cache``, ``tmp``, ``config`` and ``runtime`` — the
application comes back as if newly installed but keeps the documents in ``data``.
``delete data`` removes ``data`` too.
``uninstall`` removes the whole identity directory, and every grant in the trust
store, and the autostart entry if there is one.

**Every destructive operation checks containment before it deletes.** The target
is resolved with symlinks followed and then required to be inside the capsule
root by path component. This is not defensive decoration: the root is
configurable through the environment so that tests and demos can have their own,
which means it is also configurable by anything that can set an environment
variable, and ``rm -rf`` on a path derived from a configurable root is exactly the
mistake that has to be impossible rather than unlikely.

**A capsule's directories are never bound into another capsule.** §20 forbids
mounting one application's private data into another; :func:`is_capsule_private`
is how the isolation planner recognises such a path without needing to know which
capsule it belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import stat
from typing import Iterable, Mapping

from trust.persistence import private_directory
from trust.resources import contains, real_path

from .errors import CapsuleContainmentError, CapsuleSchemaError
from .identity import CapsuleIdentity

__all__ = [
    "CLEARABLE",
    "DELETABLE",
    "DIRECTORIES",
    "RESETTABLE",
    "CapsuleLayout",
    "default_capsule_root",
    "is_capsule_private",
    "storage_usage",
]

#: Every directory a capsule owns, in the order they are created.
DIRECTORIES = ("data", "config", "cache", "tmp", "runtime", "exports", "inbox")

#: Removed by "clear temporary data".
CLEARABLE = ("cache", "tmp", "runtime")

#: Removed by "reset this app". Adds the application's own settings, which is
#: what makes a reset different from a cache clear.
RESETTABLE = CLEARABLE + ("config", "inbox")

#: Removed by "delete this app's data". Everything the capsule holds.
DELETABLE = RESETTABLE + ("data", "exports")

_ENVIRONMENT_ROOT = "BUNNY_CAPSULE_ROOT"

#: The directory component that marks a tree as belonging to the capsule system.
#: Present in every capsule path and in no user path, so that recognising "this
#: is some capsule's private directory" does not require enumerating capsules —
#: which would be a check that silently weakened as capsules were added.
CAPSULE_MARKER = "capsules"


def default_capsule_root(root: Path | None = None) -> Path:
    """Where capsules live.

    Under the user's XDG data directory, because a capsule is per-user state: two
    accounts on one machine share no capsule, no cache and no grant. The
    environment override exists for tests, the vertical slice and the demo.
    """
    if root is not None:
        return Path(root)
    if os.environ.get(_ENVIRONMENT_ROOT):
        return Path(os.environ[_ENVIRONMENT_ROOT])
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home) if data_home else Path.home() / ".local" / "share"
    return base / "bunny" / CAPSULE_MARKER


def is_capsule_private(path: Path, *, root: Path | None = None) -> bool:
    """Whether ``path`` is inside the capsule tree at all.

    Used by the isolation planner to refuse binding one capsule's data into
    another, and by the exchange to refuse exporting *into* a capsule. Resolves
    first: a symlink in the user's Documents pointing at a capsule's ``data``
    directory is exactly the case a string check would miss.
    """
    return contains(real_path(default_capsule_root(root)), real_path(path))


@dataclass(frozen=True)
class CapsuleLayout:
    """One capsule's directories, created and checked.

    Construction does not touch the filesystem. :meth:`provision` does, and is
    idempotent, so reopening an existing capsule is the same call as creating one
    — which is what makes "opening the application reconnects to its existing
    capsule" a property of the code rather than of a branch somebody has to get
    right.
    """

    identity: CapsuleIdentity
    root: Path

    @classmethod
    def for_identity(cls, identity: CapsuleIdentity, *, root: Path | None = None) -> "CapsuleLayout":
        base = default_capsule_root(root)
        return cls(identity=identity, root=base / identity.directory_name)

    # -- paths -----------------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def directory(self, name: str) -> Path:
        """One of the capsule's own directories, checked against the list.

        Takes a name from :data:`DIRECTORIES` rather than a path, so there is no
        call site through which a caller can name a directory outside the
        capsule. The containment check below is the second line, not the first.
        """
        if name not in DIRECTORIES:
            raise CapsuleSchemaError(f"not a capsule directory: {name!r}")
        return self.root / name

    # -- creation --------------------------------------------------------

    def provision(self) -> "CapsuleLayout":
        """Create everything that is missing. Safe to call on every launch."""
        private_directory(self.root)
        for name in DIRECTORIES:
            private_directory(self.root / name)
        return self

    def exists(self) -> bool:
        return self.root.is_dir()

    # -- destruction -----------------------------------------------------

    def _inside(self, target: Path) -> Path:
        """Resolve ``target`` and require it to be inside this capsule.

        Both sides are resolved. Comparing a resolved target against an
        unresolved root fails open whenever the root itself is a symlink, which
        it is on any machine where ``/home`` links to ``/var/home``.
        """
        resolved_root = real_path(self.root)
        resolved = real_path(target)
        if not contains(resolved_root, resolved):
            raise CapsuleContainmentError(f"{target} is not inside {self.identity.application_id}'s capsule")
        return resolved

    def _remove(self, names: Iterable[str]) -> tuple[str, ...]:
        removed: list[str] = []
        for name in names:
            path = self.directory(name)
            if not path.exists():
                continue
            self._inside(path)
            shutil.rmtree(path, ignore_errors=False)
            removed.append(name)
        # Recreate the ones the capsule needs to exist, so the next launch does
        # not have to distinguish "cleared" from "never provisioned".
        for name in names:
            private_directory(self.root / name)
        return tuple(removed)

    def clear_temporary(self) -> tuple[str, ...]:
        """Remove regenerable data. The application keeps its settings and files."""
        return self._remove(CLEARABLE)

    def reset(self) -> tuple[str, ...]:
        """Return the application to a newly-installed state, keeping its documents."""
        return self._remove(RESETTABLE)

    def delete_data(self) -> tuple[str, ...]:
        """Remove everything the capsule holds, including the user's documents in it."""
        return self._remove(DELETABLE)

    def destroy(self) -> bool:
        """Remove the capsule directory entirely. Used by uninstall.

        Three checks before anything is deleted, and each one has a specific
        mistake behind it:

        * **The last component is this capsule's derived name.** A layout whose
          root was assembled by hand, or by string concatenation somewhere, does
          not delete. The name is a digest of the application id and cannot be
          arrived at accidentally.
        * **The resolved directory is inside its own resolved parent.** Catches
          the case where the capsule directory is itself a symlink pointing
          somewhere else — deleting through it would delete the target.
        * **The target is not a filesystem root or a home directory.** A
          backstop against a misconfigured root, checked by depth rather than by
          string, because it costs nothing and the failure it prevents is
          unrecoverable.
        """
        if not self.root.exists():
            return False
        if self.root.name != self.identity.directory_name:
            raise CapsuleContainmentError(
                f"{self.root} is not the directory for {self.identity.application_id}"
            )
        resolved = real_path(self.root)
        if not contains(real_path(self.root.parent), resolved) or resolved == real_path(self.root.parent):
            raise CapsuleContainmentError("the capsule directory is not inside its own parent")
        home = real_path(Path.home()) if os.path.expanduser("~") != "~" else None
        if resolved == home or len(resolved.parts) <= 2:
            raise CapsuleContainmentError(f"refusing to remove {resolved}")
        shutil.rmtree(resolved, ignore_errors=False)
        return True

    # -- accounting ------------------------------------------------------

    def usage(self) -> Mapping[str, int]:
        """Bytes per directory, plus a total. What Settings shows as storage."""
        return storage_usage(self.root)


def storage_usage(root: Path) -> Mapping[str, int]:
    """Bytes used under ``root``, per top-level directory and in total.

    Counts the *apparent* size of regular files and does not follow symlinks —
    following them would attribute a linked-to file's size to the capsule, and a
    capsule that linked to a large file elsewhere would appear to be using space
    it is not.
    """
    totals: dict[str, int] = {}
    grand = 0
    for name in DIRECTORIES:
        directory = root / name
        subtotal = 0
        if directory.is_dir():
            for current, _directories, files in os.walk(directory, followlinks=False):
                for filename in files:
                    path = Path(current) / filename
                    try:
                        status = path.lstat()
                    except OSError:
                        continue
                    if stat.S_ISREG(status.st_mode):
                        subtotal += status.st_size
        totals[name] = subtotal
        grand += subtotal
    totals["total"] = grand
    return totals
