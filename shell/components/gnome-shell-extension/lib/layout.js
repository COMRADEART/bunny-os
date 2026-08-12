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

/**
 * Cards that are kept when a column has to shed one.
 *
 * The assistant card is where a task is typed, where its state is shown, and
 * where the permission question appears. Dropping it does not remove a
 * convenience; it removes the ability to answer Trust, which §40 lists among the
 * behaviours a visual refactor must not regress. Everything else in a column is
 * discretionary against that.
 */
export const PROTECTED_CARDS = ['assistant'];

/** Every rectangle `solve` returns that must not overlap any other. */
export const PANEL_KEYS = [
    'topBar', 'sidebar', 'dock', 'character',
    ...LEFT_COLUMN, ...RIGHT_COLUMN,
];

/**
 * Natural heights at the reference resolution and 100 % text.
 *
 * These are *content* heights, so they grow with the type scale rather than with
 * the padding scale — a card holding six rows of 24px text is twice as tall as
 * one holding six rows of 12px text, near enough, and the rounding error is
 * absorbed by the drop rule below.
 */
const CARD_HEIGHT = {
    systemOverview: 236,
    quickAccess: 168,
    media: 132,
    agenda: 196,
    systemMonitor: 200,
    assistant: 232,
};

const BREAKPOINTS = [
    // Chosen from the four resolutions the brief names, plus a floor. `cardWidth`
    // is a fraction of the theme's card metric rather than a pixel count, so a
    // 200 % desktop narrows its cards in proportion instead of keeping a 608px
    // column that nothing fits beside.
    {minWidth: 1800, name: 'wide', cardShare: 1.0, density: 1.0, sidebar: 'expanded'},
    {minWidth: 1500, name: 'standard', cardShare: 0.91, density: 0.94, sidebar: 'expanded'},
    {minWidth: 1200, name: 'compact', cardShare: 0.82, density: 0.88, sidebar: 'collapsed'},
    {minWidth: 0, name: 'narrow', cardShare: 0.76, density: 0.82, sidebar: 'collapsed'},
];

/**
 * Chrome sizes at 100 % text, mirroring METRIC in design/tokens.js.
 *
 * Stated here rather than imported because this module imports nothing — that is
 * what lets the whole layout be measured under node against a table of
 * resolutions. `solve` takes the scaled values as arguments instead, and
 * tests/shell/test_design_theme.py asserts these defaults equal the theme's.
 */
export const BASE_METRICS = {
    topBarHeight: 44,
    sidebarExpanded: 196,
    sidebarCollapsed: 60,
    dockHeight: 64,
    cardWidth: 304,
    edge: 20,
    gap: 16,
    characterMinWidth: 300,
};

export function breakpointFor(width) {
    return BREAKPOINTS.find(point => width >= point.minWidth) ?? BREAKPOINTS[BREAKPOINTS.length - 1];
}

/**
 * @param {{width: number, height: number}} screen work area of the primary monitor
 * @param {object} options
 * @param {number} [options.scale] the text scaling factor. Applied to card
 *   heights, because larger text makes cards taller, which is exactly the
 *   condition under which one has to be dropped.
 * @param {object} [options.metric] chrome sizes *already scaled* by the theme.
 *   Passing them in rather than scaling here keeps one set of scaling rules —
 *   design/theme.js — instead of two that can disagree about what 150 % means.
 * @returns {{breakpoint: string, sidebarMode: string, rects: object, dropped: string[]}}
 */
export function solve(screen, {scale = 1, metric = null} = {}) {
    const m = metric ?? BASE_METRICS;
    const TOP_BAR_HEIGHT = m.topBarHeight ?? BASE_METRICS.topBarHeight;
    const DOCK_HEIGHT = m.dockHeight ?? BASE_METRICS.dockHeight;
    const EDGE = m.edgeGap ?? m.edge ?? BASE_METRICS.edge;
    const GAP = m.cardGap ?? m.gap ?? BASE_METRICS.gap;
    const CHARACTER_MIN_WIDTH = m.characterMinWidth ?? BASE_METRICS.characterMinWidth;
    const baseCardWidth = m.cardWidth ?? BASE_METRICS.cardWidth;
    const expandedSidebar = m.sidebarWidth ?? BASE_METRICS.sidebarExpanded;
    const collapsedSidebar = m.sidebarCollapsedWidth ?? BASE_METRICS.sidebarCollapsed;

    const width = Math.max(640, Math.round(screen.width));
    const height = Math.max(480, Math.round(screen.height));
    const point = breakpointFor(width);

    // The sidebar collapses on a narrow screen and *also* when enlarging the
    // text has made it wide enough to matter. At 200 % the expanded rail is
    // 392px, which is a fifth of a 1920 screen spent on eight nav labels; the
    // collapsed rail keeps the icons and gives the width back to the content.
    // This is the reflow §5 asks for, as opposed to scaling the whole desktop.
    const sidebarExpandedIsAffordable = expandedSidebar <= width * 0.16;
    const sidebarMode = point.sidebar === 'expanded' && sidebarExpandedIsAffordable
        ? 'expanded' : 'collapsed';
    const sidebarWidth = sidebarMode === 'expanded' ? expandedSidebar : collapsedSidebar;

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
    // The narrowest a card may become before a column is given up instead. It
    // scales with the cards, because "210px" is only a sensible floor while a
    // line of body text is 12px — at 200 % a 210px card holds three words.
    const cardFloor = Math.round(baseCardWidth * 0.69);
    let cardWidth = Math.round(baseCardWidth * point.cardShare);
    let columns = 2;
    const fits = count => contentRight - contentLeft - count * (cardWidth + GAP) >= CHARACTER_MIN_WIDTH;
    while (columns > 0 && !fits(columns)) {
        if (cardWidth > cardFloor)
            cardWidth = Math.max(cardFloor, cardWidth - 12);
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

        const heightOf = key => Math.round(CARD_HEIGHT[key] * point.density * scale);

        // Work out what survives *before* placing anything, so that a protected
        // card at the bottom of a column is not lost to a discretionary card
        // above it. Placing top-to-bottom and dropping whatever overflows is
        // what made the assistant card — the surface the Trust prompt appears
        // in — the first casualty of enlarging the text: at 150 % on a 1920
        // screen the desktop dropped exactly the panel a person needs in order
        // to answer a permission question. §5 and §40 both say that is not
        // allowed, so importance decides who is dropped and reading order
        // decides where the survivors go.
        const surviving = [...keys];
        const total = () => surviving.reduce((sum, key) => sum + heightOf(key) + GAP, -GAP);
        for (let index = surviving.length - 1; index >= 0 && total() > bandHeight; index -= 1) {
            if (PROTECTED_CARDS.includes(surviving[index]))
                continue;
            dropped.push(surviving[index]);
            surviving.splice(index, 1);
        }
        // Still too tall with only protected cards left. Nothing is exempt from
        // physics; the drop is recorded so the shell can say what went.
        while (surviving.length > 1 && total() > bandHeight)
            dropped.push(surviving.pop());

        let y = bandTop;
        for (const key of surviving) {
            const cardHeight = heightOf(key);
            if (y + cardHeight > bandTop + bandHeight && surviving.length > 1) {
                dropped.push(key);
                continue;
            }
            rects[key] = {x: columnX, y, width: cardWidth, height: Math.min(cardHeight, bandHeight)};
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
        sidebarMode,
        cardWidth,
        columns,
        scale,
        rects,
        dropped,
    };
}

/**
 * How many tiles fit across a card, at whatever size everything currently is.
 *
 * This was the constant `TILES_PER_ROW = 4`, derived by hand from "the card is
 * 304px and a tile is 55px". Both of those are now theme values that move with
 * the text scale, so the arithmetic has to move with them or the grid runs out
 * over the wallpaper again — which is the defect the constant was introduced to
 * fix, and it would have come back the first time anyone enlarged the text.
 *
 * Pure, and exported, so the property can be measured at every scale rather
 * than asserted once against a comment.
 *
 * @param {object} options
 * @param {number} options.cardWidth   the card's outer width
 * @param {number} options.cardPadding the card's horizontal padding, one side
 * @param {number} options.tileWidth   a tile's width
 * @param {number} options.tilePadding a tile's horizontal padding, one side
 * @param {number} options.gap         column spacing in the grid
 * @returns {number} at least one
 */
export function tilesPerRow({cardWidth, cardPadding, tileWidth, tilePadding, gap}) {
    const content = cardWidth - 2 * cardPadding;
    const occupied = tileWidth + 2 * tilePadding;
    if (content <= 0 || occupied <= 0)
        return 1;
    return Math.max(1, Math.floor((content + gap) / (occupied + gap)));
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
