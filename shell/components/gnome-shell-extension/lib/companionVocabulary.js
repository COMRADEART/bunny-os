// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Phase 1 companion vocabulary: seventeen states, three presentation
// modes, four rendering tiers.
//
// This is a projection, not a second lifecycle. companion.presentation owns
// phases; companion.states owns the task machine; lib/character/state.js owns
// the ten drawable poses. Everything here maps onto those so a bubble, a
// figure and a task card cannot invent a different truth.

import {OS_COMPANION_STATES, OS_PRESENTATION_MODES, RENDERING_TIERS} from './design/tokens.js';
import {buildTaskStatus} from './taskState.js';

export const OS_STATES = Object.keys(OS_COMPANION_STATES);

export const PRESENTATION_MODES = Object.keys(OS_PRESENTATION_MODES);

export const RENDERING_TIER_NAMES = Object.keys(RENDERING_TIERS);

/**
 * Presentation phase (and optional tool activity) -> one OS companion state.
 *
 * Finer than the ten drawable poses: coding / reading / searching are
 * different things for the character to be doing even when the task card
 * still says "Working".
 */
export const PHASE_TO_OS_STATE = {
    idle: 'idle',
    starting: 'thinking',
    recovering: 'thinking',
    understanding: 'understanding',
    planning: 'planning',
    waiting_for_approval: 'asking',
    // Visual-key name for the same Trust wait. Not a second lifecycle.
    waiting_for_permission: 'asking',
    listening: 'listening',
    transcribing: 'listening',
    speaking: 'working',
    working: 'working',
    reviewing: 'reading',
    presenting_result: 'success',
    success: 'success',
    cancelling: 'waiting',
    cancelled: 'idle',
    paused: 'waiting',
    blocked: 'warning',
    error: 'error',
    disconnected: 'offline',
};

const ACTIVITY_TO_OS_STATE = {
    code: 'coding',
    coding: 'coding',
    type: 'coding',
    typing: 'coding',
    read: 'reading',
    reading: 'reading',
    review: 'reading',
    search: 'searching',
    searching: 'searching',
    research: 'searching',
};

/** Which of the ten drawable poses a seventeen-state OS value should take. */
export const OS_STATE_TO_POSE = {
    idle: 'idle',
    listening: 'listening',
    understanding: 'thinking',
    thinking: 'thinking',
    planning: 'thinking',
    working: 'working',
    coding: 'working',
    reading: 'thinking',
    searching: 'working',
    waiting: 'idle',
    asking: 'warning',
    warning: 'warning',
    error: 'error',
    success: 'success',
    celebrating: 'celebrating',
    sleep: 'sleeping',
    offline: 'idle',
};

export function osStateFromPhase(phase = 'idle', {toolActivity = '', celebrating = false, sleeping = false} = {}) {
    if (sleeping)
        return 'sleep';
    if (celebrating)
        return 'celebrating';
    let state = PHASE_TO_OS_STATE[phase] ?? 'idle';
    if (state === 'working') {
        const activity = String(toolActivity ?? '').trim().toLowerCase();
        for (const [needle, mapped] of Object.entries(ACTIVITY_TO_OS_STATE)) {
            if (activity.includes(needle))
                return mapped;
        }
    }
    return state;
}

export function poseForOsState(state) {
    return OS_STATE_TO_POSE[state] ?? 'idle';
}

/**
 * Map a rendering-tier name onto the fidelity ladder the presence resolver
 * already knows. Unimplemented tiers still resolve so a caller can ask for
 * BALANCED on a machine that only has animated-2d without inventing a fifth
 * renderer.
 */
export function fidelityForTier(tier = 'FULL') {
    const entry = RENDERING_TIERS[String(tier).toUpperCase()] ?? RENDERING_TIERS.FULL;
    return entry.fidelity;
}

/**
 * Whether a named rendering tier is a live ceiling on the fidelity ladder.
 * Phase 4: all four names are implemented. FULL remains the only fully
 * featured tier — see `tierIsFullyFeatured`.
 */
export function tierIsImplemented(tier = 'FULL') {
    const entry = RENDERING_TIERS[String(tier).toUpperCase()] ?? RENDERING_TIERS.FULL;
    return entry.implemented === true;
}

/** True only for FULL. Lower tiers must not advertise full-3d chrome. */
export function tierIsFullyFeatured(tier = 'FULL') {
    const entry = RENDERING_TIERS[String(tier).toUpperCase()] ?? RENDERING_TIERS.FULL;
    return entry.fullyFeatured === true;
}

const TRUST_WAIT_NAMES = new Set(['waiting_for_approval', 'waiting_for_permission', 'asking']);

/**
 * One projection for Trust waiting. Bubble, figure and task card must all
 * consume this rather than each inventing a synonym.
 *
 * `waiting_for_approval` is the presentation phase. `waiting_for_permission`
 * is the Visual Key name. `asking` is the OS companion state. They are one
 * wait, mapped onto the existing `warning` pose.
 */
export function projectTrustWait(name = 'waiting_for_approval') {
    const key = String(name ?? '');
    if (!TRUST_WAIT_NAMES.has(key))
        return null;
    const presentation = OS_COMPANION_STATES.asking;
    return {
        phase: 'waiting_for_approval',
        osState: 'asking',
        visualKey: 'waiting_for_permission',
        companionState: 'waiting-for-approval',
        taskState: 'approval',
        pose: poseForOsState('asking'),
        label: presentation.label,
        token: presentation.token,
        needsAnswer: true,
    };
}

/**
 * Where a permission question is drawn for a layout solution.
 *
 * The Phase 1 live desktop is `skeleton`, which drops the assistant card.
 * Trust then cannot live only inside that card: it has to be a chrome dialog
 * (focusable) with a bubble caption. The `full` profile still uses the card
 * when that card is actually placed and live.
 */
export function consentSurfaceForLayout({
    profile = 'full',
    dropped = [],
    cardLive = null,
} = {}) {
    const droppedList = Array.isArray(dropped) ? dropped : [];
    const cardDropped = profile === 'skeleton' || droppedList.includes('assistant');
    const live = cardLive === null ? !cardDropped : Boolean(cardLive);
    const useCard = live && !cardDropped;
    return {
        card: useCard,
        dialog: !useCard,
        bubble: true,
        focusable: true,
        kind: useCard ? 'card' : 'dialog',
        reason: useCard
            ? 'assistant card is placed'
            : 'assistant card is hidden; Trust uses the dialog overlay',
    };
}

export function normalisePresentationMode(mode) {
    const value = String(mode ?? '').toLowerCase();
    if (value === 'ambient' || value === 'minimal')
        return 'ambient';
    if (PRESENTATION_MODES.includes(value))
        return value;
    return 'full';
}

/**
 * One companion, one truth, three sizes.
 *
 * `off` is still how a person turns the character off — that lives in
 * companionModes.js. This module answers the Phase 1 brief's FULL / COMPACT
 * / AMBIENT axis and refuses to invent a different task caption per mode.
 */
export function buildOsCompanion({
    phase = 'idle',
    caption = '',
    mode = 'compact',
    toolActivity = '',
    celebrating = false,
    sleeping = false,
    reducedMotion = false,
    hidden = false,
    stages = [],
    stageIndex = -1,
} = {}) {
    const task = buildTaskStatus({phase, caption, stages, stageIndex});
    const state = osStateFromPhase(phase, {toolActivity, celebrating, sleeping});
    const presentation = OS_COMPANION_STATES[state];
    const resolvedMode = normalisePresentationMode(mode);
    const parts = OS_PRESENTATION_MODES[resolvedMode];

    return {
        state,
        pose: poseForOsState(state),
        label: presentation.label,
        token: presentation.token,
        intensity: reducedMotion ? 'still' : presentation.intensity,
        behaviour: presentation.behaviour,
        mode: resolvedMode,
        parts,
        hidden: Boolean(hidden),
        task,
        announcement: [presentation.label, task.detail].filter(Boolean).join('. '),
        requiredToUseOs: false,
        questions: {
            doing: task.detail || task.label,
            bunny: presentation.label,
            next: task.needsAnswer ? 'Answer the question.' : (task.terminal ? 'Continue with something else.' : 'Watch, pause, or cancel.'),
        },
    };
}
