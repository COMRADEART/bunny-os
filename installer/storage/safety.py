"""Wrong-disk and destructive-operation protections."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib

from .models import DiskInfo


@dataclass(frozen=True)
class SafetyFinding:
    code: str
    severity: str
    message: str
    blocks: bool


def disk_identity(disk: DiskInfo) -> str:
    label = (disk.model or "Unknown model").strip()
    gib = disk.sizeBytes / (1024**3)
    return f"{label} — {gib:.1f} GiB — {disk.devicePath}"


def confirmation_phrase(disk: DiskInfo) -> str:
    digest = hashlib.sha256(f"{disk.id}:{disk.sizeBytes}".encode("utf-8")).hexdigest()[:6].upper()
    return f"ERASE {disk.devicePath} {digest}"


def assess_target(disk: DiskInfo, *, mode: str, on_ac_power: bool | None = None) -> tuple[SafetyFinding, ...]:
    findings: list[SafetyFinding] = []
    if disk.installationMedia:
        findings.append(SafetyFinding("installation-media", "blocker", "The selected disk contains the running installation media.", True))
    if disk.readOnly:
        findings.append(SafetyFinding("read-only", "blocker", "The selected disk is read-only.", True))
    if disk.sizeBytes < 40 * 1024**3:
        findings.append(SafetyFinding("small-disk", "blocker", "At least 40 GiB is required for this beta profile.", True))
    if disk.logicalSectorSize not in {512, 4096}:
        findings.append(SafetyFinding("sector-size", "blocker", "The logical sector size is not qualified.", True))
    if disk.storageStack != "plain":
        findings.append(SafetyFinding("complex-storage", "blocker", "RAID and multipath targets are detected but not supported by the beta installer.", True))
    if disk.removable:
        findings.append(SafetyFinding("removable", "warning", "The selected target is removable media.", False))
    if any(part.mountPoints for part in disk.partitions):
        findings.append(SafetyFinding("mounted", "blocker", "The target contains mounted partitions.", True))
    if any(part.encrypted for part in disk.partitions):
        findings.append(SafetyFinding("encrypted-existing", "warning", "The disk contains encrypted data that the installer cannot inspect.", mode != "erase_disk"))
    if disk.existingOperatingSystems:
        names = ", ".join(sorted({item.name for item in disk.existingOperatingSystems}))
        findings.append(SafetyFinding("existing-os", "warning", f"Existing operating system detected: {names}.", False))
    if on_ac_power is False:
        findings.append(SafetyFinding("battery", "warning", "Connect external power before storage changes.", False))
    if mode == "erase_disk":
        findings.append(SafetyFinding("destructive", "danger", f"All data on {disk_identity(disk)} will be erased.", False))
    return tuple(findings)


def assert_confirmed(disk: DiskInfo, *, acknowledgement: str, second_confirmation: bool) -> None:
    if acknowledgement != confirmation_phrase(disk) or not second_confirmation:
        raise ValueError("destructive confirmation does not match the selected disk")

