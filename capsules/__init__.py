# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""App Capsules: one persistent, protected environment per installed application.

The user-facing idea is one sentence: *every application runs in its own
protected space, and that space is still there next time.* The engineering
consequence is that a capsule is keyed on the **application**, not on the task,
the launch or the session. Opening an application reconnects to what is already
there — its data, its settings, its cache, and the permissions a person decided
about it — rather than building something new. That is the difference between an
App Capsule and a disposable per-task sandbox, and it is why launching is fast
enough to be the normal way applications start.

Bunny does not implement the isolation. Linux does. This package decides *what*
the sandbox should contain and hands that to Flatpak, to Bubblewrap with user
namespaces, or — where neither confines — to a systemd scope that says openly
that it only applies limits. §7's rule is followed literally: no custom security
boundary where a mature primitive already exists.

Three properties are worth stating because everything here is arranged around
them.

**The plan starts empty.** :mod:`capsules.isolation` builds a sandbox by
*adding* what grants authorise, never by starting from the user's home directory
and taking things away. A forgotten check in a subtractive design leaves the home
directory mounted; a forgotten check here leaves a capability absent.

**A launch that cannot be isolated does not happen.** There is no fallback path
that runs an application unconfined because the sandbox was unavailable. The
person is told which mechanism is missing.

**Nothing runs by default.** The runtime's default executor builds the plan,
renders the argument vector, records both and starts no process. Running for real
is an explicit choice, and this repository's own maturity ladder is the reason:
*source implemented* and *runtime validated* are different states and the code
should not blur them.

Module map:

:mod:`~capsules.identity`
    Who a capsule is. An application id can never become a path.
:mod:`~capsules.layout`
    The seven directories, and what each Settings button actually deletes.
:mod:`~capsules.manifest`
    What the application is: source, declared permissions, limits, backend.
:mod:`~capsules.lifecycle`
    The state table, including why a capsule found active after a crash goes to
    ``unknown`` rather than to ``running``.
:mod:`~capsules.backends`
    Flatpak, Bubblewrap, systemd scope — what each enforces, and the probe that
    says which are actually present.
:mod:`~capsules.isolation`
    Grants in, sandbox out. The four refusals live here.
:mod:`~capsules.command`
    The plan rendered as an argument vector, inspectable without running it.
:mod:`~capsules.exchange`
    A file in by bind mount, a result out by verified copy that never silently
    replaces the original.
:mod:`~capsules.runtime`
    The only module that changes anything.
"""

from __future__ import annotations

from .backends import BACKENDS, BACKEND_IDS, BackendDescriptor, MachineProbe, available_backends, select_backend
from .command import render
from .errors import (
    CapsuleBusy,
    CapsuleContainmentError,
    CapsuleError,
    CapsuleExportRefused,
    CapsuleIsolationError,
    CapsuleSchemaError,
    CapsuleStateError,
    CapsuleUnavailable,
)
from .exchange import ExportResult, ImportDescription, describe_import, export_artifact, user_destinations
from .identity import CapsuleIdentity, capsule_identity
from .isolation import BindMount, IsolationPlan, plan_isolation
from .layout import CapsuleLayout, default_capsule_root, is_capsule_private
from .lifecycle import STATES, CapsuleState, transition_allowed
from .manifest import CapsuleManifest, ResourceLimits
from .runtime import Capsule, CapsuleRuntime, Executor, LaunchRecord, RecordingExecutor, SubprocessExecutor

#: Bumped with ``schemas/app-capsule.schema.json``.
CAPSULE_SCHEMA_VERSION = 1

__all__ = [
    "BACKENDS",
    "BACKEND_IDS",
    "CAPSULE_SCHEMA_VERSION",
    "STATES",
    "BackendDescriptor",
    "BindMount",
    "Capsule",
    "CapsuleBusy",
    "CapsuleContainmentError",
    "CapsuleError",
    "CapsuleExportRefused",
    "CapsuleIdentity",
    "CapsuleIsolationError",
    "CapsuleLayout",
    "CapsuleManifest",
    "CapsuleRuntime",
    "CapsuleSchemaError",
    "CapsuleState",
    "CapsuleStateError",
    "CapsuleUnavailable",
    "Executor",
    "ExportResult",
    "ImportDescription",
    "IsolationPlan",
    "LaunchRecord",
    "MachineProbe",
    "RecordingExecutor",
    "ResourceLimits",
    "SubprocessExecutor",
    "available_backends",
    "capsule_identity",
    "default_capsule_root",
    "describe_import",
    "export_artifact",
    "is_capsule_private",
    "plan_isolation",
    "render",
    "select_backend",
    "transition_allowed",
    "user_destinations",
]
