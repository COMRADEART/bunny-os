# Bunny OS Phase 3 first-run accessibility report

Date: 2026-07-28

## Source status

The GTK4/libadwaita flow uses native labels/buttons, explicit headings, non-colour progress text, Back/Next/Finish controls, wrapped descriptions, and no timed step. It is closable/resumable and the desktop remains usable. Live welcome exposes labelled keyboard-focusable buttons and describes storage safety. Installation strings are centralised for first-run steps, and Anaconda supplies the primary localised installer UI.

## Not tested

No GTK window ran on this host. Orca announcements/reading order, keyboard-only completion, focus after navigation/error, high contrast, 200% text/reflow, reduced motion, GDM/live login, password/recovery fields, disk table, progress/errors, locale switching, magnification, switch access, mixed DPI, and physical assistive devices are untested.

## Disposition

Source structure is suitable for a GNOME accessibility test pass; no WCAG 2.2 AA, EN 301 549, or release conformance claim is made. Runtime accessibility is a beta blocker.

