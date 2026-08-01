<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Update fixture report

Date: 2026-08-01
Status: **PARTIAL — signed-metadata battery passed against the real update agent; N/N+1 image pair and staged deployment execution PENDING EXECUTION**

## Result

```text
Signed-metadata battery       ran 2026-08-01 against the real update agent:
                              bunny_update_agent._validate_manifest, with its
                              own _canonical_payload and openssl Ed25519
                              verification; trust store reassigned to a
                              tempdir

valid dev-signed manifest     ACCEPTED
unknown_key                   REJECTED — unregistered key
bad_signature                 REJECTED — rogue key forging a trusted keyId
bad_signature                 REJECTED — flipped osVersion
bad_signature                 REJECTED — swapped imageDigest
invalid_document              REJECTED — truncated bytes
invalid_manifest              REJECTED — missing signature
expired_manifest              REJECTED — past expiresAt

N/N+1 image pair              PENDING EXECUTION
deployment staging/rollback   PENDING EXECUTION — update_rollback_offline.py
                              exists; its run is not yet evidence
```

Every rejection class fired, and the one manifest that should pass, passed.
The battery exercised the production validation code, not a reimplementation:
the agent's own canonicalisation and its openssl Ed25519 verification, with
only the trust store location reassigned to a temporary directory. All keys
were development keys, minted at runtime, never present in the repository.

## Method

The battery is
`qualification/installed-system/scripts/update_manifest_tests.py`, run
against `bunny_update_agent._validate_manifest`. Forged manifests were signed
with a rogue runtime-minted key claiming a trusted keyId; tampered manifests
flipped `osVersion` or swapped `imageDigest` under a valid signature over the
original payload; the malformed cases truncated the document bytes or dropped
the signature; the expiry case set `expiresAt` in the past.

The offline staged-deployment executor,
`qualification/installed-system/scripts/update_rollback_offline.py`, exists
but has not run in this pass. A script that exists is not evidence, and no
line below pretends otherwise.

## The N+1 policy

N+1 is a real commit with its own archive target and its own reproducibility
qualification — not a synthetic variant. The N/N+1 difference is a version
marker in `schemas/`, which lands in `/usr/share/bunny-os/schemas` on the
installed system. The fixture's rerun level is the local repeatability gate,
with the reasoning recorded: the update fixture consumes the archive, and the
archive's cross-builder properties are already established at the archive
stage for the mechanism the fixture exercises.

## What this establishes, and what it does not

**Established.** The update agent's manifest validation refuses every
tampering class the battery encodes — unknown keys, forged key identities,
payload tampering under both flipped version and swapped digest, truncation,
missing signatures and expiry — and accepts a correctly dev-signed manifest.
The validation exercised is the agent's own code path.

**Not established.** That an update applies. The N/N+1 image pair has not
been built, no deployment has been staged, no rollback has been executed, and
`update_rollback_offline.py` has produced no evidence. Signing remains
development-only; nothing here touches production signing. Metadata
validation passing is a prerequisite of the update matrix, not the matrix.

## Where the evidence lives

```text
qualification/installed-system/scripts/update_manifest_tests.py
                                          the battery
qualification/installed-system/scripts/update_rollback_offline.py
                                          the offline executor — present,
                                          not yet run
qualification/installed-system/evidence-context.json
                                          binds evidence to Commit E
                                          (d496e7760316219932c1f8f542061a9d3bfbe789)
```

## Gate position

```text
Update metadata validation   PASS — signed-metadata battery, dev keys only
Update matrix                PENDING EXECUTION — N/N+1 pair and staged
                             deployment owed
Rollback matrix              PENDING EXECUTION
Installation matrix          rows move only through
                             qualification/installed-system/scripts/
                             import_matrix_results.py
Qualification candidate      still BLOCKED
Stable release               NO-GO, unchanged
```

This report moves the metadata-validation line and no other. The update and
rollback matrices move when the N/N+1 pair exists and the executor's run
becomes evidence.
