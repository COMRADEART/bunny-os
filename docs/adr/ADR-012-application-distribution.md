# ADR-012: Application distribution

- Status: accepted
- Date: 2026-07-28

## Decision

Keep kernel, firmware, drivers, system libraries, GNOME, Bunny services, and recovery in the bootc image. Use per-user Flatpak for ordinary GUI applications through portals. A curated Bunny remote may be image-configured only with reviewed signing metadata; Flathub requires explicit user choice. GNOME Software is the primary application centre rather than a proprietary store.

Developer tooling runs in rootless Podman/Toolbox-style project containers. Bunny plugins retain their separate signed manifest, capability, sandbox, update, and rollback system and are not installed as root OS packages.

## Security policy

No broad filesystem permission is granted by default. Permission views show source-declared Flatpak permissions and say `Not enforced by this package format` for native packages rather than inventing revocation. Remote metadata and signatures are validated; incompatible native repositories are not mixed.

## Offline profile

The beta image includes only essential desktop, browser, terminal, files, settings, editor/viewer, archive, diagnostics, recovery, and Bunny components justified in `docs/APPLICATIONS.md`. Multi-gigabyte local models are never downloaded automatically.
