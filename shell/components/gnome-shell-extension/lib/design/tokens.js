// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Bunny design system, as data. One source, four themes, no IO.
//
// ## Why this file exists and lib/tokens.js did not survive
//
// The desktop had a token module already. It described one theme, in absolute
// pixels, and `stylesheet.css` repeated every literal by hand with the token
// name in a comment — a pairing kept honest by a test rather than by a compiler.
// That arrangement cannot express a second theme, so when the accessibility run
// measured the desktop at `text-scaling-factor 1.5` and at high contrast, it
// found 0.09 % and 0.18 % of the screen changed against a 0.15 % noise floor.
// Nothing was broken. There was simply nothing there to change.
//
// So the values moved here and the stylesheet became output. `lib/design/
// stylesheet.js` renders CSS from a *resolved* theme, and `lib/themeManager.js`
// re-renders it whenever the scheme, the text scale, the contrast preference or
// the motion preference changes. The shipped `stylesheet.css` is now a small
// hand-written safety net rather than the desktop's appearance.
//
// ## No IO, deliberately
//
// Everything below is a JavaScript literal. GJS could read
// `/usr/share/bunny-shell/themes/tokens.json` at startup, and then a missing
// file, a bad mount or a JSON syntax error would be a desktop that draws no
// colours — during `enable()`, inside the try/catch that exists to hand the user
// back a working GNOME session. A design system is not worth a boot failure.
// `shell/themes/tokens.json` is generated *from* this file by
// `build/scripts/render_design_assets.mjs` for the Python consumers, and
// tests/shell/test_design_system.py fails if the two drift.
//
// ## Naming
//
// `PALETTE` holds primitives and is not exported: a component that could reach
// `violet600` would eventually reach for it, and §6 is explicit that components
// consume meaning rather than swatches. Every exported colour is a role.

export const SCHEMA_VERSION = 3;

// ---------------------------------------------------------------- primitives

// Internal. The only place a colour is named for how it looks.
//
// The Bunny accent is violet. That is a decision this phase had to make rather
// than inherit: there were two palettes, an evergreen/mint one in
// shell/themes/tokens.json that no display server had ever loaded, and this
// violet one, which is the palette in every screenshot the project has. Keeping
// the rendered one and retiring the paper one changes what nobody has seen
// rather than what everybody has. docs/DESIGN_SYSTEM.md records the change.
const PALETTE = {
    // Violet — the accent, and the only hue Bunny uses decoratively.
    violet300: '#C4B5FD',
    violet400: '#A78BFA',
    violet500: '#8B5CF6',
    // The fill behind white text. #8B5CF6 measures 4.23:1 against white and
    // misses AA for the 11px button role; the contrast gate found it, and one
    // step darker is the smallest change that fixes it everywhere at once.
    violet600: '#7C3AED',
    violet700: '#6D28D9',
    violet800: '#5B21B6',

    // Warm neutrals. The light foundation is not pure white; §44 asks for a
    // warm neutral surface and a paper-white desktop is fatiguing at length.
    warm50: '#F7F5F2',
    warm100: '#EFECE7',
    warm200: '#E2DED7',

    // Cool near-blacks. The dark foundation, unchanged from what shipped.
    ink900: '#080B12',
    ink800: '#111520',
    ink700: '#1B1F2D',
    ink100: '#F7F8FA',
    slate300: '#B4BAC6',
    slate400: '#8F96A4',

    plum900: '#161320',
    plum700: '#4A4658',
    plum600: '#6A6578',

    // Status. Chosen per theme rather than shared, because a green that reads
    // on near-black is not the green that reads on warm white.
    green400: '#22C55E',
    green700: '#15803D',
    amber400: '#F59E0B',
    amber700: '#A16207',
    red400: '#EF4444',
    red700: '#B91C1C',
    rose300: '#FDA4AF',
    rose800: '#9F1239',

    // High contrast. Black, white, cyan and yellow, as docs/DESIGN_SYSTEM.md
    // has specified since the first accessibility review.
    black: '#000000',
    white: '#FFFFFF',
    cyan: '#00FFFF',
    yellow: '#FFFF00',
    hcGreen: '#00FF7F',
    hcAmber: '#FFD700',
    // Each of these three was chosen by eye and then moved by the gate. The
    // high-contrast themes have to beat the ordinary ones on every pair, and
    // #FF8A8A, #B00000 and #00308F each measured *worse* than the ordinary
    // theme's equivalent for the blocked and selection roles — a person
    // enabling high contrast would have got a downgrade on exactly the two
    // states that say a permission was refused.
    hcRed: '#FFAFAF',
    hcBlue: '#00308F',
    hcSelectionLight: '#002060',
    hcFocusLight: '#0000CC',
    hcGreenDark: '#006400',
    hcAmberDark: '#7A4F00',
    hcRedDark: '#8B0000',
    near0: '#0A0A0A',
    near1: '#1A1A1A',
    nearWhite: '#E6E6E6',
};

// --------------------------------------------------------------- typography

/**
 * Semantic type roles. `size` is the px size at 100 % scaling.
 *
 * Eight roles for what used to be eight distinct pixel values (9, 10, 11, 12,
 * 13, 14, 19, 24) chosen per widget. The two smallest — 9 px labels on quick
 * tiles, media times and file locations — were folded upward into `caption`,
 * because 9 px is below what the rest of the desktop asks anyone to read and
 * having a role for it would have made it permanent.
 *
 * `role` selects a family at render time: `ui` takes the system UI font, `mono`
 * the system monospace. Neither is bundled — §26, and Bunny ships no font file.
 */
export const TYPE = {
    display: {size: 24, weight: 600, role: 'ui'},
    title: {size: 19, weight: 700, role: 'ui'},
    heading: {size: 14, weight: 600, role: 'ui'},
    body: {size: 12, weight: 400, role: 'ui'},
    bodySmall: {size: 11, weight: 400, role: 'ui'},
    caption: {size: 10, weight: 500, role: 'ui'},
    button: {size: 11, weight: 600, role: 'ui'},
    mono: {size: 11, weight: 400, role: 'mono'},
};

/** Largest scale the type ramp is defined at. Beyond this the desktop reflows but does not grow. */
export const MAX_TEXT_SCALE = 2.0;
export const MIN_TEXT_SCALE = 0.75;

// ------------------------------------------------------------------ spacing

/** §10. One scale, used everywhere; no per-component margins. */
export const SPACE = {xxs: 2, xs: 4, sm: 8, md: 12, lg: 20, xl: 32, xxl: 48};

/**
 * How fast whitespace grows relative to glyphs.
 *
 * Half-rate. Padding that scaled 1:1 with type turned a 200 % desktop into three
 * cards and a lot of air; padding that did not scale at all left 24 px text
 * touching a 1 px border. Neither is what a person who enlarged the text asked
 * for, and the midpoint is.
 */
export const SPACE_SCALE_RATE = 0.5;

// ------------------------------------------------------------------- shape

/**
 * §11. Radius carries hierarchy: the further a surface is from the page, the
 * softer its corner. Controls are the exception — they are small, and a small
 * shape with a large radius reads as a pill rather than as a button.
 */
export const RADIUS = {
    control: 12,
    card: 18,
    panel: 22,
    floating: 20,
    modal: 24,
};

// --------------------------------------------------------------- elevation

/**
 * §12. Four levels, and only `dialog` is raised without being asked — that is
 * the Trust prompt, the one thing in Bunny OS permitted to interrupt.
 *
 * Shadows are stated per theme rather than here, because a shadow on a near-
 * black desktop and a shadow on warm white are not the same shadow, and at high
 * contrast there are no shadows at all — a border does the separating, since a
 * shadow is exactly the cue a person using high contrast cannot see.
 */
export const ELEVATION_LEVELS = ['base', 'raised', 'overlay', 'dialog'];

// ------------------------------------------------------------------ motion

/**
 * §14. Four durations and two easings, named for what the movement is doing.
 *
 * `REDUCED` is what every duration collapses to when the system asks for less
 * motion. It is zero rather than small because a 40 ms fade is still a fade, and
 * the setting is not "please hurry".
 */
export const MOTION = {
    instant: 0,
    fast: 120,
    normal: 220,
    slow: 360,
    reduced: 0,
    easeOut: 'ease-out',
    easeInOut: 'ease-in-out',
};

// ------------------------------------------------------------------- focus

/**
 * §13. One treatment, everywhere, in every theme.
 *
 * Three pixels at high contrast rather than two, and the ring colour is the one
 * token that is never the accent: a focus ring that shares a colour with a
 * selected row is a focus ring you have to hunt for.
 */
export const FOCUS = {
    widthPx: 2,
    highContrastWidthPx: 3,
    offsetPx: 2,
    insetOffsetPx: -1,
};

// ----------------------------------------------------------------- metrics

/**
 * Chrome dimensions at 100 % scaling.
 *
 * `scaled` names the ones that contain text and must grow with it. `fixed` names
 * the ones that do not — gaps and icon boxes — which grow at the spacing rate or
 * not at all. Getting this list wrong is how a 200 % desktop ends up with a
 * sidebar wider than its content, so it is stated rather than inferred.
 */
export const METRIC = {
    scaled: {
        topBarHeight: 44,
        sidebarWidth: 196,
        sidebarCollapsedWidth: 60,
        dockHeight: 64,
        cardWidth: 304,
        quickTileWidth: 55,
        searchWidth: 300,
        searchResultsWidth: 560,
        notificationWidth: 360,
        bubbleMaxWidth: 300,
        turnMaxWidth: 240,
    },
    fixed: {
        dockIcon: 44,
        cardGap: 16,
        edgeGap: 20,
        quickTileGap: 6,
        characterMinWidth: 300,
    },
};

/** Icon sizes by role, scaled with type so an icon beside a label stays its size. */
export const ICON = {small: 14, medium: 18, large: 26};

// ------------------------------------------------------------------ themes

/**
 * The four themes, by semantic role. §6: a component asks for `textSecondary`,
 * never for `slate300`.
 *
 * `shadow` values are per level and per theme; high contrast sets them all to
 * `none` and pays for the separation with a visible border instead.
 */
export const THEMES = {
    dark: {
        name: 'dark',
        scheme: 'dark',
        highContrast: false,
        colour: {
            surfacePrimary: PALETTE.ink900,
            surfaceSecondary: 'rgba(17, 21, 32, 0.72)',
            surfaceRaised: 'rgba(27, 31, 45, 0.65)',
            surfaceOverlay: 'rgba(17, 21, 32, 0.94)',
            surfaceHover: 'rgba(255, 255, 255, 0.07)',
            surfaceActive: 'rgba(255, 255, 255, 0.12)',
            textPrimary: PALETTE.ink100,
            textSecondary: PALETTE.slate300,
            textMuted: PALETTE.slate400,
            textOnAccent: PALETTE.white,
            textOnSelection: PALETTE.white,
            border: 'rgba(255, 255, 255, 0.06)',
            // 0.36, not 0.18. This is a control boundary — the search entry,
            // the approval card — and at 0.18 it measured 1.72:1 against the
            // panel, which is a line you can see only if you know it is there.
            borderStrong: 'rgba(255, 255, 255, 0.36)',
            focus: PALETTE.violet400,
            accent: PALETTE.violet600,
            accentText: PALETTE.violet400,
            accentSoft: 'rgba(139, 92, 246, 0.16)',
            success: PALETTE.green400,
            warning: PALETTE.amber400,
            danger: PALETTE.red400,
            blocked: PALETTE.rose300,
            trust: PALETTE.violet400,
            selection: 'rgba(139, 92, 246, 0.30)',
            scrim: 'rgba(8, 11, 18, 0.72)',
            wallpaperStart: '#141033',
            wallpaperEnd: PALETTE.ink900,
        },
        shadow: {
            base: 'none',
            raised: '0 10px 32px rgba(0, 0, 0, 0.50)',
            overlay: '0 14px 40px rgba(0, 0, 0, 0.58)',
            dialog: '0 24px 64px rgba(0, 0, 0, 0.66)',
        },
    },

    light: {
        name: 'light',
        scheme: 'light',
        highContrast: false,
        colour: {
            surfacePrimary: PALETTE.warm50,
            surfaceSecondary: 'rgba(255, 255, 255, 0.90)',
            surfaceRaised: PALETTE.white,
            surfaceOverlay: 'rgba(255, 255, 255, 0.97)',
            surfaceHover: 'rgba(22, 19, 32, 0.06)',
            surfaceActive: 'rgba(22, 19, 32, 0.11)',
            textPrimary: PALETTE.plum900,
            textSecondary: PALETTE.plum700,
            textMuted: PALETTE.plum600,
            textOnAccent: PALETTE.white,
            // The light selection is a 18 % violet wash, not a solid fill, so
            // the text on it stays dark. White here would be the same defect
            // the gate caught in the high-contrast themes, in the other
            // direction.
            textOnSelection: PALETTE.plum900,
            border: 'rgba(22, 19, 32, 0.12)',
            borderStrong: 'rgba(22, 19, 32, 0.52)',
            focus: PALETTE.violet700,
            accent: PALETTE.violet700,
            accentText: PALETTE.violet800,
            accentSoft: 'rgba(109, 40, 217, 0.12)',
            success: PALETTE.green700,
            warning: PALETTE.amber700,
            danger: PALETTE.red700,
            blocked: PALETTE.rose800,
            trust: PALETTE.violet800,
            selection: 'rgba(109, 40, 217, 0.18)',
            scrim: 'rgba(22, 19, 32, 0.40)',
            wallpaperStart: PALETTE.warm100,
            wallpaperEnd: PALETTE.warm200,
        },
        shadow: {
            base: 'none',
            raised: '0 2px 6px rgba(22, 19, 32, 0.08), 0 12px 32px rgba(22, 19, 32, 0.08)',
            overlay: '0 4px 10px rgba(22, 19, 32, 0.10), 0 18px 44px rgba(22, 19, 32, 0.12)',
            dialog: '0 8px 24px rgba(22, 19, 32, 0.16), 0 32px 64px rgba(22, 19, 32, 0.18)',
        },
    },

    highContrastDark: {
        name: 'highContrastDark',
        scheme: 'dark',
        highContrast: true,
        colour: {
            surfacePrimary: PALETTE.black,
            surfaceSecondary: PALETTE.black,
            surfaceRaised: PALETTE.near0,
            surfaceOverlay: PALETTE.black,
            surfaceHover: PALETTE.near1,
            surfaceActive: PALETTE.cyan,
            textPrimary: PALETTE.white,
            textSecondary: PALETTE.white,
            textMuted: PALETTE.nearWhite,
            textOnAccent: PALETTE.black,
            textOnSelection: PALETTE.black,
            border: PALETTE.white,
            borderStrong: PALETTE.white,
            focus: PALETTE.yellow,
            accent: PALETTE.cyan,
            accentText: PALETTE.cyan,
            accentSoft: PALETTE.black,
            success: PALETTE.hcGreen,
            warning: PALETTE.hcAmber,
            danger: PALETTE.hcRed,
            blocked: PALETTE.hcRed,
            trust: PALETTE.cyan,
            selection: PALETTE.cyan,
            scrim: 'rgba(0, 0, 0, 0.92)',
            wallpaperStart: PALETTE.black,
            wallpaperEnd: PALETTE.black,
        },
        shadow: {base: 'none', raised: 'none', overlay: 'none', dialog: 'none'},
    },

    highContrastLight: {
        name: 'highContrastLight',
        scheme: 'light',
        highContrast: true,
        colour: {
            surfacePrimary: PALETTE.white,
            surfaceSecondary: PALETTE.white,
            surfaceRaised: PALETTE.white,
            surfaceOverlay: PALETTE.white,
            surfaceHover: '#E8E8E8',
            surfaceActive: PALETTE.hcBlue,
            textPrimary: PALETTE.black,
            textSecondary: PALETTE.black,
            textMuted: PALETTE.near1,
            textOnAccent: PALETTE.white,
            textOnSelection: PALETTE.white,
            border: PALETTE.black,
            borderStrong: PALETTE.black,
            focus: PALETTE.hcFocusLight,
            accent: PALETTE.hcBlue,
            accentText: PALETTE.hcBlue,
            accentSoft: PALETTE.white,
            success: PALETTE.hcGreenDark,
            warning: PALETTE.hcAmberDark,
            danger: PALETTE.hcRedDark,
            blocked: PALETTE.hcRedDark,
            trust: PALETTE.hcBlue,
            selection: PALETTE.hcSelectionLight,
            scrim: 'rgba(255, 255, 255, 0.92)',
            wallpaperStart: PALETTE.white,
            wallpaperEnd: PALETTE.white,
        },
        shadow: {base: 'none', raised: 'none', overlay: 'none', dialog: 'none'},
    },
};

/** Every semantic colour role, so a test can assert a theme defines all of them. */
export const COLOUR_ROLES = Object.freeze(Object.keys(THEMES.dark.colour));

// --------------------------------------------------------- semantic meaning

/**
 * §19. Risk gets a colour *and* a marker shape.
 *
 * The marker is the point. A permission prompt is the worst place in the system
 * to encode severity as a hue, because the person who cannot distinguish that
 * hue is the person being asked to make a security decision.
 */
export const RISK = {
    low: {token: 'trust', marker: false, label: 'Low risk'},
    medium: {token: 'trust', marker: false, label: 'Medium risk'},
    high: {token: 'warning', marker: true, label: 'High risk'},
    critical: {token: 'danger', marker: true, label: 'Critical risk'},
};

/**
 * §19. What a permission is standing at, as a glyph, a word and a colour.
 *
 * `unenforced` coexists with `granted` rather than replacing it: "allowed, and
 * this build cannot actually restrict it" is two facts, and collapsing them into
 * one row is how a person ends up believing a restriction is in force.
 */
export const STANDING = {
    granted: {token: 'success', glyph: 'check', label: 'Allowed'},
    denied: {token: 'textSecondary', glyph: 'slash', label: 'Not allowed'},
    blocked: {token: 'blocked', glyph: 'block', label: 'Blocked'},
    'not-asked': {token: 'textMuted', glyph: 'dash', label: 'Not asked'},
    'not-declared': {token: 'textMuted', glyph: 'dash', label: 'Not declared'},
    unenforced: {token: 'warning', glyph: 'warning', label: 'Declared, not enforced'},
    unavailable: {token: 'textMuted', glyph: 'dash', label: 'Unavailable'},
};

/**
 * One entry per `companion.presentation.PRESENTATION_PHASES` value, so a phase
 * the runtime can produce always has something to draw.
 *
 * `attention` is the only intensity permitted to pulse, and only when the motion
 * budget is non-zero — see §15, and `lib/animation.js`, which is where the
 * budget is actually enforced.
 */
export const COMPANION_PHASE = {
    idle: {token: 'trust', intensity: 'quiet'},
    starting: {token: 'textMuted', intensity: 'quiet'},
    recovering: {token: 'warning', intensity: 'quiet'},
    understanding: {token: 'trust', intensity: 'active'},
    planning: {token: 'trust', intensity: 'active'},
    waiting_for_approval: {token: 'warning', intensity: 'attention'},
    listening: {token: 'focus', intensity: 'active'},
    speaking: {token: 'trust', intensity: 'active'},
    working: {token: 'trust', intensity: 'active'},
    reviewing: {token: 'trust', intensity: 'quiet'},
    presenting_result: {token: 'trust', intensity: 'active'},
    success: {token: 'success', intensity: 'active'},
    cancelling: {token: 'textMuted', intensity: 'quiet'},
    cancelled: {token: 'textMuted', intensity: 'quiet'},
    paused: {token: 'textMuted', intensity: 'quiet'},
    blocked: {token: 'blocked', intensity: 'attention'},
    error: {token: 'danger', intensity: 'attention'},
    disconnected: {token: 'textMuted', intensity: 'quiet'},
};

/** §16. Companion presentation sizes, in px at 100 % scaling. */
export const COMPANION_SIZE = {full: 220, compact: 128, minimal: 48, indicator: 28};

export const OPACITY = {
    surface: 0.86,
    surfaceReducedTransparency: 1.0,
    disabled: 0.45,
    unavailable: 0.38,
};

/** WCAG 2.2 AA, restated as data so the gate and the docs cannot disagree. */
export const CONTRAST_THRESHOLDS = {
    minimumBodyRatio: 4.5,
    minimumLargeTextRatio: 3.0,
    minimumNonTextRatio: 3.0,
};

/**
 * Text roles paired with the surface they are drawn on, for the contrast gate.
 *
 * This table is the reason the gate finds anything: checking every colour
 * against every surface would produce mostly meaningless pairs and a number
 * nobody trusts. These are the pairs that actually occur on screen.
 */
export const CONTRAST_PAIRS = [
    {text: 'textPrimary', surface: 'surfaceSecondary', type: 'body'},
    {text: 'textSecondary', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'textMuted', surface: 'surfaceSecondary', type: 'caption'},
    {text: 'textPrimary', surface: 'surfaceRaised', type: 'body'},
    {text: 'textSecondary', surface: 'surfaceRaised', type: 'bodySmall'},
    {text: 'textMuted', surface: 'surfaceRaised', type: 'caption'},
    {text: 'textPrimary', surface: 'surfacePrimary', type: 'body'},
    {text: 'textSecondary', surface: 'surfacePrimary', type: 'bodySmall'},
    {text: 'accentText', surface: 'surfaceSecondary', type: 'button'},
    {text: 'accentText', surface: 'surfaceRaised', type: 'button'},
    {text: 'success', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'warning', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'danger', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'blocked', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'trust', surface: 'surfaceSecondary', type: 'bodySmall'},
    {text: 'textOnAccent', surface: 'accent', type: 'button'},
    {text: 'textOnSelection', surface: 'selection', type: 'body'},
];

/**
 * Non-text pairs: a border or a focus ring has to be visible too, and 3:1 is
 * the threshold for a control boundary rather than 4.5:1.
 */
export const NON_TEXT_PAIRS = [
    {mark: 'focus', surface: 'surfaceSecondary'},
    {mark: 'focus', surface: 'surfacePrimary'},
    {mark: 'focus', surface: 'surfaceRaised'},
    {mark: 'borderStrong', surface: 'surfaceSecondary'},
    {mark: 'accent', surface: 'surfaceSecondary'},
];
