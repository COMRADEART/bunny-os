# ADR 0016 — Update and rollback model

**Status:** Accepted, amended · **Date:** 2026-07-26 · **Spec:** §20.3, §25.5

## Context
C6 makes reversibility a platform guarantee. Phase 0 §18 names atomic images with transactional rollback as the system-level analogue. The existing self-updater is egress-checked with install-strategy detection but no signature verification.

## Decision

**Application (Modes A–C):** signature verification added to the existing updater; staged install with a rollback to the prior version; update channels.

**OS (Mode D):** `bootc upgrade` against a signed, versioned OCI tag, chunked layers, two channels as separate tags, and soft-reboot for userspace-only updates. **OS updates surface as a single plan-level decision (C1), never as a package list.**

**Rollback:** `greenboot` with a **Bunny-specific required health check** asserting that the permission gate loads, the deny-rule set parses, and the memory store opens read-write, with a bounded boot-attempt count. `bootc rollback` is exposed in the UI as *"undo the last system update"*, never as a terminal command.

This extends C6 in an important way: **reversibility covers safety-substrate failure, not just boot failure.** A machine that boots perfectly but whose permission gate failed to load rolls itself back.

**Signing and freshness:** cosign verifies image digest/signer, combined with TUF-style monotonic version and expiry metadata, threshold release signatures, channel targets, offline root/recovery keys, and tested key rotation/revocation. A valid signature on a mutable tag is not freshness or rollback protection.

**State compatibility:** because `/var` persists across an OS deployment rollback, authoritative schemas remain `N/N−1` readable. Incompatible migrations are journaled and reversible or carry a durable-state snapshot that rolls back with the code deployment.

**Sealed verified-boot images are a Phase 2 target, not a Phase 1 claim.** Current bootc does support `install to-disk --block-setup tpm2-luks`; Bunny adopts and validates that path, including recovery and TPM-failure UX, rather than building encryption enrolment itself.

## Alternatives
- *Keyless/OIDC signing* — rejected for a project-held key pair: simpler trust root for a small team, and no dependency on an external identity provider at verification time.
- *Claiming a verified update chain now* — rejected: policy enforcement on the upgrade path is currently asserted rather than confirmed. If P25 fails, Bunny OS distribution is deferred; documenting the hole is not a release gate.

## Consequences
An over-strict required health check turns a cosmetic bug into a boot loop. The required set stays minimal; everything else is advisory.

## Risks
A tag-move release model makes an accidental promotion instantly global; signature alone does not stop freeze or rollback. Mitigated by threshold promotion plus monotonic/expiring metadata and offline recovery keys.

## Validation required
P25 (unsigned, wrongly signed, expired, replayed, rollback, below-threshold, and rotation cases refuse), P17 (greenboot rolls back on substrate failure).

## Phase 0 principles satisfied
C6, C4, C15, §18.
