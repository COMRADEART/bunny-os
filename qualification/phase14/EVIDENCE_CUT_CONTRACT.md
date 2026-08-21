<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The Evidence Cut Contract (Track B)

A release decision operates against a **sealed evidence cut**: a
deterministic identification of everything the decision may rely on.
`build_evidence_cut` produces it; the seal is the Phase 9/13 algorithm
(sha256 over canonical JSON minus the seal), so a cut is a sealed
record like every other.

## What a cut identifies

- the subject artifact (identifier plus all five digests);
- the ledger identity (`ledgerSha256`, entry count) and every intake ID
  it contains, with the gate-eligible accepted subset listed;
- the artifact-graph bytes (`graphSha256`);
- the Phase 11 and Phase 12 register bytes;
- every policy version, authority record, risk acceptance, and
  authorization — each by identifier, seal, and its **state at this
  cut** (STANDING / EXPIRED / REVOKED, derived);
- the revocation and resolution identifiers;
- the operator-stated `asOf` evaluation date and its time basis (no
  clock is ever read — the commit is the tamper-evident time);
- the seal over all of it.

## The rules

1. **Reproducible.** The same immutable inputs derive byte-identical
   cuts and byte-identical decisions (PH14-B1). There is nothing
   nondeterministic to hide in.
2. **Post-cut evidence is detected, never absorbed.**
   `compare_cut_to_ledger` names every intake ID that arrived after the
   cut (PH14-B2). The decision sealed over the cut stands as recorded.
3. **A later decision supersedes; it never rewrites.**
   `supersede_assembly` produces a new record pointing at the earlier
   cut's seal; the earlier assembly stays byte-identical, and
   superseding the *same* cut refuses — a rerun is a reproduction, not
   a supersession (PH14-B8).
4. **Expiring records make `--as-of` mandatory.** The moment any input
   record carries `expires_at`, a cut without an operator-stated
   evaluation date refuses to exist (PH14-B7). This is the Phase 13
   rule, extended from the status derivation to the cut itself.
5. **Expired records contribute no favorable authority after expiry.**
   An assignment, acceptance, or authorization standing at cut A and
   expired at cut B is `EXPIRED` in cut B's rows and confers nothing
   there (PH14-B5, PH14-G8, PH14-I1, PH14-I2). The record itself is
   never edited; what changes is the evaluation, per cut.
6. **Revocation after a cut does not rewrite the cut.** A revocation
   recorded after cut A leaves cut A's decision re-derivable exactly as
   sealed; every later cut observes the revocation and derives
   `REVOKED` (PH14-B6, PH14-H9).

## Relation to Phase 13's `evidence_cut`

A Phase 13 authorization record carries a minimal cut
(`ledgerSha256`, `ledgerEntries`, `intakeIds`); Phase 13 validation
refuses a record whose cut names different ledger bytes than presented.
The Phase 14 cut is a superset built for the assembly layer; it changes
nothing about the Phase 13 record contract and is validated by the same
seal discipline.
