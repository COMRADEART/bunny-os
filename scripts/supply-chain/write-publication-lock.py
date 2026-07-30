#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 ComradeArt
# SPDX-License-Identifier: GPL-3.0-or-later
"""Record where a retained input was published, and under what retention terms.

A published input that a repository cleanup policy can delete is not retained;
it is retained until somebody tidies up. So the lock records the retention
configuration and the deletion protection alongside the digest, and a field
nobody can answer is written as ``unverified`` with the reason rather than left
out — an absent field reads as "fine" and an ``unverified`` one does not.

The blob inventory is recorded because a manifest digest only pins the manifest.
A registry that served the manifest and lost a layer would satisfy a digest
check and fail a pull, and the cold-pull verification needs a list to check
against.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

REFUSED = 2

#: What each published input is for, so the lock says why it is being kept
#: rather than only that it is.
PURPOSE = {
    "base": (
        "the retained fedora-bootc base every qualification build starts from. Upstream rebuilds "
        "this tag daily and old digests stop resolving — measured: the Phase 6 digest fb71f099 "
        "returns 'manifest unknown' — so a build that could only pull it from upstream would stop "
        "being reproducible on upstream's schedule."
    ),
    "builder": (
        "the pinned builder image. Both builders must present this digest; the hosts may differ "
        "in every other respect, which is what makes them independent."
    ),
    "snapshot": (
        "the 474 signed RPMs, their repodata, the Fedora keys that verify them and the signed "
        "snapshot manifest. Without it a second builder resolves packages from a live repository "
        "and gets whatever Fedora ships that day."
    ),
}


def blob_inventory(reference: str) -> dict[str, Any]:
    """Every blob the published manifest references, from the registry itself."""
    result = subprocess.run(
        ["skopeo", "inspect", "--no-tags", "--raw", f"docker://{reference}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {"error": result.stderr.strip()[:400]}
    manifest = json.loads(result.stdout)
    layers = manifest.get("layers") or []
    config = manifest.get("config") or {}
    return {
        "mediaType": manifest.get("mediaType"),
        "configDigest": config.get("digest"),
        "configSize": config.get("size"),
        "layerCount": len(layers),
        "layers": [
            {"digest": layer.get("digest"), "size": layer.get("size"),
             "mediaType": layer.get("mediaType")}
            for layer in layers
        ],
        "totalBytes": int(config.get("size", 0)) + sum(int(l.get("size", 0)) for l in layers),
    }


def main() -> int:
    parser = argparse.ArgumentParser(prog="write-publication-lock")
    parser.add_argument("--kind", required=True, choices=("base", "builder", "snapshot"))
    parser.add_argument("--registry", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--pushed-digest", required=True)
    parser.add_argument("--locked-digest", required=True)
    parser.add_argument("--source-layout", required=True)
    parser.add_argument("--publisher", default="")
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()

    # Passed in rather than asked for. The publisher is whoever the token
    # resolves to, the pushing script has already established that, and `gh` is
    # not necessarily present on the machine that runs the push.
    publisher = args.publisher or "unrecorded"

    entry: dict[str, Any] = {
        "kind": args.kind,
        "purpose": PURPOSE[args.kind],
        "registryRepository": args.registry,
        "humanReadableTag": args.tag,
        "digest": args.pushed_digest,
        "digestReference": f"{args.registry}@{args.pushed_digest}",
        "tagReference": f"{args.registry}:{args.tag}",
        "lockedDigest": args.locked_digest,
        # For the base and the builder, the locked digest and the pushed digest
        # describe the same manifest and must be equal — the push is refused
        # otherwise.
        #
        # For the snapshot they describe different things. The snapshot lock's
        # manifestDigest is the digest of the *signed snapshot manifest*, which
        # is content inside the artifact; the pushed digest is the OCI wrapper
        # built around it. Comparing them would be comparing a document to the
        # envelope it was posted in, and reporting `false` would read as a
        # corrupted push. Recorded as not applicable, with both values kept.
        "digestMatchesLock": (
            None if args.kind == "snapshot" else args.pushed_digest == args.locked_digest
        ),
        "digestComparison": (
            "not-applicable: lockedDigest is the signed snapshot manifest's digest and digest is "
            "the OCI wrapper's; they describe different bytes by design. The snapshot manifest is "
            "verified from its own content by the cold-pull verification."
            if args.kind == "snapshot"
            else "equal: the registry returned the manifest digest that was retained and locked"
        ),
        "sourceLayout": args.source_layout,
        "publicationAccount": publisher,
        "blobInventory": blob_inventory(f"{args.registry}@{args.pushed_digest}"),
        # Recorded as claims about configuration that has to be checked against
        # the registry rather than asserted here. `unverified` is the honest
        # value until something reads the package settings back.
        "retention": {
            "expectedRetentionPeriod": "indefinite while any qualification evidence references it",
            "deletionProtection": "unverified",
            "deletionProtectionNote": (
                "GitHub package retention and deletion are repository settings, not properties of "
                "a push. This field stays 'unverified' until the settings are read back and "
                "recorded; an untagged-version cleanup policy can delete a digest silently, which "
                "would break every build pinned to it."
            ),
            "backupLocation": args.source_layout,
            "backupNote": (
                "The local retention store is the backup and is on one machine. It is a copy, not "
                "a second independent location, and it does not by itself satisfy independent "
                "availability."
            ),
            "recoveryProcess": (
                "Re-push from the retained OCI layout with scripts/supply-chain/"
                "publish-retained-inputs.sh; the digest is preserved by --preserve-digests and is "
                "checked against the lock, so a recovered publication is the same artifact or it "
                "fails."
            ),
            "accessPolicy": "unverified",
            "accessPolicyNote": (
                "Package visibility is a repository setting. Until it is read back, whether an "
                "independent builder can pull without a credential is not established — and the "
                "cold-pull verification is what actually answers it."
            ),
        },
        "note": (
            "The digest is the pin. The tag is a convenience reference; qualification builds must "
            "use the digest, because a tag is a promise about a channel and not about content."
        ),
    }

    lock: dict[str, Any] = {"schemaVersion": 1, "inputs": {}}
    if args.lock.is_file():
        try:
            lock = json.loads(args.lock.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    lock.setdefault("inputs", {})[args.kind] = entry
    lock["schemaVersion"] = 1
    lock["published"] = sorted(lock["inputs"])
    lock["complete"] = sorted(lock["inputs"]) == ["base", "builder", "snapshot"]
    lock["completenessNote"] = (
        "All three inputs must be published before an independent builder can build without "
        "reaching a live repository. Two of three establishes nothing: the missing one is the one "
        "that decides."
    )

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    args.lock.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )

    inventory = entry["blobInventory"]
    print(f"    recorded {args.kind}: {entry['digestReference']}")
    if "error" not in inventory:
        print(f"    {inventory['layerCount']} layers, {inventory['totalBytes']} bytes")
    print(f"    published so far: {', '.join(lock['published'])}")
    if not lock["complete"]:
        missing = sorted({"base", "builder", "snapshot"} - set(lock["published"]))
        print(f"    still unpublished: {', '.join(missing)}")
    print(f"    wrote {args.lock}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            raise SystemExit(REFUSED) from None
        raise
