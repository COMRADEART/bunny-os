# Twenty-minute evidence demo

Perform these only on the approved disposable-disk builder and label every unexecuted item:

1. Build the digest-pinned beta, live, and recovery images.
2. Verify checksum and detached signature; corrupt a copy and show rejection.
3. Boot the live session under UEFI/OVMF.
4. Run hardware preflight and distinguish VM evidence from physical support.
5. Launch Anaconda Web UI as the unprivileged presentation path.
6. Select a fresh virtual disk and show its model, size, path, and installation source.
7. Preview all partition operations and confirm no writes occurred.
8. Select LUKS2 and enter a password through the protected UI path.
9. Display, save, and confirm the test recovery key without recording it.
10. Deploy the verified embedded bootc payload and show truthful stages.
11. Install/preserve deterministic Fedora shim/GRUB entries.
12. Run post-install target, image, user, encryption, recovery, service, and secret verification.
13. Reboot from the virtual disk and remove ISO media.
14. Test password unlock, wrong-password rejection, and recovery-key unlock.
15. Complete, interrupt, resume, and close first run without blocking the desktop.
16. Show Bunny is optional and select local-only/configure-later.
17. Select one search location; show no whole-home default.
18. Install/update/remove one per-user Flatpak and inspect permissions.
19. Stage a signed OS update; show previous deployment and user/app preservation.
20. Boot recovery and previous deployment, then export redacted diagnostics.

Archive exact commands, versions, artifact hashes, serial log, screenshots without secrets, and pass/fail rows. Do not mark Phase 3 complete if encrypted install, upgrade, rollback, or critical security/accessibility gates are missing.
