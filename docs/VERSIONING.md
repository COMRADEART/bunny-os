# Versioning

| Component | Phase 1 version | Authority |
|---|---|---|
| Bunny OS release | 0.1.0 | release metadata/semver |
| OS image | `0.1.0-<profile>.<commit>` | every OCI/disk composition |
| Bunny application | 0.2.0 placeholder | upstream Bunny release |
| OS integration contract | 1.0.0 | schema; independent major compatibility |
| privileged broker | 0.1.0 | implementation/API behavior |
| update manifest | schema 1 + monotonic sequence | signed channel metadata |
| recovery image | 0.1.0 | recovery profile/provenance |
| Bunny database | upstream-owned | never inferred or migrated by OS image |

Every image records all applicable versions, base version/reference, source commit/date, profile, package inventory, and build tool. Kernel and desktop exact RPM versions come from the embedded package inventory. Image digest and artifact hashes are recorded after composition.

