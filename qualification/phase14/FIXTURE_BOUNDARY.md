<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# The Fixture Boundary (Track J)

Every demonstration in this phase runs on `TEST_FIXTURE_ONLY` material.
The boundary that keeps that material away from real evidence is
structural, layered, and executed on every run — never a naming
convention, never a promise.

## The markers

A Phase 14 fixture file carries **all three** markers — `fixtureClass:
"TEST_FIXTURE_ONLY"`, `"fixture": true`, `"test_fixture_only": true` —
and `verify` refuses a fixture with fewer. Consumption is the inverse:
**any one** marker makes a record a fixture everywhere it is read
(`is_fixture`, identical to Phase 13's rule), so a partially stripped
fixture is still refused.

## The walls, from outside in

1. **The router**: a fixture derives `TEST_FIXTURE_ONLY` before
   anything else is examined, and routes nowhere.
2. **The Phase 9 boundary**: `register` rejects a record declaring the
   marker — structurally, whatever the filename — and the credential
   scan runs before a byte is ingested. Executed against the real
   registration code in scratch trees on every suite run.
3. **The Phase 13 registries**: `append_record` refuses fixtures;
   committed governance registries may not hold a marked record; sealed
   records cannot be edited into or out of fixture-hood without
   breaking their seal (`IMMUTABILITY FAIL`).
4. **The derivations**: Phase 10 applicability, Phase 11/12 register
   derivation, Phase 13 status derivation, and the Phase 14 assembler
   each refuse fixture-marked inputs independently.
5. **The byte comparison**: every rehearsal snapshots all eighteen real
   immutable inputs (ledger, decision record, graph, baseline, both
   registers, the Phase 12 policy, the Phase 13 status, blocking, and
   all nine governance registries) and refuses a single changed byte.
   This is deliberately not an emptiness assertion — the guarantee
   survives the day real evidence arrives.

## What the fixtures wrap

The scratch registrations use the **inner** records
(`fixture["record"]`), which carry no markers — exactly what a real
submitter would send. The wrapper with the markers never travels. This
is what lets the rehearsals prove the *real* intake behavior (a clean
inner record is genuinely ACCEPTED in a scratch tree) while the marked
wrapper is genuinely REJECTED at the same boundary — both directions
executed, every run.

## Scratch universes

A rehearsal universe is a temporary directory holding its own intake
tree and ledger, seeded with the real subject-artifact identity
(read-only) and zero entries. It is deleted after each scenario. No
scratch path, digest, or artifact appears in any derived output except
`MATRIX.json`'s deterministic scenario rows, which contain no paths at
all.
