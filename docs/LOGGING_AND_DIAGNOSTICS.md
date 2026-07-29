# Logging and diagnostics

journald is primary for boot, broker, updater, health, recovery, firewalld, GNOME/GDM, and system services. Upstream Bunny owns its per-user Core/app-server/Desktop/sandbox/model/plugin logging and must preserve its existing redaction policy. `/var/log/bunny` is reserved for integrations that cannot use journald and expires after 14 days; caches expire after 30 days.

`bunny-os logs export` asks the broker for at most 24 hours of selected integration-unit logs plus release status. It never traverses home directories or Bunny databases. It removes credential-shaped values, writes fixed-name tar members with mode 0600/mtime 0, creates the archive in a fixed non-listable `/var/lib/bunny-os/support` directory, changes only that archive to the authenticated requester at mode 0600, and returns its local path. tmpfiles expires bundles after 14 days. Export needs Polkit and never uploads.

Excluded by design: raw credentials/tokens/environments, provider payloads, prompts, structured memory bodies, user-file contents, model inputs, browser history, camera/microphone/screen data. Phase 1 redaction is defense in depth, not proof that arbitrary third-party log text is safe; inspect a bundle before sharing.
