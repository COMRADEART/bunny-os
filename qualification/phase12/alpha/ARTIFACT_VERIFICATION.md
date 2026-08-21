# Identify what you are actually running

Every report binds to bytes, not to a filename or a download link. Before
testing — ideally before booting — independently identify the artifact in
your hands. Do not take the project's word for it; your report records
what **you** observed.

## The published identity

`ARTIFACT_IDENTITY.json` beside this file carries the five digests of
artifact `e906a48793d7`. For most testers the relevant one is the ISO:

    823d50caba35afe72452768affd5f6fa0ac8cfc13c164f0e1bc909fa887ab421

## Compute your own

Linux / macOS:

    sha256sum bunny-os-0.3.0-live.e906a48793d7-x86_64.iso

Windows (PowerShell):

    Get-FileHash .\bunny-os-0.3.0-live.e906a48793d7-x86_64.iso -Algorithm SHA256

Write down the value you got. That value — not the published one — goes
into your report as `artifact_digest_observed`.

## The four identity states your report can claim

    VERIFIED               you computed the digest AND compared it against
                           the published identity yourself
    OBSERVED_UNVERIFIED    you computed and recorded a digest but did not
                           compare it
    MISSING                you could not or did not compute one
    MISMATCH               you computed one and it does NOT match

Claim `VERIFIED` only when your report contains the digest you computed —
the tooling refuses a `VERIFIED` claim with no observed digest, and it
refuses a report whose observed digest is silently replaced by the
expected one. `MISSING` is honest and acceptable: the report is preserved
as unbound user evidence and a later revision can bind it.

## If it does not match

Stop. Do not boot the image. Submit a report with
`artifact_identity_status: "MISMATCH"` and the digest you computed, plus
where the file came from. A mismatch is a first-class report — possibly
the most important kind — and it is never your mistake to have found one.
