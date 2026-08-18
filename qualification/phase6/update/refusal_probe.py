#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Phase 6 section 10 -- qualify the update refusal as intentional behaviour.

Runs INSIDE a container started from the subject artifact's own image, with no
network. Every check records what was asked, what happened, and whether that is
the intended answer.

The load-bearing part is not that the agent refuses. It is B3: a control key is
installed and a correctly signed manifest is then ACCEPTED. Without that, every
refusal here is equally well explained by "openssl is missing" or "the key path
is wrong", and the qualification would prove nothing about the trust store.

This file is the instrument. Its verdict logic is unit-tested in
tests/qualification/test_phase6_refusal_probe.py against recorded fixtures, so
that a probe which silently stops checking is caught by something other than
reading it.
"""

from __future__ import annotations

import base64
import importlib.machinery
import importlib.util
import json
import pathlib
import subprocess
import sys

AGENT = "/usr/libexec/bunny-update-agent"
KEYDIR = pathlib.Path("/usr/share/bunny-os/update-keys")
CONFIG = pathlib.Path("/etc/bunny-os/update.json")
OUTPUT = pathlib.Path("/out/refusal-qualification.json")

#: Every check this probe is required to perform. A run that does not produce
#: exactly this set is incomplete, however green the checks it did run were --
#: a probe that stops early has historically been the failure mode here, not a
#: probe that reports the wrong answer.
REQUIRED_CHECKS = (
    "A0", "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8",
    "B1", "B2", "B3", "B4",
    "C1", "C2",
    "D1", "D2", "D3",
)


def summarise(results):
    """Turn a list of check records into the run verdict.

    Separated from the checks themselves so it can be tested against fixtures
    that the probe cannot produce on this host, including the cases where it
    must report UNEXPECTED and INCOMPLETE.
    """
    seen = [record["id"] for record in results]
    duplicates = sorted({name for name in seen if seen.count(name) > 1})
    missing = [name for name in REQUIRED_CHECKS if name not in seen]
    unexpected = [record for record in results if record["verdict"] != "AS_INTENDED"]

    if duplicates:
        result = "INVALID"
    elif missing:
        result = "INCOMPLETE"
    elif unexpected:
        result = "UNEXPECTED"
    else:
        result = "AS_INTENDED"

    return {
        "schemaVersion": 1,
        "record": "phase6-update-refusal-qualification",
        "checks": len(results),
        "requiredChecks": len(REQUIRED_CHECKS),
        "asIntended": len(results) - len(unexpected),
        "unexpectedChecks": [record["id"] for record in unexpected],
        "missingChecks": missing,
        "duplicateChecks": duplicates,
        "result": result,
        "results": results,
    }


def main() -> int:
    results: list[dict] = []

    def record(ident, question, expected, observed, ok, detail=None):
        verdict = "AS_INTENDED" if ok else "UNEXPECTED"
        results.append({
            "id": ident,
            "question": question,
            "expected": expected,
            "observed": observed,
            "verdict": verdict,
            "detail": detail,
        })
        print("[%s] %s: %s" % (verdict, ident, question))
        print("        expected: %s" % expected)
        print("        observed: %s" % observed)
        if detail:
            print("        detail:   %s" % detail)

    def run_agent(action):
        proc = subprocess.run([AGENT, action], capture_output=True, text=True)
        body = (proc.stdout or proc.stderr or "").strip()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = None
        return proc.returncode, parsed, body

    # ------------------------------------------------------------- Part A
    print("=== A -- the image exactly as it ships ===")

    # A0 MUST run before any other action. `status` returns the recorded status
    # file when one exists, and every refusal below writes one. Asked later, it
    # answers a different question and an assertion on the exit code alone would
    # pass without ever seeing the value it names.
    code, parsed, raw = run_agent("status")
    record(
        "A0", "on an untouched system, does status overstate what is configured?",
        "exit 0, state idle, configured true -- a field that means only that the file exists",
        "exit %s, body %s" % (code, json.dumps(parsed, sort_keys=True) if parsed else raw),
        code == 0
        and isinstance(parsed, dict)
        and parsed.get("state") == "idle"
        and parsed.get("configured") is True,
        detail=(
            "configured:true is derived from CONFIG_PATH.exists() alone. It is true of "
            "an image that can never update, because the file it is testing for is the "
            "one that says enabled:false. Recorded because a status field that reads as "
            "capability and means file-presence is something a reviewer must be told "
            "rather than left to discover."
        ),
    )

    pems = sorted(p.name for p in KEYDIR.glob("*.pem")) if KEYDIR.is_dir() else []
    contents = sorted(p.name for p in KEYDIR.iterdir()) if KEYDIR.is_dir() else []
    record(
        "A1", "does the shipped trust store contain any trusted signing key?",
        "no .pem files; only revoked-keys.json",
        "%d pem file(s); directory holds %s" % (len(pems), contents),
        not pems,
    )

    config = json.loads(CONFIG.read_text())
    record(
        "A2", "what does the shipped update configuration say?",
        "enabled false, and a manifestUrl that cannot resolve",
        json.dumps(config, sort_keys=True),
        config.get("enabled") is False,
    )

    revocations = json.loads((KEYDIR / "revoked-keys.json").read_text())
    record(
        "A3", "what does the shipped revocation list contain?",
        "a valid, empty list -- revocation is available but unused",
        json.dumps(revocations, sort_keys=True),
        revocations.get("revokedKeyIds") == [],
    )

    for ident, action in (("A4", "check"), ("A5", "stage"), ("A6", "install")):
        code, parsed, _ = run_agent(action)
        error = (parsed or {}).get("error", {})
        record(
            ident, "does the agent refuse the %s action as shipped?" % action,
            "exit 2, error code not_configured",
            "exit %s, code %r, message %r" % (code, error.get("code"), error.get("message")),
            code == 2 and error.get("code") == "not_configured",
        )

    code, parsed, raw = run_agent("status")
    record(
        "A7", "after a refusal, does status report the refusal rather than idle?",
        "exit 0, state failed, error code not_configured",
        "exit %s, body %s" % (code, json.dumps(parsed, sort_keys=True) if parsed else raw),
        code == 0
        and isinstance(parsed, dict)
        and parsed.get("state") == "failed"
        and parsed.get("error", {}).get("code") == "not_configured",
        detail=(
            "status is a record of the last outcome, not a current assessment: it "
            "returns the status file when one exists and only computes idle when none "
            "does. A0 and A7 are therefore the same command answering two different "
            "questions, which is why both are asked and why A0 has to be first."
        ),
    )

    wants = []
    for base in ("/usr/lib/systemd/system", "/etc/systemd/system"):
        root = pathlib.Path(base)
        if root.is_dir():
            wants += [str(p) for p in root.glob("*.wants/bunny-update-agent.timer")]
    record(
        "A8", "is the update timer enabled in the shipped image?",
        "no enablement symlink -- the timer exists but is wanted by no target",
        "symlinks found: %s" % (wants if wants else "none"),
        not wants,
    )

    # ------------------------------------------------------------- Part B
    print()
    print("=== B -- the trust store itself, exercised against the shipped code ===")

    loader = importlib.machinery.SourceFileLoader("shipped_agent", AGENT)
    spec = importlib.util.spec_from_loader("shipped_agent", loader)
    agent = importlib.util.module_from_spec(spec)
    loader.exec_module(agent)

    def verify(manifest):
        try:
            agent._verify_signature(manifest)
            return None
        except agent.UpdateError as exc:
            return exc.code

    code = verify({"keyId": "attacker-key", "signature": "AAAA"})
    record(
        "B1", "is a manifest naming an untrusted key refused?",
        "refused with unknown_key",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "unknown_key",
    )

    revocation_path = KEYDIR / "revoked-keys.json"
    original = revocation_path.read_text()
    revocation_path.write_text(
        json.dumps({"schemaVersion": 1, "revokedKeyIds": ["attacker-key"]})
    )
    code = verify({"keyId": "attacker-key", "signature": "AAAA"})
    record(
        "B2", "is a revoked key refused, and refused before the key lookup?",
        "refused with revoked_key, not unknown_key",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "revoked_key",
    )
    revocation_path.write_text(original)

    subprocess.run(
        ["/usr/bin/openssl", "genpkey", "-algorithm", "ed25519",
         "-out", "/tmp/p6-control.key"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["/usr/bin/openssl", "pkey", "-in", "/tmp/p6-control.key", "-pubout",
         "-out", str(KEYDIR / "p6-control.pem")],
        check=True, capture_output=True,
    )

    signed = {"keyId": "p6-control", "sequence": 1, "channel": "developer"}
    pathlib.Path("/tmp/p6-payload.bin").write_bytes(agent._canonical_payload(signed))
    subprocess.run(
        ["/usr/bin/openssl", "pkeyutl", "-sign", "-inkey", "/tmp/p6-control.key",
         "-rawin", "-in", "/tmp/p6-payload.bin", "-out", "/tmp/p6-payload.sig"],
        check=True, capture_output=True,
    )
    signed["signature"] = base64.b64encode(
        pathlib.Path("/tmp/p6-payload.sig").read_bytes()
    ).decode()

    code = verify(dict(signed))
    record(
        "B3", "NEGATIVE CONTROL -- is a correctly signed manifest accepted?",
        "accepted; no exception",
        "accepted" if code is None else "refused with %r" % code,
        code is None,
        detail=(
            "This is the check that gives B1 and B2 their meaning. If a manifest signed "
            "by an installed key were also refused, the refusals above would be evidence "
            "of a broken verifier, not of an empty trust store."
        ),
    )

    tampered = dict(signed)
    tampered["channel"] = "stable"
    code = verify(tampered)
    record(
        "B4", "is a signed manifest whose payload was altered refused?",
        "refused with bad_signature",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "bad_signature",
    )

    # ------------------------------------------------------------- Part C
    print()
    print("=== C -- are the two controls independent? ===")

    code, parsed, _ = run_agent("check")
    error = (parsed or {}).get("error", {})
    record(
        "C1", "with a VALID key now installed, does the disabled config still refuse?",
        "exit 2, not_configured -- configuration disablement is a separate control",
        "exit %s, code %r" % (code, error.get("code")),
        code == 2 and error.get("code") == "not_configured",
        detail=(
            "The control key from B3 is still in the trust store for this check. If the "
            "refusal came only from the empty store, this would now succeed."
        ),
    )

    CONFIG.write_text(json.dumps({
        "enabled": True,
        "channel": "developer",
        "manifestUrl": "https://updates.invalid.bunny-os.example/developer/x86_64/manifest.json",
        "imageRepositories": ["quay.io/comradeart/bunny-os"],
    }))
    code, parsed, _ = run_agent("check")
    error = (parsed or {}).get("error", {})
    record(
        "C2", "with updates ENABLED and no reachable source, does it fail closed?",
        "exit 2, download_failed -- it stops, it does not proceed",
        "exit %s, code %r" % (code, error.get("code")),
        code == 2 and error.get("code") == "download_failed",
    )

    # ------------------------------------------------------------- Part D
    print()
    print("=== D -- downgrade protection ===")

    agent.SEQUENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    agent.SEQUENCE_PATH.write_text("5\n")

    def validate(sequence, enforce_new):
        document = {
            "schemaVersion": 1, "sequence": sequence, "channel": "developer",
            "osVersion": "0.3.0", "imageVersion": "test", "architecture": "x86_64",
            "imageReference": "quay.io/comradeart/bunny-os",
            "imageDigest": "sha256:" + "0" * 64,
            "publishedAt": "2026-01-01T00:00:00Z",
            "expiresAt": "2099-01-01T00:00:00Z",
            "contractVersion": "1.0.0", "downloadSize": 1, "installedSize": 1,
            "keyId": "p6-control", "signature": "AAAA",
        }
        configuration = {
            "channel": "developer",
            "imageRepositories": ["quay.io/comradeart/bunny-os"],
        }
        try:
            agent._validate_manifest(document, configuration, enforce_new)
            return None
        except agent.UpdateError as exc:
            return exc.code

    code = validate(3, False)
    record(
        "D1", "is a manifest with a LOWER sequence than accepted refused?",
        "refused with rollback_attack",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "rollback_attack",
    )

    code = validate(5, True)
    record(
        "D2", "is a REPLAY of the accepted sequence refused when staging?",
        "refused with rollback_attack",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "rollback_attack",
    )

    code = validate(9, True)
    record(
        "D3", "does a higher sequence reach the signature check?",
        "refused with bad_signature -- the sequence check passes, authenticity does not",
        ("refused with %r" % code) if code else "ACCEPTED",
        code == "bad_signature",
        detail=(
            "Recorded because it locates where authentication happens. "
            "_verify_signature is the LAST call in _validate_manifest: every field "
            "above it was parsed and compared before the manifest was known to be "
            "authentic. Unreachable while updates are unsupported, and a design point "
            "an independent reviewer should be handed rather than left to find."
        ),
    )

    # ------------------------------------------------------------- summary
    print()
    summary = summarise(results)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("=== %d/%d as intended; %d required; result %s ===" % (
        summary["asIntended"], summary["checks"],
        summary["requiredChecks"], summary["result"],
    ))
    return 0 if summary["result"] == "AS_INTENDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
