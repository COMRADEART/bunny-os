# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware discovery: the only part of the capability runtime that touches the machine.

Discovery runs a fixed list of probes inside **one shared deadline**. That is
the whole reason this orchestrator exists rather than each caller invoking
probes directly. §17 of the brief requires that boot not block indefinitely on
unavailable devices, and per-probe timeouts do not deliver that: twelve probes
with a three-second timeout each is a thirty-six-second stall on a machine where
every device is wedged. One deadline across all of them is a bound the caller
can actually reason about.

A probe that overruns, raises, or finds nothing does not fail the pass. It
contributes ``unknown`` observations and a recorded :class:`ProbeOutcome`
saying why, and discovery continues. An inventory with holes in it is useful —
the budget engine and the policy engine are both built to be conservative in
exactly those holes — whereas an exception at boot is not.
"""

from __future__ import annotations

import time
from typing import Callable

from ..model import (
    AudioFacts,
    CpuFacts,
    DisplayFacts,
    Inventory,
    MemoryFacts,
    NetworkFacts,
    PowerFacts,
    ProbeOutcome,
    StorageFacts,
    SystemFacts,
    ThermalFacts,
    now_iso8601,
)
from . import cpu, gpu, interaction, memory, network, power, storage, system
from .sources import Deadline

__all__ = ["DEFAULT_BUDGET_MS", "Deadline", "discover"]

#: Total wall-clock budget for one discovery pass. Two seconds is enough for
#: every sysfs read on any machine plus one vendor-tool invocation, and short
#: enough that a boot-time pass is not perceptible. Callers that can afford more
#: — an interactive ``capability inspect``, say — raise it explicitly.
DEFAULT_BUDGET_MS = 2000


def discover(
    *,
    budget_ms: int = DEFAULT_BUDGET_MS,
    probe_runtimes: bool = True,
    probe_reachability: bool = False,
    endpoints: tuple[tuple[str, int], ...] = (),
    clock: Callable[[], float] = time.monotonic,
) -> Inventory:
    """Collect a capability inventory within ``budget_ms``.

    ``probe_reachability`` defaults to off and requires ``endpoints``: nothing
    here contacts the network unless a caller asked for it with somewhere
    specific to contact.
    """
    deadline = Deadline(budget_ms, clock=clock)
    outcomes: list[ProbeOutcome] = []

    def guard(name: str, probe: Callable[[], object], fallback: Callable[[], object]) -> object:
        """Run one probe, recording what it did and never letting it escape."""
        if deadline.expired:
            outcomes.append(ProbeOutcome(name, "skipped", 0, "discovery deadline exhausted before this probe started"))
            return fallback()
        start = clock()
        try:
            value = probe()
        except Exception as exc:  # noqa: BLE001 - a probe must never fail a boot
            duration = int((clock() - start) * 1000)
            outcomes.append(ProbeOutcome(name, "failed", duration, f"{exc.__class__.__name__}"))
            return fallback()
        duration = int((clock() - start) * 1000)
        outcomes.append(ProbeOutcome(name, "ok", duration))
        return value

    # Ordered cheapest and most decision-critical first, so that a pass which
    # runs out of budget has still answered the questions the budget engine
    # cannot proceed without: architecture, memory ceiling and CPU quota.
    system_facts = guard("system", lambda: system.probe(deadline), SystemFacts)
    memory_facts = guard("memory", lambda: memory.probe(deadline), MemoryFacts)
    cpu_facts = guard("cpu", lambda: cpu.probe(deadline), CpuFacts)
    storage_facts = guard("storage", lambda: storage.probe(deadline), StorageFacts)
    display_facts = guard("display", lambda: interaction.probe_display(deadline), DisplayFacts)
    power_facts = guard("power", lambda: power.probe_power(deadline), PowerFacts)
    thermal_facts = guard("thermal", lambda: power.probe_thermal(deadline), ThermalFacts)
    audio_facts = guard("audio", lambda: interaction.probe_audio(deadline), AudioFacts)
    network_facts = guard(
        "network",
        lambda: network.probe(deadline, endpoints=endpoints, probe_reachability=probe_reachability),
        NetworkFacts,
    )
    # GPU last: it is the only probe that may invoke vendor tools, so it is the
    # one whose truncation costs least. A missing GPU section produces a
    # CPU-only plan, which is safe; a missing memory section would not be.
    gpus = guard("gpu", lambda: gpu.probe(deadline, probe_runtimes=probe_runtimes), list)
    accelerators = guard("accelerators", lambda: gpu.probe_accelerators(deadline), list)

    return Inventory(
        detected_at=now_iso8601(),
        system=system_facts,           # type: ignore[arg-type]
        cpu=cpu_facts,                 # type: ignore[arg-type]
        memory=memory_facts,           # type: ignore[arg-type]
        gpu=tuple(gpus),               # type: ignore[arg-type]
        accelerators=tuple(accelerators),  # type: ignore[arg-type]
        storage=storage_facts,         # type: ignore[arg-type]
        network=network_facts,         # type: ignore[arg-type]
        power=power_facts,             # type: ignore[arg-type]
        thermal=thermal_facts,         # type: ignore[arg-type]
        display=display_facts,         # type: ignore[arg-type]
        audio=audio_facts,             # type: ignore[arg-type]
        probes=tuple(outcomes),
        detection_budget_ms=budget_ms,
        detection_duration_ms=deadline.elapsed_ms,
    )
