# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Which local AI providers this machine actually has, asked one layer at a time.

§8 asks five questions per provider and they are five questions, not one:

======================  ==========================================================
Installed?              is the runtime on this machine at all
Running?                is it answering right now
Models available?       does it offer weights, and which
Resource requirement?   roughly what running the smallest one would cost
Eligible?               all of the above, and this machine can afford it
======================  ==========================================================

Collapsing them is the failure this module exists to prevent. A first run that
reports "local AI unavailable" when Ollama is installed but stopped has told the
user something true and useless; the actionable sentence is *start it*, and the
only way to produce that sentence is to have measured installation and execution
separately.

The other half of §8 is a prohibition: **do not pretend that hardware capability
means a local model exists.** A 32 GiB machine with a discrete GPU and no
weights on disk has no local AI, and every "your machine can run local models!"
claim made from a RAM figure alone is that mistake. So the eligibility rule here
never reads memory *first*: a provider with no models is ineligible for the
reason "no models", and the memory comparison only happens once there is a model
whose size can be compared to something.

Nothing here starts a server, installs a package or downloads weights. The
survey is read-only against the machine, and every remedy is a sentence the user
can act on rather than an action taken on their behalf.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "LOCAL_PROVIDER_KINDS",
    "LocalProviderFinding",
    "LocalProviderSurvey",
    "ModelSummary",
    "survey_local_providers",
]

#: How each shipped local adapter is reached, which decides what "installed"
#: and "running" can even mean for it. A server is installed when its program
#: is on the path and running when its endpoint answers; a subprocess runtime
#: has no separate running state — the program *is* the runtime — so the two
#: collapse deliberately and the finding says which case it is.
LOCAL_PROVIDER_KINDS: Mapping[str, str] = {
    "ollama": "server",
    "llamacpp": "server",
    "llamacli": "subprocess",
}

#: What to look for on ``PATH`` to answer "installed?" for each adapter, in
#: order. First hit wins. ``llama-server`` and ``llama-cpp-server`` are both in
#: use upstream; ``server`` alone is deliberately not here, because a binary
#: called ``server`` on a user's path is not evidence of anything.
_PROGRAM_CANDIDATES: Mapping[str, tuple[str, ...]] = {
    "ollama": ("ollama",),
    "llamacpp": ("llama-server", "llama-cpp-server", "llamacpp-server"),
    "llamacli": ("llama-cli", "llama"),
}

#: Where a packaged runtime lands when it is installed as a service rather than
#: onto ``PATH``. Checked only when the path lookup fails, and reported as the
#: evidence when it succeeds, so "installed" is never asserted without saying
#: what was found.
_INSTALL_MARKERS: Mapping[str, tuple[str, ...]] = {
    "ollama": (
        "/usr/local/bin/ollama",
        "/usr/lib/systemd/system/ollama.service",
        "/etc/systemd/system/ollama.service",
    ),
    "llamacpp": ("/usr/local/bin/llama-server",),
    "llamacli": ("/usr/local/bin/llama-cli",),
}

#: A model's file size is not its resident size, and this is the factor between
#: them that the survey uses for the estimate. Weights are memory-mapped and the
#: runtime adds a KV cache proportional to context; 1.25 is the low end of what
#: llama.cpp costs above the file at a small context, and the estimate is
#: labelled an estimate everywhere it is shown.
_RESIDENT_FACTOR = 1.25

#: Below this much *available* memory the survey will not call a model eligible,
#: whatever its size, because the desktop and the companion also have to run.
_HEADROOM_BYTES = 512 * 1024 * 1024

_MAX_MODELS_REPORTED = 32


@dataclass(frozen=True)
class ModelSummary:
    """One set of weights a provider offers, and what it would cost.

    ``size_bytes`` is what the provider reported: a file size for llama-cli, the
    manifest size for Ollama, whatever ``/v1/models`` carries for a server. Zero
    means the provider did not say, and a zero here must never be read as a
    small model — :attr:`resource_known` is the flag that says whether the
    estimate means anything.
    """

    model_id: str
    revision: str = ""
    size_bytes: int = 0
    context_limit_tokens: int = 0

    @property
    def resource_known(self) -> bool:
        return self.size_bytes > 0

    @property
    def estimated_resident_bytes(self) -> int:
        """Roughly what holding this model would cost. An estimate, not a
        measurement, and zero when the provider reported no size."""
        return int(self.size_bytes * _RESIDENT_FACTOR) if self.size_bytes > 0 else 0

    def to_json(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "revision": self.revision,
            "sizeBytes": self.size_bytes,
            "contextLimitTokens": self.context_limit_tokens,
            "resourceKnown": self.resource_known,
            "estimatedResidentBytes": self.estimated_resident_bytes,
            "estimateBasis": (
                f"an estimate: the reported size x {_RESIDENT_FACTOR}, for weights plus a "
                "small KV cache. Not a measurement of this model running here"
                if self.resource_known
                else "no estimate: the provider reported no size for this model"
            ),
        }


@dataclass(frozen=True)
class LocalProviderFinding:
    """One local provider, at every layer §8 asks about."""

    provider_id: str
    adapter_id: str
    kind: str
    installed: bool
    installed_evidence: str
    running: bool
    running_evidence: str
    models: tuple[ModelSummary, ...] = ()
    eligible: bool = False
    reason: str = ""
    remedy: str = ""
    #: The smallest model's estimate, which is the one that decides whether the
    #: machine can run *anything* from this provider.
    estimated_resident_bytes: int = 0
    available_memory_bytes: int = 0

    @property
    def model_count(self) -> int:
        return len(self.models)

    @property
    def layer(self) -> str:
        """The furthest rung reached, for a one-word status column.

        A ladder, so each rung implies the one below it. Written as a descent
        rather than a series of independent tests because the first version was
        the latter, and it reported ``models-present`` for a provider whose
        ``installed`` was ``False`` — a rung above one that did not hold, which
        is not a state anything can be.
        """
        if self.eligible:
            return "eligible"
        if self.running and self.models:
            return "models-present"
        if self.running:
            return "running"
        if self.installed:
            return "installed"
        return "absent"

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "adapterId": self.adapter_id,
            "kind": self.kind,
            "installed": self.installed,
            "installedEvidence": self.installed_evidence,
            "running": self.running,
            "runningEvidence": self.running_evidence,
            "modelCount": self.model_count,
            "models": [model.to_json() for model in self.models],
            "eligible": self.eligible,
            "layer": self.layer,
            "reason": self.reason,
            "remedy": self.remedy,
            "estimatedResidentBytes": self.estimated_resident_bytes,
            "availableMemoryBytes": self.available_memory_bytes,
        }


@dataclass(frozen=True)
class LocalProviderSurvey:
    """Every local provider on this machine, and one sentence about all of them."""

    findings: tuple[LocalProviderFinding, ...] = ()
    available_memory_bytes: int = 0
    #: Set when the survey could not run at all — no registry, an unreadable
    #: configuration. Distinct from "surveyed and found nothing", because the
    #: remedies differ completely.
    error: str = ""

    @property
    def eligible(self) -> tuple[LocalProviderFinding, ...]:
        return tuple(finding for finding in self.findings if finding.eligible)

    @property
    def any_eligible(self) -> bool:
        return bool(self.eligible)

    @property
    def any_model_present(self) -> bool:
        return any(finding.models for finding in self.findings)

    @property
    def summary(self) -> str:
        """The sentence the first-run page and the diagnostics both print.

        §32 requires that a machine with no model says so *clearly*, so the
        no-model case is spelled out rather than reported as an empty list.
        """
        if self.error:
            return f"Local AI providers could not be surveyed: {self.error}"
        eligible = self.eligible
        if eligible:
            names = ", ".join(finding.provider_id for finding in eligible)
            return f"Local AI is available through {names}. Bunny will use it before anything remote."
        if self.any_model_present:
            return (
                "A local model is installed but no provider can currently serve it. "
                "Bunny still works: type a request, and the provider page explains what is missing."
            )
        installed = [finding for finding in self.findings if finding.installed]
        if installed:
            names = ", ".join(finding.provider_id for finding in installed)
            return (
                f"A local AI runtime is installed ({names}) but no model is available to it. "
                "Bunny still starts and typed input still works; no model is downloaded automatically."
            )
        return (
            "No local AI provider is installed on this machine. Bunny still starts, "
            "the character appears and typed input works; answers need a provider you install yourself."
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "anyEligible": self.any_eligible,
            "anyModelPresent": self.any_model_present,
            "availableMemoryBytes": self.available_memory_bytes,
            "summary": self.summary,
            "error": self.error,
            "providers": [finding.to_json() for finding in self.findings],
        }


def _available_memory_bytes() -> int:
    """``MemAvailable``, which is the only number worth comparing a model to.

    ``MemTotal`` would say a 16 GiB machine can hold a 14 GiB model while a
    desktop session is using 4 GiB of it.
    """
    try:
        content = Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    for line in content.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                return int(parts[1]) * 1024
    return 0


def _installed(adapter_id: str) -> tuple[bool, str]:
    """Is the runtime on this machine? Answered from the filesystem only.

    Deliberately not answered from the probe: a probe that reaches a loopback
    port says something about a *server*, and the question here is about a
    *package*. They differ in both directions — an installed runtime that is not
    running, and a port that answers because something else is listening on it.
    """
    for program in _PROGRAM_CANDIDATES.get(adapter_id, ()):
        resolved = shutil.which(program)
        if resolved:
            return True, f"{program} resolves to {resolved}"
    for marker in _INSTALL_MARKERS.get(adapter_id, ()):
        if Path(marker).exists():
            return True, f"{marker} exists"
    candidates = ", ".join(_PROGRAM_CANDIDATES.get(adapter_id, ())) or adapter_id
    return False, f"none of {candidates} is on PATH and no packaged install marker was found"


def _models(probe: Any) -> tuple[ModelSummary, ...]:
    listings: Iterable[Any] = getattr(probe, "models", ()) or ()
    summaries: list[ModelSummary] = []
    for listing in tuple(listings)[:_MAX_MODELS_REPORTED]:
        summaries.append(ModelSummary(
            model_id=str(getattr(listing, "model_id", "") or ""),
            revision=str(getattr(listing, "revision", "") or ""),
            size_bytes=max(0, int(getattr(listing, "size_bytes", 0) or 0)),
            context_limit_tokens=max(0, int(getattr(listing, "context_limit_tokens", 0) or 0)),
        ))
    return tuple(summary for summary in summaries if summary.model_id)


def _verdict(
    *,
    adapter_id: str,
    kind: str,
    installed: bool,
    running: bool,
    models: Sequence[ModelSummary],
    available_memory: int,
    detail: str,
) -> tuple[bool, str, str, int]:
    """``(eligible, reason, remedy, estimated_resident_bytes)``.

    The order of the tests is the contract. Installation, then execution, then
    weights, then memory — so that the reason a user is shown names the first
    thing that is missing rather than the last thing that was checked.
    """
    name = {"ollama": "Ollama", "llamacpp": "llama.cpp server", "llamacli": "llama-cli"}.get(
        adapter_id, adapter_id,
    )
    # For a *server*, answering is the operational fact and the local binary is
    # only evidence for the remedy. Gating eligibility on the binary reported a
    # working endpoint as "not installed — install it", on a machine where a
    # container was serving the port. Measured on the development host: Ollama
    # on 11434 with six models, something else on 8080 with one, and the survey
    # told the user to install a server that was already answering.
    #
    # For a *subprocess* runtime there is nothing to answer, so the program is
    # the whole of it and its absence is decisive.
    if kind == "subprocess" and not installed:
        return False, f"{name} is not installed on this machine.", (
            f"Install {name} from your usual software source, then return to this page and "
            "choose Check again. Bunny does not download AI runtimes or models for you."
        ), 0
    if kind == "server" and not running:
        if installed:
            hint = (
                " On a systemd install that is: systemctl --user start ollama"
                if adapter_id == "ollama" else ""
            )
            return False, f"{name} is installed but is not answering.", (
                f"Start {name} and leave it running, then choose Check again.{hint}"
            ), 0
        return False, f"{name} is not installed and nothing is answering for it.", (
            f"Install {name} from your usual software source and start it, then choose "
            "Check again. Bunny does not download AI runtimes or models for you."
        ), 0
    if not models:
        return False, f"{name} is running but offers no models.", (
            f"Add a model to {name} yourself — Bunny never downloads one for you, because a model "
            "is several gigabytes of your disk and your connection. Once one is present, "
            "choose Check again."
        ), 0
    sized = [model for model in models if model.resource_known]
    if not sized:
        # Models exist and none reported a size. Eligible, because refusing a
        # working provider over a missing number would be the survey inventing a
        # requirement, but the unknown is carried into the reason.
        return True, "", (
            f"{name} offers {len(models)} model(s). Their size was not reported, so no "
            "memory estimate is shown."
        ), 0
    smallest = min(sized, key=lambda model: model.size_bytes)
    estimate = smallest.estimated_resident_bytes
    if available_memory and estimate + _HEADROOM_BYTES > available_memory:
        return False, (
            f"{name}'s smallest model ({smallest.model_id}) is estimated to need "
            f"{_human(estimate)} and only {_human(available_memory)} is available."
        ), (
            "Close some applications and check again, or add a smaller model. "
            "The figure is an estimate from the model's size, not a measurement."
        ), estimate
    return True, "", (
        f"{name} is ready. The smallest model, {smallest.model_id}, is estimated to need "
        f"about {_human(estimate)}; that is an estimate from its size, not a measurement."
    ), estimate


def _human(value: int) -> str:
    if value <= 0:
        return "an unknown amount"
    gib = value / (1024 ** 3)
    if gib >= 1.0:
        return f"{gib:.1f} GiB"
    return f"{value / (1024 ** 2):.0f} MiB"


def survey_local_providers(
    registry: Any = None,
    *,
    monotonic: float = 0.0,
    refresh: bool = True,
    available_memory_bytes: int | None = None,
) -> LocalProviderSurvey:
    """Survey every local provider this build ships an adapter for.

    ``registry`` is an :class:`companion.agents.registry.AgentProviderRegistry`.
    Passing ``None`` builds one from the user's configuration, falling back to
    the default local-only configuration — which is the right behaviour for a
    first run, where no configuration file exists yet and the three local
    candidates are exactly what should be probed.

    Remote providers are skipped entirely. §8 is about local AI, and probing a
    remote endpoint during onboarding would be an outbound connection the user
    has not authorised — §13's rule, and §27's default.
    """
    memory = _available_memory_bytes() if available_memory_bytes is None else available_memory_bytes
    owned = False
    if registry is None:
        try:
            registry, owned = _default_registry(), True
        except Exception as error:  # pragma: no cover - configuration is validated elsewhere
            return LocalProviderSurvey(available_memory_bytes=memory, error=str(error))
    try:
        findings = tuple(_survey(registry, monotonic=monotonic, refresh=refresh, memory=memory))
    except Exception as error:  # pragma: no cover - defensive: onboarding must not crash
        return LocalProviderSurvey(available_memory_bytes=memory, error=str(error))
    finally:
        if owned:
            close = getattr(registry, "close", None)
            if callable(close):
                close()
    return LocalProviderSurvey(findings=findings, available_memory_bytes=memory)


def _default_registry() -> Any:
    from ..agents.adapters import default_adapters
    from ..agents.config import default_configuration, load_agent_configuration
    from ..agents.registry import AgentProviderRegistry

    root = Path(
        os.environ.get("BUNNY_COMPANION_CONFIG_HOME")
        or (Path.home() / ".config" / "bunny-os")
    )
    try:
        configuration = load_agent_configuration(root)
    except Exception:
        configuration = default_configuration(root)
    if not configuration.providers:
        configuration = default_configuration(root)
    return AgentProviderRegistry(configuration, default_adapters())


def _survey(
    registry: Any, *, monotonic: float, refresh: bool, memory: int,
) -> Iterable[LocalProviderFinding]:
    configuration = registry.configuration
    for config in configuration.providers:
        adapter_id = str(getattr(config, "adapter_id", ""))
        if getattr(config, "remote", False) or adapter_id not in LOCAL_PROVIDER_KINDS:
            continue
        kind = LOCAL_PROVIDER_KINDS[adapter_id]
        installed, installed_evidence = _installed(adapter_id)
        try:
            probe = registry.probe(config.provider_id, monotonic=monotonic, refresh=refresh)
        except Exception as error:
            probe = None
            detail = f"probe failed: {error}"
        else:
            detail = str(getattr(probe, "detail", "") or "")
        available = bool(getattr(probe, "available", False)) if probe is not None else False
        models = _models(probe) if probe is not None else ()
        if kind == "subprocess":
            # There is no server to be up: the program being present *is* the
            # runtime running. Saying "not running" about a binary that exists
            # would be a status nobody could act on.
            running = installed
            running_evidence = (
                "a subprocess runtime has no separate service; the program is the runtime"
                if installed else installed_evidence
            )
        else:
            running = available or bool(models)
            locator = getattr(getattr(config, "endpoint", None), "locator", "") or "its endpoint"
            running_evidence = (
                f"{locator} answered: {detail}" if running
                else f"{locator} did not answer: {detail or 'no response'}"
            )
        eligible, reason, remedy, estimate = _verdict(
            adapter_id=adapter_id, kind=kind, installed=installed, running=running,
            models=models, available_memory=memory, detail=detail,
        )
        yield LocalProviderFinding(
            provider_id=str(config.provider_id),
            adapter_id=adapter_id,
            kind=kind,
            installed=installed,
            installed_evidence=installed_evidence,
            running=running,
            running_evidence=running_evidence,
            models=models,
            eligible=eligible,
            reason=reason,
            remedy=remedy,
            estimated_resident_bytes=estimate,
            available_memory_bytes=memory,
        )
