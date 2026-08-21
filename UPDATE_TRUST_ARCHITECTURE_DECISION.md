# Update trust architecture — the decision

## Decision: **updates are UNSUPPORTED for the alpha release class**

§10 of the Phase 6 brief offers three outcomes and forbids taking one silently:

    A. Implement update trust architecture
    B. Explicitly declare updates unsupported for this release class
    C. Defer updates and retain the release gate as BLOCKED

**B.** Taken on 2026-08-18 by **Raviteja Allamsetti**, product and security
owner, who is accountable for the decision and for the risk it carries.

Machine-readable record: `operations/data/update-support-policy.json`.
Admission check: `python scripts/release.py update-support-policy`.

This document is at the repository root rather than under `docs/adr/` on
purpose. `docs/` is a build `COPY` root installed to `/usr/share/doc/bunny-os`,
so an ADR written now would change the contents of any future image while
changing nothing about the artifact this decision is bound to.

---

## 1. Why not A, and why not C

**A was not available.** An update trust architecture needs a trust root; a
trust root needs a production signing key; and the production signing ceremony
requires two people, of whom this project has one. That is not a scheduling
problem that a phase can work around — `docs/PRODUCTION_SIGNING_CEREMONY.md`
makes two-person approval an entry condition for the `updateMetadata` role
precisely so that it cannot be. Implementing the architecture without the key
would produce a mechanism that could never be exercised and a matrix that could
never be closed, which is the position Phase 5 was already in.

**C was available and is worse.** Deferring leaves the gate `BLOCKED` and the
product's actual behaviour undescribed. Users of an alpha would still receive no
updates; the difference is only whether anyone said so. A release class that
ships without updates and does not say so is not more cautious than one that
says so — it is the same product with less disclosure.

**B is what the product already does.** The image ships `enabled: false`, an
unresolvable manifest URL and an empty trust store. B makes that a stated
position with an accountable owner, an expiry, and — the part that makes it
a position rather than a description — **evidence that the refusal is real**.

---

## 2. The seven questions, answered

§10 requires the decision to answer these explicitly. Each answer below is
either a measurement or a stated absence; none is an intention.

### Where does Bunny obtain update metadata?

**Nowhere.** `/etc/bunny-os/update.json` names
`https://updates.invalid.bunny-os.example/developer/x86_64/manifest.json` — a
host in a namespace reserved for non-resolution. No metadata is published for
this release class and no endpoint is operated.

### How is that metadata authenticated?

**By a mechanism that exists and is unused.** A manifest carries a `keyId` and a
base64 raw signature. The agent canonicalises the manifest with the `signature`
field removed — sorted keys, no whitespace, UTF-8 — and verifies with
`openssl pkeyutl -verify -pubin -rawin` against
`/usr/share/bunny-os/update-keys/<keyId>.pem`.

Measured: a correctly signed manifest verifies (check **B3**), and one whose
payload was altered by a single field is refused `bad_signature` (**B4**).

### What root of trust is present?

**None.** The trust store contains exactly one file — `revoked-keys.json` — and
**zero** `.pem` files (check **A1**). Every manifest is therefore refused
`unknown_key` (**B1**), however well formed.

There is no trusted key because there is no production signing key, and there is
no production signing key because the ceremony needs a second person.

### How is root rotation handled?

**It is not, and that is a design gap this decision names rather than hides.**

Trust is conferred by the presence of `<keyId>.pem` *inside the image*. Adding,
rotating or removing a key means shipping a new image. `revoked-keys.json` can
deny a `keyId` ahead of the key lookup (measured, check **B2**) — but it also
ships inside the image.

So: no key-signing key, no online rotation path, and **no way to distrust a
compromised key without an OS update — which is the very mechanism that would be
unavailable.** Any future move to outcome A must resolve this *before* a key is
ever issued, not after.

### What happens when verification fails?

**It fails closed and does nothing.** Every failure raises, writes a status
record, prints to stderr and exits 2. No deployment is staged or switched;
`bootc switch` is reached only after a manifest has fully validated.

Measured across `not_configured` (**A4**–**A6**), `download_failed` (**C2**),
`unknown_key` (**B1**), `revoked_key` (**B2**) and `bad_signature` (**B4**).

### What prevents downgrade or substitution?

Four controls, three of them measured:

| Control | Mechanism | Measured |
| --- | --- | --- |
| Sequence monotonicity | a lower sequence is `rollback_attack`; staging also refuses an equal one | **D1**, **D2** |
| Digest pinning | the agent switches to `reference@digest` from the manifest | — |
| Repository allow-list | `imageReference` outside a configured prefix is `untrusted_image` | — |
| Expiry | a manifest past `expiresAt` is refused | — |

For this release class all four are moot, because the first control — a trusted
key — is absent.

### How does rollback interact with trusted updates?

**They do not interact, which is why rollback still works.**

`bootc rollback` plus a reboot is a local administrative action. It consults no
manifest, no key and no network. It is proven for this artifact pair:
`e501218f2fe0` → `e906a48793d7`, with all five user-state markers surviving.

Two consequences worth stating:

* the anti-rollback counter lives in `/var/lib/bunny-os/update/`, which belongs
  to the stateroot and **survives** a rollback — so rolling the OS back does not
  reset the highest accepted update sequence, which is the desirable direction;
* because rollback needs no trust root, **declaring updates unsupported removes
  nothing from the recovery story**.

---

## 3. The refusal is qualified, not assumed

A policy asserting "the system refuses" and a system that refuses are different
claims, and this project has found four harnesses that reported PASS while
measuring nothing.

**18 of 18 checks AS_INTENDED** against the subject artifact's own image, with a
negative control that **failed as required** — planting a signing key and
enabling updates flips 7 of the 18. Full account:
`qualification/phase6/update/REFUSAL_QUALIFICATION.md`.

`release/updatepolicy.py` refuses to admit an unsupported-update policy whose
negative control passed, on the grounds that a control which cannot fail is not
a control. That refusal is tested (30 tests,
`tests/update/test_update_support_policy.py`).

---

## 4. What this decision does not do

**It does not close the update matrix.** All thirteen scenarios remain
`NOT_RUN` with their recorded reasons, and `waivedScenarios` is deliberately
empty. Converting `NOT_RUN` into `NOT_APPLICABLE` would make the matrix complete
without anything having been executed — the exact move §17 forbids. The matrix
records what was run; the policy changes what the release is required to
demonstrate. Those are different registers and the decision keeps them apart.

**It does not change the release gate.** `python scripts/release.py gate --kind
qualification-candidate` produces byte-identical output before and after this
change, including `BLOCKED NOT_RUN Update matrix passed`. The policy is a
separate verb. Recomposing the gate during a release phase, on the strength of a
decision taken in the same phase, is the edit that should be reviewed rather
than slipped in.

**It does not substitute for independent security review** of the update design.
The reviewer is handed two design observations to consider: the rotation gap
above, and the fact that `_verify_signature` is the last call in
`_validate_manifest`, so a manifest's fields are parsed and compared before it is
known to be authentic.

---

## 5. Consequences for users — the part that must be said out loud

An alpha installation receives **no operating-system updates of any kind,
including security updates**.

The 8 Critical and 80 total advisories inherited from the base image **cannot be
remediated in the field**. Remediation requires reinstalling from a newer
artifact.

This must be stated to every alpha participant *before* installation, and it is
a required item in the Alpha consent record
(`qualification/phase6/alpha/`).

---

## 6. When this decision expires

The policy is **void**, and the update gate reverts to `BLOCKED`, on whichever
of these comes first:

1. a production signing key being created;
2. any trusted key shipping in `/usr/share/bunny-os/update-keys/`;
3. `/etc/bunny-os/update.json` shipping `enabled: true`;
4. promotion beyond the alpha release class;
5. **2027-02-18** — twelve months from the decision.

A policy with no way to expire becomes permanent by inattention rather than by
decision. `release/updatepolicy.py` refuses one that names no review condition.
