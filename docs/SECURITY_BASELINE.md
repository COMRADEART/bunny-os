# Security baseline

Fedora SELinux remains enforcing; firewalld drops unsolicited inbound; SSH/update timer/desktop autostart/telemetry are disabled; GNOME screen lock and normal password/Polkit policy remain distribution-managed. Root services use hardened systemd units and fixed environments. sysctl limits kernel pointer/dmesg/ptrace exposure, protected links/FIFOs/regular files, and unprivileged BPF without disabling accessibility or normal debugging under explicit admin control.

Core dumps follow Fedora defaults until crash-report privacy is tested; production should disable them for credential-bearing services or use encrypted/restricted storage. Removable media has no Bunny autorun. Browser/Tauri and Bunny capability security stay upstream responsibilities. Developer compilers are confined to the developer profile.

Automatic OS security updates are not enabled before signed-channel/recovery validation. That is safer than an unqualified updater but creates a patch-latency limitation. Production policy should check automatically with randomized delay, stage only verified images, notify locally, and require safe reboot/health behavior.

