# Bunny Settings

Bunny Settings presents Network, Bluetooth, Displays, Sound, Power, Keyboard, Mouse and Touchpad, Appearance, Applications, Notifications, Privacy, Users, Date and Time, Storage, Updates, Recovery, Bunny, Local Models, Plugins, Permissions, Accessibility, and System Information.

Stable device/user modules deep-link to GNOME Control Center. Bunny owns only its typed user preferences and the presentation of Phase 1 broker status. OS updates, previous deployments, rollback, recovery scheduling, and diagnostic export remain separate broker operations with Polkit. Bunny application updates are never merged into the OS update state.

Settings schema 1 gives every value a type, default, validation function, reset behavior, policy owner, and scope. Atomic writes and backups precede reset/migration. Ordinary settings never store provider secrets; `defaultProviderAlias` is only a bounded alias. Secure OS storage remains Bunny Desktop's credential responsibility.

Local-only mode sets the local provider and disables cloud failover. Offline mode also disables cloud failover but does not disable loopback. Telemetry and clipboard history default off. Search-location authority remains Bunny Search. Values that the base desktop cannot enforce are labelled policy state rather than presented as OS enforcement.
