"""Storage inventory models and strict lsblk parsing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import re
from typing import Any, Mapping


DISK_TYPES = frozenset({"disk", "mpath", "raid", "md", "loop"})
DEVICE_PATH = re.compile(r"^/dev/[A-Za-z0-9._/+:-]+$")


def _redact_serial(serial: object) -> str | None:
    if not isinstance(serial, str) or not serial.strip():
        return None
    return "sha256:" + hashlib.sha256(serial.strip().encode("utf-8")).hexdigest()[:12]


def _disk_id(path: str, model: str | None, size: int) -> str:
    stable = f"{path}\0{model or ''}\0{size}".encode("utf-8")
    return "disk-" + hashlib.sha256(stable).hexdigest()[:16]


@dataclass(frozen=True)
class ExistingOS:
    family: str
    name: str
    encrypted: bool = False


@dataclass(frozen=True)
class PartitionInfo:
    id: str
    devicePath: str
    sizeBytes: int
    filesystem: str | None = None
    label: str | None = None
    uuidRedacted: str | None = None
    partType: str | None = None
    partLabel: str | None = None
    mountPoints: tuple[str, ...] = ()
    readOnly: bool = False
    encrypted: bool = False
    installationMedia: bool = False
    freeSpace: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["mountPoints"] = list(self.mountPoints)
        return value


@dataclass(frozen=True)
class DiskInfo:
    id: str
    devicePath: str
    sizeBytes: int
    logicalSectorSize: int
    physicalSectorSize: int
    removable: bool
    readOnly: bool
    model: str | None = None
    serialRedacted: str | None = None
    rotational: bool | None = None
    transport: str | None = None
    partitions: tuple[PartitionInfo, ...] = field(default_factory=tuple)
    existingOperatingSystems: tuple[ExistingOS, ...] = field(default_factory=tuple)
    installationMedia: bool = False
    storageStack: str = "plain"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["partitions"] = [item.to_dict() for item in self.partitions]
        value["existingOperatingSystems"] = [asdict(item) for item in self.existingOperatingSystems]
        return value


def _integer(node: Mapping[str, Any], key: str, *, default: int = 0) -> int:
    value = node.get(key, default)
    if isinstance(value, bool):
        return int(value)
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid numeric lsblk field {key}") from error
    if result < 0:
        raise ValueError(f"negative lsblk field {key}")
    return result


def _mounts(node: Mapping[str, Any]) -> tuple[str, ...]:
    raw = node.get("mountpoints")
    if raw is None:
        one = node.get("mountpoint")
        raw = [one] if one else []
    if not isinstance(raw, list):
        raise ValueError("mountpoints must be a list")
    return tuple(str(item) for item in raw if isinstance(item, str) and item.startswith("/"))


def _os_from_partition(node: Mapping[str, Any]) -> tuple[ExistingOS, ...]:
    fs = str(node.get("fstype") or "").lower()
    label = str(node.get("label") or node.get("partlabel") or "")
    candidates: list[ExistingOS] = []
    if fs == "ntfs":
        candidates.append(ExistingOS("windows", label or "Windows-compatible NTFS", "bitlocker" in label.lower()))
    elif fs in {"ext2", "ext3", "ext4", "btrfs", "xfs"}:
        candidates.append(ExistingOS("linux", label or "Linux installation", False))
    elif fs in {"bitlocker", "bitlocker2"}:
        candidates.append(ExistingOS("windows", label or "BitLocker volume", True))
    return tuple(candidates)


def parse_lsblk(payload: Mapping[str, Any], *, installation_source: str | None = None) -> list[DiskInfo]:
    devices = payload.get("blockdevices")
    if not isinstance(devices, list):
        raise ValueError("lsblk payload requires blockdevices")
    disks: list[DiskInfo] = []
    for node in devices:
        if not isinstance(node, Mapping) or node.get("type") not in DISK_TYPES:
            continue
        path = str(node.get("path") or "")
        if not DEVICE_PATH.fullmatch(path):
            raise ValueError("unsafe or missing disk path")
        size = _integer(node, "size")
        model = str(node["model"]).strip() if node.get("model") else None
        partitions: list[PartitionInfo] = []
        existing: list[ExistingOS] = []
        for child in node.get("children") or []:
            if not isinstance(child, Mapping):
                raise ValueError("invalid lsblk child")
            child_path = str(child.get("path") or "")
            if not DEVICE_PATH.fullmatch(child_path) or (not child_path.startswith(path) and not child_path.startswith("/dev/mapper/")):
                raise ValueError("partition path is not associated with target disk")
            child_mounts = _mounts(child)
            is_media = bool(installation_source and (child_path == installation_source or installation_source in child_mounts))
            fs = str(child.get("fstype")) if child.get("fstype") else None
            identifier = "part-" + hashlib.sha256(child_path.encode("utf-8")).hexdigest()[:16]
            uuid = str(child.get("uuid") or "")
            partition = PartitionInfo(
                id=identifier,
                devicePath=child_path,
                sizeBytes=_integer(child, "size"),
                filesystem=fs,
                label=str(child.get("label")) if child.get("label") else None,
                uuidRedacted=_redact_serial(uuid),
                partType=str(child.get("parttype")) if child.get("parttype") else None,
                partLabel=str(child.get("partlabel")) if child.get("partlabel") else None,
                mountPoints=child_mounts,
                readOnly=bool(_integer(child, "ro")),
                encrypted=(fs or "").lower() in {"crypto_luks", "bitlocker"},
                installationMedia=is_media,
            )
            partitions.append(partition)
            existing.extend(_os_from_partition(child))
        is_media_disk = any(item.installationMedia for item in partitions) or path == installation_source
        kind = str(node.get("type"))
        stack = "raid" if kind in {"raid", "md", "mpath"} else "plain"
        disks.append(
            DiskInfo(
                id=_disk_id(path, model, size),
                devicePath=path,
                model=model,
                serialRedacted=_redact_serial(node.get("serial")),
                sizeBytes=size,
                logicalSectorSize=_integer(node, "log-sec", default=512),
                physicalSectorSize=_integer(node, "phy-sec", default=512),
                removable=bool(_integer(node, "rm")),
                rotational=bool(_integer(node, "rota")) if node.get("rota") is not None else None,
                transport=str(node.get("tran")) if node.get("tran") else None,
                readOnly=bool(_integer(node, "ro")),
                partitions=tuple(partitions),
                existingOperatingSystems=tuple(existing),
                installationMedia=is_media_disk,
                storageStack=stack,
            )
        )
    return disks
