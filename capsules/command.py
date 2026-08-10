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


def _scope_prefix(plan: IsolationPlan) -> list[str]:
    """The transient systemd scope every backend is wrapped in.

    The scope is what carries the cgroup, and therefore the resource limits and
    the background-permission lifetime. It is applied for all three backends
    rather than only the weakest, so that "one application cannot make the
    desktop unusable" does not depend on which sandbox happened to be available.
    """
    arguments = [
        "systemd-run",
        "--user",
        "--scope",
        "--quiet",
        f"--unit={plan.identity.unit_name.removesuffix('.scope')}",
        f"--description=Bunny capsule for {plan.identity.application_id}",
    ]
    for prop in plan.systemd_properties:
        arguments.extend(["--property", prop])
    return arguments


def render_bubblewrap(plan: IsolationPlan, command: Sequence[str]) -> tuple[str, ...]:
    """A ``bwrap`` invocation that expresses the whole plan."""
    arguments = _scope_prefix(plan)
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
    arguments = _scope_prefix(plan)
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
    arguments = _scope_prefix(plan)
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
