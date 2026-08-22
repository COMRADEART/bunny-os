// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Companion in four sizes, all saying the same thing.
//
// ## Two axes that were being confused
//
// `companionPresence.js` already has a ladder — full-3d, lightweight-3d,
// animated-2d, static-image, text-only — and it is not this. That ladder is
// **fidelity**: how the character can be drawn on this machine, chosen from
// measured hardware signals, degrading one tier per problem and never climbing
// back. It answers "what can this GPU do".
//
// This module is **mode**: how much of the Companion is shown, chosen by the
// person. It answers "how much of my screen do I want this to take". A machine
// with no GPU and a person who wants the full Companion get animated-2d at full
// size; a strong machine and a person who wants it out of the way get full-3d at
// minimal. The two do not constrain each other and collapsing them would make
// one of the settings a lie.
//
// The single exception is `text-only`, which is both — a fidelity floor and a
// mode — because a Companion with no picture is the same thing however you
// arrived at it. `resolve` takes both and reconciles them in one place.
//
// ## The property that matters
//
// §16: *no presentation mode may invent a different task truth.* Every mode is
// built from one `buildTaskStatus` call, so `state`, `label` and `announcement`
// are literally the same objects in all four. What differs is which *parts* are
// shown, never what they say.
//
// That is not a style preference. `VISUAL_QA_REPORT.md` §3.5 photographed the
// desktop showing "Assistant offline" and "Thinking…" at the same moment,
// because two surfaces derived availability and activity from different state
// and nothing reconciled them. Four surfaces is four times that opportunity.

import {buildTaskStatus, PHASE_TO_STATE} from './taskState.js';
import {COMPANION_SIZE} from './design/tokens.js';

/**
 * §16, in the order they shed.
 *
 * `off` is a mode and not an absence. §16 requires the system to remain fully
 * usable with no Companion presentation, and the setup surface offers it — so
 * without it here, a person who chose Off during installation would have that
 * preference silently resolved to `full` by `normaliseMode`, which is the worst
 * of the available outcomes: the one thing they asked not to see, appearing.
 *
 * What `off` still does is carry the state in words. `indicatorText` is
 * populated for every mode including this one, because Trust prompts and task
 * failures are the *system* speaking and must not disappear with the character.
 */
export const MODES = ['full', 'compact', 'minimal', 'text-only', 'off'];

/**
 * The states §16 requires a Companion mode to be able to show, mapped from the
 * runtime's own phase vocabulary.
 *
 * `taskState.PHASE_TO_STATE` is the seven-state *task* vocabulary — what a task
 * surface draws. This is the ten-state *Companion* vocabulary, which is finer:
 * a task list does not care whether a task is understanding or exporting, and a
 * character does, because those are different things for it to be doing.
 *
 * Both are derived from the same phase. Neither is derived from the other, and a
 * test asserts they agree about which phases are terminal.
 */
export const PHASE_TO_COMPANION = {
    idle: 'idle',
    starting: 'launching',
    recovering: 'working',
    understanding: 'understanding',
    planning: 'understanding',
    waiting_for_approval: 'waiting-for-approval',
    listening: 'understanding',
    // Voice-only phase (see taskState.js): capture has closed, recognition is
    // running. Same companion state as listening — the character is still on
    // the person's words rather than working on the system.
    transcribing: 'understanding',
    speaking: 'working',
    working: 'working',
    reviewing: 'working',
    presenting_result: 'exporting',
    success: 'completed',
    cancelling: 'working',
    cancelled: 'cancelled',
    paused: 'idle',
    blocked: 'blocked',
    error: 'failed',
    disconnected: 'offline',
};

/**
 * What each Companion state is called, and how the character should behave.
 *
 * §17: resting, attention, working, success, blocked, error, offline, and a
 * degraded fallback. `motion` is a *budget class*, not a duration — the actual
 * duration is zero when the system asks for less motion, and `lib/animation.js`
 * is the only place that decides so.
 *
 * `attention` is the sole class permitted to pulse, and only for the state that
 * is waiting for a person. A character that pulsed while working would be
 * asking for attention it does not need, every time.
 */
export const COMPANION_STATES = {
    idle: {label: 'Ready', behaviour: 'resting', motion: 'quiet', token: 'trust'},
    understanding: {label: 'Understanding', behaviour: 'attention', motion: 'active', token: 'trust'},
    'waiting-for-approval': {label: 'Waiting for you', behaviour: 'attention', motion: 'attention', token: 'warning'},
    launching: {label: 'Starting', behaviour: 'working', motion: 'active', token: 'trust'},
    working: {label: 'Working', behaviour: 'working', motion: 'active', token: 'trust'},
    exporting: {label: 'Saving the result', behaviour: 'working', motion: 'active', token: 'trust'},
    completed: {label: 'Done', behaviour: 'success', motion: 'active', token: 'success'},
    blocked: {label: 'Blocked', behaviour: 'blocked', motion: 'attention', token: 'blocked'},
    failed: {label: 'Something failed', behaviour: 'error', motion: 'attention', token: 'danger'},
    cancelled: {label: 'Cancelled', behaviour: 'resting', motion: 'quiet', token: 'textMuted'},
    offline: {label: 'Offline', behaviour: 'offline', motion: 'quiet', token: 'textMuted'},
};

/**
 * What each mode puts on screen.
 *
 * `character` is whether a figure is drawn at all; `sizePx` is how big. Note
 * that `minimal` still draws one — a 48px figure is the smallest thing that is
 * still recognisably the Companion, and below that it is an indicator dot, which
 * is what `text-only` uses instead.
 */
export const MODE_PARTS = {
    full: {
        character: true, sizePx: COMPANION_SIZE.full,
        caption: true, transcript: true, controls: true, indicator: false,
    },
    compact: {
        character: true, sizePx: COMPANION_SIZE.compact,
        caption: true, transcript: false, controls: true, indicator: false,
    },
    minimal: {
        character: true, sizePx: COMPANION_SIZE.minimal,
        caption: false, transcript: false, controls: false, indicator: true,
    },
    'text-only': {
        character: false, sizePx: 0,
        caption: true, transcript: true, controls: true, indicator: true,
    },
    // Nothing on screen. Not even the indicator: a person who turned the
    // Companion off did not ask for a smaller Companion. The announcement
    // survives — see `buildCompanion.indicatorText` — so an assistive
    // technology and the notification layer still have the words.
    off: {
        character: false, sizePx: 0,
        caption: false, transcript: false, controls: false, indicator: false,
    },
};

function normaliseMode(mode) {
    return MODES.includes(mode) ? mode : 'full';
}

/**
 * Reconcile the mode a person asked for with what this machine can draw.
 *
 * A fidelity of `text-only` forces the mode to `text-only`, because there is no
 * picture to be full-sized. Nothing else in the fidelity ladder changes the
 * mode: a machine that can only manage a static image still honours a request
 * for the full Companion, at full size, as a still.
 */
export function resolveMode({mode = 'full', fidelity = 'animated-2d', preferTextOnly = false} = {}) {
    if (preferTextOnly || fidelity === 'text-only')
        return 'text-only';
    return normaliseMode(mode);
}

/**
 * Build the Companion presentation for one task state, in one mode.
 *
 * @param {object} options
 * @param {string} options.phase   a companion.presentation phase
 * @param {string} options.caption the runtime's own sentence
 * @param {string} options.mode    full | compact | minimal | text-only
 * @param {string} options.fidelity the rendering tier companionPresence chose
 * @param {boolean} options.reducedMotion
 */
export function buildCompanion({
    phase = 'idle', caption = '', mode = 'full', fidelity = 'animated-2d',
    preferTextOnly = false, reducedMotion = false, stages = [], stageIndex = -1,
} = {}) {
    // One task-status projection, shared by every mode. This is the whole of
    // "no mode may invent a different task truth": there is one of it.
    const task = buildTaskStatus({phase, caption, stages, stageIndex});

    const resolved = resolveMode({mode, fidelity, preferTextOnly});
    const parts = MODE_PARTS[resolved];
    const companionState = PHASE_TO_COMPANION[phase] ?? 'idle';
    const presentation = COMPANION_STATES[companionState];

    // Reduced motion does not lower the fidelity. A person who asked for less
    // movement did not ask for a worse picture — docs/DESIGN_SYSTEM.md has said
    // so since the first accessibility review — so the *behaviour* survives and
    // only the motion class collapses.
    const motion = reducedMotion ? 'still' : presentation.motion;

    return {
        mode: resolved,
        requestedMode: normaliseMode(mode),
        fidelity,
        // The task projection, unmodified, so a caller can show the same task
        // surface beside the Companion and they cannot disagree.
        task,
        state: companionState,
        label: presentation.label,
        behaviour: presentation.behaviour,
        motion,
        token: presentation.token,
        parts,
        // Identical in all four modes, by construction.
        announcement: [presentation.label, task.detail].filter(Boolean).join('. '),
        // What a mode that draws no character shows instead. Never empty: the
        // OS must remain usable if the character is off or fails, so there is
        // always a word for the state.
        indicatorText: presentation.label,
        needsAnswer: task.needsAnswer,
        terminal: task.terminal,
    };
}

/**
 * The same state in all four modes, for the story harness and the tests.
 *
 * Exported rather than reconstructed by callers because "build all four and
 * compare" is the check §16 asks for, and a caller that built them slightly
 * differently would be checking its own loop.
 */
export function everyMode(options = {}) {
    const built = {};
    for (const mode of MODES)
        built[mode] = buildCompanion({...options, mode, preferTextOnly: mode === 'text-only'});
    return built;
}
