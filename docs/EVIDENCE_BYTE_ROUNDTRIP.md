<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Byte-attested evidence must round-trip git exactly

## The property

`release/evidence.py` verifies an evidence record by hashing the file named in
its `evidenceReference` and comparing the result against the recorded
`contentDigest`:

```python
actual = file_digest(target)
if actual != record.contentDigest:
    reasons.append(f"evidence artifact digest mismatch: ...")
```

That check means something only if the bytes on disk are the bytes that were
committed. A checkout-time content filter changes them, so the same record
verifies on one machine and fails on another — and the failure looks like
tampering rather than configuration.

`.gitattributes` therefore disables filtering for every attested path with an
explicit `-text` rule.

## What was found

Seven files are attested by `contentDigest` in
`operations/data/release-evidence.json`. None of them had filtering disabled.

On a Windows checkout with `core.autocrlf=true`, **all seven** differed from
their committed bytes. Measured before the correction:

| Path | committed | working tree |
|---|---|---|
| `evidence/build/beta-archive-digest.txt` | `fad447d59eb6` | `e881e15c836e` |
| `evidence/build/beta-license-scan.log` | `2cebcb76248e` | `86a6704f53c2` |
| `evidence/vulnerability/beta-grype.json` | `df9c0b9b877d` | `8e819f23f600` |
| `operations/data/hardware-evidence.json` | `4836c6c7e9ba` | `73fe6d481320` |
| `operations/data/pilot-requirements.json` | `c71f56233500` | `d75ea0df7675` |
| `operations/data/qualification-matrices.json` | `04c09f845bc4` | `dcfe08e49c21` |
| `operations/data/signing-keys.json` | `1f5ee2ae8c6a` | `afe9dc9ab4ce` |

### One record had already been generated on such a checkout

The digest recorded for `operations/data/hardware-evidence.json` is
`73fe6d481320` — the **CRLF** value in the table above, not the committed one.

That record was measured on a Windows checkout. It verifies there and nowhere
else: on any Linux checkout the file hashes to `4836c6c7e9ba` and the record
reports a digest mismatch. The hazard was not theoretical, and the earlier
statement in `KNOWN_LIMITATIONS.md` that it had "not yet produced a wrong record"
was wrong.

`physical-hardware` is one of the fourteen candidate prerequisites, so this is
not an incidental record.

**The fix is to re-measure that evidence, not to recompute its digest.**
Re-hashing would bind the record to bytes it was never measured from, which is
precisely the substitution the digest check exists to catch. Until it is
re-measured the record is listed in `KNOWN_CRLF_BOUND_RECORDS` in
`tests/evidence/test_byte_roundtrip.py`, where a *new* occurrence fails the
suite.

## This does not make stale evidence current

Byte round-tripping and evidence freshness are independent properties, and
correcting the first does nothing for the second.

`operations/data/qualification-matrices.json` demonstrates the difference. After
this change its bytes round-trip exactly. Its recorded digest `bc6019c3b1ae`
still matches neither the committed bytes nor the CRLF bytes, because the file
was changed by `f314864` after the twenty records were measured at `80df25b`.
That record is **stale** and still blocks, exactly as PR #18 left it.

A file can round-trip perfectly and still carry a digest measured against an
older version of itself. The first is about the checkout; the second is about
time. `test_protection_does_not_make_stale_evidence_current` asserts this
distinction so it cannot quietly erode.

No evidence record was edited, re-digested or re-dated by this change, and no
committed byte moved — the blob hashes of all seven files are identical before
and after.

## Why the rules are listed one path at a time

`.gitattributes` names each attested file rather than using
`operations/data/** -text`.

The directory holds files that are not attested, and a blanket rule would claim
protection the evidence model does not require and cannot check. Listing paths
individually keeps the rule exactly as wide as the attestation, and means a newly
attested file needs a new line — which
`test_every_attested_file_has_content_filtering_disabled` enforces by failing
until it gets one.

## Applying this correction to an existing Windows checkout

Adding the rule does not rewrite files already in the working tree, and `git
restore` will skip files whose stat cache looks current. Force a real
re-checkout:

```bash
FILES="evidence/build/beta-archive-digest.txt ..."
rm -f $FILES
git restore --source=HEAD --worktree -- $FILES
git add --renormalize $FILES     # reconciles the index; produces no new blob
```

Then verify, which is what the test suite does:

```bash
python -m unittest discover -s tests/evidence -t .
```

## What this is not

It is not a qualification result. It changes no gate outcome, satisfies no
prerequisite, and moves nothing toward release. Stable release remains **NO-GO**
and pilots remain **BLOCKED**.

It stops the next measurement inheriting a defect that had already reached one
record.
