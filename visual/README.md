# Bunny Desktop Visual Phase V1

> **VISUAL PROTOTYPE ONLY — NOT RELEASE QUALIFIED — DO NOT MERGE**

This workspace contains the design language, source assets, mock-state fixtures,
and review scenarios for Bunny Desktop Visual Phase V1. It is owned exclusively
by the long-lived `visual/bunny-desktop-v1` branch based on
`54907c30255c79f834fca2b71760b17ad78fed96`.

## Boundary

Visual V1 validates an original Bunny experience on the mature Wayland, GNOME
Shell, GJS, GTK 4, and libadwaita stack. It does not introduce a compositor,
replace authentication, modify release evidence, create a qualification target,
or change the default login session.

The selectable `Bunny Visual Preview` session is intentionally separate from
GNOME and from the existing Bunny production session. It is never selected or
enabled automatically.

## Source and output layout

- `tokens/` contains reviewed design-token sources and their JSON schema.
- `assets/` contains original, redistributable Bunny identity sources.
- `mockups/` contains explicit development-only fixtures and compositions.
- `screenshots/` contains scenario definitions and review manifests, not renders.
- `references/` records internal design decisions; third-party artwork is not
  vendored here.

Generated CSS, packages, rendered screenshots, and temporary preview state go
under `build/visual/`, which is ignored by Git. No generated review artifact is
used as functional or qualification evidence.

## Security invariant

Mock data is read only when `BUNNY_VISUAL_MOCK_MODE=1`. Every mock-capable
surface must show a persistent `VISUAL MOCK DATA` indicator. Production package
assembly rejects that environment variable. UI code may open fixed, audited
entry points but may not execute arbitrary or privileged commands.
