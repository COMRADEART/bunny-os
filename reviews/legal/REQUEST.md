<!--
SPDX-FileCopyrightText: 2026 ComradeArt
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Licensing and trademark review — request

The project's licence gate passes: seven mechanical requirements are met, there is
a root `LICENSE`, eight per-directory declarations, 127 SPDX headers, and a clean
6,077-record scan. What has *not* happened is a lawyer reading any of it.

Two questions are load-bearing, and one of them gates the OEM programme.

## Exact scope

**In scope:**

1. **Outbound licence compatibility.** The owner selected a split model on
   2026-07-29: GPL-3.0-or-later for the OS layer (`services/`, `installer/`,
   `shell/`, `build/`), Apache-2.0 for the client packages (`oem/`,
   `enterprise/`, `sync/`, `schemas/`). Is that split coherent, and is it
   compatible with the 6,077 inbound licences in the SBOM?
2. **The GPL-3.0 anti-tivoisation question.** Do the anti-tivoisation terms
   (GPLv3 §6, Installation Information) conflict with shipping Secure Boot with a
   vendor-controlled key on OEM hardware, where the end user cannot replace the
   signing key? **This question gates the OEM programme and no OEM agreement
   should be signed before it is answered.**
3. **The Apache-2.0 / GPL-3.0 boundary.** Where the Apache-2.0 client packages
   and the GPL-3.0 OS layer interact, is the combination distributable, and does
   the direction of combination matter?
4. **The trademark position.** `docs/TRADEMARK_POLICY_DRAFT.md` is a draft written
   by an engineer. Is "Bunny OS" registrable and defensible, is the draft policy
   coherent, and does it permit what the OEM and community redistribution models
   assume?
5. **Third-party notices.** Is `THIRD_PARTY_NOTICES.md` sufficient for the
   attribution obligations the SBOM implies?
6. **Redistribution terms in the base image.** `build/license-policy.json`
   refuses certain markers. Are the refusals the right ones, and are any inbound
   terms being missed?

**Out of scope:**

- Employment, corporate structure, or tax.
- Privacy law and data protection. The project operates no service and holds no
  user data; if a hosted service is ever operated that is a separate engagement.
- Export control. Ask us if you think it is in scope and we have missed it.
- Patent clearance. The project is not asking for a freedom-to-operate opinion.

## Commit

- **Evidence baseline commit:** `80df25b09f6578276d18c8a82f15c47dd8959740`.
- **Your scope commit:** the commit you are given. Record it as `scopeCommit`.

## Artifacts

| Artifact | What it is |
|---|---|
| `LICENSE` | The root licence: GPL-3.0-or-later |
| `LICENSES/` | Canonical GPL-3.0-or-later and Apache-2.0 texts, taken from the builder's `/usr/share/licenses/` and corroborated by three independent packages shipping byte-identical copies |
| Eight per-directory `LICENSE` files | `services/`, `installer/`, `shell/`, `build/`, `oem/`, `enterprise/`, `sync/`, `schemas/` |
| `operations/data/licence-decision.json` | The owner's recorded decision and approval |
| `LICENCE_DECISION_REPORT.md` | Why the split was chosen |
| `docs/LICENCE_DECISION.md`, `docs/LICENSING.md` | The licensing model |
| `LICENSE_COMPLIANCE_REPORT.md` | The compliance position |
| `THIRD_PARTY_NOTICES.md` | Attribution notices |
| `evidence/sbom/beta-license-report.json` | The 6,077-record scan output |
| `build/license-policy.json` | The markers the build refuses |
| `docs/TRADEMARK_POLICY_DRAFT.md` | The draft policy — a draft, and not written by a lawyer |
| `docs/TRADEMARK_POLICY.md` | The current published position |
| `docs/SECURE_BOOT.md`, `docs/OEM_MODE.md`, `docs/OEM_PROGRAMME.md` | The Secure Boot and OEM models the anti-tivoisation question bears on |
| `docs/FACTORY_PROVISIONING.md` | What an OEM would do at manufacture |

## Threat model

Not adversaries — the ways this project could be legally wrong:

1. **Distributing a combination that cannot lawfully be distributed** because an
   inbound licence is incompatible with the outbound one.
2. **Signing an OEM agreement that cannot be honoured** because GPLv3 §6 requires
   Installation Information the OEM's Secure Boot configuration does not permit.
3. **Losing the name** because the trademark position was never established.
4. **Failing an attribution obligation** at scale, across 6,077 records.
5. **A contributor licence gap.** There is no CLA and no DCO enforcement. Say
   whether that matters for this project's structure.

## Questions

Ordered by consequence.

1. **Do the GPL-3.0 anti-tivoisation terms conflict with shipping Secure Boot
   with a vendor-controlled key on OEM hardware?** If they do, what are the
   options — a user-replaceable key, a shim the user can re-enroll, an exception,
   or not shipping locked hardware? This is the question that gates the OEM
   programme.
2. **Is the GPL-3.0-or-later / Apache-2.0 split coherent and distributable?**
   Specifically at the boundaries where the two interact.
3. **Is the outbound position compatible with all 6,077 inbound licences?** If
   not, name the incompatible ones. The project's own scan reports zero
   unresolved records and no prohibited markers; that is a mechanical check
   against a policy file, not a legal opinion.
4. **Is "Bunny OS" registrable and defensible**, and in which jurisdictions
   should the project act?
5. **Is `docs/TRADEMARK_POLICY_DRAFT.md` coherent**, and does it permit the
   redistribution the project intends — community rebuilds, OEM branding, and
   derivative distributions?
6. **Is `THIRD_PARTY_NOTICES.md` sufficient** for the attribution the SBOM
   implies, and if not, what is the minimum that would be?
7. **Does the absence of a CLA or DCO create a problem** for relicensing,
   enforcement, or accepting contributions?
8. **Are the refusals in `build/license-policy.json` the right ones?**

## Expected report format

A written opinion, plus a machine-readable record conforming to
`security/reachability/schemas/independent-review-record.schema.json` with
`reviewType: "legal"`.

Required: `independenceDeclaration`, `scopeCommit`, `scopeArtifacts`,
`findings[]`, `conclusion` (`pass`, `conditional`, `fail`), `reportDigest`, and a
detached `signature` over `reportDigest`.

Where an answer is jurisdiction-dependent, say which jurisdiction. Where the law
is unsettled, say so — the project would rather record an unsettled question than
a confident answer that is wrong.

## Severity model

- **critical** — the project cannot lawfully distribute what it distributes, or
  cannot honour an agreement it intends to sign.
- **high** — a material obligation is unmet and would be met only by changing the
  product or the licence.
- **medium** — an obligation is met imperfectly; remediation is documentary.
- **low** — a drafting improvement.
- **informational** — observation, or a question the project should ask later.

## Expected independence statement

In your own words:

- no employment, contract, consultancy, equity or advisory relationship with
  ComradeArt or Bunny OS beyond this engagement;
- no authorship of the licensing decision or the trademark draft;
- your conclusions are your own and were not directed or edited by the project.

If a conflict of interest exists — for example, representing a party with an
interest in the OEM question — disclose it and we will find someone else.

## Confidentiality requirements

- The repository is public and source-available. Nothing in it is privileged.
- **Your opinion is the project's to publish or withhold.** If any part should
  remain privileged, mark it; the project will honour that and will publish the
  rest.
- The project intends to publish the conclusions on questions 1 and 4, because
  downstream distributors and OEM partners need them. Tell us if that is unwise.

## Prohibited claims

- **"Certified"**, "compliant", "cleared" or "approved" as bare conclusions.
- **A patent opinion.** Not in scope, and the project will not represent your
  licensing opinion as one.
- **An opinion on a document you did not read.** Say what you covered.
- **A blanket "the licensing is fine"** without addressing question 1. If the
  anti-tivoisation question is unanswered, the OEM programme stays blocked, and
  the project would rather that were explicit.
- Any statement that the project may begin an OEM pilot. That gate has six other
  unmet requirements, including physical hardware nobody has.

A `conditional` conclusion naming the OEM question as the condition is a useful
and likely outcome. The licence gate passes without this review; no OEM agreement
should be signed with it outstanding, and the project has recorded that.
