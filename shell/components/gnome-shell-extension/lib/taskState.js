// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Task state, result and failure, projected for drawing.
//
// One module for the three surfaces §21, §22 and §23 ask for, because they are
// three views of one thing: a task is waiting, or working, or it finished, or it
// did not, and a person needs the same task to look like the same task in each.
// Splitting them produced the defect `VISUAL_QA_REPORT.md` §3.5 photographed —
// the desktop showing "⚠ Assistant offline" and "Thinking…" at the same time,
// two surfaces deriving availability and activity from different state with
// nothing reconciling them.
//
// This module imports nothing, so every mapping below is measurable under node.
//
// ## No invented progress
//
// §21 is explicit: no fake percentage. A percentage that is not measured is a
// claim about how long something will take, and the only honest thing the
// desktop knows about a capsule launch is which stage it is in. `stages`
// therefore carries names and a current index, and `percent` is only ever
// non-null when the runtime supplied one.
//
// ## The error taxonomy is the point of the error component
//
// "Something went wrong" is the failure §23 names, and the reason it is a
// failure is that the six real cases have different next steps: a denial is
// reversible by asking again, a security block is not, an application crash is
// worth retrying, an internal fault is worth reporting, a missing file needs a
// different file, and an offline capability needs a network or a local model.
// Collapsing them loses the only part of the message a person can act on.

/** §21. The states a task surface must be able to draw. */
export const TASK_STATES = [
    'waiting', 'approval', 'working', 'completed', 'blocked', 'failed', 'cancelled',
];

/**
 * `companion.presentation` phase -> task state.
 *
 * The phase vocabulary is defined once, in Python, and consumed here; there is
 * no compiler that would notice drift, so tests/shell asserts this table covers
 * every value of `companion.presentation.PRESENTATION_PHASES`.
 */
export const PHASE_TO_STATE = {
    idle: 'waiting',
    starting: 'working',
    recovering: 'working',
    understanding: 'working',
    planning: 'working',
    waiting_for_approval: 'approval',
    listening: 'working',
    speaking: 'working',
    working: 'working',
    reviewing: 'working',
    presenting_result: 'working',
    success: 'completed',
    cancelling: 'working',
    cancelled: 'cancelled',
    paused: 'waiting',
    blocked: 'blocked',
    error: 'failed',
    disconnected: 'waiting',
};

/** What each state is called, and which glyph and colour role carries it. */
export const STATE_PRESENTATION = {
    waiting: {label: 'Waiting', glyph: 'WAITING', token: 'textSecondary'},
    approval: {label: 'Needs your approval', glyph: 'WARNING', token: 'warning'},
    working: {label: 'Working', glyph: 'WORKING', token: 'accentText'},
    completed: {label: 'Completed', glyph: 'SUCCESS', token: 'success'},
    blocked: {label: 'Blocked', glyph: 'BLOCKED', token: 'blocked'},
    failed: {label: 'Failed', glyph: 'FAILED', token: 'danger'},
    cancelled: {label: 'Cancelled', glyph: 'CANCELLED', token: 'textMuted'},
};

/**
 * §23. The six failures, each with what it means and what to do next.
 *
 * `headline` is what happened, in the second person and without mechanism.
 * `next` is the sentence that makes the dialog worth reading. Neither mentions
 * a subsystem: §28 puts technical detail behind Details, and a person who
 * cannot open the file they asked for is not helped by the word "capsule".
 */
export const ERROR_KINDS = {
    denied: {
        label: 'Not allowed',
        headline: 'You said no, so Bunny stopped.',
        next: 'Ask again if you change your mind.',
        token: 'textSecondary',
        severity: 'info',
    },
    blocked: {
        label: 'Blocked',
        headline: 'Bunny was not allowed to do this.',
        next: 'Check what this application is allowed to do in Settings.',
        token: 'blocked',
        severity: 'warning',
    },
    'application-failed': {
        label: 'Application failed',
        headline: 'The application could not finish.',
        next: 'Try again, or try a different file.',
        token: 'danger',
        severity: 'error',
    },
    internal: {
        label: 'Bunny problem',
        headline: 'Something inside Bunny went wrong.',
        next: 'This one is worth reporting — Details has what to include.',
        token: 'danger',
        severity: 'error',
    },
    missing: {
        label: 'Not found',
        headline: 'Bunny could not find what it needed.',
        next: 'Check the file is still where it was, then ask again.',
        token: 'warning',
        severity: 'warning',
    },
    offline: {
        label: 'Unavailable offline',
        headline: 'This needs something that is not available right now.',
        next: 'Connect to a network, or set up a local model in Settings.',
        token: 'warning',
        severity: 'warning',
    },
};

/** Reasons the runtime sends, mapped to the taxonomy. Order matters: first match wins. */
const REASON_PATTERNS = [
    [/\b(denied|declined|refused by the user|user denied|said no)\b/i, 'denied'],
    [/\b(blocked|not permitted|forbidden|policy|unauthorised|unauthorized|sandbox)\b/i, 'blocked'],
    [/\b(not found|no such file|missing|does not exist)\b/i, 'missing'],
    [/\b(offline|unreachable|no network|not connected|no provider)\b/i, 'offline'],
    [/\b(exited|crashed|non-zero|application|capsule failed)\b/i, 'application-failed'],
];

/**
 * Classify a failure.
 *
 * `kind` from the runtime wins outright when it names one of the six; the
 * pattern match is a fallback for a reason string that arrived without one, and
 * the fallback of last resort is `internal` rather than `application-failed`.
 * That default is deliberate: a failure Bunny cannot classify is a failure in
 * Bunny's own understanding, and telling a person their application misbehaved
 * when the truth is "we do not know" moves the blame to the wrong place.
 */
export function classifyFailure({kind = '', reason = ''} = {}) {
    const named = String(kind).trim();
    if (Object.prototype.hasOwnProperty.call(ERROR_KINDS, named))
        return named;
    const text = String(reason);
    for (const [pattern, classified] of REASON_PATTERNS) {
        if (pattern.test(text))
            return classified;
    }
    return 'internal';
}

/**
 * Build the task-status model.
 *
 * @param {object} state
 * @param {string} state.phase    a companion.presentation phase
 * @param {string} state.caption  the runtime's own sentence, if any
 * @param {string[]} state.stages named stages, in order
 * @param {number} state.stageIndex which stage is current, -1 for none
 * @param {number|null} state.percent a *measured* percentage, or null
 */
export function buildTaskStatus({
    phase = 'idle', caption = '', stages = [], stageIndex = -1, percent = null,
} = {}) {
    const state = PHASE_TO_STATE[phase] ?? 'waiting';
    const presentation = STATE_PRESENTATION[state];
    const named = Array.isArray(stages) ? stages.filter(s => typeof s === 'string' && s.trim()) : [];
    const index = Number.isInteger(stageIndex) ? stageIndex : -1;

    return {
        phase,
        state,
        label: presentation.label,
        glyph: presentation.glyph,
        token: presentation.token,
        // The runtime's sentence, when it has one. Never composed here: the
        // desktop saying something different from the runtime is how a surface
        // reporting availability and a surface reporting activity came to
        // contradict each other on a booted screen.
        detail: String(caption ?? ''),
        stages: named.map((name, position) => ({
            name,
            done: index >= 0 && position < index,
            current: position === index,
        })),
        // Only ever a number the runtime measured. §21.
        percent: typeof percent === 'number' && Number.isFinite(percent)
            ? Math.min(100, Math.max(0, percent))
            : null,
        // Spoken as one phrase, because a screen reader announcing "Working"
        // and then a separate caption gives no clue the two are one status.
        announcement: [presentation.label, caption].filter(Boolean).join('. '),
        busy: state === 'working',
        needsAnswer: state === 'approval',
        terminal: ['completed', 'blocked', 'failed', 'cancelled'].includes(state),
    };
}

/**
 * §22. The completion surface.
 *
 * `provenance` is a short sentence, not an audit trail: the brief is explicit
 * that the normal result view must not be overwhelmed by audit detail, and the
 * audit detail already has a home in the Approval Centre.
 */
export function buildResult({
    files = [], kind = '', preview = '', provenance = '', unchanged = '',
} = {}) {
    const named = (Array.isArray(files) ? files : [])
        .map(file => String(file ?? '').trim())
        .filter(Boolean);
    return {
        files: named,
        primary: named[0] ?? '',
        kind: String(kind ?? ''),
        preview: String(preview ?? ''),
        provenance: String(provenance ?? ''),
        // "Your original wasn't changed" is the fact a person most wants after
        // an edit, so it is a field rather than a sentence inside provenance.
        unchanged: String(unchanged ?? ''),
        actions: named.length > 0
            ? [
                {id: 'open', label: 'Open', accessibleName: `Open ${named[0]}`},
                {id: 'reveal', label: 'Show in Files', accessibleName: `Show ${named[0]} in Files`},
            ]
            : [],
        announcement: named.length > 0
            ? `Completed. ${named.join(', ')}${provenance ? `. ${provenance}` : ''}`
            : 'Completed.',
    };
}

/** §23. The failure surface. */
export function buildError({kind = '', reason = '', detail = '', canRetry = false} = {}) {
    const classified = classifyFailure({kind, reason});
    const entry = ERROR_KINDS[classified];
    const actions = [];
    if (canRetry)
        actions.push({id: 'retry', label: 'Try again', accessibleName: 'Try this task again'});
    if (classified === 'blocked' || classified === 'denied')
        actions.push({id: 'permissions', label: 'Open Settings', accessibleName: 'Open permission settings'});

    return {
        kind: classified,
        label: entry.label,
        headline: entry.headline,
        // The runtime's own sentence, kept beside the taxonomy's rather than
        // replacing it: the taxonomy says what class of thing happened and the
        // reason says which one.
        explanation: String(reason ?? ''),
        next: entry.next,
        token: entry.token,
        severity: entry.severity,
        detail: String(detail ?? ''),
        actions,
        announcement: [entry.headline, reason, entry.next].filter(Boolean).join(' '),
    };
}

/**
 * §20. The protected-space component.
 *
 * Simple and technical views from the *same* effective plan, which is what makes
 * them unable to disagree. `plan` is `capsule_status`'s record; the simple rows
 * are a projection of it and the technical rows are the whole of it, and neither
 * is assembled from a separate description of what the capsule is supposed to
 * be doing.
 */
export function buildProtectedSpace(plan = {}) {
    const value = key => {
        const found = plan?.[key];
        return typeof found === 'string' && found.trim() ? found.trim() : '';
    };
    const network = value('network');
    const rows = [
        {key: 'files', label: 'Files', value: value('fileAccess'), standing: 'granted'},
        {
            key: 'network',
            label: 'Network',
            value: network,
            standing: network.toLowerCase() === 'off' ? 'blocked' : 'granted',
        },
        {key: 'appData', label: 'App data', value: value('privateAppData'), standing: 'granted'},
    ].filter(row => row.value);

    const enforced = plan?.enforced !== false;
    return {
        on: rows.length > 0,
        heading: rows.length > 0 ? 'Protected space: On' : 'Protected space: not in use',
        rows: rows.map(row => ({...row, enforced})),
        // §19: the difference between a restriction and a claim about one.
        standing: enforced ? 'granted' : 'unenforced',
        details: Object.entries(plan ?? {})
            .filter(([, entry]) => typeof entry === 'string' || typeof entry === 'number')
            .map(([label, entry]) => ({label, value: String(entry)})),
        announcement: rows.length > 0
            ? `Protected space on. ${rows.map(r => `${r.label}: ${r.value}`).join('. ')}. ` +
              `${enforced ? 'Enforced' : 'Declared, not enforced'}.`
            : 'Protected space is not in use for this task.',
    };
}
