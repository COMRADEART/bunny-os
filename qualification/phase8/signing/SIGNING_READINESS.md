# Production signing readiness

**Current state: the artifact is UNSIGNED.** Zero signature files exist for
the subject artifact or anything else — measured in Phase 6
(`qualification/phase6/signing/SIGNING_POSITION.md`), unchanged since, and
not softened here. This document establishes the process that must exist
before any signing claim can be made. It signs nothing.

## Two categories that never merge (§10)

| Category | What it proves | Current state |
| --- | --- | --- |
| SIGNING DRILL | the procedure works on constructed inputs | 9/9, two-person drill included (`DEVELOPMENT_SIGNING_DRILL_REPORT.md`, `TWO_PERSON_DEVELOPMENT_SIGNING_DRILL_REPORT.md`) |
| PRODUCTION ARTIFACT SIGNED | the exact released bytes carry a verified signature from an authorized key | **has never happened** |

A successful drill satisfies nothing in the second row. Every future record
states which category it belongs to in its first line.

## The procedure a real signing must follow

    1. exact artifact        the signer states the digest they are signing:
                             image sha256:c87a6616… / ISO 823d50ca… — never
                             "the tree", never "latest", and recomputes it
                             from the bytes in front of them
    2. authorized authority  a production key under controlled access
                             (hardware token, offline HSM, or protected
                             signing service), with a recorded public
                             identity and fingerprint
    3. signature creation    detached signature over the artifact bytes
                             (the existing verifier contract:
                             `<artifact>.sig`, checked by
                             `openssl pkeyutl -verify -pubin -rawin`,
                             as `vm-recovery-test.sh` already enforces)
    4. independent           a verification run by someone or something
       verification          other than the signing command itself, from the
                             public key and the artifact bytes alone,
                             recorded with its own output

## The record a real signing produces

`signing-record.json` (does not exist yet — its absence is the evidence of
the UNSIGNED state):

    artifactDigest, signatureIdentifier, signerIdentity (public),
    signerAuthority, signingTimestamp, verificationResult,
    verificationRunBy, category: "PRODUCTION ARTIFACT SIGNED"

## What never appears anywhere

Private keys — not in the repository, not in qualification evidence, not in
screenshots, logs, shell history, or generated reports. Evidence carries
public key identity, certificate identity, fingerprint, signature digest and
verification results, and nothing else. A record that violates this is
destroyed, the key is treated as compromised, and the event is itself
recorded.

## Governance note

If the release policy for the controlled Alpha cohort accepts unsigned
distribution, that is blocking-condition-7 territory: an explicit exception
with owner, risk, exact artifact and expiration — never a silent default,
and never a reason to stop this process from being completed.
