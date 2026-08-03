# Bunny Desktop accessibility standard

Accessibility is a visual-architecture constraint for every Bunny-owned shell
and application surface. Visual V1 targets WCAG 2.2 AA where it applies to
desktop software and follows GNOME platform accessibility behavior.

## Input and focus

- Every action is reachable and operable by keyboard without timing-dependent
  gestures. Tab order follows the visible reading order.
- Focus is a 2 px high-contrast outline with 2 px separation. Focus is not
  indicated by color alone.
- `Escape` closes transient Command Palette, Assistant, and Approval surfaces
  and returns control to the desktop. Critical authorization flows retain focus
  until dismissed through an explicit neutral or negative action.
- Pointer targets are at least 40 × 40 logical px. Touch layouts use at least
  44 × 44 logical px. Text is not placed inside a drag-only target.
- Drag-and-drop has an equivalent application favorite and overview path.

## Names, roles, and state

All non-text shell controls and GTK controls receive programmatic names. Groups
are introduced by visible headings in reading order. State text includes the
status word; color, position, motion, and sound are supplementary.

Approval controls announce the request identifier and decision. Critical
approval starts on `Inspect details`, never `Approve`. Expired or disconnected
requests expose disabled controls with an explanation.

## Vision

- Normal text and all semantic status text meet 4.5:1 contrast against their
  intended canvas. Large text meets at least 3:1.
- Visible focus and non-text control boundaries meet at least 3:1.
- High-contrast mode removes shadows, uses explicit 2 px boundaries, and
  preserves system symbolic icons.
- Large text and 200% scaling reflow or scroll; content is not clipped or made
  unreachable. Monospace evidence can be selected and horizontally wrapped.
- Meaningful states include icon/shape and text, not color alone.

## Motion, sound, and cognition

Reduced-motion mode makes Bunny transitions immediate and does not suppress
state feedback. No visual surface flashes, autoplays, or continuously animates.
Event sounds are optional, nonessential, and never the sole signal. Labels use
stable verbs and expose consequence before action.

## Assistive technology

Owned GTK controls use AT-SPI-accessible names and descriptions. Shell controls
set accessible names on icon-only and compound actors. Testing includes Orca
navigation, screen magnifier, keyboard layout changes, and accessibility menu
reachability in the actual nested Fedora/GNOME preview; source checks do not
claim to replace runtime AT-SPI observation.

## Required test matrix

| Area | Automated baseline | Nested/manual baseline |
| --- | --- | --- |
| Keyboard and focus | shortcut, focus-class, and Escape assertions | full task walkthrough |
| Orca | accessible-name source assertions | spoken role/name/state review |
| Contrast | token contrast calculation | high-contrast visual review |
| Large text / scaling | logical layout bounds at 200% | 200% GNOME scaling |
| Reduced motion | zero-duration token and controller assertion | transition review |
| Color vision | status text/icon assertions | simulator review |
| Magnifier | panel bound and scroll assertions | GNOME magnifier walkthrough |
| Small screen | 1366 × 768 layout-model assertion | nested screenshot and keyboard pass |
| Touch | minimum target-token assertion | touchscreen/hardware pass when available |

Results from screenshot inspection are review artifacts, not functional proof.
