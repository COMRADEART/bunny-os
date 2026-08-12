// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// One set of settings in, one fully resolved theme out.
//
// Everything a surface needs to draw itself is decided here and nowhere else: no
// component branches on `highContrast`, no component multiplies anything by the
// text scale, and no component knows that reduced transparency exists. They ask
// for `theme.type.body.size` and get a number.
//
// That is what makes the accessibility configurations testable without a
// display. `resolveTheme` imports nothing but the tokens and the contrast
// arithmetic, so tests/shell/test_design_theme.py can run it under node at 100,
// 125, 150 and 200 percent and measure that the numbers actually move — which is
// the claim the previous accessibility run could not make about the desktop.
//
// The one thing resolved here that is *not* a number is transparency. Reduced
// transparency does not mean "less alpha"; it means none, and a surface that was
// `rgba(17, 21, 32, 0.72)` over the background becomes the opaque colour that
// composites to. Computing it rather than listing a second palette means the two
// cannot disagree.

import {composite} from './contrast.js';
import {
    FOCUS, ICON, MAX_TEXT_SCALE, METRIC, MIN_TEXT_SCALE, MOTION, RADIUS,
    SPACE, SPACE_SCALE_RATE, THEMES, TYPE,
} from './tokens.js';

/** The four themes, keyed the way the settings pick one. */
export function themeNameFor({scheme = 'dark', highContrast = false} = {}) {
    const dark = scheme !== 'light';
    if (highContrast)
        return dark ? 'highContrastDark' : 'highContrastLight';
    return dark ? 'dark' : 'light';
}

/**
 * A text scale that is safe to multiply by.
 *
 * GNOME's `text-scaling-factor` is a double with no upper bound in the schema —
 * `gsettings set … 6.0` is a legal thing for a person or a script to do. Clamped
 * rather than trusted, because the layout solver's guarantee that nothing
 * overlaps is only tested up to 2.0 and a desktop that draws garbage is worse
 * than one that stops enlarging.
 */
export function clampTextScale(value) {
    const scale = Number(value);
    if (!Number.isFinite(scale) || scale <= 0)
        return 1;
    return Math.min(MAX_TEXT_SCALE, Math.max(MIN_TEXT_SCALE, scale));
}

/** Glyph-rate scaling: type and the boxes that hold it. */
function scaleType(base, scale) {
    return Math.max(1, Math.round(base * scale));
}

/**
 * Half-rate scaling: padding, gaps, radii.
 *
 * See SPACE_SCALE_RATE. At 200 % this gives 1.5x rather than 2x, which is the
 * difference between a large-text desktop and a desktop with three cards on it.
 */
function scaleSpace(base, scale) {
    return Math.max(1, Math.round(base * (1 + (scale - 1) * SPACE_SCALE_RATE)));
}

function opaque(colour, base) {
    return colour.startsWith('rgba(') ? composite(colour, base) : colour;
}

/**
 * Resolve a theme.
 *
 * @param {object} options
 * @param {'light'|'dark'} options.scheme
 * @param {boolean} options.highContrast
 * @param {number} options.textScale     org.gnome.desktop.interface text-scaling-factor
 * @param {boolean} options.reducedMotion
 * @param {boolean} options.reducedTransparency
 * @returns {object} a theme with every value already decided
 */
export function resolveTheme({
    scheme = 'dark',
    highContrast = false,
    textScale = 1,
    reducedMotion = false,
    reducedTransparency = false,
} = {}) {
    const name = themeNameFor({scheme, highContrast});
    const source = THEMES[name];
    const scale = clampTextScale(textScale);

    // High contrast implies opaque surfaces. A person who asked for maximum
    // separation between foreground and background did not ask for the
    // background to show through the foreground, and treating the two settings
    // as independent is how a "high contrast" theme ends up at 4:1.
    const flatten = reducedTransparency || source.highContrast;
    const base = source.colour.surfacePrimary;

    const colour = {};
    for (const [role, value] of Object.entries(source.colour))
        colour[role] = flatten ? opaque(value, base) : value;

    const type = {};
    for (const [role, spec] of Object.entries(TYPE)) {
        type[role] = {
            size: scaleType(spec.size, scale),
            weight: spec.weight,
            family: spec.role === 'mono' ? 'monospace' : 'inherit',
        };
    }

    const space = {};
    for (const [role, value] of Object.entries(SPACE))
        space[role] = scaleSpace(value, scale);

    const radius = {};
    for (const [role, value] of Object.entries(RADIUS))
        radius[role] = scaleSpace(value, scale);

    const metric = {};
    for (const [role, value] of Object.entries(METRIC.scaled))
        metric[role] = scaleType(value, scale);
    for (const [role, value] of Object.entries(METRIC.fixed))
        metric[role] = scaleSpace(value, scale);

    const icon = {};
    for (const [role, value] of Object.entries(ICON))
        icon[role] = scaleType(value, scale);

    // Reduced motion is zero, not shorter. The easings survive because a
    // zero-duration transition never consults them and a component that reads
    // `theme.motion.easeOut` should not have to check first.
    const motion = reducedMotion
        ? {...MOTION, instant: 0, fast: 0, normal: 0, slow: 0}
        : {...MOTION};

    return {
        name,
        scheme: source.scheme,
        highContrast: source.highContrast,
        reducedMotion,
        reducedTransparency: flatten,
        textScale: scale,
        colour,
        type,
        space,
        radius,
        metric,
        icon,
        motion,
        shadow: source.shadow,
        focus: {
            width: source.highContrast ? FOCUS.highContrastWidthPx : FOCUS.widthPx,
            offset: FOCUS.offsetPx,
            insetOffset: FOCUS.insetOffsetPx,
            colour: colour.focus,
        },
    };
}

/**
 * The settings this theme depends on, as a string.
 *
 * `themeManager` re-renders when this changes and does nothing when it does not,
 * so a settings signal that fires without changing anything — GNOME emits
 * several during startup — does not cost a stylesheet reload and a full restyle
 * of every actor on screen.
 */
export function themeKey(options) {
    const theme = resolveTheme(options);
    return [
        theme.name,
        theme.textScale.toFixed(3),
        theme.reducedMotion ? 'rm' : 'motion',
        theme.reducedTransparency ? 'opaque' : 'translucent',
    ].join(':');
}
