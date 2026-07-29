# Third-party notices

Date: 2026-07-29. Generated from review of the repository source and the recorded SPDX output, not from a shipped artifact.

## Scope and honesty statement

This document covers third-party components in the **Bunny OS source tree** and the component classes a Phase 7 deployment would introduce. It is not a notices file for a released artifact, because no artifact has been released. A shipping image requires notices generated from that image's SBOM.

There is currently no root `LICENSE` file in this repository. That is an unresolved gap recorded in `LICENSE_COMPLIANCE_REPORT.md`; it is not asserted here that any particular licence applies.

## Phase 7 source dependencies

**None.** All Phase 7 code — `oem/`, `enterprise/`, `sync/`, `scripts/phase7.py` — is Python 3 standard library only. No package was added, vendored, or bundled. Verified by review: the only imports are `argparse`, `dataclasses`, `datetime`, `hashlib`, `hmac`, `json`, `os`, `pathlib`, `re`, `shutil`, `tempfile`, and `typing`, plus intra-repository modules.

## Repository-level third-party components

| Component | Where | Licence | Notes |
|---|---|---|---|
| `jsonschema` | Development and CI only | MIT | Soft-imported by `scripts/task.py`; used to check schema validity, never for runtime validation. Not shipped. |
| `typescript`, `@types/node`, `undici-types` | `node_modules/` | Apache-2.0, MIT | Vendored artefacts of the upstream Bunny application, not Bunny OS source. Excluded from `validate_python` and from container builds. |
| Shell artwork | `shell/assets/` | CC BY 4.0 | Provenance and terms recorded in `shell/assets/LICENSE.md` |

`docs/VISUAL_IDENTITY.md` records that no third-party font, raster artwork, or trademark asset is bundled, and that the visual identity is original rather than derived from another operating system's marks.

## Components an image would introduce

Not enumerated here, because no image has been built with a recorded SBOM in this phase. The mechanism exists: `make sbom` runs `syft` to emit CycloneDX and SPDX, and `build/scripts/license-scan.py` checks the SPDX against `build/license-policy.json`. The last recorded run against a beta image produced 6,077 SPDX records with zero unresolved licences and zero prohibited markers.

A released image would carry Fedora base userspace, the Linux kernel, systemd, GNOME, Mutter, NetworkManager, firewalld, SELinux policy, `bootc`, and their transitive dependencies. Their notices must be generated from the image SBOM at release time, not transcribed here.

## Phase 7 component classes requiring review before any deployment

| Class | Status |
|---|---|
| OEM drivers | None reviewed; no OEM profile has been accepted |
| OEM firmware | Redistribution terms must be recorded per `firmware[].licenceReference`; none supplied |
| Management services | Not written; separate repositories |
| Sync libraries | Not selected; no reviewed backend installed |
| Cryptographic libraries | libsodium (ISC) and OpenSSL 3 (Apache-2.0) are the named candidates; neither is vendored or currently a dependency |
| Enterprise console | Not written; would introduce a web dependency tree requiring its own notices |
| Installer customisation | No OEM customisation has been built |
| Device-agent dependencies | None; standard library only |

## What this document does not do

It does not assert compliance. It records what is present, what is absent, and what must be reviewed. See `LICENSE_COMPLIANCE_REPORT.md` for the compliance position and its open items.
