# Visual V2 known limitations

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

- This host is Windows; no real GNOME Shell, GDM, Wayland, Orca, magnifier, or
  GTK/libadwaita session was executed here.
- Interaction latency and idle CPU targets have instrumentation but no live
  Linux measurement. Deterministic build time is not a substitute.
- Screenshot SVGs are mock review compositions, not captured functional state.
- The approval adapter is integrated by a fixed interface but was not exercised
  against a live backend.
- Network, Bluetooth, audio, media, update, and privacy values use the mock
  projection for visual scenarios.
- Character reference rights are not redistribution-cleared.
- GNOME Shell versions 45–48 are declared; runtime compatibility still needs a
  Linux test matrix.
- The preview package is a source-layout tarball, not an RPM, ISO, or release
  artifact.
