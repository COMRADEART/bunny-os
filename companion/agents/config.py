# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Provider configuration: a file the user edits, not an operation a task calls.

§21 separates provider configuration from task execution, and this module is
that separation: configurations are loaded from ``<root>/agents/providers.json``
at service start, validated strictly, and never mutated by any protocol
operation. Changing a provider is editing a file and restarting a worker —
an explicit user action with a visible artifact — rather than something a
generation could be talked into.

**Local candidates exist by default; remote providers do not.** The built-in
configuration names the two local runtimes this build genuinely speaks —
Ollama and a llama.cpp server, both pinned to loopback — plus the local
subprocess runner. They are enabled because a local provider can leak nothing:
its endpoint type is incapable of naming a non-loopback host. A remote
provider reaches the registry only from an explicit file entry with
``"remote": true``, an ``https`` endpoint, an ``enabled: true`` the user
typed, and a credential *reference* (§5 — never a credential). A remote entry
missing any of these is a :class:`ProviderConfigurationError` naming the gap,
not a provider that limps.

There are no API keys in this file's schema. The credential field is a
reference — kind and locator — and a configuration carrying something
key-shaped in any string field is refused by the same scrubber the privacy
layer uses, because a key pasted where a reference belongs is a key on disk
in the wrong mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ..privacy import DATA_CLASSES, scrub_text
from .credentials import CredentialReference
from .descriptor import (
    COST_CLASSES,
    EndpointIdentity,
    SUPPORTED_TASK_CLASSES,
)
from .errors import ProviderConfigurationError
from .wire import HttpTarget

__all__ = [
    "AgentConfiguration",
    "CONFIGURATION_FILE_NAME",
    "ProviderConfiguration",
    "default_configuration",
    "load_agent_configuration",
]

CONFIGURATION_FILE_NAME = "providers.json"
_MAX_PROVIDERS = 16
_MAX_FILE_BYTES = 64 * 1024

#: Ports the built-in local candidates listen on by default. These are the
#: runtimes' own documented defaults, not choices this build made.
OLLAMA_DEFAULT_PORT = 11434
LLAMACPP_DEFAULT_PORT = 8080


@dataclass(frozen=True)
class ProviderConfiguration:
    """One provider as the user configured it. Validation refuses, never repairs."""

    provider_id: str
    adapter_id: str
    endpoint: EndpointIdentity
    http: HttpTarget | None = None
    program: str = ""
    model_id: str = ""
    model_revision: str = ""
    enabled: bool = True
    remote: bool = False
    credential: CredentialReference = field(default_factory=CredentialReference)
    cost_class: str = "free"
    maximum_privacy_class: str = "secret"
    context_limit_tokens: int = 4096
    maximum_output_tokens: int = 1024
    supported_task_classes: tuple[str, ...] = ("question", "summarise", "transform", "compute")
    supported_languages: tuple[str, ...] = ("en",)
    license_reference: str = ""
    #: Integer cost units per thousand tokens, for the *estimate* column only.
    estimated_units_per_kilotoken: int = 0
    pricing_reference: str = ""
    user_preferred: bool = False

    def __post_init__(self) -> None:
        if self.cost_class not in COST_CLASSES:
            raise ProviderConfigurationError(f"cost class {self.cost_class!r} is unknown")
        if self.maximum_privacy_class not in DATA_CLASSES:
            raise ProviderConfigurationError(f"privacy class {self.maximum_privacy_class!r} is unknown")
        for task_class in self.supported_task_classes:
            if task_class not in SUPPORTED_TASK_CLASSES:
                raise ProviderConfigurationError(f"task class {task_class!r} is unknown")
        if self.context_limit_tokens <= 0 or self.maximum_output_tokens <= 0:
            raise ProviderConfigurationError("context and output limits must be positive")
        if self.estimated_units_per_kilotoken < 0:
            raise ProviderConfigurationError("pricing must be non-negative")
        # Locality coherence: the endpoint kind, the remote flag and the wire
        # target must tell one story.
        if self.remote:
            if self.endpoint.kind != "remote-https":
                raise ProviderConfigurationError(
                    f"remote provider {self.provider_id!r} must use a remote-https endpoint"
                )
            if self.http is None or self.http.scheme != "https" or self.http.local:
                raise ProviderConfigurationError(
                    f"remote provider {self.provider_id!r} must name an https, non-loopback target"
                )
            if self.credential.kind == "none":
                raise ProviderConfigurationError(
                    f"remote provider {self.provider_id!r} declares no credential source; "
                    "an unauthenticated remote endpoint is not configurable"
                )
            if self.maximum_privacy_class not in ("public", "internal"):
                raise ProviderConfigurationError(
                    f"remote provider {self.provider_id!r} may not hold data above internal"
                )
            if self.cost_class == "free":
                raise ProviderConfigurationError(
                    f"remote provider {self.provider_id!r} cannot be cost class 'free'; "
                    "metered is the honest floor for somebody else's computer"
                )
        else:
            if self.endpoint.kind == "remote-https":
                raise ProviderConfigurationError(
                    f"provider {self.provider_id!r} has a remote endpoint but no remote marker; "
                    "locality is stated twice so it cannot drift once"
                )
            if self.http is not None and not self.http.local:
                raise ProviderConfigurationError(
                    f"local provider {self.provider_id!r} must target loopback"
                )
        if self.endpoint.kind == "subprocess" and not self.program:
            raise ProviderConfigurationError("a subprocess provider names its program")
        # Nothing key-shaped hides in any string field.
        for name, value in (
            ("providerId", self.provider_id),
            ("modelId", self.model_id),
            ("modelRevision", self.model_revision),
            ("licenseReference", self.license_reference),
            ("pricingReference", self.pricing_reference),
            ("credential locator", self.credential.locator),
        ):
            if scrub_text(value) != value:
                raise ProviderConfigurationError(
                    f"configuration field {name} carries credential-shaped content; "
                    "credentials are referenced, never written into configuration"
                )

    @property
    def local(self) -> bool:
        return not self.remote

    def to_json(self) -> dict[str, Any]:
        return {
            "providerId": self.provider_id,
            "adapterId": self.adapter_id,
            "endpoint": self.endpoint.to_json(),
            "program": self.program,
            "modelId": self.model_id,
            "modelRevision": self.model_revision,
            "enabled": self.enabled,
            "remote": self.remote,
            "credential": self.credential.to_json(),
            "costClass": self.cost_class,
            "maximumPrivacyClass": self.maximum_privacy_class,
            "contextLimitTokens": self.context_limit_tokens,
            "maximumOutputTokens": self.maximum_output_tokens,
            "supportedTaskClasses": list(self.supported_task_classes),
            "supportedLanguages": list(self.supported_languages),
            "licenseReference": self.license_reference,
            "estimatedUnitsPerKilotoken": self.estimated_units_per_kilotoken,
            "pricingReference": self.pricing_reference,
            "userPreferred": self.user_preferred,
        }


@dataclass(frozen=True)
class AgentConfiguration:
    """Everything the subsystem is configured with, in configuration order.

    Order matters: §9's deterministic selection breaks ties by position in
    this tuple, so "which provider wins" is answerable by reading the file
    top to bottom.
    """

    providers: tuple[ProviderConfiguration, ...] = ()
    #: Which executor the runtime should put first: the deterministic local
    #: one (the existing behaviour, and the default) or the provider-backed
    #: one. A preference, not a removal — both remain constructed.
    executor_preference: str = "deterministic"
    #: Provider id for the observation-only reviewer, empty for none.
    reviewer_provider_id: str = ""
    approved_credential_directories: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.executor_preference not in ("deterministic", "provider"):
            raise ProviderConfigurationError(
                f"executor preference {self.executor_preference!r} is not "
                "'deterministic' or 'provider'"
            )
        if len(self.providers) > _MAX_PROVIDERS:
            raise ProviderConfigurationError(f"more than {_MAX_PROVIDERS} providers configured")
        seen: set[str] = set()
        for item in self.providers:
            if item.provider_id in seen:
                raise ProviderConfigurationError(f"provider id {item.provider_id!r} appears twice")
            seen.add(item.provider_id)
        if self.reviewer_provider_id and self.reviewer_provider_id not in seen:
            raise ProviderConfigurationError(
                f"reviewer provider {self.reviewer_provider_id!r} is not configured"
            )

    def provider(self, provider_id: str) -> ProviderConfiguration | None:
        for item in self.providers:
            if item.provider_id == provider_id:
                return item
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "providers": [item.to_json() for item in self.providers],
            "executorPreference": self.executor_preference,
            "reviewerProviderId": self.reviewer_provider_id,
            "approvedCredentialDirectories": list(self.approved_credential_directories),
        }


def default_configuration(root: Path | None = None) -> AgentConfiguration:
    """The out-of-the-box shape: local candidates only, nothing remote."""
    directories: tuple[str, ...] = tuple(
        str(item) for item in (
            (root / "credentials") if root is not None else None,
            Path.home() / ".config" / "bunny-os" / "credentials",
        ) if item is not None
    )
    return AgentConfiguration(
        providers=(
            ProviderConfiguration(
                provider_id="local.ollama",
                adapter_id="ollama",
                endpoint=EndpointIdentity(kind="loopback-http", locator=f"127.0.0.1:{OLLAMA_DEFAULT_PORT}"),
                http=HttpTarget(scheme="http", host="127.0.0.1", port=OLLAMA_DEFAULT_PORT),
                license_reference="runtime MIT; model licenses per model",
            ),
            ProviderConfiguration(
                provider_id="local.llamacpp",
                adapter_id="llamacpp",
                endpoint=EndpointIdentity(kind="loopback-http", locator=f"127.0.0.1:{LLAMACPP_DEFAULT_PORT}"),
                http=HttpTarget(scheme="http", host="127.0.0.1", port=LLAMACPP_DEFAULT_PORT),
                license_reference="runtime MIT; model licenses per model",
            ),
            ProviderConfiguration(
                provider_id="local.llamacli",
                adapter_id="llamacli",
                endpoint=EndpointIdentity(kind="subprocess", locator="llama-cli"),
                program="llama-cli",
                license_reference="runtime MIT; model licenses per model",
            ),
        ),
        approved_credential_directories=directories,
    )


def _reference_from_json(value: Mapping[str, Any], provider_id: str) -> CredentialReference:
    if not isinstance(value, Mapping):
        raise ProviderConfigurationError(f"provider {provider_id!r}: credential must be an object")
    kind = value.get("kind", "none")
    locator = value.get("locator", "")
    if not isinstance(kind, str) or not isinstance(locator, str):
        raise ProviderConfigurationError(f"provider {provider_id!r}: credential fields must be strings")
    return CredentialReference(kind=kind, locator=locator)


def _provider_from_json(value: Mapping[str, Any], index: int) -> ProviderConfiguration:
    if not isinstance(value, Mapping):
        raise ProviderConfigurationError(f"providers[{index}] is not an object")
    provider_id = value.get("providerId", "")
    if not isinstance(provider_id, str) or not provider_id:
        raise ProviderConfigurationError(f"providers[{index}] has no providerId")
    known = {
        "providerId", "adapterId", "endpoint", "program", "modelId", "modelRevision",
        "enabled", "remote", "credential", "costClass", "maximumPrivacyClass",
        "contextLimitTokens", "maximumOutputTokens", "supportedTaskClasses",
        "supportedLanguages", "licenseReference", "estimatedUnitsPerKilotoken",
        "pricingReference", "userPreferred",
    }
    unknown = set(value) - known
    if unknown:
        raise ProviderConfigurationError(
            f"provider {provider_id!r} carries unknown fields {sorted(unknown)}; "
            "unknown configuration fails closed"
        )
    endpoint_value = value.get("endpoint")
    if not isinstance(endpoint_value, Mapping):
        raise ProviderConfigurationError(f"provider {provider_id!r} has no endpoint object")
    kind = endpoint_value.get("kind", "")
    remote = bool(value.get("remote", False))
    http: HttpTarget | None = None
    if kind in ("loopback-http", "remote-https"):
        host = endpoint_value.get("host", "")
        port = endpoint_value.get("port", 0)
        base_path = endpoint_value.get("basePath", "")
        if not isinstance(host, str) or not isinstance(port, int) or not isinstance(base_path, str):
            raise ProviderConfigurationError(f"provider {provider_id!r} endpoint fields are malformed")
        http = HttpTarget(
            scheme="https" if kind == "remote-https" else "http",
            host=host, port=port, base_path=base_path,
        )
        locator = http.locator
    elif kind == "subprocess":
        locator = str(endpoint_value.get("program", value.get("program", "")))
    else:
        raise ProviderConfigurationError(f"provider {provider_id!r} endpoint kind {kind!r} is unknown")
    return ProviderConfiguration(
        provider_id=provider_id,
        adapter_id=str(value.get("adapterId", "")),
        endpoint=EndpointIdentity(kind=kind, locator=locator),
        http=http,
        program=str(value.get("program", "")),
        model_id=str(value.get("modelId", "")),
        model_revision=str(value.get("modelRevision", "")),
        enabled=bool(value.get("enabled", not remote)),
        remote=remote,
        credential=_reference_from_json(value.get("credential", {"kind": "none", "locator": ""}), provider_id),
        cost_class=str(value.get("costClass", "metered" if remote else "free")),
        maximum_privacy_class=str(value.get("maximumPrivacyClass", "internal" if remote else "secret")),
        context_limit_tokens=int(value.get("contextLimitTokens", 4096)),
        maximum_output_tokens=int(value.get("maximumOutputTokens", 1024)),
        supported_task_classes=tuple(value.get("supportedTaskClasses",
                                               ("question", "summarise", "transform", "compute"))),
        supported_languages=tuple(value.get("supportedLanguages", ("en",))),
        license_reference=str(value.get("licenseReference", "")),
        estimated_units_per_kilotoken=int(value.get("estimatedUnitsPerKilotoken", 0)),
        pricing_reference=str(value.get("pricingReference", "")),
        user_preferred=bool(value.get("userPreferred", False)),
    )


def load_agent_configuration(root: Path) -> AgentConfiguration:
    """Load ``<root>/agents/providers.json``, or the defaults when absent.

    A file that exists but cannot be accepted is an error, not a fallback to
    defaults: silently ignoring a broken configuration would run providers
    the user thought they had replaced.
    """
    path = root / "agents" / CONFIGURATION_FILE_NAME
    if not path.exists():
        return default_configuration(root)
    raw = path.read_bytes()
    if len(raw) > _MAX_FILE_BYTES:
        raise ProviderConfigurationError(f"{path} exceeds {_MAX_FILE_BYTES} bytes")
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderConfigurationError(f"{path} is not JSON: {error}") from None
    if not isinstance(document, Mapping):
        raise ProviderConfigurationError(f"{path} must hold a JSON object")
    providers_value = document.get("providers", [])
    if not isinstance(providers_value, list):
        raise ProviderConfigurationError("'providers' must be a list")
    providers = tuple(
        _provider_from_json(item, index) for index, item in enumerate(providers_value)
    )
    directories = document.get("approvedCredentialDirectories", None)
    if directories is None:
        directories = default_configuration(root).approved_credential_directories
    elif not (isinstance(directories, list) and all(isinstance(item, str) for item in directories)):
        raise ProviderConfigurationError("'approvedCredentialDirectories' must be a list of strings")
    else:
        directories = tuple(directories)
    return AgentConfiguration(
        providers=providers,
        executor_preference=str(document.get("executorPreference", "deterministic")),
        reviewer_provider_id=str(document.get("reviewerProviderId", "")),
        approved_credential_directories=tuple(directories),
    )
