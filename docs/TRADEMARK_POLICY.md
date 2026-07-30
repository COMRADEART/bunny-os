# Trademark and branding policy

Date: 2026-07-29. Status: **draft; not reviewed by anyone qualified to review it.**

`LICENSE_COMPLIANCE_REPORT.md` records the absence of this policy as an open item that blocks OEM and enterprise distribution independently of every other gate. This is a first draft so the gap is a reviewable document rather than nothing. It has not had legal review and should not be relied on until it has.

Marks covered: the name **Bunny OS**, the Bunny OS logo, and the rounded-arc motif described in `docs/VISUAL_IDENTITY.md`.

## The distinction that matters

The source licence governs what you may do with the *code*. This policy governs what you may call the *result*. They are separate, and a permissive code licence does not grant the right to call a modified build "Bunny OS".

The reason is not control for its own sake. A user who downloads something called Bunny OS should be able to rely on it having passed the Bunny OS release gate. If any build can use the name, the name stops carrying that meaning and the gate stops protecting anyone.

## Permitted without permission

- Stating accurately that your product **runs** Bunny OS, or is **based on** or **derived from** Bunny OS.
- Using the name in documentation, articles, reviews, comparisons, academic work and conference talks.
- Using the name to identify the project in a bug report, security advisory, or package dependency.
- Redistributing the **unmodified** official image under its own name.

## Requires a written agreement

- Calling a modified image "Bunny OS" without qualification.
- Using the logo on hardware, packaging, retail listings or marketing.
- The phrases **"Official Bunny OS device"**, **"Supported OEM partner"** and **"Certified"**, each of which maps to a programme level in `docs/OEM_PROGRAMME.md`.
- Any use implying endorsement, partnership or a support relationship that does not exist.

## Never permitted

- Presenting a modified image as official Bunny OS. `oem/validation/profile.py` enforces the technical half: `claimsOfficialBunnyOsDevice` requires the matching programme level, a signed hardware qualification report, and validated recovery. The policy half is this document.
- Describing hardware as "certified" without a completed formal certification process. `oem/qualification.py` refuses the claim without two independent repeat runs and no declared limitations. No hardware has ever met that bar, so no certification claim is currently permissible by anyone.
- Using the marks on a build whose update trust root differs from the official one. Such a build is an `independent-oem-variant` and must carry its own name; `oem/validation/profile.py` rejects the combination of an independent variant and an official-device claim.
- Using the marks in a way that suggests the project provides support it does not, given the project currently has one maintainer and no support rota.

## Community remixes

Encouraged, with a different name. Say "based on Bunny OS" rather than "Bunny OS Remix", so a user can tell at a glance whether they are running something that passed the release gate.

If you distribute a remix, you take on the security-response obligation for it. The project cannot issue advisories for builds it did not produce.

## Enforcement

By correspondence first. The project has no interest in litigation and no budget for it; the realistic remedy is asking someone to rename, and most people do.

## Open questions for legal review

1. Whether the marks should be registered, and in which jurisdictions.
2. Whether "Bunny" alone is defensible or only "Bunny OS", given how common the word is.
3. How this interacts with the upstream Fedora trademark policy, since Bunny OS is a Fedora derivative and inherits obligations there.
4. Whether the OEM programme levels should be contractual terms rather than policy statements.

Until these are answered by someone qualified, treat this document as a statement of intent.
