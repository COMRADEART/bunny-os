# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rendering decisions in a form a person can check.

Everything here reads the structured records produced upstream and formats
them. Nothing recomputes, re-derives or paraphrases a decision — if an
explanation could disagree with the arithmetic that produced it, then one of
them is wrong and the user has no way to tell which.

The distinction §11 draws is worth restating at the top of the module that
implements it: **this is not model reasoning.** Every line rendered here comes
from a measurement, a declared requirement or a policy setting. There is no
inference to expose, and none is exposed.
"""

from __future__ import annotations

from typing import Any, Iterable

from .budget import Budget
from .manifest import RequirementCheck
from .model import Inventory, Observation
from .plan import Decision, ExecutionPlan
from .registry import Registry
from .scores import ScoreSet

__all__ = [
    "format_bytes",
    "render_budget",
    "render_inventory",
    "render_plan",
    "render_scores",
    "render_service",
]

_UNITS = (("TiB", 1024 ** 4), ("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024))


def format_bytes(value: Any) -> str:
    """Bytes in the largest unit that leaves a number a person can hold."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "unknown"
    if value < 0:
        return "unknown"
    for name, size in _UNITS:
        if value >= size:
            return f"{value / size:.1f} {name}"
    return f"{int(value)} B"


def _observation(observation: Observation) -> str:
    if observation.state == "measured":
        return str(observation.value)
    if observation.state == "absent":
        return f"absent ({observation.detail})" if observation.detail else "absent"
    return f"unknown ({observation.detail})" if observation.detail else "unknown"


def _requirement_line(check: RequirementCheck) -> str:
    if check.requirement.endswith("Bytes"):
        required, measured = format_bytes(check.required), format_bytes(check.measured)
    else:
        required, measured = str(check.required), str(check.measured)
    mark = {True: "ok  ", False: "FAIL", None: "?   "}[check.satisfied]
    line = f"  {mark} {check.requirement}: required {required}, measured {measured}"
    return f"{line}\n         {check.detail}" if check.detail else line


def render_inventory(inventory: Inventory) -> str:
    """The sanitized inventory as a person would read it."""
    lines = [
        f"Capability inventory, detected {inventory.detected_at}",
        f"  discovery took {inventory.detection_duration_ms} ms of a {inventory.detection_budget_ms} ms budget",
        "",
        "System",
        f"  architecture      {_observation(inventory.system.architecture)}",
        f"  kernel            {_observation(inventory.system.kernel_release)}",
        f"  virtualized       {_observation(inventory.system.virtualized)}",
        f"  containerized     {_observation(inventory.system.containerized)}",
        "",
        "CPU",
        f"  model             {_observation(inventory.cpu.model)}",
        f"  logical threads   {_observation(inventory.cpu.logical_threads)}",
        f"  cgroup quota      {_observation(inventory.cpu.quota_cores)}",
        f"  effective cores   {inventory.cpu.effective_cores(0.0) or 'unknown'}",
        f"  load average      {_observation(inventory.cpu.load_average_1m)}",
        "",
        "Memory",
        f"  physical          {format_bytes(inventory.memory.physical_bytes.get(None))}",
        f"  cgroup ceiling    {format_bytes(inventory.memory.cgroup_limit_bytes.get(None))}",
        f"  usable            {format_bytes(inventory.memory.usable_bytes(None))}",
        f"  available now     {format_bytes(inventory.memory.usable_available_bytes(None))}",
        f"  pressure (some)   {_observation(inventory.memory.pressure_some_avg10)}",
        "",
        "Graphics and accelerators",
    ]
    if not inventory.gpu:
        lines.append("  no GPU devices were enumerated")
    for device in inventory.gpu:
        runtimes = ", ".join(
            f"{name}={_observation(value)}" for name, value in sorted(device.runtimes.items())
        ) or "none probed"
        lines.extend([
            f"  GPU {device.index}: {_observation(device.description)} ({_observation(device.kind)})",
            f"    driver          {_observation(device.driver)}",
            f"    render node     {_observation(device.render_node)}",
            f"    usable          {'yes' if device.driver_ready else 'no - presence is not usability'}",
            f"    VRAM            {format_bytes(device.vram_total_bytes.get(None))}",
            f"    runtimes        {runtimes}",
        ])
    for accelerator in inventory.accelerators:
        lines.append(f"  {accelerator.kind}: {_observation(accelerator.description)}")

    lines.extend([
        "",
        "Storage",
        f"  root free         {format_bytes(inventory.storage.root_available_bytes.get(None))} "
        f"of {format_bytes(inventory.storage.root_total_bytes.get(None))}",
        f"  filesystem        {_observation(inventory.storage.filesystem)}",
        f"  read-only         {_observation(inventory.storage.read_only)}",
        f"  class             {_observation(inventory.storage.storage_class)}",
        "",
        "Network",
        f"  default route     {_observation(inventory.network.default_route)}",
        f"  connection type   {_observation(inventory.network.connection_type)}",
        f"  metered           {_observation(inventory.network.metered)}",
        "",
        "Power and thermal",
        f"  supply            {_observation(inventory.power.supply)}",
        f"  battery           {_observation(inventory.power.battery_percent)}",
        f"  cooling engaged   {_observation(inventory.thermal.throttled)}",
        "",
        "Display and interaction",
        f"  connected outputs {_observation(inventory.display.connected_outputs)}",
        f"  resolution        {_observation(inventory.display.max_resolution)}",
        f"  keyboard          {_observation(inventory.display.keyboard)}",
        f"  pointer           {_observation(inventory.display.pointer)}",
        f"  touch             {_observation(inventory.display.touch)}",
        f"  audio out / in    {_observation(inventory.audio.output_present)} / {_observation(inventory.audio.input_present)}",
        "",
        "This inventory is local. It contains no serial numbers, MAC addresses or",
        "hostnames, and nothing here is transmitted.",
    ])

    incomplete = [item for item in inventory.probes if item.state != "ok"]
    if incomplete:
        lines.append("")
        lines.append("Probes that did not complete:")
        lines.extend(f"  {item.name}: {item.state} - {item.detail}" for item in incomplete)
    return "\n".join(lines)


def render_scores(scores: ScoreSet) -> str:
    lines = [
        "Capability scores (0-100 per dimension; there is no overall score)",
        "",
    ]
    for name, question in _dimension_order(scores):
        score = scores.get(name)
        value = "unmeasured" if score.value is None else f"{score.value:5.1f}"
        lines.append(f"  {name:26} {value}   confidence: {score.confidence}")
        lines.append(f"  {'':26} {question}")
        for note in score.notes:
            lines.append(f"  {'':26} - {note}")
        lines.append("")
    lines.append("A high score in one dimension may not be used to satisfy a requirement in another.")
    return "\n".join(lines)


def _dimension_order(scores: ScoreSet) -> Iterable[tuple[str, str]]:
    from .scores import DIMENSIONS

    for name, question in DIMENSIONS:
        if name in scores.scores:
            yield name, question


def render_budget(budget: Budget) -> str:
    lines = [
        "Resource budget",
        "",
        f"  usable memory          {format_bytes(budget.usable_bytes)}",
        f"  available right now    {format_bytes(budget.currently_available_bytes)}",
        f"  protected reserve      {format_bytes(budget.protected_reserve_bytes)}  (never allocatable, by anything)",
        f"  allocatable (idle)     {format_bytes(budget.allocatable_bytes)}",
        f"  allocatable (now)      {format_bytes(budget.currently_allocatable_bytes)}",
        f"  essential services     {format_bytes(budget.essential_services_bytes)}",
        f"  foreground workload    {format_bytes(budget.foreground_workload_bytes)}",
        "",
        "  Memory categories",
    ]
    for name, category in budget.categories.items():
        if category.funded:
            lines.append(f"    {name:22} {format_bytes(category.bytes_allowed):>10}   {category.purpose}")
        else:
            lines.append(f"    {name:22} {'unfunded':>10}   {category.reason}")

    lines.extend([
        "",
        "  CPU",
        f"    effective cores      {budget.effective_cores:g}",
        f"    background quota     {budget.background_cpu_percent:.0f}%",
        f"    interactive quota    {budget.interactive_cpu_percent:.0f}%",
        "",
        "  GPU",
        f"    local inference      {'permitted' if budget.gpu_local_inference_allowed else 'not permitted'}",
        f"    rendering            {'permitted' if budget.gpu_rendering_allowed else 'not permitted'}",
    ])
    lines.extend(f"    - {reason}" for reason in budget.gpu_reasons)
    lines.extend([
        "",
        "  Storage",
        f"    cache                {format_bytes(budget.cache_storage_bytes)}",
        f"    logs                 {format_bytes(budget.log_storage_bytes)}",
        f"    temporary            {format_bytes(budget.temporary_storage_bytes)}",
    ])

    if not budget.viable:
        lines.extend([
            "",
            f"  This machine is short {format_bytes(budget.essential_shortfall_bytes)} of what its own",
            "  essential services declare they need. Bunny OS cannot run its control plane here.",
        ])
    if budget.notes:
        lines.append("")
        lines.extend(f"  note: {note}" for note in budget.notes)
    return "\n".join(lines)


def render_plan(plan: ExecutionPlan, registry: Registry | None = None) -> str:
    lines = [f"Execution plan, generated {plan.generated_at}", ""]
    width = max((len(decision.service_id) for decision in plan.decisions), default=10)
    for decision in plan.decisions:
        implementation = f" via {decision.implementation_id}" if decision.implementation_id else ""
        grant = f"  {format_bytes(decision.memory_grant_bytes)}" if decision.memory_grant_bytes else ""
        lines.append(f"  {decision.service_id:{width}}  {decision.action:<13}{implementation}{grant}")
    lines.extend([
        "",
        f"  {len(plan.running())} of {len(plan.decisions)} services will run, "
        f"granted {format_bytes(plan.granted_memory_bytes)} in total.",
    ])
    if plan.notes:
        lines.append("")
        lines.extend(f"  note: {note}" for note in plan.notes)
    lines.append("")
    lines.append("  Run 'bunny-os capability explain <service-id>' for the reasoning behind any line.")
    return "\n".join(lines)


def render_service(
    decision: Decision,
    registry: Registry,
    budget: Budget,
    inventory: Inventory,
) -> str:
    """The full explanation for one service, in the shape §11 specifies."""
    service = registry.get(decision.service_id)
    title = service.title if service else decision.service_id

    headline = {
        "start_local": f"{decision.service_id} runs locally.",
        "start_remote": f"{decision.service_id} runs remotely.",
        "suspend": f"{decision.service_id} is suspended.",
        "stop": f"{decision.service_id} is stopped.",
        "defer": f"{decision.service_id} is deferred.",
        "reject": f"{decision.service_id} was not started locally.",
    }[decision.action]

    lines = [headline, ""]
    if service:
        lines.extend([
            f"  {title}",
            f"  {service.description}" if service.description else "",
            f"  essential: {'yes' if service.essential else 'no'}    priority: {service.priority}"
            f"    budget category: {service.budget_category}",
            "",
        ])

    lines.append("Reason:")
    for reason in decision.reasons:
        lines.append(f"  - {reason.message}")
        if reason.required is not None or reason.measured is not None:
            required = format_bytes(reason.required) if isinstance(reason.required, int) and reason.required > 4096 else reason.required
            measured = format_bytes(reason.measured) if isinstance(reason.measured, int) and reason.measured > 4096 else reason.measured
            lines.append(f"      required {required}, measured {measured}")

    blocking = [check for check in decision.checks if check.blocking]
    if blocking:
        lines.extend(["", "Requirements not satisfied:"])
        lines.extend(_requirement_line(check) for check in blocking)

    satisfied = [check for check in decision.checks if check.satisfied is True]
    if satisfied and decision.running:
        lines.extend(["", "Requirements satisfied:"])
        lines.extend(_requirement_line(check) for check in satisfied)

    if decision.implementation_id and service:
        implementation = service.implementation(decision.implementation_id)
        ladder = service.ordered_implementations()
        if implementation and len(ladder) > 1:
            lines.extend(["", "Implementation ladder (richest first):"])
            for item in ladder:
                marker = "->" if item.id == decision.implementation_id else "  "
                lines.append(f"  {marker} {item.id:22} {item.locality:7} {item.title}")

    if decision.fallback:
        lines.extend(["", "Fallback selected:", f"  - {decision.fallback}"])

    dependents = registry.dependents_of(decision.service_id)
    if dependents and not decision.running:
        lines.extend(["", "Also affected:", f"  - {', '.join(dependents)} depend on this service"])

    lines.extend([
        "",
        "This explanation describes system measurements and deterministic policy.",
        "It contains no model reasoning.",
    ])
    return "\n".join(line for line in lines if line is not None)
