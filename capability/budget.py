# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""The resource-budget engine: how much Bunny OS may safely consume.

Two memory numbers come out of here and the difference between them is the
point:

**allocatable** — what Bunny OS may consume when the machine is otherwise idle.
Derived from *usable* memory (physical, or the cgroup ceiling, whichever binds)
minus the protected reserve. This is the planning number, and it is stable: it
does not move when a user opens a browser.

**currently allocatable** — what may be committed *right now*, derived from
memory that is actually free. This is the admission number. A service is
started against this one, so a machine under pressure stops admitting work
without the plan being rewritten.

Budgeting against only the first over-commits a loaded machine; budgeting
against only the second makes the plan flap every time a user opens a tab. Both
exist because both questions get asked, and by different callers.

The **protected reserve** is never allocatable by anything, essential included.
Its floor is absolute rather than proportional: 20% of 64 MiB is 13 MiB, which
is not enough for the kernel to reclaim its way out of trouble, so a hard floor
applies underneath the fraction. Ceilings apply above it too — 20% of 256 GB
would idle 51 GB for no benefit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .model import Inventory
from .policy import Policy
from .scores import ScoreSet

__all__ = [
    "ALL_CATEGORIES",
    "CATEGORIES",
    "ESSENTIAL_CATEGORY",
    "Budget",
    "CategoryBudget",
    "MAXIMUM_RESERVE_BYTES",
    "MINIMUM_RESERVE_BYTES",
    "compute_budget",
]

#: Essential services declare this category. It is deliberately *not* one of the
#: discretionary categories below: essential memory is not a share of a pool
#: that other categories compete for, it is taken off the top before the pool
#: exists. A category that could be outbid would not be essential.
ESSENTIAL_CATEGORY = "essential_services"

_MIB = 1024 ** 2
_GIB = 1024 ** 3

#: The reserve never drops below this, whatever the fraction works out to. A
#: machine with less than this much slack cannot reclaim, cannot fork, and
#: cannot run the OOM killer's own bookkeeping without stalling.
MINIMUM_RESERVE_BYTES = 24 * _MIB

#: ...and never rises above this, whatever the fraction works out to. Holding
#: back a proportional share of a 256 GB host would strand tens of gigabytes to
#: protect against a risk that stopped scaling long before.
MAXIMUM_RESERVE_BYTES = 2 * _GIB

#: Default share of usable memory held in reserve.
DEFAULT_RESERVE_FRACTION = 0.20

#: Discretionary categories, their share of the pool left after essential
#: services, and the size below which funding one is pointless.
#:
#: ``minimumUsefulBytes`` is what makes this engine honest on constrained
#: hardware. A 64 MB device does not receive a 3 MB "local AI inference budget"
#: that no model could ever load into; the category is reported unfunded, with
#: the shortfall stated, and its share is redistributed to categories that can
#: use it. This is §5 of the brief implemented as arithmetic rather than as a
#: promise: the constrained device is not pretending.
CATEGORIES: Mapping[str, Mapping[str, Any]] = {
    "optional_services": {"weight": 0.15, "minimumUsefulBytes": 8 * _MIB,
                          "purpose": "Background Bunny OS services nobody is waiting on"},
    "user_applications": {"weight": 0.30, "minimumUsefulBytes": 64 * _MIB,
                          "purpose": "Headroom left for the applications the user runs"},
    "local_ai_inference": {"weight": 0.25, "minimumUsefulBytes": 512 * _MIB,
                           "purpose": "Model weights and inference working set"},
    "companion_rendering": {"weight": 0.10, "minimumUsefulBytes": 192 * _MIB,
                            "purpose": "The visual companion's renderer"},
    "speech_recognition": {"weight": 0.05, "minimumUsefulBytes": 256 * _MIB,
                           "purpose": "Local speech-to-text"},
    "text_to_speech": {"weight": 0.03, "minimumUsefulBytes": 48 * _MIB,
                       "purpose": "Local voice synthesis"},
    "agent_orchestration": {"weight": 0.05, "minimumUsefulBytes": 32 * _MIB,
                            "purpose": "Plan execution and agent coordination"},
    "caching": {"weight": 0.04, "minimumUsefulBytes": 8 * _MIB,
                "purpose": "In-memory caches"},
    "logs": {"weight": 0.02, "minimumUsefulBytes": 2 * _MIB,
             "purpose": "Log buffers before they are flushed"},
    "temporary_files": {"weight": 0.01, "minimumUsefulBytes": 2 * _MIB,
                        "purpose": "In-memory temporary storage"},
}

#: Every category a manifest may declare.
ALL_CATEGORIES = (ESSENTIAL_CATEGORY, *CATEGORIES)


@dataclass(frozen=True)
class CategoryBudget:
    name: str
    bytes_allowed: int
    funded: bool
    purpose: str
    reason: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "category": self.name,
            "bytesAllowed": self.bytes_allowed,
            "funded": self.funded,
            "purpose": self.purpose,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class Budget:
    """What Bunny OS may consume, and the arithmetic that produced it."""

    usable_bytes: int | None
    currently_available_bytes: int | None
    protected_reserve_bytes: int
    allocatable_bytes: int
    currently_allocatable_bytes: int
    essential_services_bytes: int
    foreground_workload_bytes: int | None
    categories: Mapping[str, CategoryBudget]

    background_cpu_percent: float
    interactive_cpu_percent: float
    effective_cores: float

    gpu_local_inference_allowed: bool
    gpu_rendering_allowed: bool
    gpu_reasons: tuple[str, ...]

    cache_storage_bytes: int
    log_storage_bytes: int
    temporary_storage_bytes: int

    essential_shortfall_bytes: int = 0
    notes: tuple[str, ...] = ()
    confidence: str = "measured"

    @property
    def viable(self) -> bool:
        """Whether the machine can fund its own essential services."""
        return self.essential_shortfall_bytes == 0

    def category_bytes(self, name: str) -> int:
        entry = self.categories.get(name)
        return entry.bytes_allowed if entry is not None else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "confidence": self.confidence,
            "viable": self.viable,
            "memory": {
                "usableBytes": self.usable_bytes,
                "currentlyAvailableBytes": self.currently_available_bytes,
                "protectedReserveBytes": self.protected_reserve_bytes,
                "allocatableBytes": self.allocatable_bytes,
                "currentlyAllocatableBytes": self.currently_allocatable_bytes,
                "essentialServicesBytes": self.essential_services_bytes,
                "essentialShortfallBytes": self.essential_shortfall_bytes,
                "optionalServicesBytes": sum(
                    item.bytes_allowed for name, item in self.categories.items() if name != "user_applications"
                ),
                "foregroundWorkloadBytes": self.foreground_workload_bytes,
                "categories": [self.categories[name].to_json() for name in CATEGORIES if name in self.categories],
            },
            "cpu": {
                "backgroundQuotaPercent": round(self.background_cpu_percent, 1),
                "interactiveQuotaPercent": round(self.interactive_cpu_percent, 1),
                "effectiveCores": self.effective_cores,
            },
            "gpu": {
                "localInferenceAllowed": self.gpu_local_inference_allowed,
                "renderingAllowed": self.gpu_rendering_allowed,
                "reasons": list(self.gpu_reasons),
            },
            "storage": {
                "cacheBytes": self.cache_storage_bytes,
                "logBytes": self.log_storage_bytes,
                "temporaryBytes": self.temporary_storage_bytes,
            },
            "notes": list(self.notes),
        }


def _reserve_bytes(usable: int, policy: Policy) -> int:
    fraction = policy.protected_reserve_fraction
    if fraction is None:
        fraction = DEFAULT_RESERVE_FRACTION
    proportional = int(usable * fraction)
    bounded = max(MINIMUM_RESERVE_BYTES, min(MAXIMUM_RESERVE_BYTES, proportional))
    # On a machine so small that even the floor would consume everything, the
    # reserve is capped at half. Reserving more than the machine has produces a
    # negative allocatable budget, and a negative budget is not a safety
    # property — it is an arithmetic accident that would refuse to boot.
    return min(bounded, usable // 2)


def _allocate_categories(pool: int) -> dict[str, CategoryBudget]:
    """Split ``pool`` by weight, dropping categories that would be too small.

    Iterative because dropping one category raises everyone else's share, which
    can lift a second category over its own floor. The loop is bounded by the
    number of categories and is deterministic: same pool in, same split out, in
    the same order, on any machine.
    """
    eligible = dict(CATEGORIES)
    dropped: dict[str, str] = {}

    while True:
        total_weight = sum(float(entry["weight"]) for entry in eligible.values())
        if total_weight <= 0 or not eligible:
            break
        shares = {
            name: int(pool * float(entry["weight"]) / total_weight)
            for name, entry in eligible.items()
        }
        short = [
            name for name, amount in shares.items()
            if amount < int(eligible[name]["minimumUsefulBytes"])
        ]
        if not short:
            break
        # Drop the single worst-funded category, then recompute. Dropping all of
        # them at once would discard categories that the redistribution would
        # have rescued.
        worst = min(short, key=lambda name: shares[name] - int(eligible[name]["minimumUsefulBytes"]))
        minimum = int(eligible[worst]["minimumUsefulBytes"])
        dropped[worst] = (
            f"share would be {shares[worst] // _MIB} MiB against a {minimum // _MIB} MiB floor; "
            "funding it would allocate memory too small to be used"
        )
        del eligible[worst]

    result: dict[str, CategoryBudget] = {}
    total_weight = sum(float(entry["weight"]) for entry in eligible.values())
    for name, entry in CATEGORIES.items():
        if name in eligible and total_weight > 0:
            amount = int(pool * float(entry["weight"]) / total_weight)
            result[name] = CategoryBudget(name, amount, True, str(entry["purpose"]))
        else:
            result[name] = CategoryBudget(
                name, 0, False, str(entry["purpose"]),
                dropped.get(name, "no discretionary memory remained after the protected reserve and essential services"),
            )
    return result


def _cpu_quotas(scores: ScoreSet, policy: Policy) -> tuple[float, float, list[str]]:
    notes: list[str] = []
    background_score = scores.get("background_capacity").value
    if background_score is None:
        # Unmeasured headroom is not assumed headroom. 10% is enough for the
        # control plane to make progress and small enough that a wrong guess
        # does not hurt an interactive user.
        background = 10.0
        notes.append("Background headroom was not measured; a conservative 10% quota is applied.")
    else:
        background = background_score * 0.6

    if policy.prefer_low_energy:
        background *= 0.5
        notes.append("preferLowEnergy halves the background CPU quota.")
    if policy.maximum_background_cpu_percent is not None:
        if policy.maximum_background_cpu_percent < background:
            notes.append(
                f"User limit maximumBackgroundCpuPercent={policy.maximum_background_cpu_percent:g} "
                f"is below the derived {background:.0f}% and takes precedence."
            )
        background = min(background, policy.maximum_background_cpu_percent)

    background = max(0.0, min(100.0, background))
    # Interactive work gets whatever background does not, floored so that a
    # zero-background machine still has a foreground quota to state.
    interactive = max(10.0, 100.0 - background)
    return background, interactive, notes


def _gpu_permissions(inventory: Inventory, scores: ScoreSet, policy: Policy) -> tuple[bool, bool, list[str]]:
    reasons: list[str] = []
    usable = inventory.usable_gpus
    if not usable:
        if inventory.gpu:
            reasons.append(f"{len(inventory.gpu)} GPU device(s) present, none with both a bound driver and a render node.")
        else:
            reasons.append("No GPU devices were enumerated.")
        return False, False, reasons

    compute_capable = [device for device in usable if device.runtime_ready("cuda") or device.runtime_ready("rocm")]
    vram = scores.get("gpu_memory").value
    inference = bool(compute_capable) and vram is not None and vram > 0
    if inference:
        reasons.append(
            f"{len(compute_capable)} GPU(s) expose a compute runtime and dedicated memory; local inference is permitted."
        )
    elif compute_capable:
        reasons.append("A compute runtime is present but no dedicated video memory was measured; local inference is not permitted.")
    else:
        reasons.append("No GPU exposes CUDA or ROCm; local GPU inference is not permitted.")

    rendering = any(device.runtime_ready("vulkan") for device in usable)
    if rendering and not inventory.display.has_display:
        rendering = False
        reasons.append("A rendering-capable GPU is present but no display is connected; local rendering is not permitted.")
    elif rendering:
        reasons.append("A Vulkan-capable GPU and a connected display are both present; local rendering is permitted.")
    else:
        reasons.append("No GPU reported a verified Vulkan runtime; accelerated rendering is not permitted.")

    if policy.prefer_low_energy and inference:
        inference = False
        reasons.append("preferLowEnergy withdraws permission for local GPU inference.")
    return inference, rendering, reasons


def _storage_budgets(inventory: Inventory) -> tuple[int, int, int, list[str]]:
    notes: list[str] = []
    if inventory.storage.read_only.get(False) is True:
        notes.append("The root filesystem is read-only; no cache or log budget is granted on it.")
        return 0, 0, 0, notes

    available = inventory.storage.root_available_bytes.get(None)
    if not isinstance(available, int):
        notes.append("Free storage was not measured; only a minimal log budget is granted.")
        return 0, 16 * _MIB, 0, notes

    cache = min(int(available * 0.10), 20 * _GIB)
    logs = max(16 * _MIB, min(int(available * 0.02), 512 * _MIB))
    temporary_available = inventory.storage.temporary_available_bytes.get(available)
    temporary = min(int(temporary_available * 0.5), 4 * _GIB)

    # Never let the three budgets together promise more than exists.
    total = cache + logs + temporary
    if total > available:
        scale = available / total
        cache, logs, temporary = int(cache * scale), int(logs * scale), int(temporary * scale)
        notes.append("Storage budgets were scaled down proportionally to fit the free space actually present.")
    return cache, logs, temporary, notes


def compute_budget(
    inventory: Inventory,
    scores: ScoreSet,
    policy: Policy,
    *,
    essential_floor_bytes: int = 0,
) -> Budget:
    """Derive every budget from one inventory, one score set and one policy.

    ``essential_floor_bytes`` is the summed minimum of the services marked
    essential in the registry. It is passed in rather than read here so that
    this module stays a pure function of measurement and configuration, and so
    that a caller can ask "what would the budget be if the essential set
    changed" without editing a manifest.
    """
    notes: list[str] = []
    usable = inventory.memory.usable_bytes(None)
    available = inventory.memory.usable_available_bytes(None)

    if usable is None:
        # Nothing is known about memory. Fund the essential floor at its
        # minimums — the control plane is what reports that nothing could be
        # measured, so refusing it would leave the machine silent — and grant no
        # discretionary budget at all. §16 requires that missing data produce
        # conservative behaviour rather than a crash, and this is the shape of
        # it: essential only, nothing optional, and the reason stated.
        notes.append(
            "Usable memory could not be measured. Essential services are funded at their "
            "declared minimums and no discretionary budget is granted, so every optional "
            "service will be refused until memory can be measured."
        )
        return Budget(
            usable_bytes=None,
            currently_available_bytes=None,
            protected_reserve_bytes=MINIMUM_RESERVE_BYTES,
            allocatable_bytes=essential_floor_bytes,
            currently_allocatable_bytes=0,
            essential_services_bytes=essential_floor_bytes,
            foreground_workload_bytes=None,
            categories=_allocate_categories(0),
            background_cpu_percent=5.0,
            interactive_cpu_percent=95.0,
            effective_cores=inventory.cpu.effective_cores(1.0),
            gpu_local_inference_allowed=False,
            gpu_rendering_allowed=False,
            gpu_reasons=("Memory is unmeasured, so no GPU workload is permitted.",),
            cache_storage_bytes=0,
            log_storage_bytes=16 * _MIB,
            temporary_storage_bytes=0,
            essential_shortfall_bytes=0,
            notes=tuple(notes),
            confidence="unknown",
        )

    reserve = _reserve_bytes(usable, policy)
    allocatable = max(0, usable - reserve)

    if policy.maximum_service_memory_bytes is not None and policy.maximum_service_memory_bytes < allocatable:
        notes.append(
            f"User limit maximumServiceMemoryBytes={policy.maximum_service_memory_bytes // _MIB} MiB "
            f"is below the derived {allocatable // _MIB} MiB and takes precedence."
        )
        allocatable = policy.maximum_service_memory_bytes

    essential = min(essential_floor_bytes, allocatable)
    shortfall = max(0, essential_floor_bytes - allocatable)
    if shortfall:
        notes.append(
            f"Essential services declare {essential_floor_bytes // _MIB} MiB of minimums but only "
            f"{allocatable // _MIB} MiB is allocatable. Bunny OS cannot run its own control plane here."
        )

    discretionary = max(0, allocatable - essential)

    if available is None:
        currently_allocatable = discretionary
        foreground = None
        notes.append("Currently free memory was not measured; admission uses the idle-machine budget.")
    else:
        # Everything already in use that is not ours is the user's foreground
        # workload. Budgeting on top of it, rather than pretending it will go
        # away, is what stops an admission decision from evicting their work.
        foreground = max(0, usable - available)
        currently_allocatable = max(0, min(discretionary, available - reserve))
        if currently_allocatable < discretionary:
            notes.append(
                f"Only {currently_allocatable // _MIB} MiB is free right now against a "
                f"{discretionary // _MIB} MiB idle budget; admission uses the smaller number."
            )

    categories = _allocate_categories(discretionary)
    background, interactive, cpu_notes = _cpu_quotas(scores, policy)
    inference_allowed, rendering_allowed, gpu_reasons = _gpu_permissions(inventory, scores, policy)
    cache, logs, temporary, storage_notes = _storage_budgets(inventory)

    memory_confidence = scores.get("memory_available").confidence
    return Budget(
        usable_bytes=usable,
        currently_available_bytes=available,
        protected_reserve_bytes=reserve,
        allocatable_bytes=allocatable,
        currently_allocatable_bytes=currently_allocatable,
        essential_services_bytes=essential,
        foreground_workload_bytes=foreground,
        categories=categories,
        background_cpu_percent=background,
        interactive_cpu_percent=interactive,
        effective_cores=inventory.cpu.effective_cores(1.0),
        gpu_local_inference_allowed=inference_allowed,
        gpu_rendering_allowed=rendering_allowed,
        gpu_reasons=tuple(gpu_reasons),
        cache_storage_bytes=cache,
        log_storage_bytes=logs,
        temporary_storage_bytes=temporary,
        essential_shortfall_bytes=shortfall,
        notes=tuple([*notes, *cpu_notes, *storage_notes]),
        confidence=memory_confidence,
    )
