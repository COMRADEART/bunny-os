# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""An isolation plan rendered as an argument vector, and nothing else.

Rendering is separated from planning and from execution so that the argument
vector can be *inspected* — by a test, by a diagnostic, by a person reading
``bunny-os capsule show`` — without a sandbox being built or a process being
started. Most of the security properties in this phase are properties of this
vector, and a property nobody can look at is a property nobody can check.

Three renderers, one per backend, and each is a total function over the plan: it
reads only the plan, adds nothing of its own, and refuses rather than guessing.
A renderer that quietly dropped a bind it did not know how to express would
produce a sandbox looser than the plan; a renderer that added one would make the
plan not the whole story. Both are refusals here.

**No shell, anywhere.** Every vector is a list of arguments passed to ``execve``.
There is no string that gets word-split, no ``sh -c``, no environment
interpolation. An application id, a file name or a domain that contained a
metacharacter would be an argument containing a metacharacter, and nothing more.

**The command the capsule runs comes from the manifest's package reference**, not
from a caller and never from a provider. :func:`render` takes the command as an
explicit argument so that the *caller* is the one place that decides it, and the
runtime's only caller derives it from the manifest.
"""

from __future__ import annotations

from typing import Sequence

from .backends import BackendDescriptor, backend as backend_descriptor
from .errors import CapsuleIsolationError, CapsuleSchemaError
from .isolation import IsolationPlan

__all__ = ["render", "render_bubblewrap", "render_flatpak", "render_systemd_scope"]


def _check_command(command: Sequence[str]) -> tuple[str, ...]:
    if not command:
        raise CapsuleSchemaError("a capsule launch needs a command")
    for argument in command:
        if not isinstance(argument, str):
            raise CapsuleSchemaError("every command argument must be a string")
        if "\x00" in argument:
            raise CapsuleSchemaError("a command argument may not contain a null byte")
    return tuple(command)


def _unit_prefix(plan: IsolationPlan) -> list[str]:
    """The transient systemd unit every backend is wrapped in.

    The unit is what carries the cgroup, and therefore the resource limits and
    the background-permission lifetime. It is applied for all three backends
    rather than only the weakest, so that "one application cannot make the
    desktop unusable" does not depend on which sandbox happened to be available.

    **Not a scope.** A scope is forked by whoever asks for it, so it inherits
    that process's seccomp filter and mount namespace. In the product the process
    that asks is the Companion, whose units set ``RestrictNamespaces=yes`` — and
    bubblewrap cannot build a sandbox without ``unshare(2)``. The launcher
    qualification section measures this directly: the same vector succeeds from a
    plain process and from an unhardened transient unit, and fails inside a unit
    carrying either Companion unit's own properties. Asking the *manager* for a
    transient service instead means the manager spawns it, and the capsule is
    confined by the plan it declares rather than by whatever its launcher
    happened to be confined by.

    Deliberately **not** ``--collect``. A collected unit takes its exit status
    with it, and a capsule that failed instantly was garbage-collected before
    the runtime could read one — which the executor then reported as a zero, so
    a program that could not be executed at all looked like one that had
    succeeded and written nothing. The stale unit is cleared by a
    ``reset-failed`` immediately before the next launch instead, where the name
    is needed and the status is not.
    """
    arguments = [
        "systemd-run",
        "--user",
        "--quiet",
        f"--unit={plan.identity.unit_name.removesuffix('.service')}",
        f"--description=Bunny capsule for {plan.identity.application_id}",
    ]
    for prop in plan.systemd_properties:
        arguments.extend(["--property", prop])
    return arguments


def render_bubblewrap(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """A ``bwrap`` invocation that expresses the whole plan."""
    arguments = _unit_prefix(plan)
    arguments += ["bwrap", "--die-with-parent", "--new-session"]

    for namespace in plan.unshare:
        arguments.append(f"--unshare-{namespace}")

    # A read-only /usr and the loader paths, and nothing else from the host root.
    arguments += ["--ro-bind", "/usr", "/usr", "--symlink", "usr/lib", "/lib",
                  "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/bin", "/bin",
                  "--symlink", "usr/sbin", "/sbin"]
    arguments += ["--proc", "/proc", "--dev", "/dev"]

    for device in plan.devices:
        if device in ("/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom", "/dev/tty"):
            # Provided by --dev. Naming them again would be a second mount over
            # the same path, which bwrap accepts and which makes the vector lie
            # about how many device grants there are.
            continue
        arguments += ["--dev-bind-try", device, device]

    for bind in plan.binds:
        if bind.kind == "tmpfs":
            arguments += ["--tmpfs", bind.target]
        elif bind.writable:
            arguments += ["--bind", bind.source, bind.target.rstrip("/") or "/"]
        else:
            arguments += ["--ro-bind", bind.source, bind.target.rstrip("/") or "/"]

    # The sandbox's own root, read-only, after every mount is in place.
    #
    # bwrap builds the root as a fresh tmpfs and leaves it writable, so an
    # application could create files at `/` inside its own sandbox. Nothing
    # escapes — the tmpfs dies with the namespace — but the Linux qualification
    # run recorded it as a capability the capsule had and the *unconfined*
    # control did not, which is a strange enough shape to be worth removing.
    #
    # Ordering is the whole of it, and it was measured rather than assumed: with
    # `--remount-ro /` placed here, after the binds and the tmpfs, the root
    # becomes read-only and the capsule's own seven directories and /tmp stay
    # writable, because each is its own mount and keeps its own flags. Placed
    # before them it would have made them read-only too.
    arguments += ["--remount-ro", "/"]

    arguments += ["--clearenv"]
    for key in sorted(plan.environment):
        arguments += ["--setenv", key, plan.environment[key]]

    arguments += ["--chdir", plan.environment.get("HOME", "/")]
    arguments += ["--"]
    arguments += list(_check_command(command))
    return tuple(arguments)


def render_flatpak(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """A ``flatpak run`` invocation with every default revoked and the plan added.

    ``--nofilesystem=host`` and the empty ``--socket`` set come first so that the
    application's own manifest cannot widen what Bunny decided. Flatpak applies
    overrides on top of the packaged permissions, and an override that only
    *added* would leave whatever the packager asked for in place.
    """
    arguments = _unit_prefix(plan)
    arguments += [
        "flatpak", "run",
        "--nofilesystem=host",
        "--nofilesystem=home",
        "--unshare=network" if plan.network == "none" else "--share=network",
        "--nodevice=all",
        "--no-talk-name=*",
    ]
    for device in plan.devices:
        if device == "/dev/dri":
            arguments.append("--device=dri")
    for bind in plan.binds:
        if bind.origin == "capsule" or bind.kind == "tmpfs":
            continue
        mode = "rw" if bind.writable else "ro"
        arguments.append(f"--filesystem={bind.source}:{mode}")
    for name in plan.dbus_talk:
        arguments.append(f"--talk-name={name}")
    for key in sorted(plan.environment):
        arguments.append(f"--env={key}={plan.environment[key]}")
    arguments.append(f"--command={_check_command(command)[0]}")
    arguments.append(plan.identity.application_id)
    arguments.extend(_check_command(command)[1:])
    return tuple(arguments)


def render_systemd_scope(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """Limits and nothing else.

    Deliberately does not attempt to express a bind mount or a device
    restriction. This backend does not confine, :attr:`IsolationPlan.confining`
    says so, and a renderer that produced a partially-restricting vector here
    would make the honest ``confines=False`` in :mod:`capsules.backends` false.
    """
    if plan.confining:
        raise CapsuleIsolationError("a confining plan cannot be rendered as a bare scope")
    arguments = _unit_prefix(plan)
    for key in sorted(plan.environment):
        arguments += ["--setenv", f"{key}={plan.environment[key]}"]
    arguments += list(_check_command(command))
    return tuple(arguments)


_RENDERERS = {
    "bubblewrap": render_bubblewrap,
    "flatpak": render_flatpak,
    "systemd-scope": render_systemd_scope,
}


def render(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """Render ``plan`` for its own backend."""
    descriptor: BackendDescriptor = backend_descriptor(plan.backend)
    renderer = _RENDERERS.get(descriptor.backend)
    if renderer is None:  # pragma: no cover - guarded by a test over BACKEND_IDS
        raise CapsuleIsolationError(f"no renderer for backend {plan.backend!r}")
    return renderer(plan, command)
