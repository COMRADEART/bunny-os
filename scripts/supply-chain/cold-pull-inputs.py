#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prove the retained inputs are obtainable without this repository's credentials.

The retention policy's claim is not "we can fetch our inputs". It is that *an
independent party* can, by digest, without access to this repository. A pull
that succeeds because the puller happens to be us establishes availability to
us, which is a strictly weaker statement and not the one being made.

So this fetches every published input by digest with every credential removed —
no auth file entries, no ``GITHUB_TOKEN``, no host registry configuration — and
compares what comes back against the digest the lock names. It writes nothing
into the retention directory and pulls no blobs: the manifest is enough, because
the manifest digest *is* the identity being pinned.

It is deliberately separate from ``hydrate-retained-inputs.py``. Hydration has
to succeed for the build to happen at all and may legitimately use a credential;
this has to succeed for the *claim* to hold. Running them as one step would mean
a credentialed fallback silently satisfied both.

Exit codes:
    0   every input resolved anonymously and its digest matched
    2   an input could not be resolved, or a digest disagreed
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


def references(publication: dict[str, Any]) -> list[tuple[str, str]]:
    """Every published input and its digest-pinned reference."""
    inputs = publication.get("inputs")
    if not isinstance(inputs, dict):
        raise SystemExit("BLOCKED: the publication lock has no inputs object")
    found: list[tuple[str, str]] = []
    for name in sorted(inputs):
        entry = inputs[name]
        if not isinstance(entry, dict):
            continue
        reference = entry.get("digestReference")
        if isinstance(reference, str) and "@sha256:" in reference:
            found.append((name, reference))
    if not found:
        raise SystemExit("BLOCKED: no digest-pinned references in the publication lock")
    return found


def inspect_anonymously(reference: str, authfile: str, timeout: float) -> tuple[bool, str, str]:
    """Fetch a manifest with no credential. Returns (ok, digest, detail)."""
    environment = dict(os.environ)
    # Belt and braces: the caller is expected to have stripped these, and this
    # makes the guarantee a property of the program rather than of the caller.
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "DOCKER_CONFIG", "XDG_CONFIG_HOME"):
        environment.pop(name, None)
    environment["REGISTRY_AUTH_FILE"] = authfile

    try:
        completed = subprocess.run(
            [
                "skopeo", "inspect", "--raw", "--tls-verify=true",
                "--authfile", authfile, f"docker://{reference}",
            ],
            capture_output=True, text=True, check=False,
            timeout=timeout, env=environment,
        )
    except subprocess.TimeoutExpired:
        return False, "", f"the anonymous fetch did not return inside {timeout:.0f}s"
    except FileNotFoundError:
        return False, "", "skopeo is not installed"

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        return False, "", detail[-1][:240] if detail else "skopeo failed with no diagnostic"

    digest = "sha256:" + hashlib.sha256(completed.stdout.encode()).hexdigest()
    return True, digest, f"{len(completed.stdout)} byte manifest"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--publication", required=True, type=Path)
    parser.add_argument("--authfile", required=True,
                        help="an EMPTY containers auth file; its emptiness is asserted")
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    arguments = parser.parse_args()

    try:
        publication = json.loads(arguments.publication.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: {arguments.publication} could not be read: {exc}", file=sys.stderr)
        return 2

    # An auth file with entries would make "anonymous" a claim about a file
    # nobody checked.
    try:
        auth = json.loads(Path(arguments.authfile).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"BLOCKED: the auth file {arguments.authfile} is unreadable: {exc}", file=sys.stderr)
        return 2
    if auth.get("auths"):
        print(
            f"BLOCKED: {arguments.authfile} carries credentials, so nothing this run "
            "does would be an anonymous pull",
            file=sys.stderr,
        )
        return 2

    results: list[dict[str, Any]] = []
    for name, reference in references(publication):
        expected = reference.split("@", 1)[1]
        ok, digest, detail = inspect_anonymously(reference, arguments.authfile, arguments.timeout)
        if ok and digest != expected:
            ok = False
            detail = f"DIGEST MISMATCH: lock names {expected}, registry returned {digest}"
        results.append({
            "input": name,
            "reference": reference,
            "expectedDigest": expected,
            "observedDigest": digest or None,
            "ok": ok,
            "detail": detail,
        })
        print(f"  [{'OK  ' if ok else 'FAIL'}] {name}: {detail}")

    passed = all(item["ok"] for item in results)
    document = {
        "schemaVersion": 1,
        "claim": "anonymous-cold-pull-by-digest",
        "isolation": {
            "emptyAuthFile": True,
            "githubTokenRemoved": True,
            "dockerConfigRemoved": True,
            "tlsVerify": True,
        },
        "results": results,
        "inputsChecked": len(results),
        "allReachable": passed,
        "note": (
            "Manifests only. The manifest digest is the identity the lock pins, so "
            "resolving it anonymously is the whole claim; pulling blobs would prove "
            "nothing further and would cost the runner its disk."
        ),
    }
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(f"\n{len(results)} input(s) checked anonymously; allReachable={passed}")
    print(f"wrote {arguments.report}")

    if not passed:
        print(
            "BLOCKED: at least one retained input could not be obtained without a "
            "credential. The retention claim is that an independent party can fetch "
            "these; this run establishes that they cannot.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
