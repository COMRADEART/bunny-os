# Bunny Desktop V2 dual-mode contract

> VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN

`regular` and `character` are presentations of the same Bunny Desktop. They
never select different commands, providers, approval adapters, settings
backends, application binaries, or security behavior.

## Runtime invariants

1. `visual-mode` accepts only `regular` and `character`.
2. Regular Mode is the default and loads no character asset or placeholder.
3. Character Mode loads at most one approved pose into a bounded illustration
   region after the corresponding UI state is observed.
4. A settings change updates registered surfaces in place. GNOME Shell is not
   restarted and the preview session is not replaced.
5. Compact and Focus layouts may suppress character art without changing the
   selected visual mode.
6. All action dispatch, approvals, state observation, and privacy indicators
   remain identical in both modes.

The mode can be changed from Quick Settings, Control Center, Command Palette,
onboarding, or `Super+Alt+B`. Each entry point writes the same GSettings key.

