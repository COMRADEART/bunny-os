# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The systemd backend: the only code in Bunny OS that can change a live host.

Everything here is written on the assumption that it is the most dangerous file
in the package, because it is. The rules it follows are not stylistic:

**No shell, ever.** Every invocation is an argument array handed to
``subprocess.run`` with ``shell=False``. There is no string interpolation into a
command line anywhere in this module, so there is no quoting bug that can become
an injection. A service manifest cannot reach this layer with a command, only
with an identifier, and that identifier is validated against a regular
expression before it is used and then checked against an allowlist.

**An allowlist, not a denylist.** The backend is constructed with the exact set
of units it may operate. A unit not in that set is refused with
``unit_not_authorized``, whatever it is called. This is what stops a compromised
or merely wrong manifest from stopping ``sshd``: not that ``sshd`` is forbidden,
but that only Bunny OS's own units are permitted.

**Opt-in twice.** Constructing the backend requires ``allow_host_modification``.
Without it every mutating method refuses before it does anything, and only the
read paths work. A developer checkout that constructs this class by accident
still cannot stop a developer's services.

**Bounded.** Every subprocess gets a timeout and the timeout is enforced by
killing the child. A ``systemctl start`` on a unit with a broken ``ExecStart``
can otherwise sit in ``activating`` until its own ``TimeoutStartSec``, which is
90 seconds by default and is not the applicator's deadline to inherit.

**Never root by ambition.** This module escalates nothing, calls no ``sudo``,
and does not check whether it is privileged. It runs whatever it is given and
reports ``permission_denied`` when the system says no, which is the same
behaviour as a correctly-confined service and the correct behaviour under
privilege separation.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Mapping, Sequence

from .backends import BackendOutcome, EnforcedLimits, ServiceLimits
from .cgroup import NullCgroupController
from .state import ServiceObservation

__all__ = [
    "DEFAULT_UNIT_PREFIX",
    "SystemdBackend",
    "systemd_available",
    "unit_name_for",
    "valid_unit_name",
]

#: Units Bunny OS ships are named ``bunny-<service>.service``. The prefix is
#: what makes the allowlist checkable by shape as well as by membership.
DEFAULT_UNIT_PREFIX = "bunny-"

#: A systemd unit name Bunny OS will operate. Narrower than systemd's own rules
#: on purpose: no templates (``@``), no escapes, no path units, no slices. Every
#: character class that this excludes is one that has a special meaning
#: somewhere in systemd's namespace, and none of them is needed to name a
#: Bunny OS service.
_UNIT_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}\.service$")

#: Output kept from a failing command. Bounded because a service that writes
#: continuously to stderr must not be able to fill a constrained node's disk
#: through this backend's diagnostics.
_MAXIMUM_DIAGNOSTIC = 2048

#: systemd states mapped onto the applicator's vocabulary. ``activating`` is
#: ``starting``, not ``running``: a unit that is activating has not yet proved
#: anything, and treating it as up is how a partial start becomes a committed
#: reservation for a service that never came up.
_ACTIVE_STATES: Mapping[str, str] = {
    "active": "running",
    "activating": "starting",
    "deactivating": "stopping",
    "inactive": "stopped",
    "failed": "failed",
    "reloading": "running",
    "maintenance": "degraded",
}


def valid_unit_name(name: str) -> bool:
    return isinstance(name, str) and bool(_UNIT_NAME.match(name))


def unit_name_for(service_id: str, *, prefix: str = DEFAULT_UNIT_PREFIX) -> str:
    """The unit that implements one service.

    Derived from the service id by a fixed rule rather than read from the
    manifest. That is the whole defence: a manifest cannot name a unit, so a
    manifest cannot name somebody else's unit. If a service ever needs a unit
    name that this rule does not produce, the rule changes here, in reviewed
    code, rather than in a JSON file that ships with a service.
    """
    slug = service_id.replace(".", "-")
    name = f"{prefix}{slug}.service"
    if not valid_unit_name(name):
        raise ValueError(f"{service_id!r} does not produce a valid unit name")
    return name


def systemd_available() -> bool:
    """Whether this machine is running systemd as PID 1.

    ``/run/systemd/system`` is the documented marker and is what systemd's own
    tooling uses. Checking for the ``systemctl`` binary is not enough: a
    container image can ship it while running something else as PID 1, and a
    backend that mistook that for systemd would issue commands to a bus nobody
    is on.
    """
    return Path("/run/systemd/system").is_dir()


@dataclass
class SystemdBackend:
    """A bounded, allowlisted systemd service manager.

    ``authorized_units`` is the complete set of unit names this instance may
    touch. It is built by the caller from the registry — that is, from what
    Bunny OS itself declares — and never from anything a service supplied.
    """

    #: Unit names this backend may operate. Empty means it may operate nothing.
    authorized_units: frozenset[str] = frozenset()
    #: The second opt-in. Without it, every mutating operation refuses.
    allow_host_modification: bool = False
    #: ``--user`` rather than system units. A development default that cannot
    #: reach anything outside the invoking user's own session.
    user_scope: bool = False
    #: Applies limits when systemd cannot. Normally a
    #: :class:`~capability.apply.cgroup.CgroupController`; a null one by default
    #: so that an unconfigured backend reports honestly rather than silently.
    cgroups: Any = field(default_factory=NullCgroupController)
    unit_prefix: str = DEFAULT_UNIT_PREFIX
    name: str = "systemd"
    #: Injected for tests. Signature matches :func:`subprocess.run`'s use here.
    runner: Any = None
    #: Path to systemctl. Resolved once; never taken from the environment at
    #: call time, so a modified PATH between construction and use cannot
    #: redirect an invocation.
    systemctl: str | None = None

    def __post_init__(self) -> None:
        if self.systemctl is None:
            self.systemctl = shutil.which("systemctl")
        for unit in self.authorized_units:
            if not valid_unit_name(unit):
                raise ValueError(
                    f"{unit!r} is not a unit name this backend will accept into its allowlist"
                )

    # ------------------------------------------------------------------ #
    # Availability and authorisation
    # ------------------------------------------------------------------ #

    def available(self) -> bool:
        return systemd_available() and self.systemctl is not None

    def unavailable_reason(self) -> str:
        if not systemd_available():
            return "/run/systemd/system is absent; systemd is not the init system on this machine"
        if self.systemctl is None:
            return "systemctl was not found on PATH"
        return ""

    def unit_for(self, service_id: str) -> str | None:
        try:
            return unit_name_for(service_id, prefix=self.unit_prefix)
        except ValueError:
            return None

    def authorized(self, service_id: str) -> bool:
        unit = self.unit_for(service_id)
        return unit is not None and unit in self.authorized_units

    # ------------------------------------------------------------------ #
    # Command execution
    # ------------------------------------------------------------------ #

    def _argv(self, *arguments: str) -> list[str]:
        argv = [str(self.systemctl)]
        if self.user_scope:
            argv.append("--user")
        argv.extend(arguments)
        return argv

    def _run(self, argv: Sequence[str], timeout_seconds: float) -> tuple[int, str, str]:
        """Run one command with a hard deadline. Never raises for a failed command.

        A non-zero exit is data, not an exception: ``systemctl is-active`` exits
        3 for an inactive unit, and a backend that treated that as an error
        would be unable to observe a stopped service.
        """
        runner = self.runner if self.runner is not None else subprocess.run
        try:
            completed = runner(
                list(argv),
                capture_output=True,
                text=True,
                timeout=max(0.1, timeout_seconds),
                check=False,
                shell=False,
                # A minimal environment. Inheriting the caller's would let
                # anything that set SYSTEMD_* or LD_PRELOAD in this process
                # change what the child does.
                env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SYSTEMD_COLORS": "0"},
            )
        except subprocess.TimeoutExpired:
            return 124, "", "the command did not return inside its deadline"
        except FileNotFoundError:
            return 127, "", "systemctl could not be executed"
        except PermissionError as exc:
            return 126, "", f"permission denied: {exc}"
        except OSError as exc:
            return 125, "", f"the command could not be run: {exc}"
        return (
            int(completed.returncode),
            (completed.stdout or "")[:_MAXIMUM_DIAGNOSTIC],
            (completed.stderr or "")[:_MAXIMUM_DIAGNOSTIC],
        )

    def _classify(self, code: int, stderr: str) -> str:
        """Map an exit status onto a failure class.

        Exit codes first, text second, and the text matching is confined to the
        two phrases systemd is documented to produce for the conditions that
        have no distinct exit code. A classifier built on text alone would break
        the first time a translation was installed; one built on exit codes
        alone cannot tell a missing unit from a failed one, because systemctl
        exits 5 for the first and 1 for the second only sometimes.
        """
        if code == 124:
            return "startup_timeout"
        if code in (126, 127):
            return "backend_unavailable"
        lowered = stderr.lower()
        if "access denied" in lowered or "permission denied" in lowered or "interactive authentication required" in lowered:
            return "permission_denied"
        # The bus check comes before the missing-unit check: "Failed to connect
        # to bus: No such file or directory" contains both phrases, and reading
        # it as a missing unit would classify a dead service manager as a
        # permanent configuration error and stop the applicator retrying it.
        if "failed to connect to bus" in lowered or "no such bus" in lowered:
            return "backend_unavailable"
        if code == 5 or "not found" in lowered or "no such file" in lowered:
            return "configuration_error"
        return "unexpected_internal_error"

    def _refuse(self, operation: str, service_id: str) -> BackendOutcome | None:
        """The checks every operation shares. Order is the security property.

        Availability, then authorisation, then the modification opt-in. Asking
        for the opt-in last means an unauthorised unit is reported as
        unauthorised even in a process that would have been allowed to modify
        the host, which is the more useful diagnostic and the safer default.
        """
        if not self.available():
            return BackendOutcome(
                False, operation, service_id, "backend_unavailable", self.unavailable_reason(),
            )
        unit = self.unit_for(service_id)
        if unit is None:
            return BackendOutcome(
                False, operation, service_id, "unit_not_authorized",
                f"{service_id!r} does not produce a unit name this backend accepts",
            )
        if unit not in self.authorized_units:
            return BackendOutcome(
                False, operation, service_id, "unit_not_authorized",
                f"{unit} is not in this backend's authorised unit set",
            )
        if operation != "health" and not self.allow_host_modification:
            return BackendOutcome(
                False, operation, service_id, "permission_denied",
                "host modification is not enabled on this backend; construct it with "
                "allow_host_modification=True to operate real services",
            )
        return None

    # ------------------------------------------------------------------ #
    # Observation
    # ------------------------------------------------------------------ #

    def inspect(self, service_id: str) -> ServiceObservation:
        """Read one unit's state. Never modifies anything, needs no opt-in."""
        unit = self.unit_for(service_id)
        if unit is None:
            return ServiceObservation(
                service_id, "unknown", observed_by=self.name,
                detail=f"{service_id!r} does not produce a valid unit name",
            )
        if not self.available():
            return ServiceObservation(
                service_id, "unknown", observed_by="inferred",
                detail=self.unavailable_reason(),
            )
        if unit not in self.authorized_units:
            # Observed, but explicitly not ours. This is the state that stops a
            # reconciliation deciding it may stop somebody else's service.
            code, stdout, _ = self._run(
                self._argv("show", unit, "--property=ActiveState", "--value"), 5.0,
            )
            active = stdout.strip()
            return ServiceObservation(
                service_id,
                "externally_managed" if code == 0 and active == "active" else "unknown",
                observed_by=self.name,
                detail=f"{unit} is not in the authorised set and is not Bunny OS's to control",
            )

        code, stdout, stderr = self._run(
            self._argv(
                "show", unit,
                "--property=ActiveState", "--property=SubState",
                "--property=LoadState", "--property=MemoryMax",
                "--property=MemoryCurrent", "--property=CPUQuotaPerSecUSec",
            ),
            5.0,
        )
        if code == 124:
            return ServiceObservation(
                service_id, "unknown", observed_by="inferred",
                detail="systemctl show did not return inside its deadline",
            )
        if code != 0:
            return ServiceObservation(
                service_id, "unknown", observed_by="inferred",
                detail=f"systemctl show failed: {stderr.strip()[:200]}",
            )

        properties = _parse_show(stdout)
        if properties.get("LoadState") == "not-found":
            return ServiceObservation(
                service_id, "stopped", observed_by=self.name,
                detail=f"{unit} is not installed on this machine",
            )
        state = _ACTIVE_STATES.get(properties.get("ActiveState", ""), "unknown")
        return ServiceObservation(
            service_id,
            state,
            memory_limit_bytes=_parse_property_int(properties.get("MemoryMax")),
            enforced_memory_limit_bytes=_parse_property_int(properties.get("MemoryMax")),
            healthy=True if state == "running" else (False if state == "failed" else None),
            observed_by=self.name,
            detail=f"{unit}: {properties.get('ActiveState', '?')}/{properties.get('SubState', '?')}",
        )

    # ------------------------------------------------------------------ #
    # Mutation
    # ------------------------------------------------------------------ #

    def _operate(
        self, operation: str, service_id: str, verb: str, timeout_seconds: float,
        *extra: str,
    ) -> BackendOutcome:
        refusal = self._refuse(operation, service_id)
        if refusal is not None:
            return refusal
        unit = self.unit_for(service_id)
        assert unit is not None  # _refuse returns for the None case
        started = time.monotonic()
        code, stdout, stderr = self._run(self._argv(verb, unit, *extra), timeout_seconds)
        duration = time.monotonic() - started
        if code != 0:
            return BackendOutcome(
                False, operation, service_id,
                self._classify(code, stderr),
                f"systemctl {verb} {unit} exited {code}",
                duration_seconds=duration,
                diagnostic=_redact(stderr or stdout),
            )
        return BackendOutcome(
            True, operation, service_id,
            observation=self.inspect(service_id),
            duration_seconds=duration,
            detail=f"systemctl {verb} {unit} succeeded",
        )

    def start(
        self, service_id: str, implementation_id: str | None,
        limits: ServiceLimits, *, timeout_seconds: float = 60.0,
    ) -> BackendOutcome:
        """Apply limits, then start, then confirm.

        Limits go on before the unit runs. A service started first and limited
        second has already had a window in which it could allocate past its
        grant, and on a constrained machine that window is exactly when the
        machine is least able to survive it.
        """
        refusal = self._refuse("start", service_id)
        if refusal is not None:
            return refusal

        enforced = self.cgroups.apply(service_id, limits)
        outcome = self._operate("start", service_id, "start", timeout_seconds)
        outcome = replace(outcome, limits=enforced)
        if not outcome.ok:
            return outcome

        # systemctl start returning zero means the job was enqueued and
        # completed, not that the service is up and staying up. The state is
        # read back, and a unit that is not active is a failed start however the
        # command exited.
        observation = self.inspect(service_id)
        if observation.state in ("running", "starting"):
            return replace(outcome, observation=observation)
        return BackendOutcome(
            False, "start", service_id,
            "health_check_failure" if observation.state == "failed" else "startup_timeout",
            f"systemctl reported success but the unit is {observation.state}",
            observation=observation, limits=enforced,
            duration_seconds=outcome.duration_seconds,
        )

    def stop(self, service_id: str, *, graceful: bool = True, timeout_seconds: float = 30.0) -> BackendOutcome:
        """Stop a unit. ``graceful=False`` sends SIGKILL rather than SIGTERM.

        The ungraceful path exists for the emergency policy and is reached from
        nowhere else. It is a distinct systemctl verb rather than a flag on the
        normal one so that an audit record of a killed service is unambiguous.
        """
        if graceful:
            return self._operate("stop", service_id, "stop", timeout_seconds)
        return self._operate("stop", service_id, "kill", timeout_seconds, "--signal=SIGKILL")

    def suspend(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        """Freeze a unit's processes, keeping its memory and its state.

        ``systemctl freeze`` is a cgroup freezer operation: the service keeps
        every page it has and yields only CPU. That is the honest meaning of
        suspend here, and it is why suspending does *not* release a memory
        reservation — claiming the memory back would be a lie the ledger would
        then act on.
        """
        return self._operate("suspend", service_id, "freeze", timeout_seconds)

    def resume(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._operate("resume", service_id, "thaw", timeout_seconds)

    def reload(self, service_id: str, *, timeout_seconds: float = 30.0) -> BackendOutcome:
        return self._operate("reload", service_id, "reload", timeout_seconds)

    def apply_limits(self, service_id: str, limits: ServiceLimits, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        refusal = self._refuse("apply_limits", service_id)
        if refusal is not None:
            return refusal
        enforced = self.cgroups.apply(service_id, limits)
        return BackendOutcome(
            enforced.enforced, "apply_limits", service_id,
            None if enforced.enforced else "cgroup_unavailable",
            enforced.detail or "limits applied",
            limits=enforced,
        )

    def health(self, service_id: str, *, timeout_seconds: float = 10.0) -> BackendOutcome:
        """Confirm the service is up. A read, so it needs no modification opt-in."""
        refusal = self._refuse("health", service_id)
        if refusal is not None:
            return refusal
        observation = self.inspect(service_id)
        if observation.state == "running":
            return BackendOutcome(True, "health", service_id, observation=observation, detail="active")
        if observation.state == "starting":
            return BackendOutcome(
                False, "health", service_id, "startup_timeout",
                "the unit is still activating", observation=observation,
            )
        return BackendOutcome(
            False, "health", service_id, "health_check_failure",
            f"the unit is {observation.state}", observation=observation,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "available": self.available(),
            "unavailableReason": self.unavailable_reason(),
            "allowHostModification": self.allow_host_modification,
            "userScope": self.user_scope,
            "authorizedUnits": sorted(self.authorized_units),
            "cgroups": self.cgroups.to_json() if hasattr(self.cgroups, "to_json") else None,
        }


def authorized_units_for(registry: Any, *, prefix: str = DEFAULT_UNIT_PREFIX) -> frozenset[str]:
    """Every unit Bunny OS declares, and nothing else.

    The allowlist is derived from the registry rather than configured, so that
    adding a service to the allowlist requires shipping a manifest for it, and
    so that no configuration file exists whose editing would widen what the
    backend may touch.
    """
    units: set[str] = set()
    for service in registry.ordered():
        try:
            units.add(unit_name_for(service.id, prefix=prefix))
        except ValueError:
            continue
    return frozenset(units)


def _parse_show(stdout: str) -> dict[str, str]:
    """Parse ``systemctl show``'s ``Key=Value`` output.

    Values may contain ``=``; keys may not, so the split is bounded to one.
    """
    properties: dict[str, str] = {}
    for line in stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator:
            properties[key.strip()] = value.strip()
    return properties


def _parse_property_int(raw: str | None) -> int | None:
    """A systemd numeric property. ``infinity`` and ``[not set]`` are not limits."""
    if raw is None or raw in ("infinity", "[not set]", ""):
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    # systemd reports an unset MemoryMax as 2^64-1 on some versions.
    return None if value >= (1 << 63) else value


def _redact(text: str) -> str:
    """Strip anything that should not reach an audit record.

    Diagnostics from a service manager can contain an environment dump, and an
    environment dump can contain an API key. The patterns below are the shapes
    a credential takes in that output; anything matching is replaced rather than
    truncated, so the surrounding diagnostic stays readable.
    """
    redacted = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|CREDENTIAL)[A-Z0-9_]*)\s*=\s*\S+",
        r"\1=[redacted]",
        text,
    )
    # Bearer tokens and long opaque strings that look like keys.
    redacted = re.sub(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{8,}", "bearer [redacted]", redacted)
    redacted = re.sub(r"\b(sk|pk|ghp|gho|xox[baprs])-[A-Za-z0-9_-]{12,}", "[redacted-credential]", redacted)
    # Home directories name the user; a diagnostic does not need to.
    home = os.path.expanduser("~")
    if home and home not in ("/", ""):
        redacted = redacted.replace(home, "~")
    return redacted[:_MAXIMUM_DIAGNOSTIC]
