# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The capsule runtime: install, open, launch, stop, reset, uninstall.

This is the only module in the package that changes anything. Everything else
describes: an identity, a layout, a manifest, a lifecycle table, an isolation
plan, an argument vector. Concentrating the effects here is what makes the rest
of the package testable without a kernel, and it is also what makes the audit
complete — there is one place where something happens, so there is one place that
records it.

**Nothing runs by default.** :class:`CapsuleRuntime` takes an
:class:`Executor`, and the default is :class:`RecordingExecutor`, which builds
the whole plan, renders the whole argument vector, records both, and starts no
process. That is not a stub: it is the honest default for a repository whose own
maturity ladder distinguishes *source implemented* from *runtime validated*.
Launching for real is :class:`SubprocessExecutor`, which is selected explicitly,
refuses on a machine with no confining backend, and is the thing a VM matrix
exercises.

**A launch that cannot be isolated does not happen.** §22, applied to the
sandbox. If the backend is unavailable, if the plan cannot be built, if a grant
resolves somewhere it must not, the capsule does not start and the person is told
which of those it was. There is no path that runs the application unconfined
because the sandbox was inconvenient.

**Opening an application reconnects to its capsule.** :meth:`open` provisions
what is missing and returns the same capsule every time, because the identity is
a function of the application id. There is no per-task container, no image built
on demand, nothing torn down between launches. §6's distinction between a
persistent capsule and a disposable sandbox is this method.

**Destructive operations stop first and check containment twice.** Reset, delete
and uninstall are legal only from a stopped state — the lifecycle table enforces
it — and the paths they remove are re-resolved and re-checked inside
:class:`~capsules.layout.CapsuleLayout` immediately before the removal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Mapping, Protocol, Sequence

from trust.audit import TrustAudit
from trust.decision import Decision, Grant
from trust.declaration import UNDECLARED, PermissionDeclaration
from trust.errors import TrustError
from trust.gate import TrustGate
from trust.request import PermissionRequest, Reason
from trust.resources import Resource
from trust.store import TrustStore

from .backends import BackendDescriptor, MachineProbe, select_backend
from .command import render
from .errors import (
    CapsuleBusy,
    CapsuleError,
    CapsuleIsolationError,
    CapsuleSchemaError,
    CapsuleStateError,
    CapsuleUnavailable,
)
from .identity import CapsuleIdentity, capsule_identity
from .isolation import IsolationPlan, plan_isolation
from .layout import CapsuleLayout, default_capsule_root
from .lifecycle import DESTRUCTIVE_FROM, CapsuleState
from .manifest import CapsuleManifest

__all__ = [
    "Capsule",
    "CapsuleRuntime",
    "Executor",
    "LaunchRecord",
    "RecordingExecutor",
    "EXIT_STATUS_UNKNOWN",
    "SubprocessExecutor",
]


#: What :meth:`SubprocessExecutor.poll` reports for a unit that has ended and
#: whose exit status the manager can no longer produce. Non-zero on purpose:
#: every caller treats non-zero as "did not succeed", which is the correct
#: reading of "it ended and nobody can say how".
EXIT_STATUS_UNKNOWN = -2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LaunchRecord:
    """What a launch attempt produced, whether or not a process started."""

    application_id: str
    backend: str
    argv: tuple[str, ...]
    started: bool
    pid: int | None
    unit_name: str
    plan: IsolationPlan
    failure: str | None = None

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.application_id,
            "backend": self.backend,
            "argv": list(self.argv),
            "started": self.started,
            "pid": self.pid,
            "unitName": self.unit_name,
            "failure": self.failure,
            "plan": dict(self.plan.as_record()),
        }


class Executor(Protocol):
    """Whatever actually turns an argument vector into a process."""

    #: Whether this executor starts anything. Read by the runtime so that a
    #: recorded launch is never reported as a running application.
    starts_processes: bool

    def start(self, argv: Sequence[str], plan: IsolationPlan) -> int | None:
        ...

    def stop(self, unit_name: str) -> bool:
        ...

    #: Optional. An executor that can answer "has this exited, and how" lets the
    #: runtime reconcile a stale ``running`` instead of believing it. Read with
    #: ``getattr`` so an executor that cannot answer simply does not, rather than
    #: every executor having to implement a method it has no way to honour.
    #:
    #: def poll(self, pid: int) -> int | None: ...


@dataclass
class RecordingExecutor:
    """Builds and records; starts nothing. The default.

    Every argument vector it is given is kept, which is what the vertical slice
    and the security tests assert against. A capsule launched through this
    executor reaches ``stopped``, not ``running``: reporting an application as
    running when nothing was started would put a false statement in the one place
    a person looks to find out what is happening.
    """

    starts_processes: bool = False
    launches: list[tuple[str, ...]] = field(default_factory=list)

    def start(self, argv: Sequence[str], plan: IsolationPlan) -> int | None:
        self.launches.append(tuple(argv))
        return None

    def stop(self, unit_name: str) -> bool:
        return False


@dataclass
class SubprocessExecutor:
    """Starts the process for real. Selected explicitly, never by fallback.

    The handles are retained. That is not bookkeeping: without them the runtime
    could start a capsule and never learn how it ended, and
    :attr:`~capsules.lifecycle.CapsuleState.last_exit_code` — a field that exists
    precisely to record that — could never be filled. The Linux qualification run
    is what surfaced it, because a harness that launches an application and
    cannot ask whether it succeeded is a harness that reports every run as a
    success.

    The launcher's environment is the plan's
    :attr:`~capsules.isolation.IsolationPlan.launcher_environment` and nothing
    else — two keys, both of which ``systemd-run --user`` needs to reach the
    user's own systemd over the session bus. It is a *different* environment from
    the application's, and ``bwrap``'s ``--clearenv`` between them is what keeps
    it from reaching inside.

    This started as ``env={}``, which is the stricter-looking choice and meant
    every launch on a real Linux host failed with "Failed to connect to user
    scope bus". The Linux qualification run found it. A sandbox that cannot start
    is not a safe sandbox — it is an application that does not run and a reason
    for somebody to reach for the unconfined path.
    """

    starts_processes: bool = True
    #: pid of the application to the unit it lives in. The pid comes from the
    #: manager, not from :mod:`subprocess`: ``systemd-run`` asks for a transient
    #: service and exits, so the pid Python sees belongs to the request and not to
    #: the application. Believing it would report every capsule as having stopped
    #: the moment it started.
    _units: dict[int, str] = field(default_factory=dict)
    #: How long to wait for the manager to publish a MainPID. A started unit has
    #: one within milliseconds; this bound exists so that a unit that never starts
    #: produces "no pid" rather than a hang.
    pid_timeout: float = 10.0

    def start(self, argv: Sequence[str], plan: IsolationPlan) -> int | None:
        if not plan.confining:
            raise CapsuleIsolationError("refusing to start an application with no confinement")
        environment = dict(plan.launcher_environment)
        # A unit that failed in a previous launch keeps its name and its failed
        # state, and systemd refuses to start a unit that is already loaded and
        # failed. Clearing it here rather than using `--collect` is what lets
        # `poll` read a real exit status afterwards: a collected unit takes its
        # status with it.
        subprocess.run(  # noqa: S603
            ["systemctl", "--user", "reset-failed", plan.identity.unit_name],
            stdin=subprocess.DEVNULL, capture_output=True, check=False, env=environment,
        )
        result = subprocess.run(  # noqa: S603 - argv is a list; no shell anywhere
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
            timeout=60,
        )
        if result.returncode != 0:
            # The manager refused the job. Say why: this is the path that used to
            # be a silent "the application did not appear", and the reason is in
            # systemd-run's stderr and nowhere else.
            raise CapsuleIsolationError(
                f"the session manager refused to start the capsule: "
                f"{(result.stderr or '').strip()[:300] or f'exit {result.returncode}'}"
            )
        unit = plan.identity.unit_name
        pid = self._main_pid(unit, environment)
        if pid is not None:
            self._units[pid] = unit
        return pid

    def _show(self, unit: str, prop: str, environment: Mapping[str, str] | None = None) -> str:
        result = subprocess.run(  # noqa: S603
            ["systemctl", "--user", "show", "--property", prop, "--value", unit],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
            env=dict(environment) if environment is not None else None,
        )
        return (result.stdout or "").strip()

    def _main_pid(self, unit: str, environment: Mapping[str, str]) -> int | None:
        deadline = time.monotonic() + self.pid_timeout
        while time.monotonic() < deadline:
            value = self._show(unit, "MainPID", environment)
            if value.isdigit() and int(value) > 0:
                return int(value)
            # A unit that has already finished has no MainPID and never will.
            if self._show(unit, "ActiveState", environment) in ("inactive", "failed"):
                return None
            time.sleep(0.05)
        return None

    def poll(self, pid: int) -> int | None:
        """The exit code if the application has ended, ``None`` if it is running.

        Asked of the manager rather than of :mod:`subprocess`, because this
        executor is no longer the parent: the manager is. ``waitpid`` on a process
        that is not our child cannot answer at all, and ``os.kill(pid, 0)`` can
        answer "gone" without ever saying how.
        """
        unit = self._units.get(pid)
        if unit is None:
            return None
        if self._show(unit, "ActiveState") in ("active", "activating", "deactivating", "reloading"):
            return None
        status = self._show(unit, "ExecMainStatus")
        if status.lstrip("-").isdigit():
            return int(status)
        # The unit has ended and the manager cannot say how. Reported as
        # :data:`EXIT_STATUS_UNKNOWN` rather than as zero.
        #
        # It was zero, once, on the reasoning that "it ended" was what the
        # caller asked. That turned a program which could not be executed at all
        # into a program that had succeeded and written nothing — the capsule
        # unit failed instantly, was garbage-collected before its status could
        # be read, and the task reported OUTPUT_MISSING. A caller cannot tell an
        # invented zero from a real one, so this does not invent one.
        return EXIT_STATUS_UNKNOWN

    def wait(self, pid: int, timeout: float | None = None) -> int | None:
        """Wait for a started application. ``None`` if this executor did not start it."""
        if pid not in self._units:
            return None
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            code = self.poll(pid)
            if code is not None:
                return code
            if deadline is not None and time.monotonic() >= deadline:
                raise subprocess.TimeoutExpired(self._units[pid], timeout or 0)
            time.sleep(0.05)

    def stop(self, unit_name: str) -> bool:
        result = subprocess.run(  # noqa: S603
            ["systemctl", "--user", "stop", unit_name],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0


@dataclass
class Capsule:
    """One application's capsule: its identity, layout, manifest and state."""

    identity: CapsuleIdentity
    layout: CapsuleLayout
    manifest: CapsuleManifest
    state: CapsuleState

    def declaration(self) -> PermissionDeclaration:
        return self.manifest.declaration()

    def as_record(self) -> Mapping[str, Any]:
        return {
            "applicationId": self.identity.application_id,
            "displayName": self.manifest.display_name,
            "state": self.state.state,
            "manifest": dict(self.manifest.as_record()),
            "storage": dict(self.layout.usage()),
        }


@dataclass
class CapsuleRuntime:
    """Everything a person can do to a capsule, and the audit of having done it."""

    store: TrustStore
    audit: TrustAudit
    gate: TrustGate
    session_id: str
    root: Path = field(default_factory=default_capsule_root)
    probe: MachineProbe = field(default_factory=MachineProbe)
    executor: Executor = field(default_factory=RecordingExecutor)
    _busy: set[str] = field(default_factory=set)

    # -- opening ---------------------------------------------------------

    def install(
        self,
        manifest: CapsuleManifest,
        *,
        install_consent: bool = False,
    ) -> Capsule:
        """Create the capsule for an application, or update its manifest.

        Idempotent. Installing over an existing capsule replaces the manifest and
        leaves every directory and every grant alone — an update must not silently
        discard a person's documents or re-ask every permission.
        """
        layout = CapsuleLayout.for_identity(manifest.identity, root=self.root).provision()
        state = CapsuleState.read(layout.state_path)
        if state.state == "absent":
            state.move("provisioning").move("ready")
        elif state.state == "removed":
            raise CapsuleStateError("that capsule was removed; install creates a new one")
        stored = manifest.with_install_consent(install_consent or manifest.install_consent)
        stored.write(layout.manifest_path)
        state.write(layout.state_path)
        return Capsule(identity=manifest.identity, layout=layout, manifest=stored, state=state)

    def reconcile(self, capsule: Capsule) -> Capsule:
        """Ask whether a capsule recorded as running actually is.

        A capsule reaches ``running`` when a process starts and nothing moves it
        back when that process ends, because an ordinary application exits
        without telling anybody. Before this existed, the second launch of an
        application refused with "already running" forever — found by the Linux
        qualification run on its second probe, and it would have been found by
        the first person to close an application and open it again.

        The executor is the authority, and only for processes it started itself.
        A record from a previous session is not reconciled here: a pid can be
        reused, so :meth:`CapsuleState.reconcile_for_session` downgrades that
        case to ``unknown`` on load and it is resolved by the state table rather
        than by a guess about somebody else's process.
        """
        if capsule.state.state not in ("running", "starting"):
            return capsule
        if capsule.state.session_id != self.session_id or capsule.state.pid is None:
            return capsule
        poll = getattr(self.executor, "poll", None)
        if poll is None:
            return capsule
        exit_code = poll(capsule.state.pid)
        if exit_code is None:
            return capsule
        if capsule.state.state == "starting":
            capsule.state.move("stopped", failure="the process ended during start-up")
        else:
            capsule.state.move("stopping").move("stopped")
        capsule.state.last_exit_code = int(exit_code)
        capsule.state.last_stopped_at = _now()
        capsule.state.pid = None
        capsule.state.write(capsule.layout.state_path)
        return capsule

    def open(self, application_id: str) -> Capsule:
        """Reconnect to an application's existing capsule.

        Raises if it has never been installed. "Open creates it" would make a
        typo in an application id produce a capsule, and a capsule that exists
        because of a typo is a capsule nobody will ever look at again.
        """
        identity = capsule_identity(application_id)
        layout = CapsuleLayout.for_identity(identity, root=self.root)
        if not layout.exists():
            raise CapsuleStateError(f"{application_id} has no capsule")
        manifest = CapsuleManifest.read(layout.manifest_path)
        state = CapsuleState.read(layout.state_path).reconcile_for_session(self.session_id)
        return self.reconcile(Capsule(identity=identity, layout=layout, manifest=manifest, state=state))

    def exists(self, application_id: str) -> bool:
        try:
            identity = capsule_identity(application_id)
        except CapsuleSchemaError:
            return False
        return CapsuleLayout.for_identity(identity, root=self.root).exists()

    def list(self) -> tuple[Capsule, ...]:
        """Every installed capsule, for the Settings list.

        A directory whose manifest will not parse is skipped rather than raising:
        one broken capsule must not make the Settings page empty. The skip is
        visible — :meth:`broken` returns them — so it is not a silent loss.
        """
        found: list[Capsule] = []
        for directory in sorted(_capsule_directories(self.root)):
            try:
                manifest = CapsuleManifest.read(directory / "manifest.json")
            except (CapsuleError, OSError):
                continue
            layout = CapsuleLayout(identity=manifest.identity, root=directory)
            state = CapsuleState.read(layout.state_path).reconcile_for_session(self.session_id)
            found.append(Capsule(identity=manifest.identity, layout=layout, manifest=manifest, state=state))
        return tuple(found)

    def broken(self) -> tuple[str, ...]:
        """Capsule directories whose manifest could not be read."""
        broken: list[str] = []
        for directory in sorted(_capsule_directories(self.root)):
            try:
                CapsuleManifest.read(directory / "manifest.json")
            except (CapsuleError, OSError):
                broken.append(directory.name)
        return tuple(broken)

    # -- permissions -----------------------------------------------------

    def request_permission(
        self,
        capsule: Capsule,
        *,
        category: str,
        resource: Resource | None = None,
        purpose: str = "use",
        reason: Reason | None = None,
        request_id: str | None = None,
        task_id: str | None = None,
    ) -> Decision:
        """Ask the trust layer, on behalf of a capsule, for one permission."""
        request = PermissionRequest.build(
            request_id=request_id or f"req-{os.urandom(6).hex()}",
            application_id=capsule.identity.application_id,
            category=category,
            session_id=self.session_id,
            resource=resource,
            purpose=purpose,
            reason=reason,
            task_id=task_id,
        )
        return self.gate.check(
            request,
            declaration=capsule.declaration(),
            install_consent=capsule.manifest.install_consent,
        )

    def grants(self, capsule: Capsule) -> tuple[Grant, ...]:
        return self.store.for_application(capsule.identity.application_id)

    def effective_permissions(self, capsule: Capsule) -> Mapping[str, Any]:
        """What Settings shows for one application.

        Built from the manifest and the store together, because neither alone is
        the answer: the manifest says what could ever be asked, the store says
        what was decided, and a person wants to see both — "it can ask for your
        camera and you have not allowed it" is a different sentence from "it
        cannot ask".
        """
        held = self.grants(capsule)
        by_category: dict[str, list[Mapping[str, Any]]] = {}
        for grant in held:
            by_category.setdefault(grant.category, []).append(dict(grant.as_record()))
        declared = sorted(capsule.manifest.required_permissions | capsule.manifest.optional_permissions)
        return {
            "applicationId": capsule.identity.application_id,
            "displayName": capsule.manifest.display_name,
            "declared": declared,
            "required": sorted(capsule.manifest.required_permissions),
            "optional": sorted(capsule.manifest.optional_permissions),
            "granted": by_category,
            "unenforced": list(capsule.manifest.unenforced_permissions()),
            "storage": dict(capsule.layout.usage()),
            "state": capsule.state.state,
        }

    # -- launching -------------------------------------------------------

    def build_plan(self, capsule: Capsule, *, allow_unconfined: bool = False) -> IsolationPlan:
        """The sandbox this capsule would run in right now.

        Public because it is worth being able to look at without launching:
        ``bunny-os capsule show`` prints it, the Settings page derives the
        reachable-paths list from it, and the security tests assert on it.
        """
        backend: BackendDescriptor = select_backend(
            capsule.manifest.preferred_backend,
            self.probe,
            allow_unconfined=allow_unconfined,
        )
        return plan_isolation(
            capsule.manifest,
            self.grants(capsule),
            backend=backend,
            layout=capsule.layout,
            capsule_root=self.root,
            session_id=self.session_id,
            controllers=self.probe.cgroup_controllers,
        )

    def launch(
        self,
        capsule: Capsule,
        *,
        command: Sequence[str] | None = None,
        allow_unconfined: bool = False,
    ) -> LaunchRecord:
        """Start the application inside its capsule, or refuse and say why."""
        application_id = capsule.identity.application_id
        if application_id in self._busy:
            raise CapsuleBusy(f"another operation owns {application_id}'s capsule")
        self._busy.add(application_id)
        try:
            self.reconcile(capsule)
            if capsule.state.state in ("running", "starting"):
                raise CapsuleStateError(f"{capsule.manifest.display_name} is already running")
            if capsule.state.state == "unknown":
                # Reconcile before deciding. A stale active state is not evidence.
                capsule.state.move("stopped", failure="reconciled after a restart")
            if capsule.state.state not in ("ready", "stopped"):
                raise CapsuleStateError(f"a capsule cannot be launched from {capsule.state.state}")

            plan = self.build_plan(capsule, allow_unconfined=allow_unconfined)
            argv = render(plan, command or _default_command(capsule.manifest))

            capsule.state.move("starting")
            capsule.state.backend = plan.backend
            capsule.state.unit_name = capsule.identity.unit_name
            capsule.state.session_id = self.session_id
            capsule.state.write(capsule.layout.state_path)

            pid = self.executor.start(argv, plan)
            started = bool(self.executor.starts_processes and pid is not None)
            capsule.state.move("running" if started else "stopped")
            capsule.state.pid = pid if started else None
            capsule.state.launch_count += 1
            capsule.state.last_started_at = _now()
            if not started:
                capsule.state.last_stopped_at = _now()
            capsule.state.write(capsule.layout.state_path)

            for category in plan.portal_allow:
                self.audit.record_use(
                    application_id=application_id,
                    category=category,
                    resource=_capability_resource(),
                    grant_id=None,
                )
            for bind in plan.binds:
                if bind.origin != "grant":
                    continue
                self.audit.record_use(
                    application_id=application_id,
                    category="folders" if bind.kind == "directory" else "files",
                    resource=Resource(kind="path", identifier="", display=Path(bind.source).name, digest=""),
                    grant_id=bind.grant_id,
                )
            return LaunchRecord(
                application_id=application_id,
                backend=plan.backend,
                argv=argv,
                started=started,
                pid=pid,
                unit_name=capsule.identity.unit_name,
                plan=plan,
            )
        except (CapsuleError, TrustError) as exc:
            if capsule.state.state == "starting":
                capsule.state.move("stopped", failure=str(exc))
                capsule.state.write(capsule.layout.state_path)
            raise
        finally:
            self._busy.discard(application_id)

    def stop(self, capsule: Capsule) -> bool:
        """Stop the application and drop the permissions it held for the session."""
        self.reconcile(capsule)
        if capsule.state.state in ("stopped", "ready"):
            return False
        if capsule.state.state == "unknown":
            capsule.state.move("stopped", failure="reconciled after a restart")
        else:
            capsule.state.move("stopping")
            self.executor.stop(capsule.state.unit_name or capsule.identity.unit_name)
            capsule.state.move("stopped")
        capsule.state.last_stopped_at = _now()
        capsule.state.pid = None
        capsule.state.write(capsule.layout.state_path)
        # §11's session scope means "while you are using it", and an application
        # that has exited is not being used.
        self._drop_session_grants(capsule)
        capsule.layout.clear_temporary()
        return True

    def _drop_session_grants(self, capsule: Capsule) -> int:
        dropped = 0
        for grant in self.store.for_application(capsule.identity.application_id):
            if grant.scope == "session":
                if self.store.revoke(grant.grant_id):
                    dropped += 1
                    self.audit.record_revocation(
                        application_id=capsule.identity.application_id,
                        category=grant.category,
                        resource=grant.resource,
                        revocation="immediate",
                    )
        return dropped

    # -- maintenance -----------------------------------------------------

    def _require_stoppable(self, capsule: Capsule, what: str) -> None:
        if capsule.state.state in ("running", "starting", "stopping", "unknown"):
            raise CapsuleStateError(f"stop {capsule.manifest.display_name} before {what}")
        if capsule.state.state not in DESTRUCTIVE_FROM:
            raise CapsuleStateError(f"{what} is not possible from {capsule.state.state}")

    def clear_temporary(self, capsule: Capsule) -> tuple[str, ...]:
        self._require_stoppable(capsule, "clearing its temporary data")
        return capsule.layout.clear_temporary()

    def reset(self, capsule: Capsule) -> tuple[str, ...]:
        """Return an application to a newly-installed state, keeping its documents."""
        self._require_stoppable(capsule, "resetting it")
        capsule.state.move("resetting")
        capsule.state.write(capsule.layout.state_path)
        removed = capsule.layout.reset()
        capsule.state.move("ready")
        capsule.state.write(capsule.layout.state_path)
        return removed

    def delete_data(self, capsule: Capsule) -> tuple[str, ...]:
        """Remove everything the capsule holds, including the user's files in it."""
        self._require_stoppable(capsule, "deleting its data")
        capsule.state.move("resetting")
        capsule.state.write(capsule.layout.state_path)
        removed = capsule.layout.delete_data()
        capsule.state.move("ready")
        capsule.state.write(capsule.layout.state_path)
        return removed

    def uninstall(self, capsule: Capsule) -> Mapping[str, Any]:
        """Remove the capsule, its data and every permission it was ever given.

        The grant removal happens *first*. If the directory removal fails
        halfway, what is left behind is data with no permissions rather than
        permissions with no application — and a permission with no application is
        the record that silently re-authorises a reinstall.
        """
        self._require_stoppable(capsule, "uninstalling it")
        application_id = capsule.identity.application_id
        revoked = self.store.revoke_application(application_id)
        capsule.state.move("removed")
        capsule.state.write(capsule.layout.state_path)
        removed = capsule.layout.destroy()
        self.audit.record_revocation(
            application_id=application_id,
            category="files",
            resource=_capability_resource(),
            revocation="immediate",
        )
        return {"applicationId": application_id, "grantsRevoked": revoked, "directoryRemoved": removed}


def _capsule_directories(root: Path) -> tuple[Path, ...]:
    base = Path(root)
    if not base.is_dir():
        return ()
    return tuple(child for child in base.iterdir() if child.is_dir() and (child / "manifest.json").exists())


def _default_command(manifest: CapsuleManifest) -> tuple[str, ...]:
    """The command a capsule runs when the caller names none.

    Derived from the manifest's package source, so a caller that passes nothing
    still cannot cause an arbitrary program to run: the only thing it can cause
    to run is the application the manifest describes.
    """
    if manifest.package_source == "flatpak":
        return (manifest.package_reference,)
    reference = manifest.package_reference
    if not reference.startswith("/"):
        raise CapsuleSchemaError("a non-flatpak capsule needs an absolute program path")
    return (reference,)


def _capability_resource() -> Resource:
    from trust.resources import no_resource

    return no_resource()
