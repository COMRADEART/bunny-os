// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Where everything goes, as arithmetic.
//
// This module imports nothing. Not St, not Clutter, not GLib. That is the
// point: "no widget overlaps another at 1920x1080" is a claim about geometry,
// and a claim about geometry that can only be checked by starting a display
// server and looking at it is a claim that gets checked once. `solve` is a pure
// function from a screen rectangle to a set of rectangles, so
// tests/shell/test_desktop_layout.py runs it under node against a table of
// resolutions and asserts on every pair — see PANEL_KEYS for the pairs it
// covers.
//
// The layout is three vertical bands. The sidebar owns the left edge, the two
// card columns own fixed-width strips inboard of it, and the character owns
// whatever is left in the middle. Bands are computed in that order and never
// negotiate, so a card column cannot grow into the character and a wide
// character cannot push a card off-screen. What gives instead is the card list:
// when a column's stack is taller than the band, cards are dropped from the end
// of a declared priority order and `dropped` says which, because a widget that
// silently vanishes is a bug report nobody can write.

/** Card stacks, in the order they are placed and the reverse order they are dropped. */
export const LEFT_COLUMN = ['systemOverview', 'quickAccess', 'media'];
export const RIGHT_COLUMN = ['agenda', 'systemMonitor', 'assistant'];

/** Every rectangle `solve` returns that must not overlap any other. */
export const PANEL_KEYS = [
    'topBar', 'sidebar', 'dock', 'character',
    ...LEFT_COLUMN, ...RIGHT_COLUMN,
];

/** Natural heights at the reference resolution. Scaled by the density factor. */
const CARD_HEIGHT = {
    systemOverview: 236,
    quickAccess: 168,
    media: 132,
    agenda: 196,
    systemMonitor: 200,
    assistant: 232,
};

const BREAKPOINTS = [
    // Chosen from the four resolutions the brief names, plus a floor.
    {minWidth: 1800, name: 'wide', cardWidth: 304, density: 1.0, sidebar: 'expanded'},
    {minWidth: 1500, name: 'standard', cardWidth: 276, density: 0.94, sidebar: 'expanded'},
    {minWidth: 1200, name: 'compact', cardWidth: 248, density: 0.88, sidebar: 'collapsed'},
    {minWidth: 0, name: 'narrow', cardWidth: 232, density: 0.82, sidebar: 'collapsed'},
];

const TOP_BAR_HEIGHT = 44;
const SIDEBAR_EXPANDED = 196;
const SIDEBAR_COLLAPSED = 60;
const DOCK_HEIGHT = 64;
const EDGE = 20;
const GAP = 16;

/** The narrowest the character band may be before card columns start dropping. */
const CHARACTER_MIN_WIDTH = 300;

export function breakpointFor(width) {
    return BREAKPOINTS.find(point => width >= point.minWidth) ?? BREAKPOINTS[BREAKPOINTS.length - 1];
}

/**
 * @param {{width: number, height: number}} screen work area of the primary monitor
 * @param {{scale?: number}} options `scale` is the text scaling factor, applied
 *   to card heights only: larger text makes cards taller, which is exactly the
 *   condition under which one has to be dropped.
 * @returns {{breakpoint: string, sidebarMode: string, rects: object, dropped: string[]}}
 */
export function solve(screen, {scale = 1} = {}) {
    const width = Math.max(640, Math.round(screen.width));
    const height = Math.max(480, Math.round(screen.height));
    const point = breakpointFor(width);
    const sidebarWidth = point.sidebar === 'expanded' ? SIDEBAR_EXPANDED : SIDEBAR_COLLAPSED;

    const rects = {};
    const dropped = [];

    rects.topBar = {x: 0, y: 0, width, height: TOP_BAR_HEIGHT};

    const bandTop = TOP_BAR_HEIGHT + EDGE;
    const dockTop = height - DOCK_HEIGHT - EDGE;
    const bandHeight = dockTop - bandTop - GAP;

    rects.sidebar = {
        x: EDGE,
        y: bandTop,
        width: sidebarWidth,
        height: bandHeight,
    };

    // The dock is centred on the whole screen rather than on the area right of
    // the sidebar. It is chrome the sidebar is not part of, and a dock that
    // shifted right when the sidebar expanded would read as a bug.
    const dockWidth = Math.min(width - 2 * EDGE, 560);
    rects.dock = {
        x: Math.round((width - dockWidth) / 2),
        y: dockTop,
        width: dockWidth,
        height: DOCK_HEIGHT,
    };

    // Card columns. Both are dropped entirely before the character is squeezed
    // below CHARACTER_MIN_WIDTH, right column first, because the brief's
    // ordering puts system status ahead of agenda and assistant.
    const contentLeft = EDGE + sidebarWidth + GAP;
    const contentRight = width - EDGE;
    let cardWidth = point.cardWidth;
    let columns = 2;
    const fits = count => contentRight - contentLeft - count * (cardWidth + GAP) >= CHARACTER_MIN_WIDTH;
    while (columns > 0 && !fits(columns)) {
        if (cardWidth > 210)
            cardWidth -= 12;
        else
            columns -= 1;
    }

    const leftColumnX = contentLeft;
    const rightColumnX = contentRight - cardWidth;

    const place = (keys, columnX, active) => {
        if (!active) {
            dropped.push(...keys);
            return;
        }
        let y = bandTop;
        for (const key of keys) {
            const cardHeight = Math.round(CARD_HEIGHT[key] * point.density * scale);
            if (y + cardHeight > bandTop + bandHeight) {
                dropped.push(key);
                continue;
            }
            rects[key] = {x: columnX, y, width: cardWidth, height: cardHeight};
            y += cardHeight + GAP;
        }
    };

    place(LEFT_COLUMN, leftColumnX, columns >= 2);
    place(RIGHT_COLUMN, rightColumnX, columns >= 1);

    // Whatever the columns left. The character keeps the middle even when both
    // columns are gone, which is the brief's "keep character visible".
    const characterLeft = columns >= 2 ? leftColumnX + cardWidth + GAP : contentLeft;
    const characterRight = columns >= 1 ? rightColumnX - GAP : contentRight;
    rects.character = {
        x: characterLeft,
        y: bandTop,
        width: Math.max(CHARACTER_MIN_WIDTH, characterRight - characterLeft),
        height: bandHeight,
    };

    return {
        breakpoint: point.name,
        sidebarMode: point.sidebar,
        cardWidth,
        columns,
        rects,
        dropped,
    };
}

/** True when two rectangles share any interior area. Touching edges do not count. */
export function overlaps(a, b) {
    return a.x < b.x + b.width && b.x < a.x + a.width &&
        a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * Every overlapping pair in a solution, as `["a", "b"]` names.
 *
 * The top bar is excluded from the comparison against nothing — it genuinely
 * spans the full width at y=0 and every other band starts below it, so if it
 * ever appears in this list something has moved that should not have.
 */
export function overlappingPairs(solution) {
    const present = PANEL_KEYS.filter(key => solution.rects[key]);
    const found = [];
    for (let i = 0; i < present.length; i += 1) {
        for (let j = i + 1; j < present.length; j += 1) {
            if (overlaps(solution.rects[present[i]], solution.rects[present[j]]))
                found.push([present[i], present[j]]);
        }
    }
    return found;
}
