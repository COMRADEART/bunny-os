# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which isolation mechanisms exist, which are here, and which actually confine.

Bunny OS does not implement a sandbox. §7 is explicit that a mature Linux
primitive is preferred to a custom boundary wherever one exists, and three do:
Flatpak's own sandbox, Bubblewrap with user namespaces, and — for the things
neither of those covers — a systemd scope with cgroup limits.

The three are not interchangeable and the table below refuses to pretend they
are. Each backend declares the set of permission categories it *enforces*.
A grant in a category the running backend does not enforce is not silently
honoured and not silently dropped: it appears in
:attr:`~capsules.isolation.IsolationPlan.unenforced`, is shown to the person in
Settings and at install, and is recorded in the audit. A permission model that
listed restrictions it did not apply would teach people that denying works.

**A declared backend is not an available one.** The ladder is the same one
:mod:`companion.desktop.catalogue` uses, for the same reason:

``declared``   this build knows the backend exists — a property of this table.
``available``  this machine can use it *now*: the binary is present, the kernel
               allows unprivileged user namespaces, the portal is answering.
               Read from the machine, never inferred from a package being
               installed, because a binary on disk in a kernel with
               ``user.max_user_namespaces=0`` confines nothing.
``selected``   the runtime chose it for this capsule.

**The weakest backend is never selected automatically.** ``systemd-scope``
applies resource limits and nothing else; :attr:`BackendDescriptor.confines` is
``False`` for it, and :func:`select_backend` will not return a non-confining
backend unless the caller passes ``allow_unconfined=True`` — which the runtime
does only for applications the catalogue marks as system components. Falling back
silently from a sandbox to no sandbox is the exact failure §22 forbids: the safe
answer when isolation is unavailable is that the application does not start.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
from typing import Mapping

from .errors import CapsuleSchemaError, CapsuleUnavailable

__all__ = [
    "BACKENDS",
    "BACKEND_IDS",
    "BackendDescriptor",
    "MachineProbe",
    "available_backends",
    "backend",
    "select_backend",
]


@dataclass(frozen=True)
class BackendDescriptor:
    """One isolation mechanism, and exactly what it is good for."""

    backend: str
    title: str
    #: Whether this backend restricts anything at all beyond resource usage.
    confines: bool
    #: Permission categories this backend can actually enforce. A category
    #: outside this set is reported as unenforced rather than assumed.
    enforces: frozenset[str]
    #: Executables that must be present.
    programs: tuple[str, ...]
    #: Whether unprivileged user namespaces are required.
    needs_user_namespaces: bool
    #: Whether an answering xdg-desktop-portal is required for the portal-mediated
    #: categories to be enforceable.
    needs_portal: bool
    note: str


#: Portal-mediated categories. Enforcement for these is the portal saying no, not
#: a mount or a device node, so they are enforceable by any backend that runs the
#: application without a direct path to the underlying service.
_PORTAL_CATEGORIES = frozenset({
    "camera", "microphone", "screen_capture", "location", "notifications",
})

#: What a filesystem-and-namespace sandbox can enforce by construction.
_NAMESPACE_CATEGORIES = frozenset({
    "files", "folders", "network", "gpu", "usb", "bluetooth", "ipc", "credentials",
})

#: What a cgroup can enforce.
_CGROUP_CATEGORIES = frozenset({"background", "startup"})

BACKENDS: Mapping[str, BackendDescriptor] = {
    entry.backend: entry
    for entry in (
        BackendDescriptor(
            backend="flatpak",
            title="Flatpak sandbox",
            confines=True,
            enforces=_PORTAL_CATEGORIES | _NAMESPACE_CATEGORIES | _CGROUP_CATEGORIES,
            programs=("flatpak",),
            needs_user_namespaces=True,
            needs_portal=True,
            note="The application's own packaging carries the sandbox; Bunny narrows it further.",
        ),
        BackendDescriptor(
            backend="bubblewrap",
            title="Bubblewrap sandbox",
            confines=True,
            enforces=_PORTAL_CATEGORIES | _NAMESPACE_CATEGORIES | _CGROUP_CATEGORIES,
            programs=("bwrap",),
            needs_user_namespaces=True,
            needs_portal=True,
            note="For applications packaged as ordinary RPMs, which carry no sandbox of their own.",
        ),
        BackendDescriptor(
            backend="systemd-scope",
            title="Resource limits only",
            confines=False,
            enforces=frozenset(_CGROUP_CATEGORIES),
            programs=("systemd-run",),
            needs_user_namespaces=False,
            needs_portal=False,
            note="Applies limits and records permissions. Restricts nothing else, and says so.",
        ),
    )
}

BACKEND_IDS = tuple(BACKENDS)

#: Preference order for automatic selection. Flatpak first because an application
#: that ships one already has an upstream-maintained sandbox and a portal-aware
#: runtime; bubblewrap second for everything else.
_PREFERENCE = ("flatpak", "bubblewrap", "systemd-scope")


def backend(name: str) -> BackendDescriptor:
    try:
        return BACKENDS[name]
    except (KeyError, TypeError):
        raise CapsuleSchemaError(f"unknown isolation backend: {name!r}") from None


@dataclass(frozen=True)
class MachineProbe:
    """What this machine can actually do, measured rather than assumed.

    Injectable so that the tests can describe a machine instead of running on
    one, and so that a test asserting "no user namespaces means no launch" does
    not depend on the machine the suite happens to run on. :meth:`measure` is the
    only thing that touches the system.
    """

    programs: frozenset[str] = frozenset()
    user_namespaces: bool = False
    portal: bool = False
    graphical_session: bool = False
    #: cgroup v2 controllers delegated to this user's systemd manager. A limit
    #: whose controller is absent cannot be applied at all.
    #:
    #: Necessary and **not sufficient**, and this repository has the measurement
    #: that proves it: on the WSL2 qualification host the ``memory`` controller
    #: is present, ``memory.max`` reads back exactly as set, and a plain user
    #: scope still allocated 2 GB against a 256 MB ceiling. Controller presence
    #: is what can be known cheaply at launch; whether the kernel acts on the
    #: limit can only be known by exceeding it, which is what
    #: ``scripts/capsules`` does once rather than on every launch.
    cgroup_controllers: frozenset[str] = frozenset()

    @classmethod
    def measure(cls) -> "MachineProbe":
        found = {name for name in ("flatpak", "bwrap", "systemd-run") if shutil.which(name)}
        return cls(
            programs=frozenset(found),
            user_namespaces=_user_namespaces_available(),
            portal=_portal_available(),
            graphical_session=bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")),
            cgroup_controllers=_delegated_controllers(),
        )

    def supports(self, name: str) -> bool:
        entry = backend(name)
        if not all(program in self.programs for program in entry.programs):
            return False
        if entry.needs_user_namespaces and not self.user_namespaces:
            return False
        return True

    def missing_for(self, name: str) -> tuple[str, ...]:
        """Why a backend is unavailable, in words a diagnostic can print."""
        entry = backend(name)
        missing = [f"{program} is not installed" for program in entry.programs if program not in self.programs]
        if entry.needs_user_namespaces and not self.user_namespaces:
            missing.append("unprivileged user namespaces are disabled")
        if entry.needs_portal and not self.portal:
            missing.append("xdg-desktop-portal is not answering")
        return tuple(missing)


def _user_namespaces_available() -> bool:
    """Whether an unprivileged process may create a user namespace.

    Two facts, both cheap. ``/proc/self/ns/user`` must exist — no namespace
    support at all otherwise — and ``user.max_user_namespaces`` must be non-zero
    where the knob exists. A kernel with the knob at zero has the binary
    installed and confines nothing, which is the case that must not read as
    available.
    """
    if not Path("/proc/self/ns/user").exists():
        return False
    knob = Path("/proc/sys/user/max_user_namespaces")
    if knob.exists():
        try:
            return int(knob.read_text(encoding="utf-8").strip()) > 0
        except (OSError, ValueError):
            return False
    return True


#: Which controller each declared limit needs. Written out rather than inferred
#: from the property name, so that adding a limit means naming its controller.
LIMIT_CONTROLLERS: Mapping[str, str] = {
    "MemoryHigh": "memory",
    "MemoryMax": "memory",
    "TasksMax": "pids",
    "CPUWeight": "cpu",
}


def _delegated_controllers() -> frozenset[str]:
    """The cgroup v2 controllers this user's manager can hand to a scope.

    Read from the user slice rather than from the root, because delegation is
    what decides whether a ``--property`` reaches a cgroup file at all. Absent
    on a machine with no cgroup v2, which is reported as an empty set rather
    than guessed at.
    """
    uid = os.getuid()
    for candidate in (
        Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/user@{uid}.service/cgroup.controllers"),
        Path(f"/sys/fs/cgroup/user.slice/user-{uid}.slice/cgroup.controllers"),
        Path("/sys/fs/cgroup/cgroup.controllers"),
    ):
        try:
            return frozenset(candidate.read_text(encoding="utf-8").split())
        except OSError:
            continue
    return frozenset()


def _portal_available() -> bool:
    """Whether an xdg-desktop-portal is reachable on the session bus.

    Checked by the socket's existence rather than by making a call: this runs on
    every launch and a D-Bus round trip in a launch path is latency §24 asks to
    be measured. A socket that exists and does not answer is caught later, by the
    portal call itself failing, which denies.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        return False
    return Path(runtime, "bus").exists() or Path(runtime, "app").is_dir()


def available_backends(probe: MachineProbe) -> tuple[str, ...]:
    return tuple(name for name in _PREFERENCE if probe.supports(name))


def select_backend(
    preferred: str,
    probe: MachineProbe,
    *,
    allow_unconfined: bool = False,
) -> BackendDescriptor:
    """Choose the backend to run under, or refuse to run.

    Tries the preferred backend, then the preference order. Refuses rather than
    returning a non-confining backend unless the caller explicitly permits one:
    §22's fail-closed rule applied to the sandbox means an application whose
    isolation cannot be built does not start, and a silent downgrade would be the
    same defect wearing a fallback's clothes.
    """
    candidates = [preferred] + [name for name in _PREFERENCE if name != preferred]
    for name in candidates:
        entry = backend(name)
        if not entry.confines and not allow_unconfined:
            continue
        if probe.supports(name):
            return entry
    reasons = "; ".join(
        f"{name}: {', '.join(probe.missing_for(name))}"
        for name in candidates
        if backend(name).confines or allow_unconfined
    )
    raise CapsuleUnavailable(f"no isolation backend is available on this machine ({reasons or 'no candidates'})")
