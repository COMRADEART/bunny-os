# Licence decision

Date: 2026-07-29. Status: **decided by the project owner.**

This document is the decision package that was put to the owner, and the record
of what they chose. It is referenced by
`operations/data/licence-decision.json` as the attestation for the decision, and
the licence gate reads that file.

## Owner decision

> **GPL-3.0-or-later for the OS layer; Apache-2.0 for the client packages.**
>
> Selected by the project owner on 2026-07-29 from the four options below.

| Tree | Licence |
|---|---|
| `services/` | GPL-3.0-or-later |
| `installer/` | GPL-3.0-or-later |
| `shell/` | GPL-3.0-or-later |
| `build/` | GPL-3.0-or-later |
| `oem/` | Apache-2.0 |
| `enterprise/` | Apache-2.0 |
| `sync/` | Apache-2.0 |
| `schemas/` | Apache-2.0 |
| everything else, including the repository root | GPL-3.0-or-later |

**The decision is attested, not cryptographically signed.** No owner signing key
exists and `docs/PRODUCTION_SIGNING_CEREMONY.md` records that no key ceremony has
been held, so signing this would mean inventing a key. The attestation is this
document plus the recorded decision; adding a signature is tracked as an open
item rather than simulated. `release/licensing.py` accepts either a signature or
an attestation reference and rejects a decision carrying neither.

## Options compared

### 1. GPL-3.0-or-later for the OS layer, Apache-2.0 for the client packages — **selected**

*For.* It matches the trust boundary the architecture already draws.
`docs/adr/ADR-023-fleet-control-plane.md` deliberately puts the fleet server,
enrolment service and console in separate repositories with separate trust
boundaries. Those components must import the protocol schemas and the policy
model to interoperate at all. A copyleft obligation on `enterprise/` would reach
into every deployment of a control plane, including ones this project neither
wrote nor supports.

Meanwhile the OS layer is exactly where copyleft does real work: an OEM cannot
take the privileged broker, weaken its permission enforcement, and ship it
closed.

*Against.* Two licences is more to explain, and a contributor must know which
tree they are in. Mitigated by per-directory `LICENSE` files and an
`SPDX-License-Identifier` in every source file, both of which the licence gate
verifies.

### 2. Uniform GPL-3.0-or-later

*For.* One licence, one explanation, maximum user protection everywhere.

*Against.* It reaches into any third-party fleet server or OEM tooling that
imports `enterprise/` or `sync/`. Given ADR-023 puts those components outside
this repository by design, uniform copyleft would make the documented
architecture legally awkward to implement. It also narrows OEM participation,
because the anti-tivoisation and patent terms lead some hardware vendors to
decline outright.

### 3. Uniform Apache-2.0

*For.* Widest OEM and enterprise acceptance. The explicit patent grant is
genuinely valuable for a project inviting hardware partners.

*Against.* An OEM may ship a modified, closed variant with weakened broker
defaults. The trademark policy would then be the only lever, and the trademark
policy is an unreviewed draft. Trading an enforceable licence term for an
unreviewed trademark is the wrong direction while the trademark is the weaker
instrument.

### 4. Another legally reviewed split

Not selected, because it presupposes the legal review that has not happened. It
remains open: if `reviews/legal/` returns a recommendation to move a boundary,
this decision is revisited rather than defended.

## Why this is a decision and not an engineering choice

The considerations below were put to the owner because each has a consequence
that outlives any technical gate.

### Kernel and userspace compatibility

Bunny OS is a Fedora derivative. The kernel, systemd, GNOME and the rest arrive
under their own licences — predominantly GPL-2.0, GPL-3.0, LGPL, MIT and
Apache-2.0 — and are unaffected by this choice. The decision governs only the
source in this repository.

### Linking implications

The broker, update agent and installer are separate processes communicating over
a typed local socket, not linked libraries. The Phase 7 packages are pure-Python
importable modules, which is the case where the licence boundary matters most —
and the reason those specific trees are permissive.

### Derivative-work implications

Under the split, a modified `services/` shipped to users must be published. A
third-party fleet server importing `enterprise/` need not be. That asymmetry is
the point.

### OEM distribution

The unresolved question is whether GPL-3.0's anti-tivoisation terms conflict
with shipping Secure Boot with a vendor-controlled key on OEM hardware. This is
load-bearing for the OEM programme and is the fourth explicit question in
`reviews/legal/REVIEW_PACKAGE.md`. It is not answered here.

### Enterprise service code

Apache-2.0 on `enterprise/` lets an organisation run a control plane without
publishing it. Given that a control plane holds an organisation's own policy and
not user content, this is the correct default.

### Cryptographic libraries

`sync/` uses AES-256-GCM, HKDF-SHA256 and RFC 3394 via the platform's
`cryptography` package. Apache-2.0 is compatible with it and with the reviewed
backends a cryptographic review might recommend.

### Contributions

Inbound = outbound. A contributor licenses their contribution under the licence
of the tree they contribute to. No CLA is required and none is proposed:
requiring one would let a future relicensing bypass this decision.

### Patents

Apache-2.0 carries an explicit patent grant and GPL-3.0 carries an implicit one
plus a termination clause. Neither tree is left without patent protection.

### Trademark separation

A licence to the code is not a licence to the marks. This is stated in `LICENSE`
and elaborated in `docs/TRADEMARK_POLICY_DRAFT.md`. The weaker the licence, the
more the trademark has to carry, which is why the permissive half makes the
trademark review more urgent rather than less.

### Source-distribution obligations

An OEM shipping a modified `services/` must offer corresponding source. Whether
the current build tooling is sufficient to discharge that obligation is the
fifth question in `reviews/legal/REVIEW_PACKAGE.md`.

## What is now in place

- `LICENSE` — licensing overview plus the full GPL-3.0-or-later text.
- `LICENSES/GPL-3.0-or-later.txt` and `LICENSES/Apache-2.0.txt` — canonical
  texts, taken from the Fedora 44 builder and each corroborated by three
  independent packages shipping byte-identical copies, rather than transcribed.
- Eight per-directory `LICENSE` files.
- 127 `SPDX-License-Identifier` headers across the eight licensed trees.
- `THIRD_PARTY_NOTICES.md`.
- `docs/TRADEMARK_POLICY_DRAFT.md`.
- A clean licence scan: 6077 SPDX records, 0 unresolved, no prohibited markers.

`make licence-gate` passes all seven requirements.

## What is still open

1. **Outbound compatibility has not been reviewed by counsel.**
   `build/license-policy.json` refuses proprietary, commercial-only,
   no-redistribution and EULA markers in dependencies, but it does not check
   whether GPL-3.0-or-later is outbound-compatible with every licence in the
   6077-record SBOM.
2. **The trademark policy is a draft.** It has not been reviewed and no mark has
   been registered.
3. **The anti-tivoisation question is unanswered**, and it gates the OEM
   programme independently of every technical blocker.

All three sit in `reviews/legal/`, which is prepared and not commissioned.
