# Accessibility

Bunny-owned interfaces target WCAG 2.2 AA and integrate with GNOME's AT-SPI, Orca, keyboard, magnification, high-contrast, text scaling, reduced-motion, and input-device settings. The image package list includes AT-SPI, Orca, and mousetweaks.

Implemented source controls include programmatic button/search labels, keyboard-activatable list rows, visible focus in all Bunny CSS themes, text wrapping, 75–200% text-scale validation, reduced motion, reduced transparency, high contrast, and text-plus-color status. Essential launcher, workspace, approvals, tasks, terminal, lock, screenshot, and settings paths have keyboard/mouse alternatives; no gesture is exclusive.

The retained GNOME base provides screen reader, focus navigation, lock/login accessibility, and magnification. Existing GNOME shortcuts such as Super+A (applications), Super+L (lock), Super+V (notifications), and workspace/monitor movement are not replaced. Bunny approvals use Super+Shift+A to avoid the conflict.

Host static tests verify labels, focus CSS, setting definitions, and keyboard activation hooks. No Orca session, switch device, login screen, magnifier, 200% scale, or real contrast screenshot was exercised on this Windows host. Those rows remain untested in `ACCESSIBILITY_REPORT.md`; static inspection is not conformance certification.
