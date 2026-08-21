# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Grants in, a sandbox out. The one place a permission becomes a mount.

Everything above this module talks about permissions. Everything below it talks
about mounts, device nodes, namespaces and environment variables. This is the
translation, and it is a *pure function*: manifest and grants in, an
:class:`IsolationPlan` out, no filesystem changed and no process started.
:mod:`capsules.runtime` executes the plan. Keeping the two apart is what makes
the plan testable — a test can assert that a capsule with no file grants has no
bind mount pointing into the user's home without needing a kernel that supports
namespaces.

**The plan starts empty and only grants add to it.** There is no "default home
directory" that later checks take things away from. A capsule with no grants gets
its own seven directories, a tmpfs ``/tmp``, no network namespace access, no
device beyond the three every process needs, no D-Bus destination and a
seven-variable environment. Everything else is *added* by a grant, which means a
missing check cannot widen anything — the failure mode of a subtractive design,
where forgetting one removal leaves the whole home directory mounted.

**Four refusals, each a real attack, each raising rather than skipping.**

*Another capsule's private data.* §20 forbids mounting one application's data
into another. Checked by resolved containment in the capsule tree, so a symlink
in the user's Documents that points at a capsule's ``data`` directory is caught.

*A credential directory.* ``~/.ssh``, ``~/.gnupg``, browser profiles, the
password store. A person *can* pick one of these in a file chooser, and the
capsule still does not get it: §7 lists SSH keys and browser profiles among the
things an application must not automatically receive, and "the user clicked past
a file chooser" is not the informed decision that should override it. The refusal
is reported so the surface can say why rather than failing silently.

*A path that stopped being what it was.* The grant holds a canonical path.
Between the grant and the launch the path can be replaced by a symlink, by a
directory, by a FIFO. Every source is re-resolved and re-typed at plan time; a
grant on a file whose path is now a directory does not become a directory bind.

*A target collision.* Two grants that would land on the same path inside the
sandbox. Refused rather than resolved, because either resolution silently gives
one grant the other's contents.

**The environment is built, not inherited.** ``LD_PRELOAD``, ``LD_LIBRARY_PATH``,
``PYTHONPATH``, ``GIO_MODULE_DIR``, ``GTK_MODULES``, proxy variables and every
token-shaped variable in the session are ways to change what runs inside a
sandbox from outside it. The plan carries an explicit map with a fixed key set;
:attr:`IsolationPlan.environment` is the whole environment the capsule gets.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from trust.decision import Grant
from trust.resources import NETWORK_CLASSES, NETWORK_DECLARED_ONLY, real_path

from .backends import LIMIT_CONTROLLERS, BackendDescriptor
from .errors import CapsuleContainmentError, CapsuleIsolationError, CapsuleSchemaError
from .identity import CapsuleIdentity
from .layout import CapsuleLayout, is_capsule_private
from .manifest import CapsuleManifest

__all__ = [
    "BASE_DEVICES",
    "CREDENTIAL_DIRECTORIES",
    "GRANT_TARGET_ROOT",
    "SANDBOX_DIRECTORIES",
    "BindMount",
    "IsolationPlan",
    "LAUNCHER_ENVIRONMENT_KEYS",
    "plan_isolation",
]

#: Device nodes every process needs and no permission covers. Nothing else is
#: present unless a grant adds it.
BASE_DEVICES = ("/dev/null", "/dev/zero", "/dev/full", "/dev/random", "/dev/urandom", "/dev/tty")

#: Directory names never bound into a capsule, wherever they appear in a path,
#: matched as whole components. These hold credentials, keys, tokens and browser
#: profiles. Deliberately a superset of what a file chooser would stop a person
#: from picking, because the file chooser is a convenience and this is a control.
CREDENTIAL_DIRECTORIES = frozenset({
    ".ssh", ".gnupg", ".pki", ".password-store", ".aws", ".azure", ".docker",
    ".kube", ".mozilla", ".thunderbird", ".config", ".local", ".secrets",
    ".git-credentials", ".netrc", ".authinfo", ".gnome2_private", "keyrings",
})

#: The system files a capsule needs before a network grant is usable, bound
#: read-only and only when a network class other than ``none`` is granted.
#:
#: Found by the Linux qualification run. Without them a capsule with network
#: permission could open a socket to a raw address and could not resolve a name,
#: because nothing in the sandbox told it where a resolver was. Every real
#: application would have failed, and the failure would have looked like the
#: network permission not working rather than like a missing file.
#:
#: Read-only, individually named, and absent entirely when the network class is
#: ``none`` — a capsule with no network has no use for a resolver and no reason
#: to learn the addresses of the machine's DNS servers.
#: The network classes this build actually enforces, derived from the one
#: declaration-only list in :mod:`trust.resources` so the two cannot drift.
#:
#: ``none`` is a network namespace with nothing in it — a kernel boundary.
#: ``internet`` is the absence of one. ``loopback``, ``local-network`` and
#: ``allowlisted`` are declared by the catalogue and mapped onto ``internet``,
#: because nothing here filters by subnet, by interface or by name.
#:
#: Measured rather than assumed: the qualification granted a capsule an
#: allowlist naming one domain, and the capsule connected to a different one.
#: Recorded, disclosed at every surface, and not papered over — asking the
#: application to respect the list would be enforcement by cooperation, which is
#: not enforcement.
NETWORK_ENFORCED_CLASSES = tuple(
    network_class for network_class in NETWORK_CLASSES if network_class not in NETWORK_DECLARED_ONLY
)

NETWORK_SYSTEM_FILES = (
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/host.conf",
    "/etc/services",
    "/etc/ssl/certs",
    "/etc/pki/tls/certs",
    "/etc/crypto-policies",
)

#: Where granted files appear inside the sandbox. A fixed, capsule-visible root
#: rather than the file's original location: an application that receives
#: ``/home/you/Pictures/cat.png`` at its real path learns your user name, your
#: directory layout and the names of the folders next to it. It receives
#: ``/run/bunny/files/<digest>/cat.png`` instead and learns the file name.
GRANT_TARGET_ROOT = "/run/bunny/files"

#: Where the capsule's own seven directories appear inside the sandbox. Standard
#: XDG paths, so an unmodified application finds them without configuration.
_CAPSULE_TARGETS: Mapping[str, str] = {
    "data": "/run/bunny/app/data",
    "config": "/run/bunny/app/config",
    "cache": "/run/bunny/app/cache",
    "tmp": "/run/bunny/app/tmp",
    "runtime": "/run/bunny/app/runtime",
    "exports": "/run/bunny/app/exports",
    "inbox": "/run/bunny/app/inbox",
}

#: The same table, under a name other packages may use. The Companion needs to
#: know where a capsule's exports appear *inside* the sandbox, because that is
#: the path it tells a confined program to write to — and computing it by string
#: concatenation somewhere else would be a second definition of the layout that
#: could drift from this one.
SANDBOX_DIRECTORIES: Mapping[str, str] = _CAPSULE_TARGETS

#: The complete environment a capsule receives, before grant-derived additions.
#: Keys, not a filter: an allowlist applied to the session's environment would
#: still pass whatever the session had put in those keys, and ``PATH`` from a
#: compromised session is a way to change which binary runs.
_BASE_ENVIRONMENT: Mapping[str, str] = {
    "PATH": "/usr/bin:/bin",
    "HOME": _CAPSULE_TARGETS["data"],
    "XDG_DATA_HOME": _CAPSULE_TARGETS["data"],
    "XDG_CONFIG_HOME": _CAPSULE_TARGETS["config"],
    "XDG_CACHE_HOME": _CAPSULE_TARGETS["cache"],
    "XDG_RUNTIME_DIR": _CAPSULE_TARGETS["runtime"],
    "TMPDIR": _CAPSULE_TARGETS["tmp"],
    "LANG": "C.UTF-8",
}

#: Session variables that are passed through when the corresponding permission is
#: granted, and are absent otherwise. Named individually; there is no pattern
#: match, because a pattern is how ``LD_PRELOAD`` gets in.
_CONDITIONAL_ENVIRONMENT: Mapping[str, tuple[str, ...]] = {
    "gpu": ("__GLX_VENDOR_LIBRARY_NAME", "LIBVA_DRIVER_NAME"),
}

#: The complete environment the **launcher** runs with — ``systemd-run``, not the
#: application. Two keys, and both are needed for the same reason: creating a
#: transient user scope means talking to the user's own systemd over the session
#: bus, and ``systemd-run --user`` finds that bus through exactly these.
#:
#: This is not a hole in :data:`_BASE_ENVIRONMENT`, and the ordering in
#: :func:`capsules.command.render_bubblewrap` is what makes that true: ``bwrap``
#: is given ``--clearenv`` *before* any ``--setenv``, so whatever the launcher
#: holds is discarded at the sandbox boundary and cannot reach the application.
#: The launcher and the application have separate environments on purpose.
#:
#: Found by the Linux qualification run. The executor previously started the
#: launcher with an empty environment, which is the stricter-looking choice and
#: meant every capsule launch failed with "Failed to connect to user scope bus".
#: A sandbox that cannot start is not a safe sandbox; it is an application that
#: does not run, and the pressure to "just run it without the scope" is exactly
#: the unconfined fallback §22 forbids.
LAUNCHER_ENVIRONMENT_KEYS = ("XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")


@dataclass(frozen=True)
class BindMount:
    """One path made visible inside the sandbox.

    ``origin`` records *why* the mount exists, which is what lets Settings show a
    person the list of things an application can currently reach and say which
    decision put each one there.
    """

    source: str
    target: str
    writable: bool
    kind: str
    origin: str
    grant_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("file", "directory", "tmpfs", "device"):
            raise CapsuleSchemaError(f"unknown bind kind: {self.kind!r}")
        if self.origin not in ("capsule", "grant", "system"):
            raise CapsuleSchemaError(f"unknown bind origin: {self.origin!r}")
        if not self.target.startswith("/"):
            raise CapsuleSchemaError("a bind target must be absolute")

    def as_record(self) -> Mapping[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "writable": self.writable,
            "kind": self.kind,
            "origin": self.origin,
            "grantId": self.grant_id,
        }


@dataclass(frozen=True)
class IsolationPlan:
    """A complete description of the sandbox one launch will run in.

    Complete is the operative word. A backend renders this and adds nothing of
    its own: if a capability is not in the plan the application does not get it,
    and a backend that added a mount would be a second policy engine.
    """

    identity: CapsuleIdentity
    backend: str
    binds: tuple[BindMount, ...]
    devices: tuple[str, ...]
    network: str
    network_domains: tuple[str, ...]
    environment: Mapping[str, str]
    #: The environment the *launcher* runs with, which is not the application's.
    #: See :data:`LAUNCHER_ENVIRONMENT_KEYS`.
    launcher_environment: Mapping[str, str]
    dbus_talk: tuple[str, ...]
    portal_allow: tuple[str, ...]
    unshare: tuple[str, ...]
    systemd_properties: tuple[str, ...]
    #: Granted categories the selected backend cannot enforce. Never empty
    #: silently: the runtime records this, Settings shows it, and the install
    #: prompt says it.
    unenforced: tuple[str, ...]
    #: Declared resource limits whose cgroup controller is not delegated on this
    #: machine, and therefore cannot be applied at all. Surfaced beside
    #: ``unenforced`` and for the same reason: a limit nobody applies is not a
    #: limit, and a status page that showed the declared figure without saying so
    #: would be describing a machine other than this one.
    unapplied_limits: tuple[str, ...]
    #: Grants that were refused at plan time and why. A refusal here is a security
    #: event, not a configuration detail.
    refusals: tuple[tuple[str, str], ...]
    #: Whether the plan restricts anything beyond resource usage.
    confining: bool
    #: Whether the granted network class is one this build can enforce. ``False``
    #: for ``loopback``, ``local-network`` and ``allowlisted``, which are
    #: declarations — see :data:`trust.resources.NETWORK_DECLARED_ONLY`.
    network_enforced: bool = True

    def reachable_paths(self) -> tuple[str, ...]:
        """Every user path this capsule can currently see. What Settings lists."""
        return tuple(sorted(bind.source for bind in self.binds if bind.origin == "grant"))

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.identity.application_id,
            "backend": self.backend,
            "binds": [dict(bind.as_record()) for bind in self.binds],
            "devices": list(self.devices),
            "network": self.network,
            "networkDomains": list(self.network_domains),
            "environmentKeys": sorted(self.environment),
            "launcherEnvironmentKeys": sorted(self.launcher_environment),
            "dbusTalk": list(self.dbus_talk),
            "portalAllow": list(self.portal_allow),
            "unshare": list(self.unshare),
            "systemdProperties": list(self.systemd_properties),
            "unenforced": list(self.unenforced),
            "unappliedLimits": list(self.unapplied_limits),
            "refusals": [{"grantId": gid, "reason": reason} for gid, reason in self.refusals],
            "confining": self.confining,
            "networkEnforced": self.network_enforced,
        }


def _credential_component(path: Path) -> str | None:
    for part in path.parts:
        if part in CREDENTIAL_DIRECTORIES:
            return part
    return None


def _grant_target(grant: Grant, source: Path, *, directory: bool) -> str:
    """Where a granted path appears inside the sandbox.

    Keyed by the resource digest so that two grants on files with the same name
    in different folders do not collide, and so the target does not disclose the
    original directory. The final component keeps the real name because an
    application that shows a person a file name should show the right one.
    """
    name = source.name or "item"
    return f"{GRANT_TARGET_ROOT}/{grant.resource.digest}/{name}" + ("/" if directory else "")


def plan_isolation(
    manifest: CapsuleManifest,
    grants: Sequence[Grant],
    *,
    backend: BackendDescriptor,
    layout: CapsuleLayout,
    capsule_root: Path | None = None,
    session_id: str | None = None,
    controllers: frozenset[str] | None = None,
) -> IsolationPlan:
    """Build the sandbox description for one launch.

    ``grants`` is what the trust store holds for this application *now*, so a
    permission revoked since the last launch is simply absent from the next plan
    — which is what makes ``next-launch`` revocation in
    :mod:`trust.categories` a real behaviour rather than a promise.

    Raises :class:`~capsules.errors.CapsuleIsolationError` if the plan cannot be
    built completely. It never returns a partial plan: a caller that received one
    would have to decide whether to launch with less isolation than intended, and
    that decision must not exist.
    """
    controllers = frozenset(controllers) if controllers is not None else frozenset(LIMIT_CONTROLLERS.values())
    binds: list[BindMount] = []
    devices: list[str] = list(BASE_DEVICES)
    environment = dict(_BASE_ENVIRONMENT)
    dbus_talk: list[str] = []
    portal_allow: list[str] = []
    refusals: list[tuple[str, str]] = []
    network = "none"
    network_domains: tuple[str, ...] = ()
    granted_categories: set[str] = set()

    # The capsule's own directories. Always present, always writable, always the
    # only writable places unless a grant says otherwise.
    for name, target in sorted(_CAPSULE_TARGETS.items()):
        binds.append(
            BindMount(
                source=str(layout.directory(name)),
                target=target,
                writable=True,
                kind="directory",
                origin="capsule",
            )
        )
    binds.append(BindMount(source="tmpfs", target="/tmp", writable=True, kind="tmpfs", origin="system"))

    seen_targets = {bind.target.rstrip("/") for bind in binds}

    for grant in grants:
        if grant.verdict != "allow":
            continue
        if grant.application_id != manifest.identity.application_id:
            raise CapsuleIsolationError(
                f"a grant for {grant.application_id} reached {manifest.identity.application_id}'s plan"
            )
        if not manifest.declares(grant.category):
            # A grant exists for something the manifest no longer declares — the
            # application was updated and dropped a permission. The grant is not
            # honoured, and the discrepancy is recorded rather than ignored.
            refusals.append((grant.grant_id, "no longer declared by the application"))
            continue

        category = grant.category
        granted_categories.add(category)

        if category in ("files", "folders"):
            directory = category == "folders"
            try:
                source = real_path(grant.resource.identifier.rstrip("/") or "/")
            except OSError as exc:  # pragma: no cover - realpath rarely raises
                refusals.append((grant.grant_id, f"path could not be resolved: {exc}"))
                continue
            if is_capsule_private(source, root=capsule_root):
                raise CapsuleContainmentError(
                    f"{manifest.identity.application_id} was granted a path inside another capsule"
                )
            credential = _credential_component(source)
            if credential is not None:
                refusals.append((grant.grant_id, f"{credential} holds credentials and is never shared"))
                continue
            if not source.exists():
                refusals.append((grant.grant_id, "that file is no longer there"))
                continue
            if directory and not source.is_dir():
                refusals.append((grant.grant_id, "that folder is no longer a folder"))
                continue
            if not directory and not source.is_file():
                refusals.append((grant.grant_id, "that file is no longer an ordinary file"))
                continue
            target = _grant_target(grant, source, directory=directory)
            key = target.rstrip("/")
            if key in seen_targets:
                raise CapsuleIsolationError(f"two grants would land on {key}")
            seen_targets.add(key)
            binds.append(
                BindMount(
                    source=str(source),
                    target=target,
                    writable=grant.purpose == "write",
                    kind="directory" if directory else "file",
                    origin="grant",
                    grant_id=grant.grant_id,
                )
            )
            continue

        if category == "network":
            requested = grant.resource.identifier
            head, _, tail = requested.partition(":")
            network = head
            network_domains = tuple(sorted(tail.split(","))) if tail else ()
            continue

        if category == "gpu":
            devices.append("/dev/dri")
            for key in _CONDITIONAL_ENVIRONMENT["gpu"]:
                value = os.environ.get(key)
                if value:
                    environment[key] = value
            continue

        if category == "usb":
            node = grant.resource.identifier
            if not node.startswith("/dev/") or ".." in Path(node).parts:
                refusals.append((grant.grant_id, "not a device node"))
                continue
            devices.append(node)
            continue

        if category == "bluetooth":
            dbus_talk.append("org.bluez")
            continue

        if category == "ipc":
            peer = grant.resource.identifier
            dbus_talk.append(peer)
            continue

        if category == "credentials":
            # Scoped to the capsule's own collection. The proxy destination is
            # named; the secret never passes through Bunny's own process, and
            # nothing about it reaches a log.
            dbus_talk.append("org.freedesktop.secrets")
            continue

        if category in ("camera", "microphone", "screen_capture", "location", "notifications"):
            portal_allow.append(category)
            continue

        if category in ("background", "startup", "clipboard"):
            # Enforced by the scope's lifetime, by an autostart entry Bunny owns,
            # and by the compositor respectively. No sandbox construction.
            continue

        raise CapsuleIsolationError(f"no isolation rule for category {category!r}")

    # A usable network needs a resolver and a trust store. Added after the
    # network class is known, so a capsule with no network grant gets neither.
    if network != "none":
        for path in NETWORK_SYSTEM_FILES:
            resolved = Path(path)
            if not resolved.exists():
                continue
            binds.append(
                BindMount(
                    source=str(resolved),
                    target=path,
                    writable=False,
                    kind="directory" if resolved.is_dir() else "file",
                    origin="system",
                )
            )

    unenforced = tuple(
        sorted(category for category in granted_categories if category not in backend.enforces)
    )

    # A backend that needs the portal for a portal-mediated category, running
    # without one, cannot enforce it. Recorded rather than assumed away.
    unshare = ("user", "pid", "ipc", "uts", "cgroup")
    if network == "none":
        unshare = unshare + ("net",)

    properties = list(manifest.limits.systemd_properties())
    if "background" not in granted_categories:
        # No background permission means the scope dies with the last process,
        # which is the enforcement rather than a policy statement about it.
        properties.append("KillMode=mixed")

    return IsolationPlan(
        identity=manifest.identity,
        backend=backend.backend,
        binds=tuple(binds),
        devices=tuple(dict.fromkeys(devices)),
        network=network,
        network_domains=network_domains,
        environment=environment,
        launcher_environment={
            key: os.environ[key] for key in LAUNCHER_ENVIRONMENT_KEYS if os.environ.get(key)
        },
        dbus_talk=tuple(sorted(set(dbus_talk))),
        portal_allow=tuple(sorted(set(portal_allow))),
        unshare=unshare,
        systemd_properties=tuple(properties),
        unenforced=unenforced,
        unapplied_limits=tuple(
            sorted(
                prop.split("=", 1)[0]
                for prop in properties
                if prop.split("=", 1)[0] in LIMIT_CONTROLLERS
                and LIMIT_CONTROLLERS[prop.split("=", 1)[0]] not in controllers
            )
        ),
        refusals=tuple(refusals),
        confining=backend.confines,
        network_enforced=network in NETWORK_ENFORCED_CLASSES,
    )
