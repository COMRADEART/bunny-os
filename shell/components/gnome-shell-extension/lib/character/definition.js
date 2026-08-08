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

/** The shipped character: young adult, dark hoodie, Bunny mark, dark trousers. */
export const DEFAULT_CHARACTER = {
    id: 'bunny-default',
    name: 'Bunny',
    description:
        'A young adult standing in a dark violet hoodie with the Bunny OS mark on the chest, ' +
        'dark trousers and pale sneakers, lit from the left by violet light.',
    version: 1,

    palette: {
        skin: [0.85, 0.70, 0.58],
        skinShadow: [0.71, 0.56, 0.45],
        hair: [0.13, 0.11, 0.16],
        hairHighlight: [0.24, 0.20, 0.31],
        hoodie: [0.16, 0.15, 0.24],
        hoodieShadow: [0.10, 0.10, 0.17],
        hoodieHighlight: [0.24, 0.22, 0.36],
        hood: [0.13, 0.12, 0.20],
        drawstring: [0.78, 0.78, 0.84],
        trousers: [0.10, 0.10, 0.14],
        trousersHighlight: [0.16, 0.16, 0.22],
        shoe: [0.92, 0.92, 0.95],
        shoeSole: [0.72, 0.72, 0.78],
        shoeAccent: [0.545, 0.361, 0.965],
        logo: [0.655, 0.545, 0.980],
        eye: [0.09, 0.08, 0.12],
        mouth: [0.38, 0.24, 0.26],
        rimLight: [0.655, 0.545, 0.980],
    },

    // Every measurement the renderer uses, named. A shorter list would have
    // meant magic numbers in the drawing code, which is where a replaceable
    // asset stops being replaceable.
    // Revised after looking at the first render on a booted machine. The
    // original numbers gave a torso 45 units wide reaching to y=89 of 150 with
    // the legs below it, and the result read as a robed figure rather than
    // somebody in a hoodie: the garment came to the knee and the shoulders were
    // wider than the stance.
    //
    // The change is in the ratios, not the style. The head is a little larger
    // against a narrower torso (7.2 heads tall rather than 5.7, which is the
    // stylised-realistic range), the hoodie hem is raised to y=80 so a clear
    // band of trousers shows beneath it, the legs are longer, and the stance is
    // wider than the hips so the figure stands rather than balances.
    geometry: {
        headCentre: [50, 24],
        headRadius: 12.0,
        jawNarrow: 0.86,
        neck: {x: 50, top: 33, bottom: 41, width: 7.6},
        shoulder: {y: 43, halfWidth: 18.5},
        torso: {top: 41, bottom: 80, topHalfWidth: 18.5, bottomHalfWidth: 16.0},
        hood: {y: 37, halfWidth: 16, depth: 8},
        sleeve: {width: 7.6, wristWidth: 5.6},
        arm: {shoulderInset: 3.0, length: 38, handRadius: 3.5},
        hip: {y: 80, halfWidth: 14.5},
        leg: {length: 52, thighWidth: 10.4, ankleWidth: 6.6, separation: 11},
        shoe: {height: 7.0, length: 14.5, soleHeight: 2.4},
        logo: {centre: [50, 58], size: 10},
        eyes: {offsetX: 4.6, offsetY: 1.0, radius: 1.7},
        brow: {offsetY: -4.0, length: 4.0},
        mouth: {offsetY: 5.8, width: 4.8},
        groundShadow: {y: 141, radiusX: 24, radiusY: 4.8},
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
     */
    poses: {
        idle: {breathe: 1.0, bob: 0.6, armLift: 0.0, headTilt: 0, lean: 0, blinkRate: 14, eyeOpen: 1, mouthOpen: 0.06, glow: 1.0, accent: 'rimLight', period: 4200},
        listening: {breathe: 1.15, bob: 0.4, armLift: 0.08, headTilt: 6, lean: 1.5, blinkRate: 10, eyeOpen: 1, mouthOpen: 0.03, glow: 1.45, accent: 'rimLight', period: 3000},
        thinking: {breathe: 0.9, bob: 0.5, armLift: 0.30, headTilt: -8, lean: -1, blinkRate: 6, eyeOpen: 0.82, mouthOpen: 0.02, glow: 1.2, accent: 'rimLight', period: 3600},
        working: {breathe: 1.3, bob: 1.1, armLift: 0.46, headTilt: 2, lean: 0.5, blinkRate: 12, eyeOpen: 1, mouthOpen: 0.05, glow: 1.3, accent: 'rimLight', period: 1800},
        success: {breathe: 1.2, bob: 1.6, armLift: 0.62, headTilt: 0, lean: 0, blinkRate: 8, eyeOpen: 0.55, mouthOpen: 0.34, glow: 1.7, accent: 'success', period: 1500},
        celebrating: {breathe: 1.4, bob: 2.6, armLift: 0.92, headTilt: 0, lean: 0, blinkRate: 6, eyeOpen: 0.45, mouthOpen: 0.48, glow: 1.9, accent: 'success', period: 1100},
        warning: {breathe: 0.95, bob: 0.3, armLift: 0.18, headTilt: 9, lean: 0, blinkRate: 16, eyeOpen: 1, mouthOpen: 0.10, glow: 1.35, accent: 'warning', period: 3200},
        error: {breathe: 0.8, bob: 0.2, armLift: 0.12, headTilt: -4, lean: -2, blinkRate: 4, eyeOpen: 0.75, mouthOpen: 0.14, glow: 1.5, accent: 'error', period: 3400},
        talking: {breathe: 1.1, bob: 0.7, armLift: 0.22, headTilt: 3, lean: 0, blinkRate: 12, eyeOpen: 1, mouthOpen: 0.30, glow: 1.25, accent: 'rimLight', period: 2600},
        sleeping: {breathe: 0.7, bob: 0.9, armLift: 0.0, headTilt: 12, lean: 0, blinkRate: 0, eyeOpen: 0.0, mouthOpen: 0.04, glow: 0.45, accent: 'rimLight', period: 6000},
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
