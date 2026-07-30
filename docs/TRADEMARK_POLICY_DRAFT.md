# Trademark policy — DRAFT

**This is a draft prepared for legal review. It has not been reviewed, no mark
has been registered, and nothing here should be relied on.** It exists so that
`reviews/legal/` has something concrete to review and so the licence gate has
the trademark input it requires.

Status: unreviewed draft. Reviewer: none. See
`operations/data/independent-reviews.json`.

## Why a project with a permissive half needs this

The licence decision makes `oem/`, `enterprise/`, `sync/` and `schemas/`
Apache-2.0. That is deliberate — third parties must be able to embed them — but
it means the licence alone does not prevent someone shipping a modified,
weakened build and presenting it as Bunny OS. The trademark is what
distinguishes *"built from Bunny OS source"* from *"is Bunny OS"*.

The weaker the licence, the more the trademark carries. That is the whole
argument for taking this seriously rather than treating it as paperwork.

## The marks

- **Bunny OS** — the operating system layer.
- **Bunny** — the application and system-intelligence layer.
- The rabbit device and the visual identity described in
  `docs/VISUAL_IDENTITY.md`.

## What the licence already permits, and this policy does not restrict

A licence to the code is a licence to the code. Nothing here restricts anything
the GPL-3.0-or-later or Apache-2.0 grants:

- Using the software, for any purpose, including commercially.
- Modifying it.
- Redistributing it, modified or unmodified.
- Studying it, forking it, and building on it.

**If this policy is ever read as restricting a freedom the licence grants, the
licence wins.** GPL-3.0 §7 does not permit adding restrictions, and a trademark
policy that tried would be void as to the GPL-licensed trees.

## Permitted uses of the marks without permission

1. **Nominative use.** Stating truthfully that something works with, is based
   on, is compatible with, or is a fork of Bunny OS. "Acme Widget for Bunny OS",
   "derived from Bunny OS", "compatible with Bunny OS 1.0".
2. **Unmodified redistribution.** Distributing an unmodified official build,
   with its marks intact, including mirroring and including for a fee.
3. **Discussion.** Reviews, tutorials, criticism, academic work, news.
4. **Community use.** User groups and events, provided they do not imply the
   project endorses or operates them.

## Uses that need permission

1. **Applying the marks to a modified build.** A modified build may not be
   distributed *as* Bunny OS. It may be described as based on or derived from
   Bunny OS. This is the core restriction and the reason the policy exists.
2. **Merchandise.**
3. **Domain names, product names, or company names** incorporating the marks.
4. **Implying endorsement, partnership, certification or affiliation.**

## Uses that will not be permitted

1. **Presenting a build with weakened security or privacy defaults as Bunny
   OS.** Specifically: disabling or bypassing update signature verification,
   weakening the privileged broker's permission enforcement, enabling telemetry
   that the privacy model says is off, or removing the ability to disable Bunny
   or run local-only. These are the guarantees the name is supposed to mean.
2. **Presenting an unofficial build as official**, or an unsupported
   configuration as supported.
3. **Use that implies the project supports a device, a fleet or a service it
   does not.** This applies directly to the OEM, enterprise and sync programmes:
   until a pilot is approved and a named support owner exists, no third party may
   suggest otherwise.

## OEM use

An OEM shipping Bunny OS on hardware is the case this policy is really for, and
it is unresolved pending review. The intended shape:

- An OEM that ships an **unmodified** qualified build may use the marks to say
  what the device runs.
- An OEM that ships a **modified** build needs a written agreement, and the
  agreement should be contingent on the OEM profile passing
  `oem/validation/profile.py` and on factory finalisation passing on real
  hardware — the same gates `gate-oem-pilot` enforces.
- No OEM agreement can be signed before the licensing review completes, because
  the anti-tivoisation question is open.

## Forks

A fork is welcome and is what the licence is for. A fork must:

- pick its own name and its own visual identity;
- not use the rabbit device or the Bunny OS wordmark as its own;
- state accurately that it derives from Bunny OS.

Nothing in this section limits the right to fork. It limits only the use of the
marks to identify the fork.

## Enforcement posture

Proportionate and slow. The intent is to prevent user-facing confusion and
security misrepresentation, not to police conversation. First contact should be
an explanation, not a demand.

## Questions for legal review

These are carried into `reviews/legal/REVIEW_PACKAGE.md`:

1. Is this policy enforceable without a registered mark, and in which
   jurisdictions should registration be sought first?
2. Does the "uses that will not be permitted" section survive GPL-3.0 §7, given
   it describes conduct rather than adding a licence condition?
3. Is the OEM modified-build restriction compatible with the anti-tivoisation
   terms, on hardware where Secure Boot uses a vendor-controlled key?
4. Does the nominative-use section give enough certainty that a downstream
   packager can act without asking?
5. Should the security-misrepresentation clause be a trademark term at all, or
   does it belong in an OEM agreement?
