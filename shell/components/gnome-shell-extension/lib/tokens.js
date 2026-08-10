// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The desktop's visual constants, in one place.
//
// GNOME Shell's St stylesheet language is a subset of CSS: no custom
// properties, no calc(), no flexbox. So a token that only ever appears in
// stylesheet.css is written there, and a token the JavaScript needs — a
// duration to pass to ease(), a colour to hand to Cairo, a size to allocate —
// is written here. Anything appearing in both places is defined here and the
// stylesheet repeats the literal, with the token name in a comment beside it,
// because a drifted literal is easier to find than a missing abstraction.
//
// The palette is the brief's, with two deliberate changes recorded in
// docs/DESIGN_SYSTEM.md: SECONDARY_TEXT is lightened from #A9AFBC to #B4BAC6 so
// it clears WCAG AA (4.5:1) against the primary panel rather than missing it at
// 4.36:1, and ACCENT is used for fills while ACCENT_BRIGHT carries text and
// focus rings, because #8B5CF6 on the panel measures 3.4:1 and cannot carry
// body text.
//
// Nothing is listed here "for later". A token defined and never used is a
// colour nobody has looked at on a screen, and it reads in review as though the
// palette were larger than it is; test_every_palette_colour_appears_in_the_
// stylesheet fails the build for one.

export const Colour = {
    BACKGROUND: '#080B12',
    PANEL: 'rgba(17, 21, 32, 0.72)',
    PANEL_SECONDARY: 'rgba(27, 31, 45, 0.65)',
    BORDER: 'rgba(255, 255, 255, 0.10)',
    TEXT: '#F7F8FA',
    TEXT_SECONDARY: '#B4BAC6',
    ACCENT: '#8B5CF6',
    ACCENT_BRIGHT: '#A78BFA',
    SUCCESS: '#22C55E',
    WARNING: '#F59E0B',
    ERROR: '#EF4444',
};

// Cairo wants floats, not strings. Parsed once rather than in every paint.
export const Rgb = {
    ACCENT: [0.545, 0.361, 0.965],
    ACCENT_BRIGHT: [0.655, 0.545, 0.980],
    SUCCESS: [0.133, 0.773, 0.369],
    WARNING: [0.961, 0.620, 0.043],
    ERROR: [0.937, 0.267, 0.267],
    TEXT: [0.969, 0.973, 0.980],
    TEXT_SECONDARY: [0.706, 0.729, 0.776],
};

export const Space = {XS: 4, SM: 8, MD: 12, LG: 20, XL: 32};

// 12–24px by component size, per the brief.
export const Radius = {CONTROL: 12, SURFACE: 18, HERO: 24};

// The brief's animation budget. REDUCED is what every duration collapses to
// when the accessibility setting asks for less motion; it is zero rather than
// small because a 40ms fade is still a fade.
export const Motion = {
    HOVER_MS: 160,
    PANEL_MS: 240,
    ENTRANCE_MS: 320,
    CHARACTER_MS: 400,
    BUBBLE_MS: 260,
    REDUCED_MS: 0,
};

// Sizes the layout solver starts from at 1920x1080 and scales down.
export const Metric = {
    TOP_BAR_HEIGHT: 44,
    SIDEBAR_WIDTH: 196,
    SIDEBAR_COLLAPSED_WIDTH: 60,
    DOCK_ICON: 44,
    CARD_WIDTH: 300,
    CARD_GAP: 16,
    EDGE_GAP: 20,
    CHARACTER_WIDTH: 320,
    CHARACTER_HEIGHT: 460,
};
