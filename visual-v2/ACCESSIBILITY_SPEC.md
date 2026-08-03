# Bunny Desktop V2 accessibility specification

> VISUAL PROTOTYPE ONLY
>
> NOT RELEASE QUALIFIED
>
> DO NOT MERGE INTO MAIN

Regular and Character modes have the same keyboard, focus, state, contrast,
scaling, and assistive-technology requirements. Character Mode cannot weaken a
requirement or add an interaction that Regular Mode lacks.

## Review matrix

- Keyboard-only navigation and logical focus order.
- Visible focus on top-bar controls, dock items, panel tabs, palette results,
  composer, approval controls, settings, and Welcome navigation.
- Orca labels that describe actions and state rather than filenames.
- Dark, intentional light, and high-contrast themes.
- Large text and 200% scaling without clipped controls.
- Reduced motion with no scale, parallax, spring, character entrance, or
  wallpaper movement.
- Icon-plus-text status communication suitable for common color-vision
  differences.
- Magnifier compatibility and non-overlapping bounded panels.
- 1366×768, 1920×1080, 2560×1440, and 3840×2160 at 200%.

The guide image is not focusable and has the accessibility role of a redundant
object. Its containing illustration region exposes a semantic sentence such as
“Bunny is explaining that approval is required.” No pose slug or filename is
exposed. Compact, Focus, and constrained logical-height layouts suppress the
region, leaving all controls available.

Critical approvals focus `Inspect details` first, require a separate
consequence-confirmation control, and never preselect approval.

`visual-v2/tools/a11y_audit.py` performs deterministic source and layout
checks. It does not claim an Orca or real-session result; those remain manual
Linux preview checks.
