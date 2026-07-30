# Public beta security review

Date: 2026-07-29. Result: **NO-GO for a public beta.** No beta artifact was reviewed, because none exists.

## Scope

What a public beta would expose that source review does not: a published artifact on real machines, a download and verification path, an update channel reaching third parties, an issue intake accepting untrusted input, and a disclosure process with an external reporter on the other end.

## Findings

**Blocker — unresolved vulnerability position.** The most recent scan of a locally built beta image reported 59 fixable findings: 8 Critical, 28 High, 23 Medium, concentrated in the Fedora kernel and the bootc-required Podman, Skopeo and Toolbox dependency set. No waiver exists and none was created. Shipping this to third parties would knowingly distribute Critical vulnerabilities.

**Blocker — no artifact signing.** `build/keys/` contains no release public key and no key ceremony has been performed. An unsigned beta artifact cannot be verified by a recipient, which makes the published download path meaningless and the update channel unsafe.

**Blocker — no independently bootable recovery.** A beta participant who breaks their system needs recovery media that boots without the installed system. None has been built or booted.

**Major — no installer.** `bunny-installer-backend` exits 78; no reviewed Anaconda adapter is installed. Participants could not install.

**Major — untested update path.** No signed manifest has been published or consumed. The update agent's validation is unit-tested but has never processed a real manifest.

**Accepted — intake handles untrusted input correctly.** Feedback ingestion redacts before storage. `installer/protocol.py` refuses secret-shaped fields recursively. `operations/crash.py` accepts exactly seven fields with no persistent user identifier. This is the one area genuinely ready for third parties.

## What was reviewed

Source, schemas, validators and their tests, plus the vulnerability scan of a locally built image. That build was an unsigned disposable validation artifact, not a beta candidate.

## What was not reviewed

Any published artifact, any installed system, any real update, any network behaviour on a participant machine, and any external disclosure. No independent security assessment has been commissioned; this is a self-review and carries the weight of one.
