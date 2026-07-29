# Developer image

Profile `developer` is Fedora 44 bootc + GNOME/Mutter Wayland + conventional terminal/file/settings apps + NetworkManager/firewalld/SELinux + broker/update/health/recovery/info/CLI + Git/compilers/debuggers/rootless container tools. Developer tools are not inherited by the future consumer profile.

The image expects GNOME Initial Setup to collect locale, keyboard, timezone, Linux user, hostname, and network. GDM then retains base GNOME and adds Bunny and Bunny Safe Shell. After the first graphical session, `bunny-first-boot.service` records privacy, optional periodic update check, optional Bunny autostart, deferred local model setup, and recovery-key guidance. All defaults work offline; no cloud/Bunny account, telemetry, payment, model, camera, microphone, or screen grant is required.

The launcher is present, but `bunny-artifact.json` says `placeholder`. Launching explains that a verified upstream 0.2.0 Linux artifact is absent; it does not pretend Bunny started. When a verified artifact is later installed, Tauri Desktop supervises its Core/app-server sidecars.

Bunny Shell components are present in the developer image so launcher/search/workspace/settings/terminal safety logic and degraded mode can be tested without the Bunny artifact. `shell` and `shell-test` profiles provide explicit Phase 2 image/evidence outputs. None was composed on the current host.

Target VM: QEMU/KVM, UEFI/OVMF, q35, 4 vCPU, 6 GiB RAM (8+ preferred), virtio disk/network/GPU, 64 GiB disk. `build/scripts/vm-smoke.sh` is noninteractive boot-marker coverage; the full manual matrix is in `docs/TESTING.md`.
