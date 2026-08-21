// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The theme in force, for the things CSS cannot reach.
//
// Most of the desktop is styled by a stylesheet, and a stylesheet can be
// replaced wholesale when a setting changes. Four surfaces cannot be: the
// character, the CPU and memory dials, the network sparkline and the speech
// bubble's tail are painted with Cairo, and Cairo wants three floats, not a
// class name.
//
// Those four are exactly the surfaces that stayed violet-on-black in the
// previous accessibility run no matter what the contrast setting said, because
// their colours came from a frozen `Rgb` table in lib/tokens.js. A high-contrast
// desktop with a violet character on it is not a high-contrast desktop.
//
// So the resolved theme is kept here, the theme manager writes it on every
// change, and a painter asks for a *role*. A module-level singleton is honest
// about the shape of the problem: there is one stage, one theme context and one
// desktop per session, and threading a theme argument through five layers of
// paint callbacks would buy nothing that is not already guaranteed.

import {composite, parseColour} from './contrast.js';
import {resolveTheme} from './theme.js';

// The default session's theme, so a painter that runs before the theme manager
// has read a single setting still gets sensible numbers rather than undefined.
let active = resolveTheme({});

/** Called by ThemeManager after every successful render. */
export function setCurrentTheme(theme) {
    if (theme && theme.colour)
        active = theme;
}

export function currentTheme() {
    return active;
}

/**
 * A semantic colour as Cairo floats, opaque.
 *
 * A translucent role is composited over the theme's own background first, so a
 * painter never has to decide what a 30 %-alpha violet means on its own.
 */
export function rgb(role) {
    const value = active.colour[role];
    if (value === undefined)
        throw new Error(`no such colour role: ${role}`);
    const {r, g, b} = parseColour(composite(value, active.colour.surfacePrimary));
    return [r / 255, g / 255, b / 255];
}

/** The same, keeping the alpha channel for a painter that wants to blend. */
export function rgba(role) {
    const value = active.colour[role];
    if (value === undefined)
        throw new Error(`no such colour role: ${role}`);
    const {r, g, b, a} = parseColour(value);
    return [r / 255, g / 255, b / 255, a];
}

/** A duration from the motion scale, already zero if motion is reduced. */
export function duration(role) {
    const value = active.motion[role];
    return typeof value === 'number' ? value : 0;
}
