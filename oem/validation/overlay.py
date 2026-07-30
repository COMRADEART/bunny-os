# SPDX-License-Identifier: Apache-2.0
"""OEM overlay validation.

An overlay is the only way an OEM adds files to an image. Because a privacy or
security default that the profile schema forbids could otherwise be smuggled in
as a dconf key, a systemd drop-in, or a shell profile fragment, overlays are
constrained twice: by destination path, and by content.

Path rules mirror the existing repository idiom in ``build/scripts`` and
``installer/validation/media.py``: reject absolute paths, reject ``..``, reject
symlinks, and require containment under the declared root.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from typing import Any, Iterable, Mapping, Sequence

from oem.validation.profile import PROTECTED_SETTINGS, scan_for_forbidden_content

#: Destination roots an OEM overlay may write to. Everything else is refused.
OVERLAY_ALLOWED_ROOTS = (
    "usr/share/bunny-oem/branding/",
    "usr/share/bunny-oem/documentation/",
    "usr/share/bunny-oem/first-run/",
    "usr/share/bunny-oem/support/",
    "usr/share/backgrounds/bunny-oem/",
    "usr/share/icons/bunny-oem/",
    "usr/lib/firmware/bunny-oem/",
    "usr/lib/bunny-oem/recovery-assets/",
)

#: Destination prefixes that are never writable by an OEM overlay, listed
#: explicitly so a reviewer can see the boundary rather than infer it.
OVERLAY_FORBIDDEN_ROOTS = (
    "etc/bunny/privacy",
    "etc/bunny/diagnostics",
    "etc/bunny/permissions",
    "etc/bunny/broker",
    "etc/bunny/update",
    "etc/containers/policy.json",
    "etc/pki/",
    "etc/polkit-1/",
    "etc/selinux/",
    "etc/sudoers",
    "etc/sudoers.d/",
    "etc/ssh/",
    "etc/systemd/system/",
    "usr/lib/systemd/system/",
    "usr/lib/bunny-os/",
    "usr/lib/bunny-system-broker/",
    "usr/lib/bunny-update-agent/",
    "usr/libexec/bunny-os/",
    "boot/",
    "efi/",
)

#: Content types an overlay may carry. Executable and archive payloads are
#: excluded so an overlay cannot become a code-delivery channel; code must ship
#: as a signed package from a reviewed repository.
OVERLAY_ALLOWED_SUFFIXES = frozenset({
    ".svg", ".png", ".jpg", ".jpeg", ".webp",
    ".md", ".txt", ".json", ".yaml", ".yml",
    ".desktop", ".ini", ".conf",
    ".bin", ".fw", ".ucode",
})

OVERLAY_FORBIDDEN_SUFFIXES = frozenset({
    ".sh", ".bash", ".zsh", ".py", ".pl", ".rb", ".php",
    ".so", ".ko", ".elf", ".exe", ".dll",
    ".service", ".socket", ".timer", ".mount", ".path",
    ".rules", ".pkla", ".policy", ".te", ".pp",
    ".tar", ".gz", ".xz", ".zst", ".zip", ".rpm", ".deb",
})

MAX_OVERLAY_FILE_BYTES = 32 * 1024 * 1024
MAX_OVERLAY_TOTAL_BYTES = 256 * 1024 * 1024
MAX_OVERLAY_FILES = 512

_DCONF_KEY = re.compile(r"^\s*([A-Za-z0-9./_-]+)\s*=", re.MULTILINE)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class OverlayVerdict:
    overlayId: str
    accepted: bool
    rejections: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    fileCount: int = 0
    totalBytes: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "overlayId": self.overlayId,
            "accepted": self.accepted,
            "rejections": list(self.rejections),
            "warnings": list(self.warnings),
            "fileCount": self.fileCount,
            "totalBytes": self.totalBytes,
        }


def _validate_destination(destination: Any, index: int, rejections: list[str]) -> None:
    if not isinstance(destination, str) or not destination:
        rejections.append(f"files[{index}] destination is absent")
        return
    if destination.startswith("/"):
        rejections.append(f"files[{index}] destination {destination!r} must be relative to the image root")
        return
    parsed = PurePosixPath(destination)
    if any(part in {"", ".", ".."} for part in parsed.parts):
        rejections.append(f"files[{index}] destination {destination!r} contains an unsafe path component")
        return
    lowered = destination.casefold()
    for forbidden in OVERLAY_FORBIDDEN_ROOTS:
        if lowered.startswith(forbidden):
            rejections.append(
                f"files[{index}] destination {destination!r} targets protected path {forbidden!r}; "
                "OEM overlays cannot modify security, update, broker, boot, or policy state"
            )
            return
    if not any(lowered.startswith(root) for root in OVERLAY_ALLOWED_ROOTS):
        rejections.append(
            f"files[{index}] destination {destination!r} is outside the OEM overlay allowlist; "
            f"permitted roots are {', '.join(OVERLAY_ALLOWED_ROOTS)}"
        )
        return
    suffix = parsed.suffix.casefold()
    if suffix in OVERLAY_FORBIDDEN_SUFFIXES:
        rejections.append(
            f"files[{index}] destination {destination!r} has forbidden type {suffix!r}; "
            "executable, unit, policy, and archive payloads must ship as signed packages"
        )
    elif suffix not in OVERLAY_ALLOWED_SUFFIXES:
        rejections.append(f"files[{index}] destination {destination!r} has unsupported type {suffix!r}")


def _scan_settings_payload(entry: Mapping[str, Any], index: int, rejections: list[str]) -> None:
    """Refuse a settings-shaped payload that targets a Bunny OS-owned key."""
    text = entry.get("inlineText")
    if not isinstance(text, str):
        return
    for match in _DCONF_KEY.finditer(text):
        key = match.group(1)
        if key in PROTECTED_SETTINGS:
            rejections.append(
                f"files[{index}] inline payload sets protected key {key!r}; "
                "privacy, telemetry, security, encryption, recovery, and permission defaults are not OEM-configurable"
            )
        if key.startswith(("bunny.privacy.", "bunny.diagnostics.", "bunny.telemetry.", "bunny.permissions.", "os.update.", "os.encryption.", "os.secureboot.")):
            rejections.append(
                f"files[{index}] inline payload sets reserved namespace key {key!r}"
            )


def validate_overlay(
    overlay: Mapping[str, Any],
    *,
    allowed_roots: Sequence[str] | None = None,
) -> OverlayVerdict:
    """Validate one OEM overlay manifest.

    The manifest describes destinations, hashes, and optional inline text. This
    function never reads the referenced payloads from disk; hash verification
    against real bytes happens in the image build, which is a separate,
    host-dependent step.
    """
    if not isinstance(overlay, Mapping):
        raise TypeError("overlay must be a mapping")

    roots = tuple(allowed_roots) if allowed_roots is not None else OVERLAY_ALLOWED_ROOTS
    rejections: list[str] = []
    warnings: list[str] = []

    overlay_id = overlay.get("overlayId")
    if not isinstance(overlay_id, str) or not overlay_id:
        rejections.append("overlayId is absent")
        overlay_id = "unknown"

    if overlay.get("schemaVersion") != 1:
        rejections.append(f"unsupported schemaVersion {overlay.get('schemaVersion')!r}")

    files = overlay.get("files")
    if not isinstance(files, list):
        rejections.append("files is absent or not a list")
        files = []
    if len(files) > MAX_OVERLAY_FILES:
        rejections.append(f"overlay declares {len(files)} files; the limit is {MAX_OVERLAY_FILES}")

    total_bytes = 0
    seen: set[str] = set()
    for index, entry in enumerate(files):
        if not isinstance(entry, Mapping):
            rejections.append(f"files[{index}] is not an object")
            continue
        destination = entry.get("destination")
        _validate_destination(destination, index, rejections)
        if isinstance(destination, str):
            if destination in seen:
                rejections.append(f"files[{index}] destination {destination!r} is declared more than once")
            seen.add(destination)

        digest = entry.get("sha256")
        if not isinstance(digest, str) or not _SHA256.match(digest):
            rejections.append(f"files[{index}] sha256 is absent or malformed")

        size = entry.get("sizeBytes")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            rejections.append(f"files[{index}] sizeBytes is absent or invalid")
        else:
            if size > MAX_OVERLAY_FILE_BYTES:
                rejections.append(f"files[{index}] is {size} bytes; the per-file limit is {MAX_OVERLAY_FILE_BYTES}")
            total_bytes += size

        mode = entry.get("mode")
        if mode is not None:
            if not isinstance(mode, str) or not re.fullmatch(r"0[0-7]{3}", mode):
                rejections.append(f"files[{index}] mode {mode!r} must be a four-digit octal string")
            elif int(mode, 8) & 0o7111:
                rejections.append(
                    f"files[{index}] mode {mode!r} sets an execute or setuid bit; overlay payloads are never executable"
                )

        if entry.get("symlinkTarget") is not None:
            rejections.append(f"files[{index}] declares a symlink; overlay symlinks are rejected")

        _scan_settings_payload(entry, index, rejections)

    if total_bytes > MAX_OVERLAY_TOTAL_BYTES:
        rejections.append(f"overlay totals {total_bytes} bytes; the limit is {MAX_OVERLAY_TOTAL_BYTES}")

    rejections.extend(scan_for_forbidden_content(overlay))

    if not files:
        warnings.append("overlay declares no files")

    return OverlayVerdict(
        overlayId=overlay_id,
        accepted=not rejections,
        rejections=tuple(rejections),
        warnings=tuple(warnings),
        fileCount=len(files),
        totalBytes=total_bytes,
    )


def require_valid_overlay(overlay: Mapping[str, Any], **kwargs: Any) -> OverlayVerdict:
    verdict = validate_overlay(overlay, **kwargs)
    if not verdict.accepted:
        raise ValueError(
            f"OEM overlay {verdict.overlayId} rejected:\n" + "\n".join(f"  - {item}" for item in verdict.rejections)
        )
    return verdict
