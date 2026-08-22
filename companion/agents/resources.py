# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine resources for local model selection: measured, not tiered.

The brief asks for "intelligent model selection" and is explicit about what
that is *not*: no invented product tiers like Low / Medium / Ultra. The only
vocabulary is the existing hardware-capability one — available RAM, the
memory-pressure band, and the bytes a model needs resident to load and keep
a context window — and the rule falls out of those three the way §9's
selection falls out of configuration order: a derivation, not a ranking.

* a **small machine** has a small available-RAM budget, so the largest
  discovered model whose footprint still fits is a smaller model — that is
  "small machine → smaller local model" with no tier named;
* a **powerful machine** has a large budget, so the same rule binds the
  largest discovered model that fits;
* **memory pressure** shrinks the budget (nominal 50%, elevated 30%,
  critical 15% of available, minus what an already-loaded model holds), so
  a model that fit a moment ago becomes ineligible and selection downgrades
  to a smaller one or, when nothing fits, refuses — "downgrade / unload /
  refuse" without a new state machine.

The estimate is honest about being an estimate. ``model_runtime_footprint``
is a conservative upper bound for a CPU ``llama-cli`` process — the weight
file plus a KV/context-cache allowance — labelled as such so the §25
measurements can replace it the way they replace every other estimate in
this package.

The guard is opt-in by measurement, not by flag. When the host cannot be
measured — no ``/proc/meminfo`` (a non-Linux build host, or a test that
injects nothing) — ``available_ram_bytes`` is zero and
:func:`model_memory_budget` returns zero, which the registry reads as "no
constraint is known" and does not refuse on. That is the backward-compatibility
path: every existing test constructs the registry without machine resources,
so nothing is refused that was not already refused, and selection is
unchanged. A zero budget is *not* a refusal: the absence of a measurement is
not a measurement of absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "CONTEXT_BYTES_PER_TOKEN",
    "MachineResources",
    "PRESSURE_LEVELS",
    "default_machine_resources",
    "model_memory_budget",
    "model_runtime_footprint",
]

#: Conservative KV/context-cache allowance per resident token, in bytes, for a
#: small CPU model running through llama-cli. The weight file dominates for a
#: 1-3B model; this term covers the context window's resident cache and a
#: margin for runtime overhead. It is an estimate, labelled as one, and §25
#: measurements replace it.
CONTEXT_BYTES_PER_TOKEN = 512

#: The pressure bands, in order of severity. ``"unknown"`` is the off-Linux /
#: unreadable case and disables the guard rather than refusing.
PRESSURE_LEVELS = ("nominal", "elevated", "critical", "unknown")

#: The share of available RAM a *new* model may occupy at each pressure band.
#: Critical pressure leaves the machine room for everything that is not the
#: model, so the budget is smallest; nominal gives the model half of what the
#: OS reports spare. ``unknown`` is never reached (the caller checks
#: :attr:`MachineResources.known` first) but the table is total.
_SHARE = {
    "nominal": 0.50,
    "elevated": 0.30,
    "critical": 0.15,
    "unknown": 0.0,
}


@dataclass(frozen=True)
class MachineResources:
    """What this machine can spare for a local model right now.

    ``available_ram_bytes`` is the OS-reported available memory (Linux
    ``MemAvailable``). ``memory_pressure_level`` is the PSI memory-pressure
    band, or ``"unknown"`` where PSI is not readable. ``active_model_bytes``
    is memory already committed to a loaded model the caller is accounting
    for, so a second model's budget is what remains after the first.
    """

    available_ram_bytes: int = 0
    memory_pressure_level: str = "unknown"
    active_model_bytes: int = 0

    def __post_init__(self) -> None:
        if self.available_ram_bytes < 0 or self.active_model_bytes < 0:
            raise ValueError("resource bytes must be non-negative")
        if self.memory_pressure_level not in PRESSURE_LEVELS:
            raise ValueError(
                f"memory pressure level {self.memory_pressure_level!r} "
                f"is not one of {PRESSURE_LEVELS}"
            )

    @property
    def known(self) -> bool:
        """Whether the budget is a constraint at all. Unknown → no refusal."""
        return self.available_ram_bytes > 0


def model_memory_budget(resources: MachineResources) -> int:
    """The most bytes a *new* model may consume on this machine right now.

    Zero means "no constraint is known" — the caller must NOT refuse a model
    on a zero budget. A non-zero budget that a model exceeds is a real
    refusal: under critical pressure the budget shrinks to 15% of available
    minus what an active model already holds, so the largest model that
    still fits is what selection keeps and the rest become ineligible.
    """
    if not resources.known:
        return 0
    share = _SHARE.get(resources.memory_pressure_level, _SHARE["nominal"])
    budget = int(resources.available_ram_bytes * share) - resources.active_model_bytes
    return max(0, budget)


def model_runtime_footprint(*, model_size_bytes: int, context_limit_tokens: int) -> int:
    """A conservative estimate of the bytes a model needs resident to run.

    Weights plus a context-cache allowance. Both inputs are non-negative;
    either being zero yields the other term alone, so a discovered model
    whose size the probe could not stat is estimated from context only, and
    a model with no declared context window is estimated from weights only.
    """
    if model_size_bytes < 0 or context_limit_tokens < 0:
        raise ValueError("footprint inputs must be non-negative")
    return model_size_bytes + context_limit_tokens * CONTEXT_BYTES_PER_TOKEN


_MEMINFO_AVAILABLE = re.compile(r"^MemAvailable:\s+(\d+)\s+kB", re.MULTILINE)
_PRESSURE_AVG = re.compile(r"^(full|some)\s+avg10=(\d+\.\d+)", re.MULTILINE)


def _read_pressure_level(proc_root: Path) -> str:
    """Map /proc/pressure/memory to a band, or ``"unknown"`` where unreadable.

    The "full" line's avg10 is the share of time *all* tasks were stalled on
    memory; where only "some" is reported, that line is used instead. The
    thresholds are conservative: 30% sustained stall is elevated, 60% is
    critical. Below 30% the machine is nominal for a model that fits.
    """
    try:
        text = (proc_root / "pressure" / "memory").read_text(encoding="utf-8")
    except OSError:
        return "unknown"
    full: float | None = None
    some: float | None = None
    for kind, value in _PRESSURE_AVG.findall(text):
        if kind == "full" and full is None:
            full = float(value)
        elif kind == "some" and some is None:
            some = float(value)
    avg = full if full is not None else some
    if avg is None:
        return "unknown"
    if avg >= 60.0:
        return "critical"
    if avg >= 30.0:
        return "elevated"
    return "nominal"


def default_machine_resources(proc_root: Path | None = None) -> MachineResources:
    """Read the live machine, or report unknown where it cannot be read.

    On Linux this reads ``/proc/meminfo`` for ``MemAvailable`` and
    ``/proc/pressure/memory`` for the pressure band. Off Linux (the build
    host, or a unit test) both reads miss and the result is unknown — which
    disables the resource guard rather than refusing every model.
    """
    proc = proc_root if proc_root is not None else Path("/proc")
    try:
        meminfo = (proc / "meminfo").read_text(encoding="utf-8")
    except OSError:
        return MachineResources(available_ram_bytes=0, memory_pressure_level="unknown")
    match = _MEMINFO_AVAILABLE.search(meminfo)
    available = int(match.group(1)) * 1024 if match is not None else 0  # kB → bytes
    level = _read_pressure_level(proc)
    if available == 0:
        level = "unknown"
    return MachineResources(available_ram_bytes=available, memory_pressure_level=level)