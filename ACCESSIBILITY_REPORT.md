# Bunny OS Phase 2 accessibility report

Date: 2026-07-28  
Target: WCAG 2.2 AA for Bunny-owned surfaces plus GNOME Linux accessibility integration

## Source/host status

PASS: GTK controls have programmatic labels; launcher rows have keyboard activation; focus is explicit in Light/Dark/High Contrast CSS; status uses text as well as color; text scale accepts 75–200%; reduced motion/transparency are settings; System and High Contrast themes exist; lock notification detail is removed; Super+A/Super+L/Super+V GNOME shortcuts are retained; every proposed gesture has keyboard/mouse alternatives; AT-SPI, Orca, and mousetweaks are in the image package definition. Three automated accessibility source tests pass.

## Not tested

Orca announcement/reading order, keyboard-only end-to-end flows, GDM/login/lock accessibility, focus after dynamic updates, 200% reflow, high-contrast screenshots/contrast sampling, magnification, switch access, touch exploration, captions, reduced-motion runtime, mixed-DPI text, and physical assistive devices. The image did not boot and GTK was not available on this host.

## Disposition

The source has an accessibility foundation but no runtime conformance claim. Phase 2 release remains blocked until the Fedora GNOME/Orca matrix passes with recorded defects and retests.

## Phase 3 addendum

The live welcome and resumable GTK first-run source use native labelled controls, headings, text progress, wrapped descriptions, and no timed completion; Anaconda Web UI is the selected primary installer. No installer/first-run GTK session, disk table, encryption/recovery fields, keyboard-only flow, Orca announcement, focus/error recovery, 200% reflow, high contrast, reduced motion, localisation, GDM/live login, or assistive hardware test ran. `FIRST_RUN_ACCESSIBILITY_REPORT.md` records the blocker; no conformance claim is added.
