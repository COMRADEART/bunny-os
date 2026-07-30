# Licence decision report

Date: 2026-07-29  
Source commit: `79bb99ddb39d8a5dbc279629f43b23346fb0e5e8`  
Result: **decided, applied, and the licence gate passes all seven requirements.**

This is one of two blockers closed outright in this phase. It had been open
since `LICENSE_COMPLIANCE_REPORT.md` first recorded it as the highest-priority
licence gap, and it blocked OEM and enterprise distribution independently of
every technical gate: a recipient could not know what they were permitted to do
with the source.

## The decision

The project owner selected the **split** model on 2026-07-29, from four options
set out in `docs/LICENCE_DECISION.md`:

| Tree | Licence |
|---|---|
| `services/`, `installer/`, `shell/`, `build/` | GPL-3.0-or-later |
| `oem/`, `enterprise/`, `sync/`, `schemas/` | Apache-2.0 |
| everything else, including the root | GPL-3.0-or-later |

The reasoning is architectural rather than ideological. `ADR-023` deliberately
places the fleet server, enrolment service and console in separate repositories;
those components must import the protocol schemas and the policy model to
interoperate at all, and a copyleft obligation on `enterprise/` would reach into
control planes this project neither wrote nor supports. Meanwhile the OS layer is
where copyleft does real work: an OEM cannot take the privileged broker, weaken
its permission enforcement, and ship it closed.

## Gate result

```text
python scripts/release.py licence-gate

licence model: gpl-os-apache-clients-split
  ok      owner-decision
  ok      owner-approval-record
  ok      root-licence
  ok      package-level-licences
  ok      third-party-notices
  ok      spdx-identifiers
  ok      licence-scan
  ok      trademark-policy
licence gate passed
```

## What was put in place

- **`LICENSE`** — a licensing overview naming both licences and the trees each
  governs, followed by the full GPL-3.0-or-later text.
- **`LICENSES/GPL-3.0-or-later.txt`** (676 lines) and
  **`LICENSES/Apache-2.0.txt`** (202 lines).
- **Eight per-directory `LICENSE` files**, each declaring its SPDX identifier
  and why that tree carries that licence.
- **127 `SPDX-License-Identifier` headers** across the eight licensed trees:
  services 8, installer 35, shell 17, build 29, oem 8, enterprise 17, sync 13.
  `schemas/` is JSON and cannot carry comments, so it is covered by its
  directory `LICENSE`.
- **A clean licence scan**: 6077 SPDX records, 0 unresolved, no prohibited
  markers, over the beta profile.
- **`docs/TRADEMARK_POLICY_DRAFT.md`**, prepared for legal review.

### The licence texts were sourced, not transcribed

Reproducing 5,600 words of GPL-3.0 from memory would risk an error in a legal
document, and an inexact licence text is worse than none. Both texts were taken
from the Fedora 44 builder's `/usr/share/licenses/`, and each was corroborated by
**three independent packages shipping byte-identical copies**:

| Licence | Digest | Corroborated by |
|---|---|---|
| GPL-3.0 | `fc82ca8b6fdb18d4…` | nano, linux-firmware, libassuan |
| Apache-2.0 | `c6596eb7be8581c1…` | bootc, bootupd, linux-firmware |

## The approval is attested, not signed

`release/licensing.py` requires a decision to carry **either** a cryptographic
signature **or** an attestation reference, and rejects one carrying neither:

```text
a licence decision must carry either a signature or an attestation reference;
an unsigned, unattributed approval is an assumption, not an approval
```

This decision carries an attestation reference —
`docs/LICENCE_DECISION.md#owner-decision` — and not a signature. No owner signing
key exists, and `docs/PRODUCTION_SIGNING_CEREMONY.md` records that no key
ceremony has been held. Signing it would have meant inventing a key, so the
attestation path was used and the gap is recorded rather than hidden.

Adding a signature once a key ceremony happens is tracked as an open item.

## What is still open

The licence gate passing does not mean licensing is finished. Three things
remain, all in `reviews/legal/`:

1. **Outbound compatibility is unreviewed.** `build/license-policy.json` refuses
   proprietary, commercial-only, no-redistribution and EULA markers in
   dependencies. It does not check whether GPL-3.0-or-later is
   outbound-compatible with every licence in the 6077-record SBOM. That needs
   counsel.
2. **The trademark policy is a draft.** It has not been reviewed and no mark has
   been registered. The permissive half of the split makes this more urgent
   rather than less: the weaker the licence, the more the trademark carries.
3. **The anti-tivoisation question is unanswered.** Whether GPL-3.0's terms
   conflict with shipping Secure Boot under a vendor-controlled key on OEM
   hardware is load-bearing for the OEM programme, and no OEM agreement should be
   signed before it is answered.

`gate-oem-pilot` accordingly still reports `brandingAndLicensingApproval` as
unmet, even though the licence gate passes. Those are two different things and
the gates keep them apart.

## Tests

`tests/licensing/` — 20 tests, including the mandated `unsigned licence approval`
adversarial case, verification that every split directory has a `LICENSE`
declaring the right identifier, and a check that every Python file in the
licensed trees carries the SPDX header its directory declares.
