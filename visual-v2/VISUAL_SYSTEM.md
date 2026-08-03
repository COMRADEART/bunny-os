# Bunny Desktop V2 visual system

> VISUAL PROTOTYPE ONLY · NOT RELEASE QUALIFIED · DO NOT MERGE INTO MAIN

Bunny Desktop uses a deep navy foundation, restrained violet and sky accents,
layered surfaces, and typography-led hierarchy. Translucency is limited to
desktop chrome; application content remains opaque enough for sustained
reading. Focus, privacy, warning, and failure states always pair color with an
icon and text.

All reusable values originate in `visual-v2/tokens/`. The generated GNOME Shell
stylesheet records the source token files at its header. Components select
semantic classes and do not embed visual constants.

## Themes

- Dark is the reference presentation: Bunny Night, Deep, Surface, Elevated,
  and Panel form a controlled depth ladder.
- Light is independently tuned around cool Cloud surfaces and dark navy text;
  it is not a mechanical inversion.
- High contrast removes translucency, strengthens borders and focus treatment,
  and retains semantic icons and labels.

## Composition

The top bar is 42 logical pixels, the normal dock uses 48-pixel targets, panels
use 22-pixel outer radii, cards use 16, and standard controls use 12. The
command palette is centered and never sends arbitrary text to a shell.

The wallpaper uses two original ribbon arcs with negative space. It contains no
text, logo, character, movement, or continuous GPU effect.

## Motion

Micro feedback is 120 ms, panels are 180 ms, visual-mode reflow is 240 ms, and
workspace movement is 280 ms. Reduced motion sets every nonessential duration
to zero and removes scale, parallax, spring, character entrance, and wallpaper
movement.

