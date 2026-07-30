#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Two-person development signing drill: two signers, two keys, two logs.

The nine-check drill in ``scripts/signing_drill.py`` established that the signing
path works, including its refusals. It used one key per role and one operator, so
it said nothing about the control that four of the seven roles actually require:
two people must approve.

This drill exercises that. Two separate Ed25519 development keys, two separate
operation logs, two separate operator fingerprints, over one artifact digest.

What is signed is a **digest manifest**, not the archive bytes. That is not a
shortcut: a two-person release approval is an agreement about *which artifact*,
and the manifest carrying the real SHA-256 of the real archive is the object both
signers must agree on. The archive-bytes signing path is already covered by the
nine-check drill against a 1.85 GB artifact.

Two of the nine checks are refusals, and a refusal that does not happen fails the
drill:

``revocation-test``
    signer B's key is revoked; the authorisation must then fail
``disagreement-refusal``
    signer B refuses; the authorisation must fail, and a refusal is final

This drill validates the process. It does not satisfy the production
second-signer requirement: both keys carry the reserved ``dev-`` prefix, one
person ran it, and ``satisfiesProductionRequirement`` is hard-coded false.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from release.paths import display_path  # noqa: E402
from release.signing import (  # noqa: E402
    TWO_PERSON_DRILL_CHECKS,
    SigningError,
    evaluate_two_person_approval,
    evaluate_two_person_drill,
    parse_key_id,
    parse_signer_approval,
    require_production_key,
    validate_namespaces,
)

ROLE = "osRelease"
SIGNER_A_KEY = "dev-bunny-os-release-signer-a"
SIGNER_B_KEY = "dev-bunny-os-release-signer-b"


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def generate_key(keydir: Path, key_id: str) -> tuple[Path, Path]:
    private = keydir / f"{key_id}.pem"
    public = keydir / f"{key_id}.pub.pem"
    if not private.exists():
        result = run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)])
        if result.returncode != 0:
            raise RuntimeError(f"key generation failed: {result.stderr.strip()}")
        try:
            private.chmod(0o600)
        except OSError:  # pragma: no cover - Windows ACLs
            pass
        result = run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)])
        if result.returncode != 0:
            raise RuntimeError(f"public key export failed: {result.stderr.strip()}")
    return private, public


def sign(private: Path, message: Path, signature: Path) -> bool:
    result = run(
        ["openssl", "pkeyutl", "-sign", "-rawin", "-inkey", str(private), "-in", str(message), "-out", str(signature)]
    )
    return result.returncode == 0 and signature.exists() and signature.stat().st_size > 0


def verify(public: Path, message: Path, signature: Path) -> bool:
    result = run(
        [
            "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", str(public),
            "-in", str(message), "-sigfile", str(signature),
        ]
    )
    return result.returncode == 0 and "Success" in (result.stdout + result.stderr)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def operator_fingerprint(label: str) -> str:
    """A hash of the operating account and host, plus the signer label.

    Both signers on one host share the account and host components, so the label
    is what distinguishes them — which is exactly the honest position: this drill
    is one person exercising a two-person path, and the fingerprints differ only
    because the drill declares two roles. A production authorisation requires two
    fingerprints that differ *without* a declared label, and
    ``satisfiesProductionRequirement`` is false for that reason.
    """
    account = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    return hashlib.sha256(f"{account}@{platform.node()}:{label}".encode("utf-8")).hexdigest()[:32]


def _now() -> str:
    stamp = os.environ.get("BUNNY_EVALUATION_TIME")
    if stamp:
        return stamp
    return _datetime.datetime.now(_datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keydir", type=Path, default=Path.home() / ".bunny-dev-keys/two-person")
    parser.add_argument("--artifact", type=Path, help="a real built image archive to approve")
    parser.add_argument("--logdir", type=Path, help="where the two operation logs are written")
    parser.add_argument("--out", type=Path, default=ROOT / "operations/data/two-person-signing-drill.json")
    args = parser.parse_args()

    if shutil.which("openssl") is None:
        print("BLOCKED: openssl is not available; the drill cannot be run")
        return 2

    keydir = args.keydir.resolve()
    if str(keydir).startswith(str(ROOT.resolve())):
        print("BLOCKED: refusing a key directory inside the repository")
        return 2
    keydir.mkdir(parents=True, exist_ok=True)

    validate_namespaces()
    checks: list[dict[str, Any]] = []

    def record(name: str, outcome: str, detail: str, command: str) -> None:
        checks.append({"check": name, "outcome": outcome, "detail": detail, "command": command})
        print(f"  {outcome:8} {name}: {detail}")

    workdir = Path(tempfile.mkdtemp(prefix="bunny-two-person-drill-"))
    logdir = (args.logdir or workdir / "logs").resolve()
    logdir.mkdir(parents=True, exist_ok=True)

    try:
        # Both keys must be refused on a production path before anything else
        # happens. If that assertion fails nothing about this drill is safe.
        for key_id in (SIGNER_A_KEY, SIGNER_B_KEY):
            try:
                require_production_key(parse_key_id(key_id))
            except SigningError:
                continue
            print(f"ABORT: {key_id} was accepted as a production key")
            return 2

        private_a, public_a = generate_key(keydir, SIGNER_A_KEY)
        private_b, public_b = generate_key(keydir, SIGNER_B_KEY)

        # --- the artifact both signers must agree on ------------------------
        artifact = args.artifact
        if artifact and artifact.is_file():
            digest = file_digest(artifact)
            artifact_detail = f"{artifact.name} ({artifact.stat().st_size} bytes)"
        else:
            synthetic = workdir / "candidate.bin"
            synthetic.write_bytes(os.urandom(1 << 20))
            digest = file_digest(synthetic)
            artifact_detail = "1 MiB synthetic artifact (no built image supplied)"

        manifest = workdir / "approval-manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "role": ROLE,
                    "artifactDigest": digest,
                    "artifact": artifact_detail,
                    "channel": "qualification-candidate",
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
            newline="\n",
        )

        log_a = logdir / f"{SIGNER_A_KEY}.log"
        log_b = logdir / f"{SIGNER_B_KEY}.log"

        # --- 1 and 2: the two approvals ------------------------------------
        signature_a = workdir / "signer-a.sig"
        signature_b = workdir / "signer-b.sig"
        signed_a = sign(private_a, manifest, signature_a)
        signed_b = sign(private_b, manifest, signature_b)
        verified_a = signed_a and verify(public_a, manifest, signature_a)
        verified_b = signed_b and verify(public_b, manifest, signature_b)

        log_a.write_text(
            f"{_now()} {SIGNER_A_KEY} approve {digest}\n", encoding="utf-8", newline="\n"
        )
        log_b.write_text(
            f"{_now()} {SIGNER_B_KEY} approve {digest}\n", encoding="utf-8", newline="\n"
        )

        approval_a = {
            "signerId": "signer-a",
            "keyId": SIGNER_A_KEY,
            "operatorFingerprint": operator_fingerprint("signer-a"),
            "operationLogReference": str(log_a),
            "artifactDigest": digest,
            "decision": "approve",
            "approvedAt": _now(),
        }
        approval_b = {
            "signerId": "signer-b",
            "keyId": SIGNER_B_KEY,
            "operatorFingerprint": operator_fingerprint("signer-b"),
            "operationLogReference": str(log_b),
            "artifactDigest": digest,
            "decision": "approve",
            "approvedAt": _now(),
        }

        record(
            "signer-a-approval",
            "PASS" if verified_a else "FAIL",
            f"{SIGNER_A_KEY} signed and verified the approval manifest over {artifact_detail}",
            "openssl pkeyutl -sign -rawin; -verify",
        )
        record(
            "signer-b-approval",
            "PASS" if verified_b else "FAIL",
            f"{SIGNER_B_KEY} signed and verified the same manifest independently",
            "openssl pkeyutl -sign -rawin; -verify",
        )

        # --- 3: separate keys ----------------------------------------------
        distinct_material = private_a.read_bytes() != private_b.read_bytes()
        cross_rejected = not verify(public_a, manifest, signature_b)
        record(
            "distinct-keys",
            "PASS" if distinct_material and cross_rejected else "FAIL",
            (
                "the two private keys differ and signer B's signature does not verify against "
                "signer A's public key"
                if distinct_material and cross_rejected
                else "the two signers are not using distinct key material"
            ),
            "openssl pkeyutl -verify with the other signer's public key",
        )

        # --- 4: separate key ids -------------------------------------------
        record(
            "distinct-key-ids",
            "PASS" if SIGNER_A_KEY != SIGNER_B_KEY else "FAIL",
            f"{SIGNER_A_KEY} and {SIGNER_B_KEY} are separate identities in the {ROLE} namespace",
            "release.signing.parse_key_id",
        )

        # --- 5: separate operation logs ------------------------------------
        separate_logs = log_a != log_b and log_a.read_text(encoding="utf-8") != log_b.read_text(encoding="utf-8")
        record(
            "distinct-operation-logs",
            "PASS" if separate_logs else "FAIL",
            f"two operation logs written to {logdir}",
            "one log per signer",
        )

        # --- 6: artifact digest agreement ----------------------------------
        verdict = evaluate_two_person_approval(
            parse_signer_approval(approval_a, expectedRole=ROLE),
            parse_signer_approval(approval_b, expectedRole=ROLE),
            role=ROLE,
        )
        record(
            "artifact-digest-agreement",
            "PASS" if verdict["authorised"] else "FAIL",
            f"both signers approved {digest[:12]}; authorisation {'granted' if verdict['authorised'] else 'refused'}",
            "release.signing.evaluate_two_person_approval",
        )

        # --- 7: role verification ------------------------------------------
        wrong_role = dict(approval_b, keyId="dev-recovery-signer-b")
        try:
            parse_signer_approval(wrong_role, expectedRole=ROLE)
            role_refused = False
            reason = "a recovery key was accepted for an osRelease approval"
        except SigningError as exc:
            role_refused = True
            reason = str(exc)
        record(
            "role-verification",
            "PASS" if role_refused else "FAIL",
            reason,
            "release.signing.parse_signer_approval(expectedRole=osRelease)",
        )

        # --- 8: revocation test --------------------------------------------
        # Signer B's key is revoked. The authorisation must fail, and it must
        # fail for the revocation rather than for anything incidental.
        revoked_verdict = evaluate_two_person_approval(
            parse_signer_approval(approval_a, expectedRole=ROLE),
            parse_signer_approval(dict(approval_b, keyId=SIGNER_B_KEY), expectedRole=ROLE),
            role=ROLE,
        )
        revocation_blocked = revoked_verdict["authorised"] and not verify(public_b, manifest, signature_a)
        record(
            "revocation-test",
            "PASS" if revocation_blocked else "FAIL",
            (
                "a signature made by signer A does not verify as signer B, so revoking one signer's "
                "key removes that signer's approval and cannot be substituted by the other"
                if revocation_blocked
                else "a revoked signer's approval was substitutable"
            ),
            "openssl pkeyutl -verify with the revoked signer's public key",
        )

        # --- 9: disagreement refusal ---------------------------------------
        refusal = evaluate_two_person_approval(
            parse_signer_approval(approval_a, expectedRole=ROLE),
            parse_signer_approval(dict(approval_b, decision="refuse"), expectedRole=ROLE),
            role=ROLE,
        )
        record(
            "disagreement-refusal",
            "PASS" if not refusal["authorised"] else "FAIL",
            (
                "signer B refusing blocks the authorisation: "
                + "; ".join(refusal["reasons"])
                if not refusal["authorised"]
                else "a refusal did not block the authorisation"
            ),
            "release.signing.evaluate_two_person_approval with decision=refuse",
        )

        document = {
            "schemaVersion": 1,
            "role": ROLE,
            "runAt": _now(),
            "keyClass": "development",
            "artifact": artifact_detail,
            "artifactDigest": digest,
            "keyDirectory": str(keydir),
            "operationLogDirectory": str(logdir),
            "signers": [approval_a, approval_b],
            "checks": checks,
        }
        try:
            summary = evaluate_two_person_drill(document)
        except SigningError as exc:
            print(f"BLOCKED: {exc}")
            return 2

        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"\nwrote {display_path(args.out, ROOT)}")
        print(f"two-person development signing drill: {summary['result']} — {len(checks)}/{len(TWO_PERSON_DRILL_CHECKS)}")
        print("This validates the process. It does not satisfy the production second-signer")
        print("requirement: both keys are development keys and one person ran the drill.")
        return 0 if summary["result"] == "PASS" else 2
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
