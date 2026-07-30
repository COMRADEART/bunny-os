"""OEM profile validation.

The JSON Schema in ``schemas/oem-profile.schema.json`` makes unrepresentable the
shapes an OEM must never be able to express at all (arbitrary scripts, root
commands, extra top-level keys). This module adds the semantic rules a schema
cannot state: signing-namespace separation, branding entitlement, reviewed
kernel-module limits, and a deep scan for embedded secrets and protected
settings.

Nothing here trusts the profile author. A profile is rejected by default and
only accepted when every rule returns a decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping, Sequence

SCHEMA_VERSION = 1

PROGRAMME_LEVELS = (
    "community-image-builder",
    "validated-hardware-integrator",
    "supported-oem-partner",
    "official-bunny-os-device",
)

UPDATE_RESPONSIBILITIES = (
    "official-image",
    "official-image-with-signed-oem-extension",
    "independent-oem-variant",
)

KNOWN_REPOSITORIES = (
    "fedora",
    "fedora-updates",
    "bunny-os-stable",
    "bunny-os-oem-signed",
    "oem-signed-extension",
)

#: Settings an OEM profile or overlay may never set, at any nesting depth. These
#: are the privacy, telemetry, security-warning, encryption, recovery, and
#: permission-enforcement defaults that Bunny OS owns unconditionally.
PROTECTED_SETTINGS = frozenset({
    "bunny.diagnostics.enabled",
    "bunny.diagnostics.upload",
    "bunny.diagnostics.redaction",
    "bunny.telemetry.enabled",
    "bunny.telemetry.endpoint",
    "bunny.privacy.local-only",
    "bunny.privacy.dashboard-visible",
    "bunny.privacy.search-indexing",
    "bunny.permissions.enforcement",
    "bunny.permissions.prompt-required",
    "bunny.plugins.capability-ceiling",
    "bunny.provider.allow-cloud-fallback",
    "bunny.broker.allowlist",
    "bunny.broker.polkit-required",
    "os.encryption.required",
    "os.encryption.cipher",
    "os.recovery.enabled",
    "os.recovery.key-escrow",
    "os.secureboot.enforce",
    "os.update.trust-root",
    "os.update.signature-verification",
    "os.update.channel-pin",
    "os.security.warnings-visible",
    "os.security.selinux-mode",
    "os.firewall.default-zone",
})

#: Keys that would introduce an execution or credential channel. Their presence
#: at any depth is a rejection, not a warning.
FORBIDDEN_KEYS = frozenset({
    "script",
    "scripts",
    "prescript",
    "postscript",
    "preinstall",
    "postinstall",
    "firstbootscript",
    "command",
    "commands",
    "exec",
    "execstart",
    "runascommand",
    "rootcommand",
    "rootcommands",
    "shell",
    "entrypoint",
    "kickstart",
    "password",
    "passphrase",
    "secret",
    "secrets",
    "token",
    "apikey",
    "privatekey",
    "credential",
    "credentials",
    "wifipsk",
    "enrolmenttoken",
    "enrollmenttoken",
})

_SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(r"^ssh-(?:rsa|ed25519) AAAA"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b(?:api[_-]?key|secret|passwd|password|passphrase)\s*[:=]\s*\S{6,}", re.IGNORECASE),
)

#: Out-of-tree modules that have completed driver review. An OEM profile may not
#: introduce a module outside this set; see docs/DRIVER_REGRESSION_POLICY.md.
REVIEWED_OUT_OF_TREE_MODULES = frozenset({
    "nvidia",
    "nvidia_drm",
    "nvidia_modeset",
    "nvidia_uvm",
    "v4l2loopback",
})

_OEM_KEY_ID = re.compile(r"^oem-[a-z0-9-]{2,48}$")
_RELEASE_KEY_PREFIXES = ("bunny-os-release", "bunny-release", "bunny-stable", "fleet-", "sync-")


@dataclass(frozen=True)
class ProfileVerdict:
    """The outcome of validating one OEM profile."""

    profileId: str
    accepted: bool
    rejections: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "profileId": self.profileId,
            "accepted": self.accepted,
            "rejections": list(self.rejections),
            "warnings": list(self.warnings),
            "checksPerformed": list(self.checked),
        }


def _walk(node: Any, path: str = "$") -> Iterable[tuple[str, str | None, Any]]:
    """Yield ``(path, key, value)`` for every node in a JSON document."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            child = f"{path}.{key}"
            yield child, str(key), value
            yield from _walk(value, child)
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            child = f"{path}[{index}]"
            yield child, None, value
            yield from _walk(value, child)


def scan_for_forbidden_content(document: Any) -> list[str]:
    """Deep-scan a document for execution channels, secrets, and protected settings.

    Used for both profiles and overlay payloads, because a privacy default that
    cannot be set in the profile could otherwise be smuggled in via an overlay.
    """
    problems: list[str] = []
    for path, key, value in _walk(document):
        if key is not None:
            normalised = key.replace("_", "").replace("-", "").casefold()
            if normalised in FORBIDDEN_KEYS:
                problems.append(f"forbidden key at {path}: {key!r} would create an execution or credential channel")
            if key in PROTECTED_SETTINGS:
                problems.append(f"protected setting at {path}: {key!r} is owned by Bunny OS and cannot be set by an OEM")
        if isinstance(value, str):
            if value in PROTECTED_SETTINGS:
                problems.append(f"protected setting referenced at {path}: {value!r} cannot be targeted by an OEM")
            for pattern in _SECRET_VALUE_PATTERNS:
                if pattern.search(value):
                    problems.append(f"embedded secret material at {path}: value matches {pattern.pattern!r}")
                    break
    return problems


def _validate_signature(profile: Mapping[str, Any], rejections: list[str]) -> None:
    signature = profile.get("signature")
    if not isinstance(signature, Mapping):
        rejections.append("unsigned profile: 'signature' is absent; unsigned OEM profiles are always rejected")
        return
    algorithm = signature.get("algorithm")
    if algorithm != "ed25519":
        rejections.append(f"unsupported signature algorithm {algorithm!r}; only ed25519 is accepted")
    key_id = signature.get("keyId")
    if not isinstance(key_id, str) or not _OEM_KEY_ID.match(key_id):
        rejections.append(f"signature keyId {key_id!r} is not in the reserved 'oem-' namespace")
    elif any(key_id[len("oem-"):].startswith(prefix) for prefix in _RELEASE_KEY_PREFIXES):
        rejections.append(
            f"signature keyId {key_id!r} impersonates a Bunny OS release, fleet, or sync key namespace; "
            "OEM keys must remain separated and must not be named to look like release keys"
        )
    value = signature.get("value")
    if not isinstance(value, str) or len(value) < 64:
        rejections.append("signature value is missing or too short to be an ed25519 signature")


def _validate_repositories(profile: Mapping[str, Any], rejections: list[str]) -> None:
    for index, package in enumerate(profile.get("packages") or []):
        if not isinstance(package, Mapping):
            rejections.append(f"packages[{index}] is not an object")
            continue
        repository = package.get("repository")
        if repository not in KNOWN_REPOSITORIES:
            rejections.append(
                f"packages[{index}] references unknown repository {repository!r}; "
                "a new repository requires explicit variant separation and a trust-root review"
            )
        if package.get("signatureRequired") is not True:
            rejections.append(f"packages[{index}] does not require signature verification")


def _validate_modules(profile: Mapping[str, Any], reviewed_modules: frozenset[str], rejections: list[str]) -> None:
    for index, driver in enumerate(profile.get("drivers") or []):
        if not isinstance(driver, Mapping):
            rejections.append(f"drivers[{index}] is not an object")
            continue
        kind = driver.get("kind")
        module = driver.get("module")
        if driver.get("signatureRequired") is not True:
            rejections.append(f"drivers[{index}] does not require signature verification")
        if kind == "reviewed-out-of-tree" and module not in reviewed_modules:
            rejections.append(
                f"drivers[{index}] module {module!r} is not a reviewed out-of-tree module; "
                "unsupported kernel modules are rejected"
            )
        if kind not in {"in-tree", "reviewed-out-of-tree"}:
            rejections.append(f"drivers[{index}] has unsupported kind {kind!r}")


def _validate_branding(
    profile: Mapping[str, Any],
    qualification: Mapping[str, Any] | None,
    rejections: list[str],
    warnings: list[str],
) -> None:
    branding = profile.get("branding")
    if not isinstance(branding, Mapping):
        rejections.append("branding block is absent")
        return
    claims_official = branding.get("claimsOfficialBunnyOsDevice")
    if claims_official is not True:
        return
    if profile.get("programmeLevel") != "official-bunny-os-device":
        rejections.append(
            "branding claims an official Bunny OS device but programmeLevel is "
            f"{profile.get('programmeLevel')!r}; only official-bunny-os-device may make that claim"
        )
    if qualification is None:
        rejections.append(
            "branding claims an official Bunny OS device but no hardware qualification report was supplied; "
            "hardware is never described as certified without repeatable evidence"
        )
        return
    if qualification.get("result") != "PASS":
        rejections.append(
            f"branding claims an official Bunny OS device but the qualification result is "
            f"{qualification.get('result')!r}"
        )
    if not qualification.get("signature"):
        rejections.append("qualification report supporting an official-device claim is unsigned")
    if qualification.get("recoveryValidated") is not True:
        rejections.append("qualification report does not record validated recovery; an OEM image cannot be approved without it")


def _validate_recovery(
    profile: Mapping[str, Any],
    recovery_profiles: Sequence[str] | None,
    rejections: list[str],
) -> None:
    recovery = profile.get("recoveryProfile")
    if not isinstance(recovery, str) or not recovery:
        rejections.append("recoveryProfile is absent; every OEM profile must provide bootable recovery")
        return
    if recovery_profiles is not None and recovery not in recovery_profiles:
        rejections.append(f"recoveryProfile {recovery!r} is not a known recovery profile")


def validate_profile(
    profile: Mapping[str, Any],
    *,
    reviewed_modules: Iterable[str] | None = None,
    recovery_profiles: Sequence[str] | None = None,
    qualification: Mapping[str, Any] | None = None,
    supported_architectures: Sequence[str] = ("x86_64", "aarch64"),
) -> ProfileVerdict:
    """Validate one OEM profile and return a structured verdict.

    ``qualification`` is the signed hardware-qualification report, required only
    when the profile claims to be an official Bunny OS device.
    """
    if not isinstance(profile, Mapping):
        raise TypeError("profile must be a mapping")

    modules = frozenset(reviewed_modules) if reviewed_modules is not None else REVIEWED_OUT_OF_TREE_MODULES
    rejections: list[str] = []
    warnings: list[str] = []
    checked = [
        "schema-version",
        "signature-namespace",
        "repository-allowlist",
        "kernel-module-review",
        "forbidden-content-scan",
        "branding-entitlement",
        "recovery-presence",
        "architecture-support",
    ]

    if profile.get("schemaVersion") != SCHEMA_VERSION:
        rejections.append(f"unsupported schemaVersion {profile.get('schemaVersion')!r}; expected {SCHEMA_VERSION}")

    profile_id = profile.get("profileId")
    if not isinstance(profile_id, str) or not profile_id:
        rejections.append("profileId is absent")
        profile_id = "unknown"

    level = profile.get("programmeLevel")
    if level is not None and level not in PROGRAMME_LEVELS:
        rejections.append(f"unknown programmeLevel {level!r}")

    responsibility = profile.get("updateResponsibility")
    if responsibility is not None and responsibility not in UPDATE_RESPONSIBILITIES:
        rejections.append(f"unknown updateResponsibility {responsibility!r}")
    if responsibility == "independent-oem-variant" and level == "official-bunny-os-device":
        rejections.append(
            "an independent OEM variant cannot also be an official Bunny OS device; "
            "an independent trust root requires explicit variant separation"
        )

    architectures = profile.get("supportedArchitectures")
    if not isinstance(architectures, list) or not architectures:
        rejections.append("supportedArchitectures is absent or empty")
    else:
        unknown = [value for value in architectures if value not in supported_architectures]
        if unknown:
            rejections.append(f"unsupported architectures requested: {', '.join(map(str, unknown))}")

    matches = profile.get("hardwareMatches")
    if not isinstance(matches, list) or not matches:
        rejections.append("hardwareMatches is absent or empty; a profile must state what hardware it applies to")

    _validate_signature(profile, rejections)
    _validate_repositories(profile, rejections)
    _validate_modules(profile, modules, rejections)
    _validate_branding(profile, qualification, rejections, warnings)
    _validate_recovery(profile, recovery_profiles, rejections)
    rejections.extend(scan_for_forbidden_content(profile))

    support = profile.get("supportMetadata")
    if isinstance(support, Mapping):
        if not support.get("securityContact"):
            rejections.append("supportMetadata.securityContact is absent; security disclosure obligations are mandatory")
        if not support.get("maintenanceUntil"):
            rejections.append("supportMetadata.maintenanceUntil is absent; a minimum maintenance commitment is mandatory")
        if not support.get("knownLimitations"):
            warnings.append("supportMetadata.knownLimitations is empty; known hardware limitations should be declared")
    else:
        rejections.append("supportMetadata is absent")

    return ProfileVerdict(
        profileId=profile_id,
        accepted=not rejections,
        rejections=tuple(rejections),
        warnings=tuple(warnings),
        checked=tuple(checked),
    )


def require_valid_profile(profile: Mapping[str, Any], **kwargs: Any) -> ProfileVerdict:
    """Validate a profile and raise ``ValueError`` when it is rejected."""
    verdict = validate_profile(profile, **kwargs)
    if not verdict.accepted:
        raise ValueError(
            f"OEM profile {verdict.profileId} rejected:\n" + "\n".join(f"  - {item}" for item in verdict.rejections)
        )
    return verdict
