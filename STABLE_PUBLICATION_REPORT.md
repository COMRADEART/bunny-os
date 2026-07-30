# Stable publication report

## Result: no stable release has been published

- Date: 2026-07-29
- Stable version: **none**
- Release candidate: **none**
- Publication date: **none**
- Git tag: **none**; `release/stable` was never created

## Why this document exists

`STABLE_PUBLICATION_REPORT.md` was absent, so the Phase 6 and Phase 7 preflights failed on a missing file. A missing file and an unpublished release look identical to a gate but are very different problems, and only one of them is honest. This records the second.

## What publication would require

Every row is a precondition, and every row is unmet.

| Requirement | State |
|---|---|
| A stable candidate manifest at `build/out/stable-rc/STABLE-CANDIDATE.json` | absent |
| Twelve signed artifacts, all checksummed | none produced |
| A production signing key from a key ceremony | no key, no ceremony |
| Reproducibility evidence from two independent builders | same-host determinism only |
| Nine protected human approvals | all nine PENDING |
| Zero blocker codes | five set |
| 25 evidence rows at PASS | 3 at PASS |
| A resolved vulnerability position | 8 Critical, 28 High, unwaived |
| A declared support window | `docs/SUPPORT_POLICY.md` promises no duration |
| Published release notes, known issues and third-party notices | notices exist; release-specific notes do not |
| A mirror and download page | none |
| Independently bootable recovery media | never built or booted |

## What publication side effects occurred

None. No branch was created, no tag was pushed, no artifact was uploaded, no announcement was made, no update channel was promoted, and no registry received an image.

This is worth stating explicitly because a report titled "publication report" could otherwise be read as describing one.

## The gate behaved correctly

`make gate-stable-release` inherits `gate-stable-candidate`, which requires the candidate manifest. That file does not exist, so the gate stops before it can evaluate anything else. When the manifest is supplied, `operations/qualification.py` then requires all 25 rows at PASS, all nine approvals literally APPROVED, and an empty blocker list, with no waiver mechanism anywhere in the evaluator.

The gate is not what is blocking publication. The absence of a release is.

## Development track

A separate, clearly-labelled development qualification track now exists and records what has genuinely been produced: real images built under Podman and image-builder, real QEMU/KVM boots reaching health markers, real SBOM and vulnerability scans. See `operations/data/dev-qualification.json` and `make gate-dev-qualification`.

Development evidence never promotes to production evidence. Physical hardware, a production key ceremony, independent review and nine human approvals cannot be produced by running more tests, and the development evaluator refuses rows that claim otherwise.

## Recommendation

Do not publish. Close the blockers in the order given in `NEXT_PHASE.md`, beginning with the vulnerability position, because every other artifact would inherit it.
