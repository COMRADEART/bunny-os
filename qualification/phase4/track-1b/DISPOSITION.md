# Track 1b — Retained-input package publication

**Disposition: PASS — published 2026-08-17.**

Supersedes `qualification/phase3/track-1b/DISPOSITION.md`, which recorded
**NOT_RUN — AUTHENTICATION BLOCKED**. That record stands as written; this is
the run it asked for.

## What changed

Phase 3 refused two credential paths because each moved a live credential
across an environment boundary. The path taken here is the one that
disposition itself named as the remaining requirement: the token is resolved
**inside the builder** by the operator's own `gh` through WSL interop, so the
credential is used where it lives. It was written to a root-only file
(`umask 077`), read once by the publishing unit, deleted by that unit before
anything else ran, and removed from the builder again after the run. No token
value appears in this directory — checked, not assumed.

## The blocker that replaced it

The first four attempts failed on `HTTP 503` from `api.github.com`, for
roughly three hours. This is recorded because it is the difference between
"the token cannot publish" and "the service was down": the run that
eventually succeeded used the same token as the first that failed. The
publishing unit polls every five minutes and refuses to proceed until the
API answers `200`, so a publication is never attempted against an API that
cannot be read back from.

## What was published

All three retained inputs, each pushed by digest and verified by reading the
manifest back from the registry:

| Kind | Reference |
| --- | --- |
| Base image | `ghcr.io/comradeart/bunny-os-base@sha256:1f08084a9a8545bd528641d4fda14e18408dfb1298acda243eaf583cd907a844` |
| Builder image | `ghcr.io/comradeart/bunny-os-builder@sha256:bf9f00d81c5d707830676193041862dbb5bccc88c18a000cdb674311917d1f3e` |
| Package snapshot | `ghcr.io/comradeart/bunny-os-package-snapshot@sha256:648636edf40e290be0425984370837859b1eaa1b5d9a56a6cd01623e4aed7195` |

For the base and the builder the script refuses the push unless the digest
the registry returns equals the retained one, and both matched. The snapshot
is a directory published as a single-layer OCI image, so its **signed
content** digest (`fa89f5e28175abf037acb0e83a5a7fa2868b415db12732c2afff98017fb70ada`)
and the **OCI wrapper** digest above are recorded separately rather than
compared — conflating them would either fail always or check nothing.

Records: `publication.log` (the full run) and `input-publication-lock.json`
(the lock the run wrote).

## What this does and does not establish

It establishes that the retained build inputs are no longer on one machine:
a second builder can now pull them by digest. It does **not** by itself
establish that a build from the published inputs reproduces — that is the
cold-pull test, which remains its own gate.
