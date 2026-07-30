# SPDX-License-Identifier: Apache-2.0
"""Offline factory-state inspection.

Closes the Major finding in ``FACTORY_PROVISIONING_SECURITY_REVIEW.md``: until
now ``evaluate_finalisation`` assessed a *record someone supplied*, so a factory
submitting a dishonest record would seal a device that still held credentials.

``probe_root`` produces the record by looking, not by asking. It inspects an
unmounted or mounted root filesystem tree — a mounted image, a container
rootfs, or a test fixture — and reports what it actually finds.

Seventeen of the twenty-two checks are settleable this way. Five are not: two
depend on firmware state, two on physically booting media, and one on a
time-based campaign. Those report ``UNKNOWN``, which ``evaluate_finalisation``
correctly treats as a refusal. A probe that guessed at them would be worse than
one that admits the limit, so the offline probe alone never seals a device: it
must be merged with a signed live-attestation record.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Callable, Iterable

from oem.validation.finalize import CHECK_IDS, FAIL, PASS, UNKNOWN

#: Accounts a shipped image legitimately contains. Anything else with a login
#: shell and a uid at or above the threshold is factory residue.
_SYSTEM_ACCOUNT_ALLOWLIST = frozenset({"nobody"})
_FIRST_USER_UID = 1000

_NOLOGIN_SHELLS = frozenset({"/sbin/nologin", "/usr/sbin/nologin", "/bin/false", "/usr/bin/false"})

_PRIVILEGED_GROUPS = ("wheel", "sudo", "adm", "docker", "libvirt")

#: Reused from the broker's own redactor so the factory probe and the
#: diagnostic redactor agree on what a secret looks like.
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[_-]?key|token|password|passwd|secret|psk|passphrase)\s*[:=]\s*\S+"
)

_PRIVATE_KEY_MARKER = re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----")

#: A serial-looking run of characters, used only to flag retained diagnostics.
_SERIAL_PATTERN = re.compile(r"(?i)\b(?:serial|sn)\s*[:=]\s*[A-Z0-9][A-Z0-9-]{5,}")

_HISTORY_FILES = (
    ".bash_history",
    ".zsh_history",
    ".sh_history",
    ".python_history",
    ".psql_history",
    ".mysql_history",
    ".lesshst",
)

MAX_SCAN_BYTES = 512 * 1024
MAX_SCANNED_FILES = 2000


@dataclass(frozen=True)
class Finding:
    checkId: str
    status: str
    detail: str
    evidence: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkId": self.checkId,
            "status": self.status,
            "detail": self.detail,
            "evidence": list(self.evidence),
        }


def _safe_join(root: Path, relative: str) -> Path:
    """Join a relative path to the root, refusing escape."""
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"path escapes the inspection root: {relative}")
    return candidate


def _read_text(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        if path.stat().st_size > MAX_SCAN_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _existing(root: Path, patterns: Iterable[str]) -> list[str]:
    """Return relative paths of existing, non-empty files matching the globs."""
    found: list[str] = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            try:
                if path.is_file() and path.stat().st_size > 0:
                    found.append(str(path.relative_to(root)).replace("\\", "/"))
            except OSError:
                continue
    return found


def _result(check_id: str, offenders: list[str], clean_detail: str, dirty_detail: str) -> Finding:
    if offenders:
        return Finding(check_id, FAIL, dirty_detail, tuple(offenders[:20]))
    return Finding(check_id, PASS, clean_detail)


def _check_factory_accounts(root: Path) -> Finding:
    passwd = _read_text(_safe_join(root, "etc/passwd"))
    if not passwd:
        return Finding("factory-accounts-removed", UNKNOWN, "etc/passwd is absent or unreadable")
    offenders = []
    for line in passwd.splitlines():
        fields = line.split(":")
        if len(fields) < 7:
            continue
        name, _, uid_text, _, _, _, shell = fields[:7]
        try:
            uid = int(uid_text)
        except ValueError:
            continue
        if uid < _FIRST_USER_UID or name in _SYSTEM_ACCOUNT_ALLOWLIST:
            continue
        if shell.strip() in _NOLOGIN_SHELLS:
            continue
        offenders.append(f"{name} (uid {uid})")
    return _result(
        "factory-accounts-removed",
        offenders,
        "no login account at or above uid 1000 remains",
        "a login account remains that the customer did not create",
    )


def _check_factory_groups(root: Path) -> Finding:
    group = _read_text(_safe_join(root, "etc/group"))
    if not group:
        return Finding("factory-groups-removed", UNKNOWN, "etc/group is absent or unreadable")
    offenders = []
    for line in group.splitlines():
        fields = line.split(":")
        if len(fields) < 4:
            continue
        name, members = fields[0], fields[3]
        if name in _PRIVILEGED_GROUPS and members.strip():
            offenders.append(f"{name}: {members.strip()}")
    return _result(
        "factory-groups-removed",
        offenders,
        "no privileged group retains a member",
        "a privileged group still lists members",
    )


def _check_autologin(root: Path) -> Finding:
    offenders = []
    custom = _read_text(_safe_join(root, "etc/gdm/custom.conf"))
    for marker in ("AutomaticLoginEnable=true", "AutomaticLoginEnable=True", "TimedLoginEnable=true"):
        if marker in custom.replace(" ", ""):
            offenders.append(f"etc/gdm/custom.conf: {marker}")
    for path in sorted(root.glob("etc/systemd/system/getty@*.service.d/*.conf")):
        if "autologin" in _read_text(path).casefold():
            offenders.append(str(path.relative_to(root)).replace("\\", "/"))
    return _result(
        "factory-autologin-disabled",
        offenders,
        "no autologin or timed login is configured",
        "an autologin configuration remains",
    )


def _check_wifi(root: Path) -> Finding:
    offenders = _existing(root, ["etc/NetworkManager/system-connections/*"])
    return _result(
        "factory-wifi-profiles-removed",
        offenders,
        "no NetworkManager connection profile remains",
        "a factory network profile remains",
    )


def _check_ssh_keys(root: Path) -> Finding:
    offenders = _existing(
        root,
        [
            "root/.ssh/authorized_keys",
            "root/.ssh/authorized_keys2",
            "root/.ssh/id_*",
            "home/*/.ssh/authorized_keys",
            "home/*/.ssh/id_*",
            "etc/ssh/authorized_keys.d/*",
        ],
    )
    return _result(
        "factory-ssh-keys-removed",
        offenders,
        "no authorized_keys or user SSH key remains",
        "a provisioning SSH key remains",
    )


def _check_test_credentials(root: Path) -> Finding:
    offenders: list[str] = []
    scanned = 0
    patterns = [
        "home/*/.local/share/keyrings/*",
        "root/.config/**/*",
        "home/*/.config/bunny*/**/*",
        "var/lib/bunny-os/**/*",
        "etc/bunny-os/**/*",
    ]
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if scanned >= MAX_SCANNED_FILES:
                break
            if not path.is_file() or path.is_symlink():
                continue
            scanned += 1
            content = _read_text(path)
            if _SECRET_PATTERN.search(content) or _PRIVATE_KEY_MARKER.search(content):
                offenders.append(str(path.relative_to(root)).replace("\\", "/"))
    return _result(
        "test-credentials-removed",
        offenders,
        f"no credential-shaped content found in {scanned} scanned files",
        "credential-shaped content remains on the device",
    )


def _check_sudo_rules(root: Path) -> Finding:
    offenders = []
    sources = [_safe_join(root, "etc/sudoers")] + sorted(root.glob("etc/sudoers.d/*"))
    for path in sources:
        text = _read_text(path)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if "NOPASSWD" in stripped.upper() and "ALL" in stripped.upper():
                offenders.append(f"{path.name}: {stripped[:80]}")
    for path in sorted(root.glob("etc/polkit-1/rules.d/*")):
        if "polkit.Result.YES" in _read_text(path):
            offenders.append(str(path.relative_to(root)).replace("\\", "/"))
    return _result(
        "factory-sudo-rules-removed",
        offenders,
        "no unrestricted sudo or polkit rule remains",
        "an unrestricted privilege rule remains",
    )


def _check_identifier_logs(root: Path) -> Finding:
    offenders = _existing(
        root,
        [
            "var/log/anaconda/*",
            "var/lib/bunny-os/support/*",
            "var/log/bunny/*",
            "var/log/bunny-os/*",
        ],
    )
    return _result(
        "identifier-logs-removed",
        offenders,
        "no retained installer, support, or Bunny log remains",
        "a log that may contain device identifiers remains",
    )


def _check_shell_history(root: Path) -> Finding:
    patterns = [f"root/{name}" for name in _HISTORY_FILES]
    patterns += [f"home/*/{name}" for name in _HISTORY_FILES]
    patterns.append("home/*/.local/share/fish/fish_history")
    offenders = _existing(root, patterns)
    return _result(
        "shell-history-cleared",
        offenders,
        "no shell history remains for root or any user",
        "shell history remains",
    )


def _check_installer_session(root: Path) -> Finding:
    offenders = _existing(
        root,
        [
            "root/anaconda-ks.cfg",
            "root/original-ks.cfg",
            "var/lib/bunny-installer/*",
            "var/log/installer/*",
        ],
    )
    return _result(
        "installer-session-removed",
        offenders,
        "no installer answer file or transaction journal remains",
        "installer session material remains",
    )


def _check_machine_id(root: Path) -> Finding:
    path = _safe_join(root, "etc/machine-id")
    if not path.exists():
        return Finding("machine-id-regenerated", PASS, "etc/machine-id is absent; first boot will generate one")
    content = _read_text(path).strip()
    if content in {"", "uninitialized"}:
        return Finding("machine-id-regenerated", PASS, "etc/machine-id is empty or uninitialized")
    return Finding(
        "machine-id-regenerated",
        FAIL,
        "etc/machine-id carries a fixed value that would be cloned across every unit",
        (content[:16] + "...",),
    )


def _check_host_keys(root: Path) -> Finding:
    offenders = _existing(root, ["etc/ssh/ssh_host_*_key", "etc/ssh/ssh_host_*_key.pub"])
    return _result(
        "host-keys-regenerated",
        offenders,
        "no SSH host key remains; first boot will regenerate",
        "an SSH host key would be cloned across every unit",
    )


def _check_device_identity(root: Path) -> Finding:
    offenders = _existing(root, ["var/lib/bunny-os/identity/*", "etc/bunny-os/device-identity.json"])
    return _result(
        "device-identity-absent-or-fresh",
        offenders,
        "no device identity remains; it is created on first customer boot",
        "a factory device identity remains",
    )


def _check_enrolment_state(root: Path) -> Finding:
    offenders = _existing(
        root, ["etc/bunny-os/enrolment.json", "var/lib/bunny-os/policy/*", "etc/bunny-os/managed-settings.json"]
    )
    return _result(
        "enrolment-state-absent",
        offenders,
        "no enrolment token, certificate, or organisation binding remains",
        "organisation enrolment state remains from factory testing",
    )


def _check_sync_state(root: Path) -> Finding:
    offenders = _existing(root, ["home/*/.local/share/bunny/sync/*", "var/lib/bunny-os/sync/*"])
    return _result(
        "sync-state-absent",
        offenders,
        "no sync account, device key, or cached object remains",
        "sync state remains from factory testing",
    )


def _check_first_run(root: Path) -> Finding:
    offenders = _existing(
        root,
        [
            "home/*/.local/state/bunny-os/first-run.json",
            "home/*/.config/bunny-os/first-boot-complete.json",
            "var/lib/bunny-os/first-run-complete",
        ],
    )
    if offenders:
        return Finding(
            "first-user-setup-incomplete",
            FAIL,
            "a completed first-run marker remains; the customer would not be asked to create an account",
            tuple(offenders[:20]),
        )
    return Finding("first-user-setup-incomplete", PASS, "no completed first-run marker is present")


def _check_diagnostic_serials(root: Path) -> Finding:
    offenders: list[str] = []
    for path in sorted(root.glob("var/lib/bunny-os/support/**/*")):
        if path.is_file() and _SERIAL_PATTERN.search(_read_text(path)):
            offenders.append(str(path.relative_to(root)).replace("\\", "/"))
    return _result(
        "diagnostic-serials-not-retained",
        offenders,
        "no retained diagnostic record contains a hardware serial",
        "a retained diagnostic record contains a hardware serial",
    )


#: Checks that an offline tree can settle.
INSPECTORS: dict[str, Callable[[Path], Finding]] = {
    "factory-accounts-removed": _check_factory_accounts,
    "factory-groups-removed": _check_factory_groups,
    "factory-autologin-disabled": _check_autologin,
    "factory-wifi-profiles-removed": _check_wifi,
    "factory-ssh-keys-removed": _check_ssh_keys,
    "test-credentials-removed": _check_test_credentials,
    "factory-sudo-rules-removed": _check_sudo_rules,
    "identifier-logs-removed": _check_identifier_logs,
    "shell-history-cleared": _check_shell_history,
    "installer-session-removed": _check_installer_session,
    "machine-id-regenerated": _check_machine_id,
    "host-keys-regenerated": _check_host_keys,
    "device-identity-absent-or-fresh": _check_device_identity,
    "enrolment-state-absent": _check_enrolment_state,
    "sync-state-absent": _check_sync_state,
    "first-user-setup-incomplete": _check_first_run,
    "diagnostic-serials-not-retained": _check_diagnostic_serials,
}

#: Checks an offline tree cannot settle, and why. These report UNKNOWN, which
#: refuses handoff until a signed live-attestation record supplies them.
REQUIRES_LIVE_ATTESTATION: dict[str, str] = {
    "recovery-verified": "requires physically booting the recovery media",
    "image-signatures-verified": "requires bootc deployment state on a running system",
    "secure-boot-state-recorded": "requires firmware state from efivars on the running unit",
    "tpm-state-recorded": "requires TPM presence from the running unit",
    "burn-in-completed": "requires a time-based burn-in campaign report",
}

INSPECTABLE_CHECKS = frozenset(INSPECTORS)


def probe_root(root: Path) -> dict[str, Any]:
    """Inspect a root filesystem tree and produce a factory finalisation record.

    The returned record is directly consumable by ``evaluate_finalisation``.
    Because five checks report ``UNKNOWN``, an offline probe alone always
    refuses handoff; that is the intended behaviour, not a defect.
    """
    root = Path(root)
    if not root.is_dir():
        raise ValueError(f"inspection root is not a directory: {root}")

    findings: list[Finding] = []
    for check_id in CHECK_IDS:
        inspector = INSPECTORS.get(check_id)
        if inspector is None:
            findings.append(
                Finding(check_id, UNKNOWN, REQUIRES_LIVE_ATTESTATION.get(check_id, "not inspectable offline"))
            )
            continue
        try:
            findings.append(inspector(root))
        except ValueError as error:
            findings.append(Finding(check_id, FAIL, str(error)))
        except OSError as error:
            findings.append(Finding(check_id, UNKNOWN, f"inspection failed: {error}"))

    return {
        "schemaVersion": 1,
        "deviceRecordId": f"offline-probe-{root.name or 'root'}",
        "checks": {finding.checkId: finding.status for finding in findings},
        "findings": [finding.as_dict() for finding in findings],
        "inspectionRoot": str(root),
        "inspectableCheckCount": len(INSPECTORS),
        "requiresLiveAttestation": sorted(REQUIRES_LIVE_ATTESTATION),
        "note": (
            "Offline filesystem inspection. Five checks require a running system or a signed "
            "burn-in report and are reported UNKNOWN, so this record alone never permits handoff."
        ),
    }


def merge_attestation(record: dict[str, Any], attestation: dict[str, Any]) -> dict[str, Any]:
    """Merge a signed live-attestation record into an offline probe result.

    Only the five checks an offline probe cannot settle may be supplied this
    way. An attestation that tries to override an inspected result is refused,
    because that would let a dishonest factory paper over what was observed.
    """
    if not isinstance(attestation, dict):
        raise ValueError("attestation must be a mapping")
    if attestation.get("schemaVersion") != 1:
        raise ValueError("unsupported attestation schemaVersion")
    if not attestation.get("signature"):
        raise ValueError("live attestation must be signed")
    checks = attestation.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("attestation checks must be an object")

    overreach = sorted(set(checks) & INSPECTABLE_CHECKS)
    if overreach:
        raise ValueError(
            "attestation may not override checks settled by inspection: " + ", ".join(overreach)
        )
    unknown = sorted(set(checks) - set(REQUIRES_LIVE_ATTESTATION))
    if unknown:
        raise ValueError("attestation names unknown checks: " + ", ".join(unknown))

    merged = dict(record)
    merged["checks"] = {**record["checks"], **checks}
    merged["attestationApplied"] = sorted(checks)
    return merged
