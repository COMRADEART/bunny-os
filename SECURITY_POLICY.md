# Bunny OS security policy

Date: 2026-07-29. Status: **defined and exercisable; never operated against a real report.**

This document was missing, which meant `missing-security-process` was an accurate blocker rather than a paperwork gap. It is written now so the process exists before it is needed, not after.

## Reporting a vulnerability

Report privately. Do not open a public issue for a security problem.

Include the affected component and version, what an attacker can do, how to reproduce it, and whether it is already public. A proof of concept helps; a working exploit is not required.

## What to expect

| Stage | Target |
|---|---|
| Acknowledgement | 3 working days |
| Initial assessment and severity | 10 working days |
| Fix or documented mitigation for Critical | 30 days |
| Fix or documented mitigation for High | 90 days |
| Coordinated disclosure | by agreement, default 90 days from acknowledgement |

**These targets are aspirational and currently unbacked.** The project has one maintainer and no on-call rotation, so a report arriving at a bad time may take longer. Saying so is more useful than publishing a target nobody can meet. `SUSTAINABILITY_REPORT.md` records this as a binding constraint on Phase 7.

## Severity

Follows `docs/STABLE_RELEASE_BLOCKERS.md`, which already defines the blocking conditions. Critical and Blocker findings stop a release. Some categories can never be waived: encryption loss, wrong-disk writes, signature bypass, recovery failure, privacy boundary violations, accessibility of essential workflows, and cross-user exposure.

## Embargo

Security fixes may be developed on a restricted `security/<issue>` branch, per `docs/BRANCHING_AND_RELEASES.md`. Embargoed work is not pushed to public branches, does not appear in public issue trackers, and does not enter pull-request CI, because CI logs are public.

OEM partners at the supported and official levels receive advance notice under `docs/OEM_PROGRAMME.md`. Community image builders do not, because there is no relationship through which to notify them confidentially.

## Signing and key compromise

Private signing keys are held outside the repository and outside CI. `build/scripts/sign-stable-rc.py` refuses a key path inside the repository and a test asserts that refusal.

If a signing key is suspected compromised: stop publishing, distribute a signed revocation naming the key id through `build/keys/revoked-keys.json` in a signed image, rotate to an overlapping new key per `docs/UPDATES.md`, and publish an advisory. **This ceremony has never been rehearsed**, and there is currently only one potential signer, which is itself a single point of failure.

## What has never happened

No vulnerability report has been received, because there are no users. No advisory has been published. No embargo has been run. No key rotation or revocation has been performed. No CVE has been requested.

The process above is real and can be followed. It has not been tested by contact with reality, and a process that has never run should be assumed to contain mistakes.

## Scope

In scope: the Bunny OS image, the privileged broker, the update agent, the installer, Bunny Shell, the OEM tooling, the device policy agent, and the encrypted sync client.

Out of scope: the upstream Fedora base and the Linux kernel — report those to Fedora and upstream, though we want to know so we can rebase. Also out of scope: findings that require an attacker to already have root on the device, and social engineering of the maintainer.
