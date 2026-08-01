#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Signed-update metadata tests, executed against the real update agent.

The point of this executor is that every verdict below comes out of
``services/bunny-update-agent/bunny_update_agent.py`` — the code that runs on
a device — not out of a harness reimplementation of it. A reimplementation
can only prove that the harness agrees with itself; the qualification
question is whether *the shipped validator* accepts a well-formed signed
manifest and refuses every tampered, mis-keyed, truncated, unsigned and
expired variant. ``build/scripts/vm-upgrade-test.sh`` established the
pattern (import the agent, call its validator); this script extends it to
the full rejection matrix and writes evidence records in the shape the
installed-system collectors use.

Signature format, learned by reading the agent rather than assuming:
the manifest embeds a base64 Ed25519 signature in its ``signature`` field,
computed over ``_canonical_payload()`` — the manifest without ``signature``
(``keyId`` stays in), serialized with sorted keys and compact separators as
UTF-8. We therefore sign with ``openssl pkeyutl -sign -rawin`` over exactly
``agent._canonical_payload(manifest)``, never over bytes we canonicalised
ourselves: if the agent's canonicalisation ever changes, this harness
follows it automatically instead of silently diverging.

Keys are real Ed25519 keys minted at runtime with openssl into a temporary
directory, mirroring ``scripts/signing_drill.py``. They carry the reserved
``dev-`` prefix, so ``release.signing.require_production_key`` refuses them
on any production path; nothing this script produces can be mistaken for
release signing evidence, which is what makes it safe to run automatically.
No key material is ever written inside the repository.

The agent hard-codes on-device paths (trust store, accepted-sequence state).
Running on a build host, those module globals are redirected into the same
temporary directory; the functions under test execute unmodified. The
sequence state is seeded at 1 and the manifest carries sequence 2 so the
accepted case genuinely exercises the N -> N+1 progression the stage path
(``enforce_new_sequence=True``) demands.

A missing prerequisite is BLOCKED (exit 2), never a quiet pass: a rejection
matrix that could not run has proven nothing.
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
AGENT_DIR = ROOT / "services" / "bunny-update-agent"
SCHEMA_PATH = ROOT / "schemas" / "bunny-os-update-manifest.schema.json"
DEFAULT_OUTPUT_DIR = ROOT / "qualification" / "installed-system" / "evidence" / "collections"

sys.path.insert(0, str(AGENT_DIR))
import bunny_update_agent as agent  # noqa: E402  (path inserted just above)

#: dev- prefix is reserved for development keys; release.signing refuses it.
TRUSTED_KEY_ID = "dev-update-qual1"
ROGUE_KEY_ID = "dev-update-rogue1"

LIMITATIONS = [
    "development keys only; production signing remains unclaimed",
    "metadata validation exercised directly against the agent's validator; "
    "the in-guest download path is not exercised",
    "the agent's on-device trust-store and sequence-state paths were redirected "
    "into a temporary directory for host execution; the validator code itself "
    "ran unmodified",
]

SIGNATURE_FORMAT = (
    "embedded base64 Ed25519 signature over agent._canonical_payload(): the "
    "manifest minus its signature field, JSON with sorted keys and compact "
    "separators, UTF-8"
)


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True)


def mint_key(keydir: Path, key_id: str) -> tuple[Path, Path]:
    """Mint a real Ed25519 keypair the way scripts/signing_drill.py does.

    Keys live only in the caller's temporary directory: the repository-wide
    rule (enforced by sign-stable-rc.py and honoured by the drill) is that
    private keys never exist inside the working tree.
    """
    private = keydir / f"{key_id}.pem"
    public = keydir / f"{key_id}.pub.pem"
    result = run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)])
    if result.returncode != 0:
        raise RuntimeError(f"key generation failed: {result.stderr.strip()}")
    private.chmod(0o600)
    result = run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)])
    if result.returncode != 0:
        raise RuntimeError(f"public key export failed: {result.stderr.strip()}")
    return private, public


def sign_manifest(manifest: dict[str, Any], private: Path, workdir: Path) -> str:
    """Sign the agent's own canonical payload; return the base64 signature.

    Uses agent._canonical_payload so the bytes signed are byte-identical to
    the bytes the agent will verify — the harness holds no opinion of its own
    about canonicalisation.
    """
    payload = workdir / "payload.bin"
    signature = workdir / "payload.sig"
    payload.write_bytes(agent._canonical_payload(manifest))
    result = run([
        "openssl", "pkeyutl", "-sign", "-rawin",
        "-inkey", str(private), "-in", str(payload), "-out", str(signature),
    ])
    if result.returncode != 0 or not signature.exists() or signature.stat().st_size == 0:
        raise RuntimeError(f"signing failed: {result.stderr.strip()}")
    return base64.b64encode(signature.read_bytes()).decode("ascii")


def iso(moment: datetime) -> str:
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def base_manifest(key_id: str, *, expired: bool = False) -> dict[str, Any]:
    """A manifest honouring schemas/bunny-os-update-manifest.schema.json.

    sequence 2 against seeded accepted-sequence 1, osVersion 1.0.0 -> 1.0.1:
    the accepted case is a genuine N -> N+1 update, not a first install.
    Architecture comes from the agent's own mapping so the manifest matches
    whatever host actually runs this (the agent refuses a mismatch).
    """
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=1)
    # An expired manifest must still be *internally* consistent
    # (expiresAt > publishedAt) so that only the expiry clause can reject it.
    expires = now - timedelta(minutes=1) if expired else now + timedelta(days=14)
    if expired:
        published = now - timedelta(days=14)
    return {
        "schemaVersion": 1,
        "sequence": 2,
        "channel": "developer",
        "osVersion": "1.0.1",
        "imageVersion": "1.0.1",
        "imageReference": "registry.bunny-os.example/bunny-os/os",
        "imageDigest": "sha256:" + "ab" * 32,
        "architecture": agent._architecture(),
        "publishedAt": iso(published),
        "expiresAt": iso(expires),
        "contractVersion": agent.CONTRACT_VERSION,
        "downloadSize": 1 << 20,
        "installedSize": 4 << 20,
        "keyId": key_id,
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="update_manifest_tests")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                        help="directory receiving the two evidence records")
    args = parser.parse_args()

    if shutil.which("openssl") is None:
        print("BLOCKED: openssl is not available; keys cannot be minted and the "
              "rejection matrix cannot run", file=sys.stderr)
        return 2
    # The agent invokes /usr/bin/openssl by absolute path with PATH=/usr/bin.
    # Without it the verifier under test cannot execute at all, and a matrix
    # whose verifier never ran must not report anything.
    if not Path("/usr/bin/openssl").is_file():
        print("BLOCKED: the update agent verifies with /usr/bin/openssl, which "
              "does not exist here; run this on Fedora (or Fedora WSL)",
              file=sys.stderr)
        return 2

    validator = getattr(agent, "_validate_manifest", None)
    if validator is None:
        print("BLOCKED: the update agent no longer exposes _validate_manifest; "
              "this harness needs updating to the new entry point", file=sys.stderr)
        return 2

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        schema_required = set(schema["required"])
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"BLOCKED: cannot read the manifest schema at {SCHEMA_PATH}: {exc}",
              file=sys.stderr)
        return 2

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # The channel/repository policy the validator enforces against. Only
    # channel and imageRepositories are consulted by _validate_manifest, but
    # the full shape of /etc/bunny-os/update.json is kept for fidelity.
    config = {
        "enabled": True,
        "channel": "developer",
        "manifestUrl": "https://updates.bunny-os.example/developer/manifest.json",
        "imageRepositories": ["registry.bunny-os.example/bunny-os"],
    }

    valid_assertions: list[dict[str, Any]] = []
    invalid_assertions: list[dict[str, Any]] = []

    def record(bucket: list[dict[str, Any]], name: str, expected: str,
               observed: str, ok: bool) -> None:
        bucket.append({"name": name, "expected": expected, "observed": observed,
                       "result": "PASS" if ok else "FAIL"})

    def attempt(manifest: dict[str, Any]) -> tuple[bool, str]:
        """Run the real validator; report (accepted, detail)."""
        try:
            validator(manifest, config, True)
            return True, "accepted"
        except agent.UpdateError as exc:
            return False, f"rejected ({exc.code}: {exc})"

    with tempfile.TemporaryDirectory(prefix="bunny-update-manifest-tests-") as scratch:
        workdir = Path(scratch)
        if str(workdir.resolve()).startswith(str(ROOT.resolve())):
            # Same rule the signing drill enforces: no key material in-tree.
            print("BLOCKED: temporary directory resolves inside the repository; "
                  "refusing to mint keys there", file=sys.stderr)
            return 2

        keydir = workdir / "keys"
        keydir.mkdir(mode=0o700)
        trusted_private, trusted_public = mint_key(keydir, TRUSTED_KEY_ID)
        rogue_private, _rogue_public = mint_key(keydir, ROGUE_KEY_ID)

        # Redirect the agent's on-device state into the scratch directory.
        # Only the trusted key's public half is installed; the rogue key is
        # deliberately absent from the trust store.
        trust_dir = workdir / "trust"
        trust_dir.mkdir(mode=0o700)
        shutil.copyfile(trusted_public, trust_dir / f"{TRUSTED_KEY_ID}.pem")
        agent.KEY_DIR = trust_dir
        agent.REVOCATIONS_PATH = trust_dir / "revoked-keys.json"
        agent.SEQUENCE_PATH = workdir / "highest-sequence"
        agent.SEQUENCE_PATH.write_text("1\n", encoding="ascii")

        # --- valid dev-signed manifest -> accepted -----------------------
        manifest = base_manifest(TRUSTED_KEY_ID)
        manifest["signature"] = sign_manifest(manifest, trusted_private, workdir)
        missing = schema_required - set(manifest)
        record(valid_assertions, "manifest-covers-schema-required-fields",
               "every schema-required field present",
               f"missing: {sorted(missing) or 'none'}", not missing)
        accepted, detail = attempt(manifest)
        record(valid_assertions, "valid-dev-signed-manifest-accepted",
               "accepted by the agent validator", detail, accepted)

        # --- wrong signing key, its own (untrusted) keyId -> rejected ----
        wrong_key = base_manifest(ROGUE_KEY_ID)
        wrong_key["signature"] = sign_manifest(wrong_key, rogue_private, workdir)
        accepted, detail = attempt(wrong_key)
        record(invalid_assertions, "wrong-key-unregistered-keyid-rejected",
               "rejected: signing key is not in the trust store", detail, not accepted)

        # --- wrong signing key claiming the trusted keyId -> rejected ----
        # The stronger attack: a rogue signer who *names* the trusted key.
        # Key lookup succeeds, so only the signature check can save us here.
        forged = base_manifest(TRUSTED_KEY_ID)
        forged["signature"] = sign_manifest(forged, rogue_private, workdir)
        accepted, detail = attempt(forged)
        record(invalid_assertions, "wrong-key-forged-keyid-rejected",
               "rejected: signature does not verify under the trusted key",
               detail, not accepted)

        # --- version field flipped after signing -> rejected -------------
        tampered_version = dict(manifest)
        tampered_version["osVersion"] = "1.0.2"
        accepted, detail = attempt(tampered_version)
        record(invalid_assertions, "modified-version-after-signing-rejected",
               "rejected: canonical payload changed under the signature",
               detail, not accepted)

        # --- image digest swapped after signing -> rejected --------------
        tampered_digest = dict(manifest)
        tampered_digest["imageDigest"] = "sha256:" + "cd" * 32
        accepted, detail = attempt(tampered_digest)
        record(invalid_assertions, "modified-image-digest-rejected",
               "rejected: canonical payload changed under the signature",
               detail, not accepted)

        # --- truncated manifest -> rejected -------------------------------
        # Truncation happens on the wire, so it is exercised at the byte
        # level through the agent's own document loader, not by mutating a
        # dict the truncation could never have produced.
        raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        truncated_path = workdir / "truncated-manifest.json"
        truncated_path.write_bytes(raw[: len(raw) - 25])
        try:
            parsed = agent._load_json(truncated_path)
            accepted, detail = attempt(parsed)  # parse survived; validator must not
        except agent.UpdateError as exc:
            accepted, detail = False, f"rejected ({exc.code}: {exc})"
        record(invalid_assertions, "truncated-manifest-rejected",
               "rejected: truncated document does not parse or validate",
               detail, not accepted)

        # --- missing signature -> rejected --------------------------------
        unsigned = dict(manifest)
        del unsigned["signature"]
        accepted, detail = attempt(unsigned)
        record(invalid_assertions, "missing-signature-rejected",
               "rejected: signature is a required field", detail, not accepted)

        # --- expired metadata -> rejected ----------------------------------
        # Expiry IS supported: expiresAt is required by
        # schemas/bunny-os-update-manifest.schema.json and _validate_manifest
        # raises expired_manifest for it (before the signature check). The
        # manifest is properly signed by the trusted key so that expiry is
        # the only clause that can reject it.
        expired = base_manifest(TRUSTED_KEY_ID, expired=True)
        expired["signature"] = sign_manifest(expired, trusted_private, workdir)
        accepted, detail = attempt(expired)
        record(invalid_assertions, "expired-metadata-rejected",
               "rejected: expiresAt is in the past", detail, not accepted)

    # PASS only if the valid case was accepted AND every rejection actually
    # rejected — a joint verdict, because a validator that accepts everything
    # makes the valid case meaningless and vice versa.
    everything = valid_assertions + invalid_assertions
    overall = "PASS" if all(a["result"] == "PASS" for a in everything) else "FAIL"

    def write_record(name: str, collection: str, assertions: list[dict[str, Any]]) -> None:
        document = {
            "schemaVersion": 1,
            "collection": collection,
            "agentEntryPoint":
                "bunny_update_agent._validate_manifest(manifest, config, enforce_new_sequence=True)",
            "signatureFormat": SIGNATURE_FORMAT,
            "keyClass": "development",
            "assertions": assertions,
            "limitations": LIMITATIONS,
            "result": overall,
        }
        path = output_dir / name
        path.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")

    write_record("update-manifest-valid.json", "update-manifest-valid", valid_assertions)
    write_record("update-invalid-signature.json", "update-invalid-signature", invalid_assertions)

    print(f"update manifest tests: {overall}")
    for assertion in everything:
        print(f"  {assertion['result']:4} {assertion['name']}: {assertion['observed'][:100]}")
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
