# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Service capability declarations and the evaluation of their requirements.

A service declares what it needs; the policy engine decides whether it gets it.
Nothing in this module makes a decision — every function here answers *"is this
requirement met, and by what margin"* and hands the answer to
:mod:`capability.engine`, which is the only place a verdict is reached.

Manifests are JSON, not YAML. The brief sketches YAML, but this repository
validates JSON documents in ``release/validation.py``, ships JSON Schemas in
``schemas/``, and has no PyYAML dependency it can rely on — the workflow
validator degrades to SKIP when PyYAML is missing. A manifest format that
cannot be validated on every host is a manifest format that is not validated,
so these are JSON and are covered by the repository's own schema validator.

**Implementations are the degradation ladder.** The brief lists degradation
steps separately from implementation selection; they are the same mechanism
seen twice. ``bunny.companion`` with a full 3D implementation, a static-avatar
implementation and a text-only implementation *is* a service with three
degradation levels, and modelling them once means the selection logic and the
degradation logic cannot disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Mapping

from . import MANIFEST_SCHEMA_VERSION
from .model import Inventory
from .scores import ScoreSet

__all__ = [
    "LOCALITIES",
    "ManifestError",
    "PRIORITIES",
    "RESTART_POLICIES",
    "Implementation",
    "RequirementCheck",
    "Requirements",
    "ServiceManifest",
    "load_manifest",
    "load_manifests",
    "parse_manifest",
]

#: Service ids are dotted, lowercase, and stable. They appear in policy files
#: users write by hand and in explanations users read, so the character set is
#: deliberately narrow.
_SERVICE_ID = re.compile(r"^[a-z][a-z0-9]*(\.[a-z0-9][a-z0-9-]*)+$")
_IMPLEMENTATION_ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")

RESTART_POLICIES = ("never", "on-failure", "always")
LOCALITIES = ("local", "remote")

#: Priority bands. Higher wins when resources are contested. These are
#: importance rankings within one Bunny OS, not product tiers: every service
#: exists on every machine, and priority decides ordering under contention.
#:
#: The vocabulary deliberately avoids "low" and "high". Those would be correct
#: English for a priority band, but this is the one codebase where they are
#: reserved words: the project rule is that Bunny OS has no low/balanced/high/
#: ultra anything, and a grep for "high" in a manifest should find nothing
#: rather than find a priority and require the reader to decide whether it is a
#: performance mode. Naming them something else costs nothing and removes the
#: ambiguity permanently.
PRIORITIES = {"critical": 90, "important": 70, "standard": 50, "deferred": 30, "background": 10}

_RESOLUTION = re.compile(r"^(\d{2,5})x(\d{2,5})$")


class ManifestError(ValueError):
    """A manifest that cannot be trusted to describe what a service needs."""


@dataclass(frozen=True)
class RequirementCheck:
    """One requirement, what it asked for, and what the machine offered.

    ``satisfied`` is deliberately three-valued. ``None`` means the machine could
    not answer — the probe did not run, the field is unknown — and it is **not**
    the same as ``False``. The engine treats ``None`` as not-satisfied for
    admission purposes, so behaviour is conservative, but the explanation says
    "could not be determined" rather than "insufficient", because telling a user
    their machine lacks 512 MB it may well have is a different and worse lie
    than telling them we could not measure it.
    """

    requirement: str
    satisfied: bool | None
    required: Any
    measured: Any
    detail: str = ""

    @property
    def blocking(self) -> bool:
        return self.satisfied is not True

    def to_json(self) -> dict[str, Any]:
        return {
            "requirement": self.requirement,
            "satisfied": self.satisfied,
            "required": self.required,
            "measured": self.measured,
            "detail": self.detail,
        }


def _bytes_field(document: Mapping[str, Any], key: str) -> int | None:
    value = document.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestError(f"{key} must be a non-negative integer number of bytes")
    return value


def _score_field(document: Mapping[str, Any], key: str) -> float | None:
    value = document.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 100.0:
        raise ManifestError(f"{key} must be a number between 0 and 100")
    return float(value)


@dataclass(frozen=True)
class Requirements:
    """What a service or implementation needs in order to run locally."""

    minimum_memory_bytes: int | None = None
    recommended_memory_bytes: int | None = None
    minimum_cpu_score: float | None = None
    minimum_cores: float | None = None

    gpu_required: bool = False
    gpu_runtime: str | None = None          # "cuda" | "rocm" | "vulkan" | "any"
    minimum_vram_bytes: int | None = None

    minimum_free_storage_bytes: int | None = None
    writable_storage_required: bool = False

    network_required: bool = False

    display_required: bool = False
    minimum_resolution: str | None = None

    audio_output_required: bool = False
    audio_input_required: bool = False

    #: Extra gates on named score dimensions, so a service can require
    #: "storage_performance >= 40" without a bespoke field being invented for it.
    minimum_scores: Mapping[str, float] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "memory": {"minimumBytes": self.minimum_memory_bytes, "recommendedBytes": self.recommended_memory_bytes},
            "cpu": {"minimumScore": self.minimum_cpu_score, "minimumCores": self.minimum_cores},
            "gpu": {"required": self.gpu_required, "runtime": self.gpu_runtime, "minimumVramBytes": self.minimum_vram_bytes},
            "storage": {"minimumFreeBytes": self.minimum_free_storage_bytes, "writable": self.writable_storage_required},
            "network": {"required": self.network_required},
            "display": {"required": self.display_required, "minimumResolution": self.minimum_resolution},
            "audio": {"outputRequired": self.audio_output_required, "inputRequired": self.audio_input_required},
            "scores": dict(self.minimum_scores),
        }

    # ----------------------------------------------------------------- #
    # Evaluation
    # ----------------------------------------------------------------- #

    def evaluate(
        self,
        inventory: Inventory,
        scores: ScoreSet,
        *,
        available_memory_bytes: int | None,
    ) -> list[RequirementCheck]:
        """Check every declared requirement against the machine.

        ``available_memory_bytes`` is the budget the caller is prepared to
        commit — the *budget's* figure, not the machine's free memory. A service
        is admitted against what Bunny OS is allowed to spend, so that the
        protected reserve cannot be consumed by an optional service simply
        because the kernel happens to have the pages free.
        """
        checks: list[RequirementCheck] = []

        if self.minimum_memory_bytes is not None:
            if available_memory_bytes is None:
                checks.append(RequirementCheck(
                    "memory.minimumBytes", None, self.minimum_memory_bytes, None,
                    "no memory budget could be derived",
                ))
            else:
                checks.append(RequirementCheck(
                    "memory.minimumBytes",
                    available_memory_bytes >= self.minimum_memory_bytes,
                    self.minimum_memory_bytes,
                    available_memory_bytes,
                    "measured against the allocatable budget, not against free physical memory",
                ))

        if self.minimum_cpu_score is not None:
            score = scores.get("cpu_compute")
            checks.append(RequirementCheck(
                "cpu.minimumScore",
                None if score.value is None else score.value >= self.minimum_cpu_score,
                self.minimum_cpu_score, score.value,
                "" if score.value is not None else "CPU capacity was not measured",
            ))

        if self.minimum_cores is not None:
            cores = inventory.cpu.effective_cores(0.0)
            checks.append(RequirementCheck(
                "cpu.minimumCores",
                None if cores <= 0 else cores >= self.minimum_cores,
                self.minimum_cores, cores or None,
                "effective cores include any cgroup quota" if cores > 0 else "no schedulable core count was measured",
            ))

        if self.gpu_required:
            usable = inventory.usable_gpus
            wanted = self.gpu_runtime or "any"
            if wanted == "any":
                ready = [device for device in usable if device.driver_ready]
                detail = "a GPU with a bound driver and a render node"
            else:
                ready = [device for device in usable if device.runtime_ready(wanted)]
                detail = f"a GPU with a verified {wanted} runtime"
            checks.append(RequirementCheck(
                "gpu.required", bool(ready), wanted, len(ready),
                f"{detail}; presence of a PCI device alone does not satisfy this",
            ))
            if self.minimum_vram_bytes is not None:
                totals = [
                    device.vram_total_bytes.value for device in ready
                    if device.vram_total_bytes.is_measured
                ]
                if not ready:
                    checks.append(RequirementCheck(
                        "gpu.minimumVramBytes", False, self.minimum_vram_bytes, 0,
                        "no usable GPU to hold it",
                    ))
                elif not totals:
                    checks.append(RequirementCheck(
                        "gpu.minimumVramBytes", None, self.minimum_vram_bytes, None,
                        "VRAM has no trustworthy source on this machine",
                    ))
                else:
                    checks.append(RequirementCheck(
                        "gpu.minimumVramBytes", max(totals) >= self.minimum_vram_bytes,
                        self.minimum_vram_bytes, max(totals),
                        "compared against the largest single device: work must fit in one of them",
                    ))

        if self.minimum_free_storage_bytes is not None:
            free = inventory.storage.root_available_bytes.get(None)
            checks.append(RequirementCheck(
                "storage.minimumFreeBytes",
                None if free is None else free >= self.minimum_free_storage_bytes,
                self.minimum_free_storage_bytes, free,
                "" if free is not None else "free storage was not measured",
            ))

        if self.writable_storage_required:
            read_only = inventory.storage.read_only
            checks.append(RequirementCheck(
                "storage.writable",
                None if not read_only.is_known else read_only.get(True) is False,
                True, not read_only.get(True),
                "" if read_only.is_known else "filesystem writability was not measured",
            ))

        if self.network_required:
            route = inventory.network.default_route
            checks.append(RequirementCheck(
                "network.required",
                None if not route.is_known else inventory.network.online,
                True, inventory.network.online if route.is_known else None,
                "" if route.is_known else "the routing table could not be read",
            ))

        if self.display_required:
            outputs = inventory.display.connected_outputs
            checks.append(RequirementCheck(
                "display.required",
                None if not outputs.is_known else inventory.display.has_display,
                True, outputs.get(None),
                "" if outputs.is_known else "display state was not measured",
            ))
            if self.minimum_resolution is not None:
                checks.append(self._resolution_check(inventory))

        if self.audio_output_required:
            observation = inventory.audio.output_present
            checks.append(RequirementCheck(
                "audio.outputRequired",
                None if not observation.is_known else observation.get(False) is True,
                True, observation.get(None),
                "" if observation.is_known else "audio devices were not enumerated",
            ))

        if self.audio_input_required:
            observation = inventory.audio.input_present
            checks.append(RequirementCheck(
                "audio.inputRequired",
                None if not observation.is_known else observation.get(False) is True,
                True, observation.get(None),
                "" if observation.is_known else "audio devices were not enumerated",
            ))

        for dimension, minimum in sorted(self.minimum_scores.items()):
            score = scores.get(dimension)
            checks.append(RequirementCheck(
                f"scores.{dimension}",
                None if score.value is None else score.value >= minimum,
                minimum, score.value,
                "" if score.value is not None else f"the {dimension} dimension has no measurement",
            ))

        return checks

    def _resolution_check(self, inventory: Inventory) -> RequirementCheck:
        wanted = _RESOLUTION.match(self.minimum_resolution or "")
        observed = inventory.display.max_resolution.get(None)
        have = _RESOLUTION.match(observed or "") if isinstance(observed, str) else None
        if wanted is None:
            return RequirementCheck("display.minimumResolution", None, self.minimum_resolution, observed,
                                    "the declared minimum resolution is not WxH")
        if have is None:
            return RequirementCheck("display.minimumResolution", None, self.minimum_resolution, observed,
                                    "no display mode was reported")
        satisfied = (
            int(have.group(1)) >= int(wanted.group(1))
            and int(have.group(2)) >= int(wanted.group(2))
        )
        return RequirementCheck("display.minimumResolution", satisfied, self.minimum_resolution, observed)


def parse_requirements(document: Mapping[str, Any]) -> Requirements:
    if not isinstance(document, Mapping):
        raise ManifestError("requirements must be an object")

    memory = document.get("memory", {}) or {}
    cpu = document.get("cpu", {}) or {}
    gpu = document.get("gpu", {}) or {}
    storage = document.get("storage", {}) or {}
    network = document.get("network", {}) or {}
    display = document.get("display", {}) or {}
    audio = document.get("audio", {}) or {}
    score_gates = document.get("scores", {}) or {}

    for name, section in (("memory", memory), ("cpu", cpu), ("gpu", gpu), ("storage", storage),
                          ("network", network), ("display", display), ("audio", audio), ("scores", score_gates)):
        if not isinstance(section, Mapping):
            raise ManifestError(f"requirements.{name} must be an object")

    minimum = _bytes_field(memory, "minimumBytes")
    recommended = _bytes_field(memory, "recommendedBytes")
    if minimum is not None and recommended is not None and recommended < minimum:
        raise ManifestError("memory.recommendedBytes must not be below memory.minimumBytes")

    runtime = gpu.get("runtime")
    if runtime is not None and runtime not in ("any", "cuda", "rocm", "vulkan"):
        raise ManifestError(f"gpu.runtime must be one of any/cuda/rocm/vulkan, not {runtime!r}")

    resolution = display.get("minimumResolution")
    if resolution is not None and not _RESOLUTION.match(str(resolution)):
        raise ManifestError(f"display.minimumResolution must be WxH, not {resolution!r}")

    gates: dict[str, float] = {}
    for dimension, value in score_gates.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 100.0:
            raise ManifestError(f"scores.{dimension} must be a number between 0 and 100")
        gates[str(dimension)] = float(value)

    return Requirements(
        minimum_memory_bytes=minimum,
        recommended_memory_bytes=recommended,
        minimum_cpu_score=_score_field(cpu, "minimumScore"),
        minimum_cores=(
            float(cpu["minimumCores"]) if isinstance(cpu.get("minimumCores"), (int, float)) and not isinstance(cpu.get("minimumCores"), bool) else None
        ),
        gpu_required=bool(gpu.get("required", False)),
        gpu_runtime=runtime,
        minimum_vram_bytes=_bytes_field(gpu, "minimumVramBytes"),
        minimum_free_storage_bytes=_bytes_field(storage, "minimumFreeBytes"),
        writable_storage_required=bool(storage.get("writable", False)),
        network_required=bool(network.get("required", False)),
        display_required=bool(display.get("required", False)),
        minimum_resolution=str(resolution) if resolution is not None else None,
        audio_output_required=bool(audio.get("outputRequired", False)),
        audio_input_required=bool(audio.get("inputRequired", False)),
        minimum_scores=gates,
    )


@dataclass(frozen=True)
class Implementation:
    """One way of providing a service. Selection among these is §8's mechanism.

    ``rank`` orders the ladder: 1 is the richest implementation, higher numbers
    are progressively reduced. The engine walks it in order and takes the first
    whose requirements are met, which makes both *implementation selection* and
    *degradation* the same deterministic walk.
    """

    id: str
    title: str
    locality: str
    rank: int
    requirements: Requirements
    provider: str | None = None
    costs_money: bool = False
    sends_user_data_remotely: bool = False
    description: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "locality": self.locality,
            "rank": self.rank,
            "provider": self.provider,
            "costsMoney": self.costs_money,
            "sendsUserDataRemotely": self.sends_user_data_remotely,
            "description": self.description,
            "requirements": self.requirements.to_json(),
        }


@dataclass(frozen=True)
class ServiceManifest:
    """Everything a service declares about what it needs and how it behaves."""

    id: str
    title: str
    essential: bool
    priority: int
    budget_category: str
    description: str
    requirements: Requirements
    implementations: tuple[Implementation, ...]
    requires: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    suspendable: bool = True
    restart_policy: str = "on-failure"
    estimated_startup_ms: int = 0
    estimated_startup_memory_bytes: int = 0
    handles_sensitive_data: bool = False

    @property
    def supports_remote(self) -> bool:
        return any(item.locality == "remote" for item in self.implementations)

    @property
    def degradable(self) -> bool:
        """More than one local implementation means there is somewhere to fall back to."""
        return len([item for item in self.implementations if item.locality == "local"]) > 1

    def ordered_implementations(self) -> tuple[Implementation, ...]:
        # Ranked, then by id, so the walk is stable when two share a rank. An
        # unstable order here would make implementation selection non-reproducible
        # for the same inventory, which §3 forbids.
        return tuple(sorted(self.implementations, key=lambda item: (item.rank, item.id)))

    def implementation(self, identifier: str) -> Implementation | None:
        for item in self.implementations:
            if item.id == identifier:
                return item
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": MANIFEST_SCHEMA_VERSION,
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "essential": self.essential,
            "priority": self.priority,
            "budgetCategory": self.budget_category,
            "handlesSensitiveData": self.handles_sensitive_data,
            "requirements": self.requirements.to_json(),
            "dependencies": {"requires": list(self.requires), "conflictsWith": list(self.conflicts_with)},
            "execution": {
                "suspendable": self.suspendable,
                "supportsRemote": self.supports_remote,
                "degradable": self.degradable,
                "restartPolicy": self.restart_policy,
            },
            "startup": {
                "estimatedMilliseconds": self.estimated_startup_ms,
                "estimatedPeakMemoryBytes": self.estimated_startup_memory_bytes,
            },
            "implementations": [item.to_json() for item in self.ordered_implementations()],
        }


def parse_manifest(document: Mapping[str, Any], *, source: str = "<memory>") -> ServiceManifest:
    """Validate a manifest document. Refuses anything it cannot trust.

    Validation is strict because a manifest is a safety input: an
    under-specified one leads to a service being started on a machine that
    cannot hold it. §14 requires manifests be validated, and "validated" here
    means a bad manifest raises rather than being partially honoured.
    """
    if not isinstance(document, Mapping):
        raise ManifestError(f"{source}: manifest must be a JSON object")

    version = document.get("schemaVersion")
    if version != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"{source}: unsupported manifest schemaVersion {version!r}")

    identifier = document.get("id")
    if not isinstance(identifier, str) or not _SERVICE_ID.match(identifier):
        raise ManifestError(f"{source}: id must be a dotted lowercase identifier, not {identifier!r}")

    title = document.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ManifestError(f"{source}: title is required")

    essential = document.get("essential")
    if not isinstance(essential, bool):
        raise ManifestError(f"{source}: essential must be true or false")

    priority_value = document.get("priority", "normal")
    if isinstance(priority_value, str):
        if priority_value not in PRIORITIES:
            raise ManifestError(f"{source}: priority must be one of {sorted(PRIORITIES)} or 0..100")
        priority = PRIORITIES[priority_value]
    elif isinstance(priority_value, int) and not isinstance(priority_value, bool) and 0 <= priority_value <= 100:
        priority = priority_value
    else:
        raise ManifestError(f"{source}: priority must be a band name or an integer 0..100")

    category = document.get("budgetCategory")
    if not isinstance(category, str) or not category:
        raise ManifestError(f"{source}: budgetCategory is required")

    execution = document.get("execution", {}) or {}
    dependencies = document.get("dependencies", {}) or {}
    startup = document.get("startup", {}) or {}
    if not all(isinstance(section, Mapping) for section in (execution, dependencies, startup)):
        raise ManifestError(f"{source}: execution, dependencies and startup must be objects")

    restart = execution.get("restartPolicy", "on-failure")
    if restart not in RESTART_POLICIES:
        raise ManifestError(f"{source}: restartPolicy must be one of {list(RESTART_POLICIES)}")

    def id_list(key: str) -> tuple[str, ...]:
        value = dependencies.get(key, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ManifestError(f"{source}: dependencies.{key} must be an array of service ids")
        return tuple(value)

    requires = id_list("requires")
    conflicts = id_list("conflictsWith")
    overlap = set(requires).intersection(conflicts)
    if overlap:
        raise ManifestError(f"{source}: {sorted(overlap)} appear in both requires and conflictsWith")
    if identifier in requires or identifier in conflicts:
        raise ManifestError(f"{source}: a service may not depend on or conflict with itself")

    implementations: list[Implementation] = []
    raw_implementations = document.get("implementations", [])
    if not isinstance(raw_implementations, list) or not raw_implementations:
        raise ManifestError(f"{source}: at least one implementation must be declared")
    seen: set[str] = set()
    for entry in raw_implementations:
        if not isinstance(entry, Mapping):
            raise ManifestError(f"{source}: each implementation must be an object")
        implementation_id = entry.get("id")
        if not isinstance(implementation_id, str) or not _IMPLEMENTATION_ID.match(implementation_id):
            raise ManifestError(f"{source}: implementation id {implementation_id!r} is not a lowercase slug")
        if implementation_id in seen:
            raise ManifestError(f"{source}: duplicate implementation id {implementation_id!r}")
        seen.add(implementation_id)
        locality = entry.get("locality")
        if locality not in LOCALITIES:
            raise ManifestError(f"{source}: implementation locality must be one of {list(LOCALITIES)}")
        rank = entry.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            raise ManifestError(f"{source}: implementation rank must be a positive integer")
        remote_data = bool(entry.get("sendsUserDataRemotely", locality == "remote"))
        if locality == "remote" and not remote_data:
            raise ManifestError(
                f"{source}: implementation {implementation_id!r} is remote but declares "
                "sendsUserDataRemotely=false, which cannot be true of remote execution"
            )
        implementations.append(Implementation(
            id=implementation_id,
            title=str(entry.get("title", implementation_id)),
            locality=locality,
            rank=rank,
            requirements=parse_requirements(entry.get("requirements", {}) or {}),
            provider=str(entry["provider"]) if entry.get("provider") else None,
            costs_money=bool(entry.get("costsMoney", False)),
            sends_user_data_remotely=remote_data,
            description=str(entry.get("description", "")),
        ))

    if essential and not any(item.locality == "local" for item in implementations):
        raise ManifestError(
            f"{source}: an essential service must have a local implementation; "
            "a control plane that only runs remotely cannot bring up the machine it runs on"
        )

    return ServiceManifest(
        id=identifier,
        title=title.strip(),
        essential=essential,
        priority=priority,
        budget_category=category,
        description=str(document.get("description", "")),
        requirements=parse_requirements(document.get("requirements", {}) or {}),
        implementations=tuple(implementations),
        requires=requires,
        conflicts_with=conflicts,
        suspendable=bool(execution.get("suspendable", True)),
        restart_policy=restart,
        estimated_startup_ms=int(startup.get("estimatedMilliseconds", 0) or 0),
        estimated_startup_memory_bytes=int(startup.get("estimatedPeakMemoryBytes", 0) or 0),
        handles_sensitive_data=bool(document.get("handlesSensitiveData", False)),
    )


def load_manifest(path: Path) -> ServiceManifest:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"{path}: could not be read: {exc}") from exc
    return parse_manifest(document, source=str(path))


def load_manifests(directory: Path) -> list[ServiceManifest]:
    """Every ``*.json`` manifest in a directory, in sorted order.

    Sorted so that two hosts with the same manifests produce the same registry
    in the same order, which is what makes an execution plan reproducible.
    """
    if not directory.is_dir():
        return []
    return [load_manifest(path) for path in sorted(directory.glob("*.json"))]
