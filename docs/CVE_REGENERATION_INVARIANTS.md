# CVE record regeneration invariants

What may differ when `security/reachability/findings/` is regenerated from the
committed evidence, and why.

Verified by:

```text
python scripts/reachability.py verify-findings
```

which regenerates into a scratch directory, compares every field of every
record, classifies each difference, and exits 2 with a structured diff if any
difference is not excludable. Nothing is stripped before the comparison.

## The rule

A field must be classified before it may be excluded, and only two
classifications may be excluded. The classification is a decision recorded here,
not a pattern inferred at comparison time.

| Classification | May differ | Meaning |
| --- | --- | --- |
| Semantic evidence | **No** | What was measured, and what it means. |
| Commit identity | **No** | Which commit the record describes. |
| Environment metadata | **No** | Where the generator ran. A record that changes with the host is describing the host. |
| Generation metadata | **Yes** | A fact about the act of generating, which cannot affect a conclusion. |
| Unstable ordering | **Yes** | Same members, different order. Tolerated in comparison, canonicalised at generation, so it should not occur. |
| Bug | **No** | A type changed, or a field appeared or vanished. |

The excludable set is enumerated in `release/regeneration.py`:

```python
GENERATION_METADATA_FIELDS = frozenset({"generatedAt"})
```

Adding a field to that set is a change to what this repository claims its
evidence proves. It requires an entry in the table below.

## Fields permitted to differ

### `generatedAt`

**Classification:** Generation metadata.

The wall-clock at which the generator ran, in every per-advisory record and in
`index.json`.

* *Cannot affect the conclusion.* Every value in the record is derived from
  `operations/data/vulnerability-disposition.json`,
  `evidence/vulnerability/beta-grype.json`, the `evidence/reachability/*` fact
  files and the tree at the candidate commit. None of those is read as of a
  time, and no field is computed from the current date.
* *The raw generated record remains available.* `verify-findings` writes the
  full comparison, including every `generatedAt` pair, to
  `build/out/qualification/reachability-regeneration.json`. The value is not
  deleted from the record and not deleted from the diff; it is classified.
* *Covered by a regression test.*
  `tests/portability/test_cve_regeneration.py::AllowedGenerationDifferenceTests`.

No other field is permitted to differ.

## Fields that were differing, and what was actually wrong

The failing CI step reported only `CVE-2020-27815.json does not regenerate from
committed evidence`. All 25 records differed. Classified:

| Field path | Classification | Disposition |
| --- | --- | --- |
| `generatedAt` | Generation metadata | Excluded, documented above. |
| `sourceCommit` | Commit identity | **Fixed at the cause.** Not excluded. |
| `desktopActivationEvidence[0]` | Commit identity inside a semantic string | **Fixed at the cause.** Not excluded. |

### `sourceCommit`

`scripts/reachability.py` resolved the commit as `git rev-parse HEAD`. The
records were generated while `HEAD` was `80df25b` and were then committed, which
moved `HEAD` to `9dc7e33`. Committing the evidence invalidated it, and no
regeneration could ever have matched.

The generator now resolves the commit through `candidateCommit` — the commit the
scanned image was built from, declared in
`operations/data/release-evidence.json` — using
`release.commits.resolve_commit_context`. The field stays in the comparison, so a
record naming the wrong commit still fails.

The declared candidate is `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`. That is
deliberately behind `HEAD`: it is the commit whose built image produced
`evidence/vulnerability/beta-grype.json`. Rebinding these records to a later
commit would claim a scan was performed against a tree that was never scanned.

### `desktopActivationEvidence[0]`

The string reads:

```text
grep '^Exec=.*(podman|skopeo|bootc|toolbox|docker)' over every shipped .desktop
at 79bb99ddb39d: no match
```

The measurement — `no match` — was identical in both versions. Only the embedded
short commit moved, for the same reason `sourceCommit` did.

Two things were wrong, and both are fixed:

1. The commit was `HEAD`, so the string moved on every commit.
2. The grep ran over the **working directory** while the string claimed to
   describe the **candidate commit**. If the tree had changed since the
   candidate, the record would have stated a measurement it had not performed.

`_tracked_desktop_entries` now reads the entries out of the candidate commit with
`git ls-tree` and `git show`, so the record describes the tree it names. This
requires the candidate commit to be present: a shallow clone fails closed with a
message naming the cause rather than silently measuring the wrong tree. CI jobs
that regenerate findings therefore check out with `fetch-depth: 0`.

Paths come from git and are POSIX-form, so the evidence string is identical on a
Windows development host and an Ubuntu runner. Previously it was built from
`Path.relative_to` and would have contained backslashes on Windows — a
cross-platform determinism defect that had not yet bitten only because the hit
list is empty.

## Ordering

Every collection in a record is canonicalised at generation:

| Field | Canonical form |
| --- | --- |
| JSON object keys | `json.dumps(..., sort_keys=True)` in `write_json` |
| `carrierObjects` | sorted at collection in `carrier_locations` |
| `desktopActivationEvidence` | `sorted(hits)`, from a sorted `git ls-tree` |
| `advisories` | `sorted(written)` |
| `distinctCarrierObjects` | `sorted(...)` |
| `candidateCarriers` | fixed tuple `CANDIDATE_CARRIERS` |
| `checks`, `systemdUnits`, `commandInvocationPaths` | fixed literal order |

The comparison additionally treats a list whose members match as
`Unstable ordering` rather than a semantic difference, so a future collection
that is genuinely a set does not fail the check while it is being canonicalised.
Both halves are needed: canonicalisation stops it happening, tolerance stops it
being reported as a changed measurement.

## What the check refuses

`tests/portability/test_cve_regeneration.py` holds each of these:

| Change | Result |
| --- | --- |
| `generatedAt` differs | passes — the only permitted difference |
| `carrierObjects` changed | **fails**, classified Semantic evidence |
| `packageName` changed | **fails**, classified Semantic evidence |
| `advisoryId` changed | **fails**, classified Semantic evidence |
| `conclusion` changed | **fails**, classified Semantic evidence |
| `sourceCommit` changed | **fails**, classified Commit identity |
| a field removed | **fails**, classified Bug |
| a field's type changed | **fails**, classified Bug |
| object keys reordered | passes — `sort_keys` makes this unobservable |
| list members reordered | passes, reported as Unstable ordering |
| a nested value changed | **fails** — the walk is recursive, not top-level |

## Failure output

The step no longer reports `does not regenerate`. It reports, per difference:

```text
security/reachability/findings/GHSA-5cgq-3rg8-m6cv.json
  field path:   conclusion
  committed:    Present but unreachable
  regenerated:  Unknown
  classification: Semantic evidence  (BLOCKING)
```

and writes the whole comparison to
`build/out/qualification/reachability-regeneration.json`.
