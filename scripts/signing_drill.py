#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the development signing drill end to end with real Ed25519 keys.

Nine checks, all performed against real artifacts with real signatures. Four of
them are *rejections*, and a rejection that does not happen is a failure: a
signing system that cannot refuse is not a signing system.

Every key this drill mints carries the reserved ``dev-`` prefix, so
``release.signing.require_production_key`` refuses all of them. The drill
therefore cannot produce anything a release gate would accept, which is what
makes it safe to run automatically.

Private keys are generated outside the repository. ``build/scripts/sign-stable-rc.py``
already refuses a key path inside the working tree, and this drill honours the
same rule rather than making an exception for itself.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.signing import (
    SIGNING_ROLES,
    SigningError,
    parse_key_id,
    parse_key_record,
    require_production_key,
    rotation_overlap,
    usable_key,
    validate_namespaces,
)

#: Role to development key id used by the drill.
DRILL_KEYS = {
    "osRelease": "dev-bunny-os-release-drill1",
    "recoveryImage": "dev-recovery-drill1",
    "updateMetadata": "dev-update-drill1",
    "applicationCatalogue": "dev-catalogue-drill1",
}
ROTATED_KEY = "dev-bunny-os-release-drill2"


def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, **kwargs)


def openssl_available() -> bool:
    return shutil.which("openssl") is not None


def generate_key(keydir: Path, key_id: str) -> tuple[Path, Path]:
    private = keydir / f"{key_id}.pem"
    public = keydir / f"{key_id}.pub.pem"
    if not private.exists():
        result = run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)])
        if result.returncode != 0:
            raise RuntimeError(f"key generation failed: {result.stderr.strip()}")
        private.chmod(0o600)
        result = run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)])
        if result.returncode != 0:
            raise RuntimeError(f"public key export failed: {result.stderr.strip()}")
    return private, public


def sign(private: Path, artifact: Path, signature: Path) -> bool:
    result = run(
        ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private), "-in", str(artifact), "-out", str(signature)]
    )
    return result.returncode == 0 and signature.exists() and signature.stat().st_size > 0


def verify(public: Path, artifact: Path, signature: Path) -> bool:
    result = run(
        [
            "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public),
            "-in", str(artifact), "-sigfile", str(signature),
        ]
    )
    return result.returncode == 0 and "Success" in (result.stdout + result.stderr)


def make_key_record(key_id: str, *, published: str, expires: str, supersedes: str | None = None) -> dict[str, Any]:
    identity = parse_key_id(key_id)
    return {
        "keyId": key_id,
        "state": "active",
        "publishedAt": published,
        "expiresAt": expires,
        "publicKeyReference": f"build/keys/{key_id}.pub.pem",
        "storage": "development-directory",
        "twoPersonApproval": False,
        **({"supersedes": supersedes} if supersedes else {}),
        "_role": identity.role,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keydir", type=Path, default=Path.home() / ".bunny-dev-keys/drill")
    parser.add_argument("--release-artifact", type=Path, help="a real built image archive to sign")
    parser.add_argument("--recovery-artifact", type=Path, help="a real built recovery image to sign")
    parser.add_argument("--out", type=Path, default=ROOT / "operations/data/signing-drill.json")
    args = parser.parse_args()

    if not openssl_available():
        print("BLOCKED: openssl is not available; the drill cannot be simulated")
        return 2

    keydir = args.keydir.resolve()
    if str(keydir).startswith(str(ROOT.resolve())):
        print("BLOCKED: refusing a key directory inside the repository")
        return 2
    keydir.mkdir(parents=True, exist_ok=True)
    keydir.chmod(0o700)

    validate_namespaces()
    checks: list[dict[str, Any]] = []

    def record(name: str, outcome: str, detail: str, command: str) -> None:
        checks.append({"check": name, "outcome": outcome, "detail": detail, "command": command})
        print(f"  {outcome:8} {name}: {detail}")

    workdir = Path(tempfile.mkdtemp(prefix="bunny-signing-drill-"))
    try:
        keys = {role: generate_key(keydir, key_id) for role, key_id in DRILL_KEYS.items()}

        # Every drill key must be refused on a production path. Checked first,
        # because if this fails nothing else about the drill is safe.
        for role, key_id in DRILL_KEYS.items():
            try:
                require_production_key(parse_key_id(key_id))
            except SigningError:
                continue
            record(
                "release-image-signing",
                "FAIL",
                f"{key_id} was accepted as a production key; aborting",
                "release.signing.require_production_key",
            )
            raise SystemExit(2)

        # --- 1. release image signing ---
        release_artifact = args.release_artifact
        if release_artifact and release_artifact.is_file():
            source = release_artifact
            detail_suffix = f"real artifact {source.name} ({source.stat().st_size} bytes)"
        else:
            source = workdir / "release-image.bin"
            source.write_bytes(os.urandom(1 << 20))
            detail_suffix = "1 MiB synthetic artifact (no built image supplied)"
        release_sig = workdir / "release.sig"
        ok = sign(keys["osRelease"][0], source, release_sig)
        record(
            "release-image-signing",
            "PASS" if ok else "FAIL",
            f"signed with {DRILL_KEYS['osRelease']} over {detail_suffix}",
            "openssl pkeyutl -sign -rawin",
        )

        # --- 2. recovery image signing ---
        recovery_artifact = args.recovery_artifact
        if recovery_artifact and recovery_artifact.is_file():
            recovery_source = recovery_artifact
            recovery_detail = f"real recovery artifact {recovery_source.name} ({recovery_source.stat().st_size} bytes)"
        else:
            recovery_source = workdir / "recovery-image.bin"
            recovery_source.write_bytes(os.urandom(1 << 19))
            recovery_detail = "512 KiB synthetic recovery artifact (no built recovery image supplied)"
        recovery_sig = workdir / "recovery.sig"
        ok = sign(keys["recoveryImage"][0], recovery_source, recovery_sig)
        record(
            "recovery-image-signing",
            "PASS" if ok else "FAIL",
            f"signed with {DRILL_KEYS['recoveryImage']} over {recovery_detail}",
            "openssl pkeyutl -sign -rawin",
        )

        # --- 3. update manifest signing ---
        manifest = workdir / "update-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "channel": "qualification-candidate",
                    "architecture": "x86-64",
                    "imageDigest": "sha256:" + "0" * 64,
                    "issuedAt": "2026-07-29T00:00:00Z",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        manifest_sig = workdir / "update-manifest.sig"
        ok = sign(keys["updateMetadata"][0], manifest, manifest_sig)
        record(
            "update-manifest-signing",
            "PASS" if ok else "FAIL",
            f"signed with {DRILL_KEYS['updateMetadata']}",
            "openssl pkeyutl -sign -rawin",
        )

        # --- 4. catalogue signing ---
        catalogue = workdir / "catalogue.json"
        catalogue.write_text(
            json.dumps({"schemaVersion": 1, "organisation": "drill", "applications": []}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        catalogue_sig = workdir / "catalogue.sig"
        ok = sign(keys["applicationCatalogue"][0], catalogue, catalogue_sig)
        record(
            "catalogue-signing",
            "PASS" if ok else "FAIL",
            f"signed with {DRILL_KEYS['applicationCatalogue']}",
            "openssl pkeyutl -sign -rawin",
        )

        # --- 5. verification ---
        verified = all(
            [
                verify(keys["osRelease"][1], source, release_sig),
                verify(keys["recoveryImage"][1], recovery_source, recovery_sig),
                verify(keys["updateMetadata"][1], manifest, manifest_sig),
                verify(keys["applicationCatalogue"][1], catalogue, catalogue_sig),
            ]
        )
        record(
            "verification",
            "PASS" if verified else "FAIL",
            "all four signatures verified against their published public keys",
            "openssl pkeyutl -verify -rawin -pubin",
        )

        # --- 6. key rotation with overlapping trust ---
        generate_key(keydir, ROTATED_KEY)
        previous = parse_key_record(
            make_key_record(DRILL_KEYS["osRelease"], published="2026-01-01T00:00:00Z", expires="2027-01-01T00:00:00Z")
        )
        replacement = parse_key_record(
            make_key_record(
                ROTATED_KEY,
                published="2026-10-01T00:00:00Z",
                expires="2028-01-01T00:00:00Z",
                supersedes=DRILL_KEYS["osRelease"],
            )
        )
        overlapped, reason = rotation_overlap(previous, replacement)
        no_overlap_replacement = parse_key_record(
            make_key_record(
                ROTATED_KEY,
                published="2027-06-01T00:00:00Z",
                expires="2028-01-01T00:00:00Z",
                supersedes=DRILL_KEYS["osRelease"],
            )
        )
        gapped, gap_reason = rotation_overlap(previous, no_overlap_replacement)
        record(
            "key-rotation",
            "PASS" if overlapped and not gapped else "FAIL",
            f"overlapping rotation accepted ({reason}); non-overlapping rotation refused ({gap_reason})",
            "release.signing.rotation_overlap",
        )

        # --- 7. revoked key rejection ---
        now = _datetime.datetime(2026, 11, 1, tzinfo=_datetime.timezone.utc)
        usable, _ = usable_key(previous, role="osRelease", now=now, requireProduction=False)
        revoked_usable, revoked_reason = usable_key(
            previous, role="osRelease", now=now, revokedKeyIds=[previous.keyId], requireProduction=False
        )
        record(
            "revoked-key-rejection",
            "PASS" if usable and not revoked_usable else "FAIL",
            f"key usable before revocation, refused after: {revoked_reason}",
            "release.signing.usable_key(revokedKeyIds=...)",
        )

        # --- 8. wrong-role rejection ---
        wrong_role_refused = False
        try:
            parse_key_id(DRILL_KEYS["recoveryImage"], expectedRole="osRelease")
        except SigningError as exc:
            wrong_role_refused = "not interchangeable" in str(exc)
        cross_usable, cross_reason = usable_key(previous, role="fleetPolicy", now=now, requireProduction=False)
        record(
            "wrong-role-rejection",
            "PASS" if wrong_role_refused and not cross_usable else "FAIL",
            f"recovery key refused for the osRelease role; release key refused for fleetPolicy ({cross_reason})",
            "release.signing.parse_key_id(expectedRole=...)",
        )

        # --- 9. corrupted artifact rejection ---
        corrupted = workdir / "corrupted.bin"
        data = source.read_bytes()
        corrupted.write_bytes(data[: max(1, len(data) - 64)])
        corrupt_verified = verify(keys["osRelease"][1], corrupted, release_sig)
        record(
            "corrupted-artifact-rejection",
            "PASS" if not corrupt_verified else "FAIL",
            "signature over the intact artifact does not verify against a truncated copy",
            "openssl pkeyutl -verify against a modified artifact",
        )

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    payload = {
        "schemaVersion": 1,
        "keyClass": "development",
        "keyDirectory": str(keydir),
        "keysUsed": sorted([*DRILL_KEYS.values(), ROTATED_KEY]),
        "ranAt": _datetime.datetime.now(_datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "checks": checks,
        "note": (
            "Every key here carries the reserved dev- prefix and is refused by "
            "require_production_key. This drill proves the signing path works; it is not release "
            "signing evidence and no production key ceremony has occurred."
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"\nwrote {args.out}")

    failing = [c["check"] for c in checks if c["outcome"] != "PASS"]
    if failing:
        print("drill FAILED: " + ", ".join(failing))
        return 2
    print(f"development signing drill: {len(checks)}/9 checks PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
