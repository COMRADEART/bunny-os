# Boot identity concept

These assets define an additive Bunny Visual Preview boot concept. They are not
activated by source checkout or package staging. A downstream disposable image
may install the Plymouth theme explicitly for visual review.

- Firmware handoff remains vendor-owned and is not modified.
- `bootloader-background.svg` is a safe optional background where the bootloader
  supports it; diagnostic and recovery entries must remain plain text.
- `bunny-visual-preview.plymouth` uses the Bunny mark and real boot-progress
  callbacks without displaying a percentage.
- `bunny-plymouth-high-contrast.svg` is the non-animated accessible fallback.
- Verbose boot remains available through the existing kernel command line and
  does not pass through this visual theme.
- Shutdown and recovery use the same identity geometry with explicit text; they
  never imitate success before shutdown or recovery actually completes.
