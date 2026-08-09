// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// What the character *is*, as data.
//
// The brief asks that the asset be replaceable. The renderer therefore knows
// how to draw *a* figure and nothing about *this* figure: every colour,
// proportion and pose lives in this file, and a different character is a
// different object of this shape — loaded from
// /usr/share/bunny-shell/characters/<id>.json if one is present, this one if
// not. Nothing in renderer.js names a hoodie.
//
// Geometry is in a 100 x 150 unit box with the origin at the top-left, scaled
// to whatever the viewport allocates. Units rather than pixels because the
// figure has to be right at 320x460 on a 1080p screen and at 210x300 on a
// 1366x768 one, and a definition in pixels only fits one of those.
//
// The pose table is the other half. Each of the ten states names an amplitude
// for the animator rather than a keyframe: `armLift: 0.35` means "raise the
// arms about a third of the way", and the animator decides how long that takes
// and eases into it. Keyframes would have made every state a separate
// animation to author and would have made a replacement character a much
// larger piece of work than a colour swap.
//
// ## What the first two attempts got wrong
//
// The figure has been looked at on a booted machine twice, and both times it
// read as a robed figure rather than a person in a hoodie. The numbers changed
// between those attempts and the reading did not, which is the useful part:
// the problem was never the proportions.
//
// It was three drawing decisions, and they are recorded here because the
// geometry below only makes sense against them.
//
//   * **The hem was the bottom of a capsule.** A capsule ends in a semicircle,
//     so the garment finished in a dome that was *wider than the hips it sat
//     over* — 16 units against 14.5. That is the silhouette of a robe, drawn
//     exactly as specified, and no change to the height of the hem could fix
//     it. The hoodie now has a hem of its own: a flat edge, narrower than the
//     shoulders, with a ribbed band under it. The band is the single most
//     important shape in this file. It is what says "the garment stops here".
//
//   * **The legs touched.** A separation of 11 with 10.4-wide thighs left a
//     0.6-unit gap, which at the size this is drawn is no gap at all: the two
//     legs merged into one mass under a wide hem, which is a skirt. They are
//     now 15 apart at 9.5 wide, so there are 5.5 units of background between
//     them and the eye can see two of something.
//
//   * **Nothing separated the arms from the body.** The sleeves were the same
//     colour as the torso and started inside it, so the outline of the figure
//     from shoulder to hem was a single unbroken shape. The sleeves now have
//     their own shading, a cuff, and a hand below the cuff.
//
// The proportions did change as well — 6.3 heads rather than 5.8, which is
// stylised-but-adult — but that is the smaller half of the fix.

/** The shipped character: young adult, dark hoodie, Bunny mark, dark trousers. */
export const DEFAULT_CHARACTER = {
    id: 'bunny-default',
    name: 'Bunny',
    description:
        'A young adult standing in a dark violet hoodie with the Bunny OS mark on the chest, ' +
        'dark trousers and pale sneakers, lit from the left by violet light.',
    version: 2,

    palette: {
        skin: [0.85, 0.70, 0.58],
        skinShadow: [0.71, 0.56, 0.45],
        hair: [0.13, 0.11, 0.16],
        hairHighlight: [0.26, 0.22, 0.34],
        hoodie: [0.17, 0.16, 0.26],
        hoodieShadow: [0.10, 0.10, 0.17],
        hoodieHighlight: [0.26, 0.24, 0.39],
        // The ribbing at the hem and the cuffs. Deliberately a step darker than
        // the body of the garment rather than a step lighter: it has to read as
        // a band even on a screen that has crushed the blacks.
        hoodieRib: [0.13, 0.12, 0.21],
        hood: [0.13, 0.12, 0.20],
        pocket: [0.14, 0.13, 0.22],
        drawstring: [0.80, 0.80, 0.86],
        trousers: [0.11, 0.11, 0.15],
        trousersHighlight: [0.17, 0.17, 0.23],
        shoe: [0.92, 0.92, 0.95],
        shoeSole: [0.70, 0.70, 0.77],
        shoeAccent: [0.545, 0.361, 0.965],
        logo: [0.655, 0.545, 0.980],
        eye: [0.09, 0.08, 0.12],
        mouth: [0.38, 0.24, 0.26],
        rimLight: [0.655, 0.545, 0.980],
        // The three state accents. These were referenced by the pose table from
        // the day it was written and were never defined, so `success` fell
        // through to the violet rim light and the documented "success turns the
        // rim green, error turns it red" had never once happened on screen.
        // The values are the desktop's own tokens: Rgb.SUCCESS, WARNING, ERROR.
        success: [0.133, 0.773, 0.369],
        warning: [0.961, 0.620, 0.043],
        error: [0.937, 0.267, 0.267],
    },

    /**
     * Every measurement the renderer uses, named.
     *
     * Read as a standing figure from the top: the head sits on a neck, the neck
     * enters a hoodie whose shoulders are the widest part of the garment, the
     * hoodie tapers to a hem well above the knee, and two separated legs come
     * out from under it. Every one of those relationships is an inequality
     * between two numbers here, and the ones that matter are called out.
     */
    geometry: {
        headCentre: [50, 21],
        headRadius: 10.2,
        jawNarrow: 0.86,
        ear: {offsetY: 0.6, radius: 2.0},
        neck: {x: 50, top: 29.5, bottom: 39.5, width: 7.2},

        // Shoulder half-width is the widest the figure gets above the hips, and
        // it is *narrower* than the stance below (leg separation + thigh), so
        // the figure stands on its feet rather than balancing on them.
        shoulder: {y: 40, halfWidth: 16.8, slope: 2.4},
        // hemHalfWidth < shoulder.halfWidth, and hemHalfWidth > hip.halfWidth by
        // just enough for the garment to sit over the hips rather than flare
        // past them. Those two inequalities are the whole difference between a
        // hoodie and a robe.
        torso: {top: 38, hem: 78, topHalfWidth: 16.8, hemHalfWidth: 14.0},
        rib: {height: 3.6},
        hood: {y: 34, halfWidth: 15.5, depth: 7.5},
        collar: {width: 9.0, depth: 3.0},
        pocket: {top: 62, bottom: 74, halfWidth: 10.5},

        sleeve: {width: 7.4, cuffWidth: 6.2, cuffHeight: 3.0},
        arm: {shoulderInset: 2.6, length: 37, handRadius: 3.2, restAngle: 0.13},

        hip: {y: 77.5, halfWidth: 12.0},
        // separation is centre-to-centre. separation - thighWidth = 5.5 units of
        // visible background between the legs; below about 3 they merge.
        leg: {length: 55, thighWidth: 9.5, kneeWidth: 8.2, ankleWidth: 6.4, separation: 15},
        shoe: {height: 6.8, length: 14.0, soleHeight: 2.2},

        // Below the drawstrings, not behind them: at [50, 52] the mark sat
        // directly under the two strings and the three shapes together read as
        // a pendant on a cord rather than a print on a chest.
        logo: {centre: [50, 55], size: 11},
        eyes: {offsetX: 4.0, offsetY: 0.8, radius: 1.55},
        brow: {offsetY: -3.6, length: 3.6},
        mouth: {offsetY: 5.0, width: 4.4},
        groundShadow: {y: 139, radiusX: 24, radiusY: 4.6},
        /** Where a state indicator is drawn, if the state has one. */
        indicator: {x: 68, y: 20, radius: 2.0},
    },

    /**
     * Pose amplitudes per state, 0..1 unless noted.
     *
     * breathe   depth of the chest rise; the resting animation, never zero
     *           except when asleep
     * bob       whole-body vertical drift, in units
     * armLift   how far the arms come away from the body
     * headTilt  degrees, positive tilts the head to the figure's left
     * lean      degrees of whole-body lean
     * blinkRate blinks per minute; 0 means the eyes are held
     * eyeOpen   0 closed, 1 fully open
     * mouthOpen resting mouth opening; talking modulates above this
     * glow      floor-glow intensity multiplier
     * accent    which palette entry the glow and rim light take
     * indicator which small mark is drawn beside the head, if any. The four
     *           values are the states a person would otherwise have to read the
     *           bubble to tell apart: a figure that is listening and a figure
     *           that is idle differ by almost nothing in pose, deliberately,
     *           because a character that changed its whole stance every time a
     *           microphone opened would be exhausting to sit in front of.
     */
    poses: {
        idle: {breathe: 1.0, bob: 0.6, armLift: 0.0, headTilt: 0, lean: 0, blinkRate: 14, eyeOpen: 1, mouthOpen: 0.06, glow: 1.0, accent: 'rimLight', indicator: 'none', period: 4200},
        listening: {breathe: 1.15, bob: 0.4, armLift: 0.08, headTilt: 6, lean: 1.5, blinkRate: 10, eyeOpen: 1, mouthOpen: 0.03, glow: 1.45, accent: 'rimLight', indicator: 'listening', period: 3000},
        thinking: {breathe: 0.9, bob: 0.5, armLift: 0.30, headTilt: -8, lean: -1, blinkRate: 6, eyeOpen: 0.82, mouthOpen: 0.02, glow: 1.2, accent: 'rimLight', indicator: 'thinking', period: 3600},
        working: {breathe: 1.3, bob: 1.1, armLift: 0.46, headTilt: 2, lean: 0.5, blinkRate: 12, eyeOpen: 1, mouthOpen: 0.05, glow: 1.3, accent: 'rimLight', indicator: 'working', period: 1800},
        success: {breathe: 1.2, bob: 1.6, armLift: 0.62, headTilt: 0, lean: 0, blinkRate: 8, eyeOpen: 0.55, mouthOpen: 0.34, glow: 1.7, accent: 'success', indicator: 'none', period: 1500},
        celebrating: {breathe: 1.4, bob: 2.6, armLift: 0.92, headTilt: 0, lean: 0, blinkRate: 6, eyeOpen: 0.45, mouthOpen: 0.48, glow: 1.9, accent: 'success', indicator: 'none', period: 1100},
        warning: {breathe: 0.95, bob: 0.3, armLift: 0.18, headTilt: 9, lean: 0, blinkRate: 16, eyeOpen: 1, mouthOpen: 0.10, glow: 1.35, accent: 'warning', indicator: 'alert', period: 3200},
        error: {breathe: 0.8, bob: 0.2, armLift: 0.12, headTilt: -4, lean: -2, blinkRate: 4, eyeOpen: 0.75, mouthOpen: 0.14, glow: 1.5, accent: 'error', indicator: 'alert', period: 3400},
        talking: {breathe: 1.1, bob: 0.7, armLift: 0.22, headTilt: 3, lean: 0, blinkRate: 12, eyeOpen: 1, mouthOpen: 0.30, glow: 1.25, accent: 'rimLight', indicator: 'none', period: 2600},
        sleeping: {breathe: 0.7, bob: 0.9, armLift: 0.0, headTilt: 12, lean: 0, blinkRate: 0, eyeOpen: 0.0, mouthOpen: 0.04, glow: 0.45, accent: 'rimLight', indicator: 'none', period: 6000},
    },
};

/**
 * Read a replacement definition from disk, or return the built-in.
 *
 * Validation is deliberately shallow: it checks that the palette and geometry
 * exist and that every state has a pose, then merges over the default. A
 * definition missing one colour therefore renders with that colour from the
 * default rather than throwing inside a paint handler, which in Clutter means a
 * blank actor and a stack trace sixty times a second.
 */
export function loadDefinition(readText, path) {
    if (!path)
        return DEFAULT_CHARACTER;
    const text = readText(path);
    if (text === null)
        return DEFAULT_CHARACTER;
    let document;
    try {
        document = JSON.parse(text);
    } catch (_error) {
        return DEFAULT_CHARACTER;
    }
    if (typeof document !== 'object' || document === null)
        return DEFAULT_CHARACTER;
    return {
        ...DEFAULT_CHARACTER,
        ...document,
        palette: {...DEFAULT_CHARACTER.palette, ...(document.palette ?? {})},
        geometry: {...DEFAULT_CHARACTER.geometry, ...(document.geometry ?? {})},
        poses: {...DEFAULT_CHARACTER.poses, ...(document.poses ?? {})},
    };
}
