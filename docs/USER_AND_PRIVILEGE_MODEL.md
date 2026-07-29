# User and privilege model

- Regular user: owns one GNOME session, Bunny Desktop/Core/app-server, XDG Bunny data, user plugins/models, and portal grants.
- Administrative user: regular user who can authenticate through Fedora/Polkit/sudo policy. No passwordless unrestricted sudo is added.
- Root services: broker, update agent, health check, and recovery only. Their systemd units narrow files, syscalls, capabilities, devices, address families, and lifetime.
- Service identities: Fedora accounts such as GDM/NetworkManager remain noninteractive. The broker is root because its fixed backend coordinates systemd/bootc; it has an empty capability set and cannot expand caller input into a command.
- Plugins/model workers: separate sandbox processes and future SELinux domains, not privileged Linux groups. Stronger distinct UID isolation is Phase 2 work.
- Recovery identity: root on local console after firmware/disk/login trust gates; never a network login and never dependent on Bunny.

Each Linux user has separate `$XDG_CONFIG_HOME/bunny`, `$XDG_DATA_HOME/bunny`, `$XDG_CACHE_HOME/bunny`, credentials in that user's Secret Service, jobs, workspaces, notifications, and audit view. Shared models are not enabled. Root-owned machine audit logs may contain UID and method metadata but no user prompts/files/tokens.

The broker's read surface returns machine facts only. Mutations bind Polkit to PID, process start time, UID, and active session. Bunny is not added to `wheel`, `disk`, `docker`, `libvirt`, or another privileged group.

