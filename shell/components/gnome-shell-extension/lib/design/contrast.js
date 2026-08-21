// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// WCAG contrast, computed rather than asserted.
//
// This module imports nothing, so the ratios it produces can be measured under
// node by tests/accessibility/test_contrast.py against every semantic pair in
// every theme. That is the whole reason it is a module and not a comment: the
// last palette was checked by hand, the arithmetic was written into
// docs/DESIGN_SYSTEM.md ("4.36:1 and misses WCAG AA"), and nothing re-checked it
// when a colour moved.
//
// Two things it deliberately does *not* do.
//
// It does not treat a passing ratio as an accessibility result. §9 is explicit
// that automated contrast is necessary and not sufficient, and a palette that
// clears 4.5:1 can still be unreadable — that is what the booted screenshots in
// §33 are for.
//
// It does not guess a backdrop. A translucent panel has no contrast ratio on its
// own; it has one once you say what is behind it. `composite` makes the backdrop
// an argument so a caller cannot forget to supply one, and `contrastRatio`
// refuses a translucent colour outright rather than silently treating alpha as
// opaque — which is how the old hand-checked figures were computed and is why
// the panel text was measured against the wrong background.

/** WCAG 2.2 AA. Large text is >=18.66px bold or >=24px regular. */
export const AA_BODY = 4.5;
export const AA_LARGE = 3.0;
export const AA_NON_TEXT = 3.0;

const HEX = /^#(?:[0-9a-f]{3}|[0-9a-f]{4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
const RGB_FUNCTION = /^rgba?\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*(?:,\s*([0-9.]+)\s*)?\)$/i;

/**
 * Parse a CSS colour into `{r, g, b, a}` with channels 0-255 and alpha 0-1.
 *
 * Accepts the two forms the token layer uses and refuses everything else. A
 * colour this cannot parse is a colour nothing can check, so throwing is the
 * correct outcome — a `null` here would become an unchecked pair later.
 */
export function parseColour(value) {
    if (typeof value !== 'string')
        throw new TypeError(`not a colour: ${String(value)}`);
    const text = value.trim();

    if (HEX.test(text)) {
        const digits = text.slice(1);
        const wide = digits.length > 4;
        const step = wide ? 2 : 1;
        const channel = index => {
            const part = digits.substr(index * step, step);
            const byte = wide ? parseInt(part, 16) : parseInt(part + part, 16);
            return byte;
        };
        const hasAlpha = digits.length === 4 || digits.length === 8;
        return {
            r: channel(0),
            g: channel(1),
            b: channel(2),
            a: hasAlpha ? channel(3) / 255 : 1,
        };
    }

    const match = RGB_FUNCTION.exec(text);
    if (match === null)
        throw new TypeError(`unsupported colour syntax: ${text}`);
    return {
        r: Number(match[1]),
        g: Number(match[2]),
        b: Number(match[3]),
        a: match[4] === undefined ? 1 : Number(match[4]),
    };
}

/** `foreground` composited over `backdrop`, both CSS colours, result opaque. */
export function composite(foreground, backdrop) {
    const front = parseColour(foreground);
    const back = parseColour(backdrop);
    if (back.a !== 1)
        throw new TypeError(`a backdrop must be opaque; got ${backdrop}`);
    const mix = (a, b) => Math.round(front.a * a + (1 - front.a) * b);
    return `#${[mix(front.r, back.r), mix(front.g, back.g), mix(front.b, back.b)]
        .map(value => value.toString(16).padStart(2, '0'))
        .join('')}`;
}

function channelLuminance(byte) {
    const value = byte / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
}

/** WCAG relative luminance. Refuses a translucent colour; see the header. */
export function relativeLuminance(colour) {
    const {r, g, b, a} = parseColour(colour);
    if (a !== 1)
        throw new TypeError(`relativeLuminance needs an opaque colour; got ${colour}. Composite it first.`);
    return 0.2126 * channelLuminance(r) + 0.7152 * channelLuminance(g) + 0.0722 * channelLuminance(b);
}

/**
 * The contrast ratio between two opaque colours, 1.0 to 21.0.
 *
 * Rounded to two places because that is the precision a threshold is stated in,
 * and an unrounded 4.4999 reported as "4.5" was how the previous palette's near
 * misses stayed invisible.
 */
export function contrastRatio(first, second) {
    const a = relativeLuminance(first);
    const b = relativeLuminance(second);
    const light = Math.max(a, b);
    const dark = Math.min(a, b);
    return Math.round(((light + 0.05) / (dark + 0.05)) * 100) / 100;
}

/**
 * The ratio of `foreground` on `surface`, where either may be translucent and
 * `base` is the opaque thing they are ultimately drawn on.
 *
 * This is the call every real check wants: the Bunny panels are translucent over
 * a wallpaper-coloured background, and the honest question is what the text
 * measures against the *result*, not against the panel's nominal colour.
 */
export function effectiveRatio(foreground, surface, base) {
    const backdrop = composite(surface, base);
    return contrastRatio(composite(foreground, backdrop), backdrop);
}

/** True when `ratio` clears the threshold for text of this size and weight. */
export function passesText(ratio, {sizePx = 12, weight = 400} = {}) {
    const large = sizePx >= 24 || (sizePx >= 18.66 && weight >= 700);
    return ratio >= (large ? AA_LARGE : AA_BODY);
}
