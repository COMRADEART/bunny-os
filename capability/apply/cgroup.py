# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""cgroup v2 resource enforcement, and the honesty about when it is absent.

The most important behaviour in this module is the one that does nothing. On a
kernel without cgroup v2, in a container without delegation, on a read-only
hierarchy, or where a controller was simply not enabled for our subtree, the
right answer is to report that the limit is not in force and let the policy
layer decide what to do about it. Writing the file and not checking, or checking
and reporting success anyway, would put a false statement about a running system
in front of a user and under the budget engine at the same time.

So every write is read back. :class:`~capability.apply.backends.EnforcedLimits`
carries the requested figure and the effective one separately, and they are
allowed to differ.

**Bunny OS owns one subtree and touches nothing else.** Every path is built by
joining a validated service identifier onto a configured root and is then
verified to still be inside that root. There is no interface by which a manifest
can name a cgroup path, because a manifest is untrusted structured input and the
consequence of a traversal here is writing ``memory.max`` onto somebody else's
slice.

Nothing in this module runs as root by design. It writes what the calling user
has been delegated and reports what it could not.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import Any, Mapping

from .backends import EnforcedLimits, ServiceLimits

__all__ = [
    "CGROUP_CONTROLLERS",
    "CgroupController",
    "CgroupEnvironment",
    "DEFAULT_CGROUP_ROOT",
    "NullCgroupController",
    "detect_environment",
    "safe_group_name",
]

#: The kernel's canonical mount point for the unified hierarchy.
DEFAULT_CGROUP_ROOT = Path("/sys/fs/cgroup")

#: Controllers this module can use, and the attribute each limit writes to.
CGROUP_CONTROLLERS: Mapping[str, tuple[str, ...]] = {
    "memory": ("memory.max", "memory.high"),
    "cpu": ("cpu.weight", "cpu.max"),
    "pids": ("pids.max",),
    "io": ("io.weight",),
}

#: A cgroup directory name Bunny OS will create. Deliberately narrow: no dots,
#: no slashes, no leading dash. Service ids contain dots, so they are
#: transliterated rather than used raw, which also keeps the directory listing
#: readable next to whatever else is in the slice.
_SAFE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

#: The service id shape the registry already enforces. Re-checked here because
#: this module must not depend on having been called through the registry: a
#: path builder that trusts its caller is a path builder that will eventually be
#: called by something that did not check.
_SERVICE_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9-]*)+$")


class CgroupError(RuntimeError):
    """A cgroup operation that must not be attempted or could not be trusted."""


def safe_group_name(service_id: str) -> str:
    """The directory name for one service's cgroup.

    Raises rather than sanitising. Quietly rewriting ``../../system.slice`` into
    something harmless would mean an attempted traversal produced a working
    cgroup and no alarm; refusing means it produces an error somebody reads.
    """
    if not isinstance(service_id, str) or not _SERVICE_ID.match(service_id):
        raise CgroupError(
            f"{service_id!r} is not a valid Bunny OS service id and will not be turned into a cgroup path"
        )
    name = service_id.replace(".", "_")
    if not _SAFE_NAME.match(name):
        raise CgroupError(f"{service_id!r} does not produce a safe cgroup directory name")
    return name


@dataclass(frozen=True)
class CgroupEnvironment:
    """What this machine will actually let the applicator do.

    Detected once and carried, rather than probed per operation: the answers do
    not change inside a reconciliation, and probing per write would multiply
    filesystem access on a constrained node by the number of services.
    """

    version: int | None                 # 2, 1, or None when there is no hierarchy
    root: Path | None
    #: Controllers enabled for our subtree, from ``cgroup.controllers``.
    available_controllers: tuple[str, ...] = ()
    #: Whether we can create directories under the root.
    delegated: bool = False
    writable: bool = False
    containerized: bool = False
    detail: str = ""

    @property
    def usable(self) -> bool:
        return self.version == 2 and self.root is not None and self.delegated and self.writable

    def supports(self, controller: str) -> bool:
        return controller in self.available_controllers

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root": str(self.root) if self.root is not None else None,
            "availableControllers": list(self.available_controllers),
            "delegated": self.delegated,
            "writable": self.writable,
            "containerized": self.containerized,
            "usable": self.usable,
            "detail": self.detail,
        }


def detect_environment(root: Path | None = None) -> CgroupEnvironment:
    """Work out what this machine permits. Never raises; reports instead.

    Detection order matters. A missing hierarchy, a v1 hierarchy, a hierarchy we
    cannot write and a hierarchy with no delegated controllers are four
    different conditions with four different remedies, and collapsing them into
    "cgroups unavailable" would leave an administrator with nothing to fix.
    """
    base = DEFAULT_CGROUP_ROOT if root is None else root

    if not base.is_dir():
        return CgroupEnvironment(
            None, None, detail=f"{base} does not exist; this kernel exposes no cgroup hierarchy here",
        )

    controllers_file = base / "cgroup.controllers"
    if not controllers_file.is_file():
        # cgroup v1 presents per-controller directories and no cgroup.controllers.
        legacy = [name for name in ("memory", "cpu", "pids", "blkio") if (base / name).is_dir()]
        return CgroupEnvironment(
            1 if legacy else None, base,
            detail=(
                "this is a cgroup v1 hierarchy; Bunny OS enforces limits through cgroup v2 only, "
                "so no limit will be applied here"
                if legacy else
                f"{controllers_file} is absent and no v1 controller directories were found"
            ),
        )

    try:
        available = tuple(sorted(controllers_file.read_text(encoding="utf-8").split()))
    except OSError as exc:
        return CgroupEnvironment(
            2, base, detail=f"{controllers_file} could not be read ({exc}); no controller is assumed available",
        )

    # Delegation is tested by asking whether we may create a directory, not by
    # inspecting ownership: ownership is one of several ways delegation is
    # granted and the only question that matters is whether the write succeeds.
    probe = base / ".bunny-os-delegation-probe"
    delegated = False
    writable = False
    detail = ""
    try:
        probe.mkdir(exist_ok=True)
        delegated = True
        writable = True
        try:
            probe.rmdir()
        except OSError:
            pass
    except PermissionError:
        detail = f"{base} is not delegated to this user; limits cannot be applied from here"
    except OSError as exc:
        detail = f"{base} could not be written ({exc}); the hierarchy may be read-only"

    return CgroupEnvironment(
        2, base,
        available_controllers=available,
        delegated=delegated,
        writable=writable,
        containerized=Path("/.dockerenv").exists() or Path("/run/.containerenv").exists(),
        detail=detail or f"cgroup v2 with controllers {', '.join(available) or 'none'}",
    )


@dataclass
class NullCgroupController:
    """The controller for every machine that cannot enforce limits.

    Returns an :class:`EnforcedLimits` saying so. It exists so that the caller
    has no branch — there is always a controller, and it always answers
    truthfully — which removes the code path where a missing controller is
    mistaken for a successful one.
    """

    reason: str = "no cgroup v2 hierarchy is usable on this machine"
    name: str = "none"

    def available(self) -> bool:
        return False

    def apply(self, service_id: str, limits: ServiceLimits) -> EnforcedLimits:
        return EnforcedLimits(
            requested=limits,
            effective=ServiceLimits(),
            enforced=False,
            detail=self.reason,
            unavailable_controllers=tuple(sorted(CGROUP_CONTROLLERS)),
        )

    def observe(self, service_id: str) -> ServiceLimits:
        return ServiceLimits()

    def release(self, service_id: str) -> bool:
        return False

    def to_json(self) -> dict[str, Any]:
        return {"controller": self.name, "available": False, "reason": self.reason}


@dataclass
class CgroupController:
    """Writes cgroup v2 limits into a Bunny OS-owned subtree, and reads them back.

    ``subtree`` is the one directory this class will create children under. It
    defaults to ``bunny-os.slice`` beneath the detected root; nothing outside it
    is ever opened for writing, and every path is re-verified to be inside it
    after resolution so that a symlink cannot move it out.
    """

    environment: CgroupEnvironment
    subtree_name: str = "bunny-os.slice"
    name: str = "cgroup-v2"
    #: Set false to make this controller read-only. The applicator uses this for
    #: dry runs against a machine whose real limits it wants to report.
    may_write: bool = False

    def available(self) -> bool:
        return self.environment.usable and self.may_write

    # ------------------------------------------------------------------ #
    # Paths
    # ------------------------------------------------------------------ #

    @property
    def subtree(self) -> Path:
        if self.environment.root is None:
            raise CgroupError("no cgroup root was detected")
        return self.environment.root / self.subtree_name

    def path_for(self, service_id: str) -> Path:
        """The cgroup directory for one service, verified to be inside our subtree.

        The containment check is done after resolution rather than on the joined
        string, because a resolved path is what the kernel will act on and a
        string check can be defeated by a symlink that the string does not show.
        """
        candidate = self.subtree / safe_group_name(service_id)
        subtree = self.subtree
        try:
            resolved = candidate.resolve()
            root = subtree.resolve()
        except OSError as exc:
            raise CgroupError(f"{candidate} could not be resolved: {exc}") from exc
        if resolved != root and root not in resolved.parents:
            raise CgroupError(
                f"{candidate} resolves to {resolved}, which is outside the Bunny OS subtree {root}; refusing"
            )
        return candidate

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    def _write(self, path: Path, attribute: str, value: str) -> str | None:
        """Write one attribute. Returns an error description, or ``None``.

        cgroup attribute files reject invalid values with ``EINVAL`` on write
        rather than at open, and a controller that is not delegated produces
        ``EPERM``. Both are conditions to report, not to raise on: one service's
        unavailable controller must not abort the reconciliation of the others.
        """
        target = path / attribute
        try:
            target.write_text(value, encoding="ascii")
        except PermissionError:
            return f"{attribute}: permission denied"
        except FileNotFoundError:
            return f"{attribute}: the controller is not enabled for this cgroup"
        except OSError as exc:
            return f"{attribute}: {exc.strerror or exc}"
        return None

    def _read(self, path: Path, attribute: str) -> str | None:
        try:
            return (path / attribute).read_text(encoding="ascii").strip()
        except OSError:
            return None

    def apply(self, service_id: str, limits: ServiceLimits) -> EnforcedLimits:
        """Apply what this machine permits, and report exactly what took effect."""
        if not self.environment.usable:
            return NullCgroupController(
                self.environment.detail or "the cgroup hierarchy is not usable"
            ).apply(service_id, limits)
        if not self.may_write:
            return EnforcedLimits(
                limits, ServiceLimits(), False,
                detail="this controller is read-only; no limit was written",
                unavailable_controllers=(),
            )

        try:
            path = self.path_for(service_id)
        except CgroupError as exc:
            return EnforcedLimits(limits, ServiceLimits(), False, detail=str(exc))

        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return EnforcedLimits(
                limits, ServiceLimits(), False,
                detail=f"{path} could not be created ({exc}); no limit is in force",
                unavailable_controllers=tuple(sorted(CGROUP_CONTROLLERS)),
            )

        problems: list[str] = []
        unavailable: list[str] = []

        if limits.memory_max_bytes is not None or limits.memory_high_bytes is not None:
            if not self.environment.supports("memory"):
                unavailable.append("memory")
            else:
                if limits.memory_max_bytes is not None:
                    error = self._write(path, "memory.max", str(int(limits.memory_max_bytes)))
                    if error:
                        problems.append(error)
                if limits.memory_high_bytes is not None:
                    error = self._write(path, "memory.high", str(int(limits.memory_high_bytes)))
                    if error:
                        problems.append(error)

        if limits.cpu_weight is not None or limits.cpu_quota_percent is not None:
            if not self.environment.supports("cpu"):
                unavailable.append("cpu")
            else:
                if limits.cpu_weight is not None:
                    error = self._write(path, "cpu.weight", str(int(limits.cpu_weight)))
                    if error:
                        problems.append(error)
                if limits.cpu_quota_percent is not None:
                    # cpu.max is "<quota> <period>" in microseconds. A quota
                    # above 100% is legitimate on a multi-core machine and is
                    # left as the caller computed it; the budget engine is the
                    # authority on what the figure should be.
                    period = 100_000
                    quota = max(1000, int(period * limits.cpu_quota_percent / 100.0))
                    error = self._write(path, "cpu.max", f"{quota} {period}")
                    if error:
                        problems.append(error)

        if limits.process_limit is not None:
            if not self.environment.supports("pids"):
                unavailable.append("pids")
            else:
                error = self._write(path, "pids.max", str(int(limits.process_limit)))
                if error:
                    problems.append(error)

        if limits.io_weight is not None:
            if not self.environment.supports("io"):
                unavailable.append("io")
            else:
                error = self._write(path, "io.weight", f"default {int(limits.io_weight)}")
                if error:
                    problems.append(error)

        effective = self.observe(service_id)
        # Enforcement is judged by what came back out of the kernel, never by
        # whether the writes returned without error. A kernel that accepts a
        # write and clamps the value has enforced something other than what was
        # asked for, and only the read-back can tell.
        enforced = not problems and not unavailable and _covers(limits, effective)
        detail = "; ".join(problems) if problems else ""
        if unavailable:
            detail = "; ".join(filter(None, [
                detail,
                "controllers not delegated for this subtree: " + ", ".join(sorted(set(unavailable))),
            ]))
        if not enforced and not detail:
            detail = "the kernel accepted the writes but reports different effective values"
        return EnforcedLimits(
            requested=limits,
            effective=effective,
            enforced=enforced,
            detail=detail,
            unavailable_controllers=tuple(sorted(set(unavailable))),
        )

    def observe(self, service_id: str) -> ServiceLimits:
        """Read back what is actually in force for one service."""
        if not self.environment.usable:
            return ServiceLimits()
        try:
            path = self.path_for(service_id)
        except CgroupError:
            return ServiceLimits()
        if not path.is_dir():
            return ServiceLimits()

        memory_max = _parse_limit(self._read(path, "memory.max"))
        memory_high = _parse_limit(self._read(path, "memory.high"))
        weight = _parse_integer(self._read(path, "cpu.weight"))
        quota = _parse_cpu_max(self._read(path, "cpu.max"))
        pids = _parse_limit(self._read(path, "pids.max"))
        io_weight = _parse_io_weight(self._read(path, "io.weight"))
        return ServiceLimits(
            memory_max_bytes=memory_max,
            memory_high_bytes=memory_high,
            cpu_weight=weight,
            cpu_quota_percent=quota,
            process_limit=pids,
            io_weight=io_weight,
        )

    def release(self, service_id: str) -> bool:
        """Remove a service's cgroup. Only ever inside our own subtree."""
        if not self.available():
            return False
        try:
            path = self.path_for(service_id)
        except CgroupError:
            return False
        try:
            path.rmdir()
        except OSError:
            # A populated cgroup cannot be removed, which is correct: processes
            # are still in it. It will be removable once they exit.
            return False
        return True

    def to_json(self) -> dict[str, Any]:
        return {
            "controller": self.name,
            "available": self.available(),
            "mayWrite": self.may_write,
            "subtree": str(self.subtree) if self.environment.root is not None else None,
            "environment": self.environment.to_json(),
        }


def _covers(requested: ServiceLimits, effective: ServiceLimits) -> bool:
    """Whether every requested limit is actually in force, at or below its ask.

    "At or below" rather than "equal": a kernel or a parent cgroup may impose
    something stricter than we asked for, and stricter is still enforced. Looser
    is not.
    """
    pairs = (
        (requested.memory_max_bytes, effective.memory_max_bytes),
        (requested.memory_high_bytes, effective.memory_high_bytes),
        (requested.process_limit, effective.process_limit),
    )
    for wanted, actual in pairs:
        if wanted is None:
            continue
        if actual is None or actual > wanted:
            return False
    if requested.cpu_quota_percent is not None:
        if effective.cpu_quota_percent is None:
            return False
        # A percent comparison with a microsecond round trip through the kernel
        # will not be exact; a 1% tolerance is well below any figure the budget
        # engine produces and well above the rounding.
        if effective.cpu_quota_percent > requested.cpu_quota_percent + 1.0:
            return False
    return True


def _parse_limit(raw: str | None) -> int | None:
    """A cgroup byte/count limit. ``max`` means unlimited, which is not a limit."""
    if raw is None or raw == "max":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_integer(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _parse_cpu_max(raw: str | None) -> float | None:
    """``cpu.max`` is ``"<quota|max> <period>"``, in microseconds."""
    if raw is None:
        return None
    parts = raw.split()
    if len(parts) != 2 or parts[0] == "max":
        return None
    try:
        quota, period = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if period <= 0:
        return None
    return round(100.0 * quota / period, 3)


def _parse_io_weight(raw: str | None) -> int | None:
    """``io.weight`` reads back as ``"default <n>"`` plus per-device lines."""
    if raw is None:
        return None
    for token in raw.split():
        if token.isdigit():
            return int(token)
    return None


def controller_for(
    environment: CgroupEnvironment | None = None,
    *,
    may_write: bool = False,
    root: Path | None = None,
) -> Any:
    """The right controller for this machine: a real one, or an honest null one."""
    resolved = environment if environment is not None else detect_environment(root)
    if not resolved.usable:
        return NullCgroupController(
            resolved.detail or "no usable cgroup v2 hierarchy was detected"
        )
    return CgroupController(resolved, may_write=may_write)
