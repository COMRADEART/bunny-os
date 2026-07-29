# ADR-010: Installer framework

- Status: accepted for implementation; destructive runtime qualification pending
- Date: 2026-07-28

## Decision

Use Fedora 44's Anaconda 44.x plus the separately versioned Anaconda Web UI as the graphical installer, with Anaconda's D-Bus/Blivet modules for storage, user, locale, bootloader, and installation lifecycle. Build the live installer container and offline bootc payload into an OSBuild unified `image-builder` `bootc-generic-iso`. Use Fedora shim/GRUB, cryptsetup/LUKS2, UDisks/Blivet discovery, and bootc for image deployment. Bunny adds configuration/branding, typed plan validation, safety policy, redacted audit, hardware preflight, first-run, and post-install health checks.

The frontend is an unprivileged presentation client. Only the installer service may invoke allowlisted backend operations through the established local interface. There is no generic command operation. Bunny's host-test backend remains simulation-only; production execution is fail-closed unless the installed Anaconda adapter and live-media identity are verified.

This follows the current [Anaconda Web UI installation flow](https://anaconda-installer.readthedocs.io/en/latest/anaconda-webui/docs/installation-steps.html) and [OSBuild bootc ISO contract](https://osbuild.org/docs/developer-guide/projects/image-builder/advanced/bootc/isos/). The unified image-builder documentation explicitly separates installer and embedded payload references.

## Rejected alternatives

- Calamares: strong general installer but requires Bunny-owned Fedora bootc deployment integration and expands the maintenance surface.
- YaST and Subiquity/Flutter: coupled to a different base ecosystem.
- systemd-repart/systemd-firstboot alone: valuable low-level/offline primitives, not a complete accessible desktop installer.
- custom destructive backend: duplicates mature partition, encryption, bootloader, and recovery logic.
- obsolete standalone bootc-image-builder Anaconda ISO flow: unified image-builder is the selected and maintained project path.

## Risks and gates

The bootc generic ISO guidance documents active integration caveats, so exact Fedora 44 package versions and installed behavior are release gates. Anaconda UI customisation must not fork storage semantics. Every erase/encrypt/UEFI path requires disposable-disk VM tests, and no beta claim is allowed until those tests pass.
