<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Evidence cut protocol — the operator workflow

Phase 14 defined the sealed evidence cut (`EVIDENCE_CUT_CONTRACT.md`);
Phase 15 makes cutting one an operator action over the real universe:

```text
python qualification/phase15/security-review-execution/tools/review_execution_ops.py \
    cut --label CUT-NNN [--as-of YYYY-MM-DD]
```

## What a cut contains

Exactly what the Phase 14 contract defines, unchanged: candidate
identity and all five digests; the ledger sha256, entry count, and
ordered intake identifiers; the gate-eligible accepted subset (which is
the revision/supersession resolution — a superseded entry is not
gate-eligible-effective); the artifact-graph and register shas (the
applicable artifact relationships and reconciliation outputs by
digest); every policy version, authority record, risk acceptance, and
authorization by identifier, seal, and derived per-cut state (the
authority status and expiry evaluation); the operator-stated `asOf` and
its time basis; and the seal over all of it (sha256 over canonical JSON
minus the seal — the Phase 9/13 algorithm).

The cut timestamp is **explicit input**: `--as-of` is stated by the
operator, recorded verbatim, and mandatory the moment any input record
carries `expires_at`. No clock is read anywhere; the commit is the
tamper-evident time.

## The rules, operationally

1. **Reproducible.** The same immutable inputs and the same explicit
   boundary derive a byte-identical cut. Proven by the guard suite:
   `same inputs + same as-of → equal JSON`, on both validation targets.
2. **Append-only.** A cut lands as `cuts/CUT-NNN.json` and an existing
   label refuses — a rerun is a reproduction, not a new cut. No command
   edits a committed cut; `verify` checks every committed seal.
3. **Post-cut evidence is named, never absorbed.**
   `compare_cut_to_ledger` lists every intake ID that arrived after the
   cut. The historical cut re-derives exactly as sealed from its own
   inputs; the later evidence belongs to a later cut.
4. **Supersession points, never rewrites.** A later assembly
   supersedes an earlier one by carrying the earlier cut's seal
   (`supersede_assembly`); superseding the same cut refuses.
5. **Expiry and revocation are evaluated per cut.** A record standing
   at cut A and expired at cut B is EXPIRED in cut B's rows; a
   revocation recorded after cut A leaves cut A re-derivable as sealed
   and makes every later cut derive REVOKED. Nothing is edited in
   either direction.

## What is committed here

`cuts/CUT-001.json` is the first real cut: the zero-evidence state of
the real universe at the Phase 15 boundary, sealed. It contains no
evidence — it *identifies* the absence: zero intake IDs, the empty
ledger's sha256, no policy versions, no authority records. When the
first real submission arrives, `compare_cut_to_ledger` against CUT-001
names it as post-cut, and the next cut includes it. That is the
designed shape of history: each cut says exactly what was available at
its boundary, forever.
