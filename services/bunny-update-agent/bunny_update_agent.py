#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed-manifest front end for transactional bootc deployments."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen


STATE_DIR = Path("/var/lib/bunny-os/update")
STATUS_PATH = STATE_DIR / "status.json"
SEQUENCE_PATH = STATE_DIR / "highest-sequence"
CONFIG_PATH = Path("/etc/bunny-os/update.json")
KEY_DIR = Path("/usr/share/bunny-os/update-keys")
REVOCATIONS_PATH = KEY_DIR / "revoked-keys.json"
CONTRACT_VERSION = "1.0.0"
BUNNY_ARTIFACT_PATH = Path("/usr/share/bunny-os/bunny-artifact.json")
MAX_MANIFEST_BYTES = 256 * 1024
RESERVED_BYTES = 2 * 1024 * 1024 * 1024
ALLOWED_ACTIONS = {"status", "check", "stage", "install"}
SAFE_KEY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
SAFE_DIGEST = re.compile(r"sha256:[a-f0-9]{64}\Z")
SAFE_REFERENCE = re.compile(r"[a-z0-9.-]+(?::[0-9]+)?/[a-z0-9._/-]{1,220}\Z")
SAFE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
SAFE_IMAGE_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]{0,127}\Z")


class UpdateError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _status(state: str, **details: Any) -> dict[str, Any]:
    value = {
        "schemaVersion": 1,
        "state": state,
        "updatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        **details,
    }
    _atomic_json(STATUS_PATH, value)
    return value


def _load_json(path: Path, maximum: int = MAX_MANIFEST_BYTES) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise UpdateError("not_configured", f"cannot read {path}") from exc
    if len(raw) > maximum:
        raise UpdateError("invalid_document", f"{path.name} is too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError("invalid_document", f"{path.name} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise UpdateError("invalid_document", f"{path.name} must contain an object")
    return value


def _configuration() -> dict[str, Any]:
    config = _load_json(CONFIG_PATH, 32 * 1024)
    allowed = {"enabled", "channel", "manifestUrl", "imageRepositories"}
    if set(config) != allowed:
        raise UpdateError("invalid_configuration", "update configuration has unexpected fields")
    if config["enabled"] is not True:
        raise UpdateError("not_configured", "OS update checks are disabled")
    if config["channel"] not in {"developer", "beta", "stable"}:
        raise UpdateError("invalid_configuration", "invalid update channel")
    parsed = urlparse(config["manifestUrl"])
    if parsed.scheme != "https" or parsed.username or parsed.password or not parsed.hostname:
        raise UpdateError("invalid_configuration", "manifestUrl must be an HTTPS URL without credentials")
    repositories = config["imageRepositories"]
    if not isinstance(repositories, list) or not repositories or not all(isinstance(item, str) and item for item in repositories):
        raise UpdateError("invalid_configuration", "imageRepositories must be a non-empty string array")
    return config


def _fetch(url: str) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "BunnyOS-Updater/0.1"})
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                raise UpdateError("download_failed", f"manifest server returned HTTP {response.status}")
            raw = response.read(MAX_MANIFEST_BYTES + 1)
    except UpdateError:
        raise
    except OSError as exc:
        raise UpdateError("download_failed", "could not download update manifest") from exc
    if len(raw) > MAX_MANIFEST_BYTES:
        raise UpdateError("invalid_manifest", "update manifest is too large")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UpdateError("invalid_manifest", "update manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise UpdateError("invalid_manifest", "update manifest must be an object")
    return value


def _canonical_payload(manifest: dict[str, Any]) -> bytes:
    unsigned = dict(manifest)
    unsigned.pop("signature", None)
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _verify_signature(manifest: dict[str, Any]) -> None:
    key_id = manifest.get("keyId")
    signature = manifest.get("signature")
    if not isinstance(key_id, str) or not SAFE_KEY_ID.fullmatch(key_id) or not isinstance(signature, str):
        raise UpdateError("bad_signature", "manifest signature metadata is invalid")
    revoked = set()
    if REVOCATIONS_PATH.exists():
        value = _load_json(REVOCATIONS_PATH, 64 * 1024)
        if value.get("schemaVersion") != 1 or not isinstance(value.get("revokedKeyIds"), list):
            raise UpdateError("invalid_trust_store", "key revocation document is invalid")
        revoked = {item for item in value["revokedKeyIds"] if isinstance(item, str)}
    if key_id in revoked:
        raise UpdateError("revoked_key", "manifest is signed by a revoked key")
    key_path = KEY_DIR / f"{key_id}.pem"
    if not key_path.is_file():
        raise UpdateError("unknown_key", "manifest signing key is not trusted")
    try:
        decoded = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError) as exc:
        raise UpdateError("bad_signature", "manifest signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="bunny-update-verify-") as temporary:
        payload_path = Path(temporary) / "manifest.json"
        signature_path = Path(temporary) / "manifest.sig"
        payload_path.write_bytes(_canonical_payload(manifest))
        signature_path.write_bytes(decoded)
        result = subprocess.run(
            ["/usr/bin/openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(key_path), "-rawin", "-in", str(payload_path), "-sigfile", str(signature_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
            timeout=15,
            check=False,
        )
    if result.returncode != 0:
        raise UpdateError("bad_signature", "manifest signature verification failed")


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise UpdateError("invalid_manifest", f"{field} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UpdateError("invalid_manifest", f"{field} is invalid") from exc
    if parsed.tzinfo is None:
        raise UpdateError("invalid_manifest", f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _architecture() -> str:
    value = platform.machine().lower()
    return {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(value, value)


def _validate_manifest(manifest: dict[str, Any], config: dict[str, Any], enforce_new_sequence: bool) -> None:
    required = {
        "schemaVersion", "sequence", "channel", "osVersion", "imageVersion", "imageReference", "imageDigest",
        "architecture", "publishedAt", "expiresAt", "contractVersion", "downloadSize", "installedSize", "keyId", "signature",
    }
    optional = {"minimumFirmware", "minimumBunnyVersion", "maximumBunnyVersion", "releaseNotesReference"}
    if not required.issubset(manifest) or set(manifest) - required - optional:
        raise UpdateError("invalid_manifest", "manifest fields do not match schema version 1")
    if manifest["schemaVersion"] != 1:
        raise UpdateError("invalid_manifest", "unsupported manifest schema")
    if not isinstance(manifest["sequence"], int) or isinstance(manifest["sequence"], bool) or manifest["sequence"] < 1:
        raise UpdateError("invalid_manifest", "sequence must be a positive integer")
    if manifest["channel"] != config["channel"]:
        raise UpdateError("wrong_channel", "manifest channel does not match configured channel")
    if manifest["architecture"] != _architecture():
        raise UpdateError("wrong_architecture", "manifest architecture does not match this machine")
    if manifest["contractVersion"] != CONTRACT_VERSION:
        raise UpdateError("incompatible_contract", "manifest requires an incompatible OS contract")
    if not isinstance(manifest["osVersion"], str) or not SAFE_VERSION.fullmatch(manifest["osVersion"]):
        raise UpdateError("invalid_manifest", "osVersion is invalid")
    if not isinstance(manifest["imageVersion"], str) or not SAFE_IMAGE_VERSION.fullmatch(manifest["imageVersion"]):
        raise UpdateError("invalid_manifest", "imageVersion is invalid")
    for field in optional:
        if field in manifest and (not isinstance(manifest[field], str) or not manifest[field] or len(manifest[field]) > 512):
            raise UpdateError("invalid_manifest", f"{field} is invalid")
    if "releaseNotesReference" in manifest:
        notes = urlparse(manifest["releaseNotesReference"])
        if notes.scheme != "https" or not notes.hostname or notes.username or notes.password:
            raise UpdateError("invalid_manifest", "releaseNotesReference must use credential-free HTTPS")
    if "minimumFirmware" in manifest:
        raise UpdateError("firmware_unverified", "this image cannot safely compare vendor firmware versions")
    if not isinstance(manifest["imageDigest"], str) or not SAFE_DIGEST.fullmatch(manifest["imageDigest"]):
        raise UpdateError("invalid_manifest", "imageDigest must be a sha256 digest")
    reference = manifest["imageReference"]
    unsafe_components = not isinstance(reference, str) or "//" in reference or any(part in {"", ".", ".."} for part in reference.split("/"))
    if unsafe_components or not SAFE_REFERENCE.fullmatch(reference) or not any(reference == prefix or reference.startswith(prefix + "/") for prefix in config["imageRepositories"]):
        raise UpdateError("untrusted_image", "image reference is outside configured repositories")
    published = _parse_time(manifest["publishedAt"], "publishedAt")
    expires = _parse_time(manifest["expiresAt"], "expiresAt")
    now = datetime.now(timezone.utc)
    if expires <= now or expires <= published:
        raise UpdateError("expired_manifest", "manifest is expired")
    for field in ("downloadSize", "installedSize"):
        if not isinstance(manifest[field], int) or isinstance(manifest[field], bool) or manifest[field] < 0:
            raise UpdateError("invalid_manifest", f"{field} must be a non-negative integer")
    try:
        highest = int(SEQUENCE_PATH.read_text(encoding="ascii").strip()) if SEQUENCE_PATH.exists() else 0
    except (OSError, ValueError) as exc:
        raise UpdateError("invalid_state", "accepted update sequence state is invalid") from exc
    if manifest["sequence"] < highest or (enforce_new_sequence and manifest["sequence"] <= highest):
        raise UpdateError("rollback_attack", "manifest sequence is not newer than the accepted sequence")
    if "minimumBunnyVersion" in manifest or "maximumBunnyVersion" in manifest:
        artifact = _load_json(BUNNY_ARTIFACT_PATH, 64 * 1024)
        current = artifact.get("bunnyVersion")
        def version_tuple(value: Any) -> tuple[int, int, int]:
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
                raise UpdateError("invalid_manifest", "Bunny compatibility versions must be semantic versions")
            return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]
        installed = version_tuple(current)
        if "minimumBunnyVersion" in manifest and installed < version_tuple(manifest["minimumBunnyVersion"]):
            raise UpdateError("incompatible_bunny", "installed Bunny is older than the update minimum")
        if "maximumBunnyVersion" in manifest and installed > version_tuple(manifest["maximumBunnyVersion"]):
            raise UpdateError("incompatible_bunny", "installed Bunny is newer than the update maximum")
    _verify_signature(manifest)


def _manifest(config: dict[str, Any], enforce_new_sequence: bool) -> dict[str, Any]:
    value = _fetch(config["manifestUrl"])
    _validate_manifest(value, config, enforce_new_sequence)
    return value


def _check_space(manifest: dict[str, Any]) -> None:
    usage = shutil.disk_usage("/var")
    required = max(manifest["downloadSize"], manifest["installedSize"]) + RESERVED_BYTES
    if usage.free < required:
        raise UpdateError("insufficient_disk", f"update requires {required} free bytes including safety reserve")


def _run_fixed(argv: list[str], timeout: int) -> None:
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env={"PATH": "/usr/sbin:/usr/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "HOME": "/root"},
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateError("backend_timeout", "bootc operation timed out") from exc
    if result.returncode != 0:
        message = (result.stdout or "").strip().splitlines()[-1:] or ["bootc operation failed"]
        raise UpdateError("deployment_failed", message[0][:512])


def perform(action: str) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        raise UpdateError("invalid_action", "update action is not allowed")
    if action == "status":
        return _load_json(STATUS_PATH) if STATUS_PATH.exists() else _status("idle", configured=CONFIG_PATH.exists())
    config = _configuration()
    if action == "check":
        manifest = _manifest(config, False)
        return _status("available", manifest={key: value for key, value in manifest.items() if key != "signature"})
    if action == "stage":
        manifest = _manifest(config, True)
        _check_space(manifest)
        _status("staging", imageVersion=manifest["imageVersion"], sequence=manifest["sequence"])
        target = f'{manifest["imageReference"]}@{manifest["imageDigest"]}'
        _run_fixed(["/usr/bin/bootc", "switch", target], 80 * 60)
        _atomic_text(SEQUENCE_PATH, f'{manifest["sequence"]}\n')
        return _status("staged", imageVersion=manifest["imageVersion"], sequence=manifest["sequence"], rebootRequired=True)
    status = _load_json(STATUS_PATH) if STATUS_PATH.exists() else {}
    if status.get("state") != "staged":
        raise UpdateError("not_staged", "no verified OS deployment is staged")
    value = _status("rebooting", imageVersion=status.get("imageVersion"), sequence=status.get("sequence"))
    _run_fixed(["/usr/bin/systemctl", "reboot"], 30)
    return value


def main() -> int:
    action = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        value = perform(action)
        print(json.dumps(value, sort_keys=True))
        return 0
    except UpdateError as exc:
        value = _status("failed", error={"code": exc.code, "message": str(exc)})
        print(json.dumps(value, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
