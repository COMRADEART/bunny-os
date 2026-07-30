# Public beta go/no-go

## Recommendation: NO-GO

- Date: 2026-07-29
- Proposed beta version: none
- Beta artifacts: none published
- Participants: zero
- Observation period: none started

## Why

A public beta distributes software to real people and asks them to run it on their own machines. That creates obligations the project cannot currently meet.

| Precondition | State |
|---|---|
| A published, signed beta artifact | none; `build/keys/` holds no release key and no candidate has been signed |
| A verified download path | `docs/VERIFY_DOWNLOAD.md` describes one; there is nothing to download |
| Independently bootable recovery media | never built or booted |
| A vulnerability position | the last scan reported 59 fixable findings, 8 Critical and 28 High, unwaived |
| An installer that can install | no reviewed Anaconda adapter exists; `bunny-installer-backend` exits 78 |
| A support commitment | `docs/SUPPORT_POLICY.md` declares no beta end date |
| An incident process for real users | defined in `SECURITY_POLICY.md`; never operated |
| Capacity to respond | one maintainer, no rota |

The installer point is decisive on its own. A beta whose installer cannot perform an installation is not a beta.

## What is genuinely ready

The privacy-safe intake path. Feedback ingestion redacts before storage, crash reports are limited to seven approved fields with no persistent user identifier, and the redactor has regression tests. If a beta ran tomorrow, participant data would be handled correctly.

That is necessary and nowhere near sufficient.

## What would change this

In order:

1. A working installer path, or an explicit decision that the beta ships as a pre-installed image only.
2. A resolved vulnerability position, or a reviewed waiver for each remaining finding.
3. A signed beta artifact with published checksums and a verified download path.
4. Independently bootable recovery media.
5. A declared beta support window and an owner for incident response.

## Authority

This recommendation is a project decision, not an automated one. `make gate-phase-4` checks that the Phase 4 documents exist; it does not and cannot decide whether a beta should run. That decision belongs to a person, and no person has taken it.
