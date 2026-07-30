# Public beta release checklist

Date: 2026-07-29. `BLOCKED` prevents a beta. `PASS-SOURCE` means the source behaviour is verified and is **not** beta evidence.

| # | Item | Status | Owner | Note |
|---|---|---|---|---|
| 1 | Beta artifact built reproducibly | BLOCKED | Release | Same-host determinism only; no second independent builder |
| 2 | Artifact signed with a reviewed key | BLOCKED | Release | No key ceremony; `build/keys/` holds no release key |
| 3 | Published checksums | BLOCKED | Release | Nothing published |
| 4 | Verified download path | BLOCKED | Release | `docs/VERIFY_DOWNLOAD.md` describes one; nothing to download |
| 5 | SBOM published with the artifact | BLOCKED | Release | SBOM generation works; no published artifact to attach it to |
| 6 | Vulnerability position resolved or waived | BLOCKED | Security | 59 fixable findings, 8 Critical, 28 High, unwaived |
| 7 | Installer completes an installation | BLOCKED | Installer | No reviewed Anaconda adapter; backend exits 78 |
| 8 | Encrypted installation boots | BLOCKED | Installer | Depends on item 7 |
| 9 | Independently bootable recovery media | BLOCKED | Recovery | Never built or booted |
| 10 | Update channel serves a signed manifest | BLOCKED | Maintenance | No manifest published |
| 11 | Rollback works from the beta | BLOCKED | Maintenance | Boot parity verified; live deployment switch not exercised |
| 12 | Privacy-safe feedback intake | PASS-SOURCE | Privacy | Redaction implemented and regression-tested; zero reports received |
| 13 | Crash reporting excludes user content | PASS-SOURCE | Privacy | Seven-field allowlist, no persistent user id; zero crashes received |
| 14 | No unexplained network activity | BLOCKED | Privacy | Capture against a booted image only; no installed system |
| 15 | Accessibility of essential workflows | BLOCKED | Accessibility | No assistive technology has been used against this system |
| 16 | Beta support window declared | BLOCKED | Maintenance | `docs/SUPPORT_POLICY.md` states no end date |
| 17 | Incident and disclosure process | PASS-SOURCE | Security | `SECURITY_POLICY.md` defines it; never operated |
| 18 | Issue intake and triage | PASS-SOURCE | Maintenance | Tooling works; ledger holds zero issues |
| 19 | Documentation for participants | PASS-SOURCE | Documentation | Getting started, troubleshooting, reporting guides exist |
| 20 | Capacity to respond to participants | BLOCKED | Maintenance | One maintainer, no rota |

**5 PASS-SOURCE, 15 BLOCKED.**

The five that pass are all intake-side: if a beta ran, participant data would be handled correctly and reports would be redacted before storage. Nothing on the distribution side is ready, and items 7 and 9 mean a participant could neither install the system nor recover it.
