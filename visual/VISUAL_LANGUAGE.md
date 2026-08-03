# Bunny visual language

## Hierarchy before decoration

Bunny surfaces communicate with spacing, typography, grouped geometry, and
explicit status labels. Shadows are used only to separate an overlay from its
working plane. Gradients belong to identity artwork, not ordinary controls.
Glass effects and glowing borders are excluded from operational UI.

## Surfaces

The desktop has three elevation bands:

1. Canvas — wallpaper and workspace background.
2. Surface — panels, lists, and ordinary cards.
3. Elevated — modal palettes, approval decisions, and temporary overlays.

Small controls use 9 px radii, cards use 16 px, large panels use 22 px, and
true pills are reserved for tags, modes, and compact binary state. A control's
shape reflects its role; the interface does not round everything into pills.

## Type

Adwaita Sans is the UI family and Adwaita Mono is used for paths, commands,
identifiers, measurements, and evidence. The operational scale is compact:

| Role | Size | Weight | Use |
| --- | ---: | ---: | --- |
| Display | 32 px | 600 | Welcome and rare empty states |
| Title | 24 px | 600 | Primary surface title |
| Heading | 18 px | 600 | Section title |
| Body | 15 px | 400 | Content and descriptions |
| Label | 14 px | 600 | Controls and compact status |
| Caption | 12 px | 400 | Secondary metadata |
| Monospace | 13 px | 400 | Data, paths, identifiers |

## Iconography

Use platform symbolic icons for shell controls, settings, device status,
privacy, approvals, diagnostics, and assistant actions. Bunny-owned symbolic
icons use a 16 or 20 px optical grid, 2 px nominal stroke, rounded joins, and a
single current-color fill. Meaning must survive high contrast.

Full-color icons are limited to Bunny applications, onboarding, About, and
large empty states. Standard application icons are never redrawn merely to
match Bunny.

## Motion

Micro feedback is 120 ms, panels are 200 ms, and workspace movement is 260 ms.
Motion explains origin, destination, and state change; it never blocks input.
Reduced-motion mode sets transition duration to zero and replaces spatial
travel with immediate state change and retained focus.

## Responsive density

Normal, CompactLayout, and FocusMode are component variants, not scalar zoom.
CompactLayout reduces gaps, margins, row height, and dock footprint while
preserving typography legibility and 40 px minimum pointer targets. FocusMode
reduces persistent chrome while retaining critical state and a visible exit.
