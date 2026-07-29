# Privacy dashboard

The privacy dashboard combines truthful state from Bunny Core, GNOME portals/settings, and Bunny OS. It shows local/cloud mode, recent provider use, microphone/camera/screen-share status, indexed locations, active capability grants, plugin network grants, recent declared external transfers, diagnostic policy, and telemetry.

Defaults are telemetry `Disabled`, clipboard history off, no search locations, plugin network deny, no cloud upload, no background capture, and local diagnostics only. Sensitive clipboard entries are never logged; password fields are excluded and history remains opt-in. There is no cloud clipboard sync.

Local-only AI mode denies cloud providers, cloud failover, remote embeddings/transcription, and external model APIs. It does not disable ordinary applications, plugin-specific network grants, or OS updates. Offline mode additionally pauses update checks and external plugin/application integrations while preserving loopback Bunny services and defining LAN behavior separately. Neither label is shown as active unless the authoritative policy state confirms it.

Screenshot, screen sharing, camera, and microphone access use XDG Desktop Portal/GNOME permission surfaces with explicit source/device selection, visible indicators, revocation, and lock-screen blocking. The screen-cast portal itself presents the selection dialog and produces revocable sessions; Bunny adds no silent capture path. See [XDG ScreenCast portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html).
