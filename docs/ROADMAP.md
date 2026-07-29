# Roadmap

Phase 2 now contains the Bunny Shell implementation and explicit blocked runtime validation. The next work is validation closure, not Phase 3 expansion.

1. Provision pinned Fedora 44/KVM builder; run full gate, fix actual compose/boot issues, archive provenance/SBOM.
2. Obtain signed upstream Bunny Linux artifact; verify manifest/hashes/modes/protocol and run Tauri/Core/app-server lifecycle tests.
3. Qualify SELinux domains, registry signature policy, update key ceremony, two-deployment health/rollback, and independent recovery media.
4. Run QEMU then VMware/VirtualBox and physical Intel/AMD/NVIDIA matrices, including Secure Boot and LUKS2.
5. Run the Phase 2 Fedora/GNOME 50 nested-shell and QEMU matrices, including Safe Shell and degraded modes.
6. Obtain the signed Bunny artifact and qualify server-authoritative task/plan/approval actions through the real app-server.
7. Close Orca, portal, multi-monitor, performance, systemd, SELinux, SBOM, image, VM, and hardware evidence rows.
8. Only after Phase 2 gates are green, prepare a Phase 3 proposal. Installer, app-store, hardware provisioning, manufacturing, consumer distribution, and stable release work remain prohibited.
