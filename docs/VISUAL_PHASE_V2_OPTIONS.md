# Visual Phase V2 options

Visual Phase V2 is a **custom Bunny Wayland shell feasibility prototype**, not
an authorization to replace the V1 stack.

Candidate investigations:

1. A wlroots-based shell prototype focused on input, output, window-management,
   accessibility, and secure session lifecycle feasibility.
2. A Mutter-based custom shell mode that preserves GNOME platform integration
   while expanding compositor-level layout control.
3. A Smithay prototype for a smaller Rust-owned compositor surface.

Before selection, V2 must compare screen-reader interoperability, input methods,
fractional scaling, color management, remote desktop, multi-GPU behavior,
security maintenance load, and recovery fallback. V1 remains the reference for
interaction and visual-language evaluation. No V2 option is release-qualified
by this document.
