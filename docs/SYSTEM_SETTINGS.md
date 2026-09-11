# Bunny Settings

Bunny Settings uses a calm sidebar with progressive disclosure, matching Phase 1 tokens and Phase 2 Control Center contracts.

**You** (always visible): Bunny, AI & Models, Privacy, Accessibility.

**This computer** (folded away until opened): Network, Bluetooth, Displays, Sound, Power, Keyboard, Mouse and Touchpad, Appearance, Applications, Notifications, Users, Date and Time, Storage. Stable device modules deep-link to GNOME Control Center.

**System** (folded away): Updates, Recovery, Plugins, Permissions, System Information.

Bunny owns typed user preferences and the presentation of broker status. OS updates, previous deployments, rollback, recovery scheduling, and diagnostic export remain separate broker operations with Polkit. Bunny application updates are never merged into the OS update state.

The Bunny page covers character, voice, personality (presentation only — never a vendor or model name), animation intensity, position and size, interaction, proactivity (off or gentle; gentle may offer and never acts), memory pointers, local/online AI, and privacy pointers. Hide the figure and Search, Settings, and Trust still work.

AI & Models is one local-first control: Automatic (default), Local only, or Online enhanced. Advanced stays collapsed: model/adapter Unknown until a real id; tok/s Not measured or a measured figure; GPU/VRAM/NPU Unknown/Absent/Unusable; why-this-model Not available; session/durable online Off; conversation summary Unwired. Cloud memory (`cloud_context`) and Online for this request (`remote_dispatch`) are two consents. “No online models ever” is Local only — not Cloud memory off.

Settings schema 1 gives every value a type, default, validation function, reset behavior, policy owner, and scope. Atomic writes and backups precede reset/migration. Ordinary settings never store provider secrets; `defaultProviderAlias` is only a bounded alias. Secure OS storage remains Bunny Desktop's credential responsibility.

Local-only mode sets the local provider and disables cloud failover. Offline mode also disables cloud failover but does not disable loopback. Telemetry and clipboard history default off. Search-location authority remains Bunny Search. Values that the base desktop cannot enforce are labelled policy state rather than presented as OS enforcement.

Application network chrome is Off or On (full internet). Site allowlists aren’t available yet. Clipboard and Bluetooth, if shown, are unenforced.
