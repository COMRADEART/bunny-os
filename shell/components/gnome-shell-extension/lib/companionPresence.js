// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// How much Companion is on screen, and how much of it moves.
//
// Two decisions, deliberately separated, because they answer to different
// people. *Presence* is what the user asked for — full, compact, a small
// indicator, or nothing. *Fidelity* is what the machine can afford — 3D,
// lightweight 3D, animated 2D, a static image, or text. A user who chose the
// full Companion on a machine that cannot render it gets the full Companion at
// a lower fidelity; a user who chose the indicator on a fast machine gets the
// indicator. Collapsing the two into one "quality" setting is how a person's
// preference silently becomes a performance decision.
//
// Three rules the resolver enforces rather than documents.
//
// **Reduced motion is not a fidelity tier.** A person who asked for less
// movement did not ask for a worse picture. prefers-reduced-motion pins the
// animation budget to zero and leaves the fidelity where it was, so the
// character is still drawn, still expressive in pose, and simply does not move
// between poses. Dropping such a user to text would be reading the setting as a
// complaint about the character.
//
// **Stability outranks appearance, always.** §5: never sacrifice system
// stability to preserve animation. A frame budget that has been missed, a
// thermal event, or a battery below the floor drops fidelity by one tier per
// evaluation and never raises it in the same evaluation — the hysteresis is
// what stops a marginal machine oscillating between tiers, which looks far worse
// than the lower tier does.
//
// **A blocked question is never made less visible by a preference.** Presence
// can be reduced to an indicator, and an indicator still has to be able to say
// "something needs you". So resolve() returns attention separately from
// presence, and the surface is required to show attention even at
// presence:'indicator'. presence:'off' is the one case where the Companion draws
// nothing — and then the question goes to a notification instead, which is why
// attention is still reported.

/** Everything the user may choose. Order is widest first. */
export const PRESENCE = ['full', 'compact', 'indicator', 'off'];

/**
 * The fidelity ladder, best first. These names match
 * companion.presentation.IMPLEMENTED_PRESENTATIONS exactly; a test asserts it,
 * because the runtime picks from that list and this module renders what it picks.
 */
export const FIDELITY = ['full-3d', 'lightweight-3d', 'animated-2d', 'static-image', 'text-only'];

/** Phases that mean the user has to do something. Drawn at any presence. */
export const ATTENTION_PHASES = ['waiting_for_approval', 'blocked', 'error'];

/** Phases that are worth showing but never worth interrupting for. */
export const QUIET_PHASES = ['idle', 'success', 'disconnected'];

/**
 * Frames-per-second floor below which a tier is considered unaffordable.
 * Measured against the compositor's own frame clock rather than a timer, because
 * a timer that is late tells you the timer was late.
 */
export const FRAME_FLOOR_FPS = 24;

/** Below this, the machine is on battery and low enough to stop animating. */
export const BATTERY_FLOOR_PERCENT = 15;

/** Animation budget in milliseconds, per fidelity tier, at normal motion. */
export const MOTION_BUDGET_MS = {
    'full-3d': 260,
    'lightweight-3d': 220,
    'animated-2d': 180,
    'static-image': 0,
    'text-only': 0,
};

function tierIndex(tier) {
    const index = FIDELITY.indexOf(tier);
    return index === -1 ? FIDELITY.length - 1 : index;
}

/**
 * Lower a tier by `steps`, never below text-only.
 *
 * Exported because the degradation is worth testing on its own: "a machine that
 * misses its frame budget twice ends up two tiers down and not at text-only"
 * is the property, and a private helper would make it a property of resolve()
 * that only a full-resolver test could reach.
 */
export function degrade(tier, steps = 1) {
    return FIDELITY[Math.min(tierIndex(tier) + Math.max(0, steps), FIDELITY.length - 1)];
}

/**
 * The highest tier this machine has been shown to sustain.
 *
 * Starts from what the runtime selected — the capability engine has already
 * ruled out tiers this build cannot do — and lowers it for each measured
 * problem. It never raises: a caller that wants to try a better tier again does
 * so by passing a higher `selected`, which is a decision somebody made rather
 * than a resolver quietly deciding the machine got faster.
 */
export function affordableFidelity(selected, machine = {}) {
    let tier = FIDELITY.includes(selected) ? selected : 'animated-2d';
    const {frameRate = null, thermalThrottled = false, onBattery = false, batteryPercent = null, memoryPressure = false} = machine;

    if (frameRate !== null && frameRate < FRAME_FLOOR_FPS)
        tier = degrade(tier, 1);
    if (thermalThrottled)
        tier = degrade(tier, 1);
    if (memoryPressure)
        tier = degrade(tier, 1);
    if (onBattery && batteryPercent !== null && batteryPercent < BATTERY_FLOOR_PERCENT)
        tier = degrade(tier, 2);
    return tier;
}

/**
 * The whole presence decision for one moment.
 *
 * Pure: every input is a value and the result is a value, so the tests evaluate
 * it under node without a compositor. That is the only reason any of this is
 * checkable at all — the drawing is not, and pretending otherwise is what the
 * repository's own maturity ladder exists to prevent.
 *
 * @param {object} options
 * @param {string} options.preference   one of PRESENCE, the user's setting
 * @param {string} options.phase        a companion.presentation phase
 * @param {string} options.selected     the fidelity the runtime selected
 * @param {object} options.accessibility {reducedMotion, textOnly, highContrast, largeText, screenReader}
 * @param {object} options.machine      {frameRate, thermalThrottled, onBattery, batteryPercent, memoryPressure}
 */
export function resolve({preference = 'full', phase = 'idle', selected = 'animated-2d', accessibility = {}, machine = {}} = {}) {
    const {reducedMotion = false, textOnly = false, screenReader = false, highContrast = false, largeText = false} = accessibility;

    const wanted = PRESENCE.includes(preference) ? preference : 'full';
    const attention = ATTENTION_PHASES.includes(phase);

    // Text-only is a presence *and* a fidelity: a person who asked for a
    // text-only Companion asked for words, and giving them a silent character
    // that also emits words would be two Companions.
    let fidelity = textOnly ? 'text-only' : affordableFidelity(selected, machine);

    // A screen reader user is not automatically a text-only user — many use one
    // alongside a visible desktop — so this does not force the tier. What it
    // does force is that every state change is announced, which is the field
    // below rather than a fidelity decision.
    const announce = screenReader || textOnly || fidelity === 'text-only';

    let presence = wanted;
    if (fidelity === 'text-only' && presence === 'full')
        presence = 'compact';
    if (attention && presence === 'off')
        presence = 'off'; // stays off; the question goes to a notification.

    const motionMs = reducedMotion ? 0 : MOTION_BUDGET_MS[fidelity];

    return {
        presence,
        fidelity,
        attention,
        // The surface must render an attention state even at 'indicator'. Stated
        // as a field rather than left to each caller to remember.
        mustShowAttention: attention && presence !== 'off',
        // True when the question has to leave the Companion entirely.
        routeToNotification: attention && presence === 'off',
        motionMs,
        announce,
        highContrast,
        largeText,
        quiet: QUIET_PHASES.includes(phase),
    };
}
