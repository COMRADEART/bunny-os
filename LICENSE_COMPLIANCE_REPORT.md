# Licence compliance report

Date: 2026-07-29. Result: **not compliant for release.** Compliance cannot be established for an artifact that has not been built, and two repository-level gaps are open.

## Machine-checkable policy

`build/license-policy.json`:

```json
{"schemaVersion": 1, "failOnNoAssertionInRelease": true,
 "prohibitedLicensePatterns": ["(?i)proprietary", "(?i)commercial-only", "(?i)no-redistribution", "(?i)eula"]}
```

Checked by `build/scripts/license-scan.py`, run as `make license-scan` or `make shell-license-scan`, with `--release` strict mode when `BUNNY_RELEASE_BUILD=1`. Covered by `tests/security/test_license_scan.py`.

## Last recorded scan

Against a locally built beta image, per `docs/PHASE_7_BASELINE.md`: 6,077 SPDX records; 306 `NOASSERTION` records all explicitly provenance-covered; zero unresolved licences; zero prohibited markers.

That scan was run against an unsigned local validation build, not a release candidate. It is not release evidence.

## Phase 7 additions

Zero new third-party dependencies. All Phase 7 code is Python standard library only, so Phase 7 introduces no new licence obligation. Verified by review of every import in `oem/`, `enterprise/`, `sync/`, and `scripts/phase7.py`.

## Open items

1. **No root `LICENSE` file.** The repository does not state its own licence. This blocks any OEM or enterprise distribution, because a recipient cannot know what they may do with the source. This is the highest-priority licence gap and it is not a Phase 7 problem to solve unilaterally — it is a project decision.
2. **No trademark policy.** `docs/VISUAL_IDENTITY.md` records that the identity is original and bundles no third-party marks, but there is no policy governing use of the Bunny OS name and marks by OEMs, derivative images, or community remixes. `docs/OEM_PROGRAMME.md` defines branding *rights* per programme level; enforcing them requires a trademark policy reviewed by someone qualified, which has not happened.
3. **No release-artifact notices.** `THIRD_PARTY_NOTICES.md` covers the source tree and names the component classes an image would add. Notices for a shipped image must be generated from that image's SBOM.
4. **OEM firmware redistribution unreviewed.** The profile schema requires a `licenceReference` for firmware entries, but no OEM firmware has been submitted, so no redistribution terms have been reviewed.
5. **Sync cryptographic library not selected.** libsodium (ISC) and OpenSSL 3 (Apache-2.0) are candidates. Neither is a dependency yet, so neither has been reviewed in context.
6. **Enterprise console dependency tree unreviewed.** The console does not exist. A web application would introduce a large transitive dependency tree requiring its own scan and notices.

## Reproducibility and supply chain

`make reproducible-build-check` fails closed by design: one build is not reproducibility evidence, and a second independent builder comparison has never been run. `make sbom` requires `syft` and an OCI archive, neither available on the current host. `make malware-scan` fails closed for lack of a candidate artifact and a pinned scanner configuration.

`build/scripts/verify-toolchain.py` pins exact `image-builder` and `podman` versions for release builds, and `build-image.sh` requires a digest-pinned base image and a reviewed Fedora snapshot repository when `BUNNY_RELEASE_BUILD=1`.

## Statement

No compliance certification is claimed, and no independent legal review has been performed. This document records the mechanism, the last measurement, and the open items. Items 1 and 2 must close before any OEM or enterprise distribution.
