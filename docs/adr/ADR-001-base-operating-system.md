# ADR-001: Base operating system

- Status: accepted for Phase 1
- Date: 2026-07-28

## Decision

Use Fedora Linux 44 `fedora-bootc` as the x86-64 primary base. Consume Fedora repositories only during the image build; add Bunny-owned files in the derived OCI layer. Do not mix Debian, Ubuntu, RPM Fusion, openSUSE, or ad-hoc repositories. System RPM changes happen in a reviewed image build, not interactively on installed machines. User applications are Flatpaks after explicit remote enablement; developer tools exist only in the developer profile.

Fedora 44 is a short-lived base. The published schedule currently places EOL in May 2027 and explicitly marks that date as changeable. Bunny OS must rebase before EOL; the OCI boundary is the migration mechanism. Sources: [Fedora 44 release schedule](https://fedorapeople.org/groups/schedule/f-44/f-44-releng-tasks.html), [Fedora Atomic Desktops](https://www.fedoraproject.org/atomic-desktops/).

## Comparison

| Strategy | Hardware/packages | Image/rollback | Secure Boot | Developer/installer path | Maintenance and rejection |
|---|---|---|---|---|---|
| Debian stable | broad; older desktop/kernel | custom image/A-B work | signed shim/kernel | mature installer, custom immutable work | good long support, but Bunny would own most atomic integration |
| Ubuntu LTS | broad, strong vendor enablement | snap-based options but no selected native bootc desktop | supported vendor chain | mature installer/tooling | longer support; branding/repository/vendor coupling and a custom image model |
| Fedora Atomic family | current kernel/graphics, strong package set | proven OSTree deployments | Fedora signed chain | mature GNOME precedent | good fit, but rpm-ostree composition is less direct than the chosen OCI workflow |
| Fedora/Universal Blue bootc | current hardware, OCI-native customization | bootc transactional deployments | inherits base components; derived image still needs qualification | `image-builder` QCOW2/raw/installer path | selected Fedora bootc directly; Universal Blue rejected to reduce an extra supply-chain/branding dependency |
| openSUSE MicroOS | strong transactional Btrfs model | snapshots and rollback | supported distribution path | good YaST/transactional tooling | smaller Bunny integration/package familiarity and a different MAC/policy ecosystem |
| custom Debian debootstrap | maximum control | entirely Bunny-owned | entirely Bunny-owned integration | flexible | rejected: excessive security, installer, update, and hardware maintenance burden |

## Policy

- Version: Fedora 44, x86-64 first; aarch64 is schema-compatible but not a Phase 1 target.
- Update source: a Bunny OS OCI registry repository containing Fedora-derived images; the manifest pins an OCI digest.
- Repository policy: official Fedora repositories only in Phase 1. Third-party drivers/apps require a later legal/security ADR.
- Package policy: explicit files under `build/packages`; no penetration-testing bundle.
- Migration: rebuild against a supported Fedora bootc version, run contract/image/VM/hardware gates, then publish a new signed channel sequence. The Bunny application data boundary does not move.

