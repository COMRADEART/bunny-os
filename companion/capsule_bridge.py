# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The seam between a person's request and work happening inside an App Capsule.

This module lives outside :mod:`capsules` for the same reason
:mod:`companion.desktop_bridge`, :mod:`companion.capability_bridge` and
:mod:`companion.agent_bridge` live outside the packages they bridge: "that
subsystem holds no task authority" stays checkable by reading one directory.
Nothing under ``capsules/`` imports the companion runtime, the store, the task
model or the approval gate. The authority facts arrive here as values, and this
file is the only place they meet.

The route is fixed and one-way::

    a person's request
      -> a capability slug           (companion.intents, or the caller)
      -> a choice between applications (catalog.selection)
      -> a person picks
      -> a capsule, installed or opened (capsules.runtime)
      -> permission asked for exactly the named inputs (trust.gate)
      -> the tool runs inside the capsule
      -> the artefact is exported to an approved place (capsules.exchange)
      -> a workspace projection says what happened

Four properties are the point of the whole file.

**Only what the person named is asked for.** The coordinator takes the input
paths as *values from the caller*, one permission request per file, purpose
``read``. There is no code path that asks for a folder because a file in it was
mentioned, and no path that widens ``read`` to ``write``. §9's example — a
graphics application should not get all of Pictures because one image was opened
— is a property of :meth:`CapsuleTaskCoordinator.prepare` rather than a rule
somebody follows.

**A denied permission stops the task.** Not "continues without the file". A task
that carried on after a refusal would either fail confusingly later or, worse,
do something partial that looks like success.

**The original survives.** The tool writes into the capsule's ``exports``
directory, and the export is a copy to a *new* path. Overwriting the input is
reachable only through an explicit request, carries its own ``write`` grant, and
still keeps a copy aside.

**The workspace holds no reasoning.** §17 forbids exposing chain-of-thought.
:class:`TaskWorkspace` has fields for the task, the application, the authorised
files, the major actions, progress, permission requests, warnings, outputs and
completion — and no field for why a model chose anything. A step's ``detail`` is
a fixed string from :data:`STEP_LABELS`, not free text a provider supplies.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from capsules.errors import CapsuleError, CapsuleExportRefused
from capsules.isolation import SANDBOX_DIRECTORIES
from capsules.exchange import ExportResult, describe_import, export_artifact, user_destinations
from capsules.manifest import CapsuleManifest, ResourceLimits
from capsules.runtime import Capsule, CapsuleRuntime, LaunchRecord
from catalog.entry import CatalogEntry
from catalog.registry import CatalogRegistry
from catalog.selection import ChoiceSet, MachineFacts, choices_for
from trust.decision import Decision
from trust.errors import TrustError
from trust.request import Reason
from trust.resources import path_resource

from .errors import CompanionError

__all__ = [
    "STEP_LABELS",
    "TASK_STATES",
    "WORKSPACE_ACTIONS",
    "CapsuleTaskCoordinator",
    "CapsuleTaskError",
    "CapsuleTaskResult",
    "CapsuleProcessTool",
    "CapsuleTool",
    "RecordingTool",
    "TaskStep",
    "TaskWorkspace",
    "ToolOutcome",
]


class CapsuleTaskError(CompanionError):
    """A capsule task could not be prepared or could not be run."""


#: Every step a capsule task can be in, in order. Fixed so the workspace shows
#: the same seven rows for every task and a person learns the shape once.
STEP_LABELS: Mapping[str, str] = {
    "choose": "Finding an app that can do this",
    "install": "Setting up its protected space",
    "permission": "Asking you about the file",
    "open": "Opening the app in its space",
    "work": "Doing the work",
    "export": "Putting the result where you can find it",
    "done": "Finished",
}

TASK_STATES = ("preparing", "waiting_for_you", "working", "completed", "failed", "cancelled")

#: What a person may do to a running task. Computed from state rather than
#: declared per surface, so the floating panel, the Companion bubble and the
#: keyboard-only path offer the same set.
WORKSPACE_ACTIONS = ("watch", "minimise", "cancel", "inspect_permissions", "open_application", "view_result")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TaskStep:
    """One row in the visible workspace.

    ``detail`` is drawn from a closed vocabulary or is a file name. It is never a
    sentence a provider wrote, and never an explanation of a decision: those are
    the two ways reasoning leaks into a surface that must not carry it.
    """

    key: str
    label: str
    state: str
    detail: str = ""

    def as_record(self) -> Mapping[str, Any]:
        return {"key": self.key, "label": self.label, "state": self.state, "detail": self.detail}


@dataclass(frozen=True)
class TaskWorkspace:
    """What the user sees while Bunny works, and nothing more.

    A projection: it is derived from the coordinator's record and decides
    nothing. A defect here shows a person the wrong row; it cannot make the task
    do the wrong thing.
    """

    task_id: str
    title: str
    state: str
    application_id: str | None
    application_name: str | None
    steps: tuple[TaskStep, ...]
    authorised_files: tuple[str, ...]
    permissions: tuple[Mapping[str, Any], ...]
    warnings: tuple[str, ...]
    outputs: tuple[Mapping[str, Any], ...]
    actions: tuple[str, ...]
    summary: str
    started_at: str
    finished_at: str | None = None

    def as_record(self) -> Mapping[str, Any]:
        return {
            "taskId": self.task_id,
            "title": self.title,
            "state": self.state,
            "applicationId": self.application_id,
            "applicationName": self.application_name,
            "steps": [dict(step.as_record()) for step in self.steps],
            "authorisedFiles": list(self.authorised_files),
            "permissions": [dict(entry) for entry in self.permissions],
            "warnings": list(self.warnings),
            "outputs": [dict(entry) for entry in self.outputs],
            "actions": list(self.actions),
            "summary": self.summary,
            "startedAt": self.started_at,
            "finishedAt": self.finished_at,
        }


@dataclass(frozen=True)
class ToolOutcome:
    """What a tool says it produced, before Bunny checks any of it.

    ``artifact_names`` are *names in the capsule's exports directory*, never
    paths. A tool that returned a path would be choosing where the result comes
    from, and the export refuses anything that is not a plain name anyway; making
    the type a name means the refusal is at the boundary rather than three calls
    later.
    """

    artifact_names: tuple[str, ...]
    ok: bool = True
    failure: str | None = None
    #: Bounded, user-facing progress notes. Not reasoning: a tool that put its
    #: deliberation here would be putting it on a person's screen, so the length
    #: is capped and the field is documented as a status line.
    notes: tuple[str, ...] = ()


class CapsuleTool(Protocol):
    """Whatever actually does the work inside the capsule.

    A tool may optionally declare ``command``, in which case the *launch itself*
    is the work: the coordinator starts the capsule running that argument vector
    and :meth:`run` waits for it and reports what appeared. A tool without
    ``command`` is started alongside a default launch and does the work in this
    process, which is what :class:`RecordingTool` does and is honest only
    because that tool makes no claim about a third-party application.

    The distinction matters and is not cosmetic. With ``command``, the process
    that reads the granted file is the confined one; without it, the process
    that reads the granted file is Bunny. Only the first is a measurement of the
    sandbox.

    ::

        def command(self, *, capability: str, inputs: Sequence[str],
                    output_directory: str, parameters: Mapping[str, Any],
                    program: str) -> tuple[str, ...]: ...
    """

    def run(
        self,
        capsule: Capsule,
        *,
        capability: str,
        inputs: Sequence[str],
        output_directory: Path,
    ) -> ToolOutcome:
        ...


@dataclass
class RecordingTool:
    """Does the work by copying the input to the output. The default.

    Not a mock in the pejorative sense: it exercises every part of the path that
    is this repository's business — the permission, the bind, the capsule's own
    directories, the export, the digest check and the workspace — while making no
    claim about a third-party application's behaviour, which this phase has not
    measured. A test that wants a real application substitutes one.
    """

    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    suffix: str = "-bunny"

    def run(
        self,
        capsule: Capsule,
        *,
        capability: str,
        inputs: Sequence[str],
        output_directory: Path,
    ) -> ToolOutcome:
        self.calls.append((capability, tuple(inputs)))
        produced: list[str] = []
        for sandbox_path in inputs:
            source_name = Path(sandbox_path).name
            stem, dot, extension = source_name.rpartition(".")
            name = f"{stem}{self.suffix}.{extension}" if dot else f"{source_name}{self.suffix}"
            (output_directory / name).write_bytes(b"")
            produced.append(name)
        return ToolOutcome(artifact_names=tuple(produced), notes=("Worked on the file you chose.",))


@dataclass
class CapsuleProcessTool:
    """Does the work by *being* the capsule's process. The production tool.

    The argument vector is built from three trusted sources and nothing else:
    the program comes from the application's manifest, the flag names come from
    :mod:`companion.capsule_tasks`' operation table, and the values are the
    sandbox paths the grant produced plus parameters that have already been
    validated to a bounded integer. There is no string from a person anywhere in
    it, and no shell to interpret one if there were.

    Waiting is done against the executor rather than by sleeping: the runtime
    records the manager's ``MainPID`` and asks systemd whether the unit is still
    active, so "finished" means the transient service finished. A poll loop over
    the exports directory would report success as soon as the first byte of a
    partially written file appeared.
    """

    #: The validated parameters for this one run. Set by the caller immediately
    #: before :meth:`run`; a tool instance is never shared between tasks.
    parameters: Mapping[str, Any] = field(default_factory=dict)
    #: The name Bunny chose for the result. The application is told where to
    #: write; it does not choose, and a file under any other name is not
    #: collected.
    output_name: str = ""
    timeout_seconds: float = 120.0
    #: Set after :meth:`run`. The exit status of the confined process, and the
    #: stderr it produced, for the audit record and the Details view.
    exit_code: int | None = None
    detail: str = ""

    def command(
        self,
        *,
        capability: str,
        inputs: Sequence[str],
        output_directory: str,
        parameters: Mapping[str, Any],
        program: str,
    ) -> tuple[str, ...]:
        if capability != "resize-image":
            raise CapsuleTaskError(f"no argument vector is defined for {capability!r}")
        if len(inputs) != 1:
            raise CapsuleTaskError("this operation takes exactly one input")
        width = parameters.get("width")
        if not isinstance(width, int) or isinstance(width, bool):
            raise CapsuleTaskError("width must have been validated before a command is built")
        return (
            program,
            "resize",
            "--input", str(inputs[0]),
            "--output", f"{output_directory.rstrip('/')}/{self.output_name}",
            "--width", str(width),
        )

    def run(
        self,
        capsule: Capsule,
        *,
        capability: str,
        inputs: Sequence[str],
        output_directory: Path,
    ) -> ToolOutcome:
        """Wait for the launched process, then report what it left behind.

        The presence of the file is checked here and *verified* by the export,
        which is the boundary that owns "is this really an artefact of this
        capsule". This method's job is only to turn "the unit ended" into "the
        name Bunny asked for exists", and to refuse the two ways that can be
        misread: a process that exited non-zero, and a process that exited zero
        having written nothing.
        """
        produced = output_directory / self.output_name
        if self.exit_code is None:
            return ToolOutcome((), ok=False, failure="the app never started")
        if self.exit_code != 0:
            # The application's lines, not systemd's. The manager's own
            # "Failed with result 'exit-code'" is the last line of the block and
            # says only that something failed — which is the thing already
            # known. Taking the last line got exactly that and threw away the
            # program's explanation directly above it.
            said = ""
            spoken = [
                line for line in self.detail.splitlines()
                if line.strip() and ".service:" not in line
            ]
            if spoken:
                said = ": " + "; ".join(spoken[-3:])
            return ToolOutcome(
                (), ok=False,
                failure=f"the app stopped with status {self.exit_code}{said}",
            )
        if not produced.is_file():
            return ToolOutcome(
                (), ok=False,
                failure="the app finished without producing the file",
            )
        return ToolOutcome(
            artifact_names=(self.output_name,),
            notes=("Worked on the file you chose.",),
        )


@dataclass(frozen=True)
class CapsuleTaskResult:
    """Everything that happened, for the record and for the sentence Bunny says."""

    task_id: str
    state: str
    application_id: str | None
    decisions: tuple[Decision, ...]
    exports: tuple[ExportResult, ...]
    launch: LaunchRecord | None
    workspace: TaskWorkspace
    failure: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.state == "completed"


@dataclass
class CapsuleTaskCoordinator:
    """Runs one capability inside one application's capsule, and says so honestly."""

    runtime: CapsuleRuntime
    registry: CatalogRegistry
    tool: CapsuleTool = field(default_factory=RecordingTool)
    machine: MachineFacts = field(default_factory=MachineFacts)

    # -- choosing --------------------------------------------------------

    def choices(self, capability: str) -> ChoiceSet:
        """The applications that could do this, with the commercial option shown."""
        installed = frozenset(
            capsule.identity.application_id for capsule in self.runtime.list()
        )
        facts = replace(self.machine, installed_application_ids=installed)
        return choices_for(capability, self.registry, machine=facts)

    # -- preparing -------------------------------------------------------

    def ensure_capsule(self, entry: CatalogEntry) -> Capsule:
        """Open the application's capsule, installing it the first time.

        Idempotent, and the manifest is rebuilt from the catalogue entry on every
        call so that a catalogue update narrowing a permission narrows the
        installed capsule too. Widening works the other way: a category added to
        the entry becomes *askable*, not granted.
        """
        manifest = CapsuleManifest(
            identity=self.runtime_identity(entry.application_id),
            display_name=entry.name,
            package_source=entry.package_source,
            package_reference=entry.package_reference,
            preferred_backend=entry.preferred_backend,
            required_permissions=frozenset(entry.required_permissions),
            optional_permissions=frozenset(entry.optional_permissions),
            permission_reasons=dict(entry.permission_reasons),
            network_ceiling=entry.network_ceiling,
            network_domains=frozenset(entry.network_domains),
            limits=ResourceLimits(),
            catalog_entry_id=entry.entry_id,
        )
        existing_consent = False
        if self.runtime.exists(entry.application_id):
            existing_consent = self.runtime.open(entry.application_id).manifest.install_consent
        return self.runtime.install(manifest, install_consent=existing_consent)

    @staticmethod
    def runtime_identity(application_id: str):  # type: ignore[no-untyped-def]
        from capsules.identity import capsule_identity

        return capsule_identity(application_id)

    # -- running ---------------------------------------------------------

    def run(
        self,
        *,
        task_id: str,
        capability: str,
        entry_id: str,
        inputs: Sequence[Path],
        destination: Path,
        request_text: str | None = None,
        overwrite_inputs: bool = False,
        parameters: Mapping[str, Any] | None = None,
    ) -> CapsuleTaskResult:
        """Do the work, or stop at the first refusal and say which one it was."""
        started = _now()
        steps: list[TaskStep] = []
        decisions: list[Decision] = []
        warnings: list[str] = []
        authorised: list[str] = []
        exports: list[ExportResult] = []
        launch: LaunchRecord | None = None
        entry: CatalogEntry | None = None
        capsule: Capsule | None = None

        def workspace(state: str, summary: str, finished: str | None = None) -> TaskWorkspace:
            return TaskWorkspace(
                task_id=task_id,
                title=request_text or STEP_LABELS["work"],
                state=state,
                application_id=entry.application_id if entry else None,
                application_name=entry.name if entry else None,
                steps=tuple(steps),
                authorised_files=tuple(authorised),
                permissions=tuple(
                    {
                        "category": decision.category,
                        "resource": decision.resource.display,
                        "verdict": decision.verdict,
                        "scope": decision.scope,
                        "reasonCode": decision.reason_code,
                    }
                    for decision in decisions
                ),
                warnings=tuple(warnings),
                outputs=tuple(dict(export.as_record()) for export in exports),
                actions=_actions_for(state),
                summary=summary,
                started_at=started,
                finished_at=finished,
            )

        def fail(message: str) -> CapsuleTaskResult:
            return CapsuleTaskResult(
                task_id=task_id,
                state="failed",
                application_id=entry.application_id if entry else None,
                decisions=tuple(decisions),
                exports=tuple(exports),
                launch=launch,
                workspace=workspace("failed", message, finished=_now()),
                failure=message,
            )

        # 1. Choose. The entry is named by the caller because a person picked it;
        #    this method never picks one on their behalf.
        try:
            entry = self.registry.entry(entry_id)
        except Exception as exc:  # noqa: BLE001 - catalogue errors become task failures
            steps.append(TaskStep("choose", STEP_LABELS["choose"], "failed", str(exc)))
            return fail("Bunny could not find that app in its catalogue.")
        if capability not in entry.capabilities:
            steps.append(TaskStep("choose", STEP_LABELS["choose"], "failed"))
            return fail(f"{entry.name} does not do that.")
        if not entry.installable:
            steps.append(TaskStep("choose", STEP_LABELS["choose"], "failed"))
            return fail(entry.sandbox_note or f"Bunny cannot install {entry.name} on this computer.")
        steps.append(TaskStep("choose", STEP_LABELS["choose"], "done", entry.name))

        # 2. Install or reopen the capsule.
        try:
            capsule = self.ensure_capsule(entry)
        except (CapsuleError, TrustError) as exc:
            steps.append(TaskStep("install", STEP_LABELS["install"], "failed", str(exc)))
            return fail(f"Bunny could not set up {entry.name}'s protected space.")
        steps.append(TaskStep("install", STEP_LABELS["install"], "done"))
        if capsule.manifest.unenforced_permissions():
            warnings.append(
                "Some of this app's permissions are recorded but not enforced in this build: "
                + ", ".join(capsule.manifest.unenforced_permissions())
            )

        # 3. Permission, one request per named input, read only.
        sandbox_inputs: list[str] = []
        for source in inputs:
            try:
                # The user's own directory names, so the prompt says
                # "Pictures/cat.png" rather than an absolute path that also
                # discloses their account name and their folder layout.
                resource = path_resource(source, roots=user_destinations())
            except Exception as exc:  # noqa: BLE001
                steps.append(TaskStep("permission", STEP_LABELS["permission"], "failed", str(exc)))
                return fail("Bunny could not find that file.")
            decision = self.runtime.request_permission(
                capsule,
                category="files",
                resource=resource,
                purpose="write" if overwrite_inputs else "read",
                reason=Reason(source="task", text=request_text) if request_text else None,
                task_id=task_id,
            )
            decisions.append(decision)
            if not decision.allowed:
                steps.append(TaskStep("permission", STEP_LABELS["permission"], "refused", resource.display))
                return fail(_refusal_sentence(decision, entry.name))
            authorised.append(resource.display)
            sandbox_inputs.append(describe_import(resource, writable=overwrite_inputs).sandbox_path)
        steps.append(TaskStep("permission", STEP_LABELS["permission"], "done", ", ".join(authorised)))

        # 4. Open the capsule. The launch is what applies the isolation; the tool
        #    runs against the capsule's own directories either way, so a recorded
        #    launch still exercises the plan and still refuses when it cannot be
        #    built.
        # A tool that declares `command` makes the launch *be* the work: the
        # confined process is the one that reads the granted file. A tool
        # without one is started alongside a default launch and does the work
        # here, which exercises the plan and claims nothing about an
        # application. The vector is built from the manifest's program, the
        # operation table's flags and already-validated values — never from the
        # request.
        command = None
        build_command = getattr(self.tool, "command", None)
        if build_command is not None:
            try:
                command = build_command(
                    capability=capability,
                    inputs=tuple(sandbox_inputs),
                    output_directory=SANDBOX_DIRECTORIES["exports"],
                    parameters=dict(parameters or {}),
                    program=capsule.manifest.package_reference,
                )
            except CapsuleTaskError as exc:
                steps.append(TaskStep("open", STEP_LABELS["open"], "failed", str(exc)))
                return fail(f"Bunny could not work out how to ask {entry.name} to do that.")
        try:
            capsule = self.runtime.open(entry.application_id)
            launch = self.runtime.launch(capsule, command=command)
        except (CapsuleError, TrustError) as exc:
            steps.append(TaskStep("open", STEP_LABELS["open"], "failed", str(exc)))
            return fail(f"Bunny could not open {entry.name} safely, so it did not open it at all.")
        steps.append(TaskStep("open", STEP_LABELS["open"], "done", launch.backend))

        # Wait for the confined process before asking what it produced. The
        # executor asks the manager whether the transient unit is still active;
        # this is not a sleep, and "finished" means the unit finished.
        if command is not None and launch.started and launch.pid is not None:
            wait = getattr(self.runtime.executor, "wait", None)
            timeout = getattr(self.tool, "timeout_seconds", 120.0)
            try:
                exit_code = wait(launch.pid, timeout=timeout) if wait else None
            except Exception:  # noqa: BLE001 - a timeout is a task failure, not a crash
                self.runtime.stop(capsule)
                steps.append(TaskStep("work", STEP_LABELS["work"], "failed", "timed out"))
                return fail(f"{entry.name} took too long, so Bunny stopped it.")
            self.tool.exit_code = exit_code
            if exit_code not in (0, None):
                # What the program said, from the journal, for the Details view.
                diagnostics = getattr(self.runtime.executor, "diagnostics", None)
                if diagnostics is not None:
                    self.tool.detail = diagnostics(launch.pid)
        elif command is not None:
            self.tool.exit_code = None
        for grant_id, reason in launch.plan.refusals:
            warnings.append(reason)

        # 5. The work itself.
        try:
            outcome = self.tool.run(
                capsule,
                capability=capability,
                inputs=tuple(sandbox_inputs),
                output_directory=capsule.layout.directory("exports"),
            )
        except Exception as exc:  # noqa: BLE001 - a tool failing is a task failure
            steps.append(TaskStep("work", STEP_LABELS["work"], "failed", type(exc).__name__))
            return fail(f"{entry.name} could not finish that.")
        if not outcome.ok:
            steps.append(TaskStep("work", STEP_LABELS["work"], "failed"))
            return fail(outcome.failure or f"{entry.name} could not finish that.")
        steps.append(TaskStep("work", STEP_LABELS["work"], "done"))

        # 6. Export. One artefact at a time, each verified, none overwriting an
        #    input unless that was explicitly asked for.
        originals = [Path(source) for source in inputs]
        for index, name in enumerate(outcome.artifact_names):
            original = originals[index] if index < len(originals) else None
            try:
                exports.append(
                    export_artifact(
                        capsule.layout,
                        name,
                        destination_root=destination,
                        original=original,
                        overwrite=overwrite_inputs,
                        capsule_root=self.runtime.root,
                    )
                )
            except (CapsuleExportRefused, CapsuleError) as exc:
                steps.append(TaskStep("export", STEP_LABELS["export"], "failed", str(exc)))
                return fail(f"The result could not be saved: {exc}")
        steps.append(
            TaskStep("export", STEP_LABELS["export"], "done", ", ".join(export.display for export in exports))
        )
        # Stop the capsule now the operation has finished.
        #
        # Not tidiness. The grant that made the input reachable is session
        # scoped, and the runtime drops session grants when a capsule stops — so
        # this is what turns "allow once" into a permission that lasted one
        # launch. An application left running would keep the file reachable for
        # the rest of the login, which is not what anybody was asked.
        #
        # Persistent capsule data survives: stopping ends a process, and the
        # application's private storage is the capsule's identity, not the
        # task's.
        try:
            self.runtime.stop(self.runtime.open(entry.application_id))
        except (CapsuleError, TrustError) as exc:  # noqa: BLE001
            warnings.append(f"the app could not be stopped cleanly: {exc}")

        steps.append(TaskStep("done", STEP_LABELS["done"], "done"))

        summary = _completion_sentence(entry.name, exports, overwrote=overwrite_inputs)
        return CapsuleTaskResult(
            task_id=task_id,
            state="completed",
            application_id=entry.application_id,
            decisions=tuple(decisions),
            exports=tuple(exports),
            launch=launch,
            workspace=workspace("completed", summary, finished=_now()),
        )


def _actions_for(state: str) -> tuple[str, ...]:
    """What a person may do to a task in this state.

    Pause is deliberately absent. §16 permits it *when technically possible*, and
    for a task whose work happens inside a third-party application it is not:
    Bunny can stop the capsule, which is a cancel, and offering a Pause that
    silently behaved like one would be worse than not offering it.
    """
    if state in ("preparing", "working", "waiting_for_you"):
        return ("watch", "minimise", "cancel", "inspect_permissions")
    if state == "completed":
        return ("view_result", "open_application", "inspect_permissions")
    return ("inspect_permissions",)


def _refusal_sentence(decision: Decision, application_name: str) -> str:
    """Why the task stopped, in a sentence that does not blame the person wrongly."""
    from trust.explain import decision_sentence

    return decision_sentence(decision, application_name=application_name)


def _completion_sentence(
    application_name: str,
    exports: Sequence[ExportResult],
    *,
    overwrote: bool,
) -> str:
    """The one thing Bunny says when it finishes. Assembled from facts only.

    In particular it does not say "your original wasn't modified" unless the
    export results say it was not — the whole value of that sentence is that it
    is checked.
    """
    if not exports:
        return f"{application_name} finished, and produced nothing to save."
    where = ", ".join(export.display for export in exports)
    preserved = all(export.original_preserved for export in exports)
    parts = [f"Done. The work happened inside {application_name}'s protected space."]
    if preserved and not overwrote:
        parts.append("Your original file wasn't changed.")
    elif not preserved:
        copies = [export.original_copy for export in exports if export.original_copy]
        if copies:
            parts.append("Your original was replaced; a copy of it is next to the new file.")
        else:
            parts.append("Your original was replaced, as you asked.")
    parts.append(f"The result is in {where}.")
    return " ".join(parts)
