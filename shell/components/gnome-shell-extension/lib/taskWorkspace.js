// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The panel that shows what Bunny is doing, built from the workspace record.
//
// The record comes from companion.capsule_bridge.TaskWorkspace.as_record(), and
// it is closed: seven step keys, a fixed action vocabulary, and no field for a
// model's reasoning. This module lays it out. It cannot add a row, so it cannot
// add a row containing something the projection was designed not to carry.
//
// Three layout decisions worth stating, because each replaces something worse.
//
// **Steps are always all seven, and the future ones are visible.** A progress
// list that only shows what has happened tells a person nothing about how much
// is left, and a spinner tells them nothing at all. The rows that have not
// happened are drawn dim, which is also how a screen reader announces "3 of 7".
//
// **A permission request takes the panel over.** When the task is waiting for an
// answer, the panel's primary content is the question, not the step list. §16
// puts permission requests in the workspace and §12 puts the Companion into an
// attention state; a question that scrolled past under a progress bar would be a
// question a person answers by accident.
//
// **Warnings never live in a step's detail.** A step says what happened; a
// warning says something about the run that the person should carry away —
// an unenforced permission, a grant that could not be honoured. They are a
// separate region so that finishing successfully does not scroll the warning off.

/** The step keys, in order. Matches companion.capsule_bridge.STEP_LABELS. */
export const STEP_KEYS = ['choose', 'install', 'permission', 'open', 'work', 'export', 'done'];

/** How each step state is drawn. Names, not colours; the theme owns values. */
export const STEP_TOKENS = {
    pending: {token: 'muted', glyph: 'circle-outline'},
    running: {token: 'accent', glyph: 'circle-progress'},
    done: {token: 'accent', glyph: 'circle-check'},
    failed: {token: 'danger', glyph: 'circle-cross'},
    refused: {token: 'warning', glyph: 'circle-hand'},
};

/** Which actions get a visible button, and in what order. */
export const ACTION_ORDER = ['view_result', 'open_application', 'watch', 'inspect_permissions', 'minimise', 'cancel'];

export const ACTION_LABELS = {
    watch: 'Watch',
    minimise: 'Hide',
    cancel: 'Stop',
    inspect_permissions: 'What can it see?',
    open_application: 'Open the app',
    view_result: 'Show me',
};

/** Task states that mean the panel should stay on screen without being asked. */
export const STICKY_STATES = ['waiting_for_you', 'failed'];

function stepStates(record) {
    const seen = new Map();
    for (const step of record.steps || [])
        seen.set(step.key, step);
    return STEP_KEYS.map((key, index) => {
        const found = seen.get(key);
        if (found)
            return {key, index, label: found.label, state: found.state, detail: found.detail || ''};
        return {key, index, label: '', state: 'pending', detail: ''};
    });
}

/**
 * Build the panel model.
 *
 * @param {object} record  TaskWorkspace.as_record()
 * @param {object} options {reducedMotion, largeText, compact}
 */
export function buildWorkspace(record, options = {}) {
    if (!record || typeof record !== 'object')
        throw new Error('a task workspace needs a record');
    const {reducedMotion = false, largeText = false, compact = false} = options;

    const steps = stepStates(record);
    const completed = steps.filter(step => step.state === 'done').length;
    const failed = steps.find(step => step.state === 'failed' || step.state === 'refused') || null;
    const running = steps.find(step => step.state === 'running') || null;

    const actions = ACTION_ORDER
        .filter(name => (record.actions || []).includes(name))
        .map(name => ({id: name, label: ACTION_LABELS[name], destructive: name === 'cancel'}));

    const outputs = (record.outputs || []).map(output => ({
        display: output.display,
        renamed: !!output.renamed,
        // The only place the panel makes a claim about the original, and it is
        // read from the export result rather than assumed.
        originalNote: output.originalPreserved
            ? 'Your original was not changed.'
            : (output.originalCopy ? 'Your original was replaced; a copy is next to it.' : 'Your original was replaced.'),
    }));

    return {
        taskId: record.taskId,
        title: record.title,
        state: record.state,
        application: record.applicationName || null,
        // 3 of 7, for both the drawn label and the announcement.
        progress: {completed, total: STEP_KEYS.length, label: `${completed} of ${STEP_KEYS.length}`},
        steps: steps.map(step => ({...step, ...STEP_TOKENS[step.state]})),
        // When a question is outstanding the panel leads with it.
        leadWithQuestion: record.state === 'waiting_for_you',
        activeStep: running ? running.key : (failed ? failed.key : null),
        files: record.authorisedFiles || [],
        permissions: (record.permissions || []).map(entry => ({
            category: entry.category,
            resource: entry.resource || '',
            verdict: entry.verdict,
            scope: entry.scope,
        })),
        warnings: record.warnings || [],
        outputs,
        actions,
        summary: record.summary || '',
        sticky: STICKY_STATES.includes(record.state),
        compact,
        largeText,
        // Zero means the panel changes rows without a transition. The rows still
        // change; a person who asked for less motion did not ask for less
        // information.
        motionMs: reducedMotion ? 0 : 180,
        announcement: buildAnnouncement(record, completed),
    };
}

/**
 * One sentence for a screen reader, rebuilt on every change.
 *
 * Deliberately not the summary: the summary is the final sentence and is empty
 * while the task runs. A person who cannot see the panel needs to know where the
 * task is *now*, which is the step and the count.
 */
export function buildAnnouncement(record, completed) {
    const total = STEP_KEYS.length;
    if (record.state === 'completed')
        return record.summary || 'Finished.';
    if (record.state === 'failed')
        return record.summary || 'That did not work.';
    if (record.state === 'waiting_for_you')
        return 'Bunny needs your answer.';
    const running = (record.steps || []).find(step => step.state === 'running');
    const label = running ? running.label : 'Working';
    return `${label}. Step ${completed + 1} of ${total}.`;
}
