// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A permission question turned into something drawable, and nothing else.
//
// This module does not compose sentences. Every string it places has already
// been written by the trust layer or the capsule bridge, in final wording, with
// the reason attributed and the enforcement note present or absent. What it
// decides is order, focus, grouping and emphasis. That split is the point — a
// surface that could write the words could write different words from the ones
// the policy engine authorised.
//
// ## Two sources, one model
//
// A permission question reaches the desktop by one of two routes and they carry
// different records:
//
//   `trust.explain.TrustPrompt.as_record()`  — the capability question:
//       "Bunny wants to use your camera". Categories, risk, scopes, revocation.
//   `companion.presentation.ApprovalPresentation.to_json()` — the task question:
//       "Bunny wants to open holiday.png in GIMP". Application identity, the
//       resource, the confinement it will run under.
//
// Both are questions a person answers with the same two buttons, so both build
// the same model and one surface draws it. Before this, neither built anything:
// `buildPrompt` had no caller outside the tests, and the desktop drew
// `approval.reason` — one string — with two buttons under it.
//
// ## Four properties, each a way a permission dialog goes wrong
//
// **Deny is focused, and it is the default action.** A person who presses Return
// without reading has denied something. That is recoverable; the opposite is not.
// The deny button is last in reading order and first in focus order, and those
// being different is deliberate: the eye reads the options in escalating order,
// the keyboard starts on the safe one.
//
// **The reason is never promoted above the fact.** The headline says what the
// application will be able to do. The reason — which is a claim, by the
// application or by the catalogue — sits below it, attributed. A dialog that led
// with "so it can check for updates" would be letting the claim frame the fact.
//
// **An unenforced permission is marked in the dialog, not only in Settings.**
// If this build cannot actually stop the application, the person deciding is the
// person who most needs to know. §19: that mark is a glyph and a word as well as
// a colour, because the reader who cannot distinguish the colour is being asked
// to make a security decision.
//
// **Nothing is truncated silently.** A resource string longer than the field is
// elided by the trust layer, which knows what part matters (the file name), and
// bounded again by `companion.presentation.PROMPT_FIELDS` before it leaves the
// runtime. If a value arrives longer than this module expects, it is shown in
// full and the layout wraps, because a path truncated in the middle of a
// directory name is a different path.

/** Reading order for the body. Fixed; the tests assert on it. */
export const BODY_ORDER = ['resource', 'capability', 'reason', 'enforcement'];

/** Risk levels that get a visible marker beside the heading. */
export const MARKED_RISKS = ['high', 'critical'];

/**
 * Which token names the surface should use for a given risk. Names rather than
 * colours, so the stylesheet and the high-contrast theme decide the values.
 */
export const RISK_TOKENS = {
    low: 'accent',
    medium: 'accent',
    high: 'warning',
    critical: 'danger',
};

/**
 * The confinement rows a task prompt shows, in reading order.
 *
 * `standing` is the vocabulary of `STANDING` in design/tokens.js, so each row
 * draws with a glyph and a word as well as a colour. `enforced` says whether
 * this build can actually hold the restriction — the difference between
 * "Network off — enforced" and "Network restrictions declared but not enforced",
 * which §19 requires a person to be able to see without reading documentation.
 */
export const CONFINEMENT_ROWS = [
    {key: 'fileAccess', label: 'Files'},
    {key: 'network', label: 'Network'},
    {key: 'privateAppData', label: 'App data'},
];

function nonEmpty(value) {
    return typeof value === 'string' && value.trim().length > 0;
}

function standingFor(key, value) {
    const text = String(value ?? '').trim();
    if (!text)
        return 'unavailable';
    if (key === 'network')
        return text.toLowerCase() === 'off' ? 'blocked' : 'granted';
    return 'granted';
}

/**
 * Build the drawable model for one `trust.explain.TrustPrompt` record.
 *
 * @param {object} record  trust.explain.TrustPrompt.as_record()
 * @param {object} options {highContrast, largeText, screenReader}
 */
export function buildPrompt(record, options = {}) {
    if (!record || typeof record !== 'object')
        throw new Error('a trust prompt needs a record');
    const {highContrast = false, largeText = false, screenReader = false} = options;

    const body = [];
    for (const key of BODY_ORDER) {
        if (key === 'resource' && nonEmpty(record.resource) && !String(record.headline).includes(record.resource))
            body.push({key, text: record.resource, emphasis: 'strong'});
        else if (key === 'capability' && nonEmpty(record.capabilityNote))
            body.push({key, text: record.capabilityNote, emphasis: 'normal'});
        else if (key === 'reason' && nonEmpty(record.reason))
            body.push({key, text: record.reason, emphasis: 'quiet'});
        else if (key === 'reason' && nonEmpty(record.reasonNote))
            body.push({key, text: record.reasonNote, emphasis: 'quiet'});
        else if (key === 'enforcement' && nonEmpty(record.enforcementNote))
            body.push({key, text: record.enforcementNote, emphasis: 'warning'});
    }

    // Reading order: the allow options in escalating order, then deny.
    const buttons = (record.options || []).map((option, index) => ({
        id: option.scope,
        label: option.label,
        verdict: 'allow',
        scope: option.scope,
        role: index === 0 ? 'suggested-weak' : 'normal',
    }));
    buttons.push({
        id: 'deny',
        label: (record.denyOption && record.denyOption.label) || "Don't allow",
        verdict: 'deny',
        scope: null,
        role: 'safe-default',
    });

    const enforced = !nonEmpty(record.enforcementNote);

    return {
        source: 'capability',
        requestId: record.requestId,
        category: record.category,
        heading: record.headline,
        subheading: record.categoryTitle,
        identity: identityOf(record),
        risk: record.risk,
        riskToken: RISK_TOKENS[record.risk] || 'accent',
        marked: MARKED_RISKS.includes(record.risk),
        body,
        confinement: [],
        buttons,
        details: detailsOf(record),
        // Focus starts on the safe option. Reading order is the array above;
        // focus order starts at the end of it and wraps.
        initialFocus: 'deny',
        defaultAction: 'deny',
        escapeAction: 'deny',
        // Closing the window is an answer, and the answer is no.
        closeAction: 'deny',
        enforced,
        standing: enforced ? 'not-asked' : 'unenforced',
        revocation: record.revocation,
        // One string for a screen reader, built by the trust layer so the spoken
        // and drawn forms cannot drift.
        announcement: record.spoken || record.headline,
        announceImmediately: screenReader,
        style: {
            highContrast,
            largeText,
            // A permission dialog never dims to the point of being missable; the
            // scrim is heavier at high contrast rather than lighter.
            scrim: highContrast ? 'solid' : 'dim',
        },
    };
}

/**
 * Build the same model from a task approval.
 *
 * The structured facts live in `approval.prompt`, which the runtime fills from
 * `CapsuleSupport.prompt_for`. When it is absent — an approval raised by
 * something that has no structured form, or an older runtime — the model falls
 * back to `approval.reason`, which is the single string every build before this
 * one drew. Degrading to the old surface is the correct failure: it is worse,
 * and it is still a question with the right two answers.
 */
export function buildApproval(approval, options = {}) {
    if (!approval || typeof approval !== 'object')
        throw new Error('a trust prompt needs an approval');
    const {highContrast = false, largeText = false, screenReader = false} = options;
    const prompt = (approval.prompt && typeof approval.prompt === 'object') ? approval.prompt : {};

    const heading = nonEmpty(prompt.presentation)
        ? prompt.presentation
        : (nonEmpty(approval.reason) ? approval.reason : 'Allow Bunny to perform this action?');

    const body = [];
    if (nonEmpty(prompt.expectedEffect))
        body.push({key: 'capability', text: prompt.expectedEffect, emphasis: 'normal'});
    if (nonEmpty(prompt.disclosure))
        body.push({key: 'resource', text: `Shared with the application: ${prompt.disclosure}`, emphasis: 'quiet'});
    // With no structured prompt there is one string, and it is the heading, so
    // repeating it in the body would show the person the same sentence twice.
    if (body.length === 0 && nonEmpty(approval.reason) && approval.reason !== heading)
        body.push({key: 'reason', text: approval.reason, emphasis: 'quiet'});

    const confinement = CONFINEMENT_ROWS
        .filter(row => nonEmpty(prompt[row.key]))
        .map(row => ({
            key: row.key,
            label: row.label,
            value: prompt[row.key],
            standing: standingFor(row.key, prompt[row.key]),
            // Every restriction shown here is one the capsule runtime holds. A
            // row this surface could not verify would need `enforced: false`
            // and the badge that goes with it; there is no such row today, and
            // the field is here so that adding one cannot be silent.
            enforced: true,
        }));

    const buttons = [
        {
            id: 'allow',
            label: 'Allow',
            verdict: 'allow',
            scope: 'once',
            role: 'suggested-weak',
            // The name the harness presses and the name Orca speaks. It says
            // what pressing does, because "Allow" alone in a list of buttons is
            // not a sentence a screen reader user can act on.
            accessibleName: 'Allow this Bunny action',
        },
        {
            id: 'deny',
            label: 'Deny',
            verdict: 'deny',
            scope: null,
            role: 'safe-default',
            accessibleName: 'Deny this Bunny action',
        },
    ];

    return {
        source: 'task',
        requestId: String(approval.requestId ?? ''),
        taskId: String(approval.taskId ?? ''),
        category: nonEmpty(prompt.kind) ? prompt.kind : 'task',
        heading,
        subheading: nonEmpty(prompt.operationId) ? prompt.operationId : (approval.action || ''),
        identity: identityOf(prompt),
        risk: 'medium',
        riskToken: RISK_TOKENS.medium,
        marked: false,
        body,
        confinement,
        buttons,
        details: detailsOf(approval),
        initialFocus: String(approval.safeDefault ?? 'denied') === 'allowed' ? 'allow' : 'deny',
        defaultAction: 'deny',
        escapeAction: 'deny',
        closeAction: 'deny',
        enforced: true,
        standing: 'not-asked',
        revocation: '',
        announcement: spokenFor(heading, body, confinement),
        announceImmediately: screenReader,
        style: {
            highContrast,
            largeText,
            scrim: highContrast ? 'solid' : 'dim',
        },
    };
}

/** Application identity, or nothing. Never a placeholder name. */
function identityOf(source) {
    const name = nonEmpty(source.applicationName) ? source.applicationName : '';
    const id = nonEmpty(source.applicationId) ? source.applicationId : '';
    if (!name && !id)
        return null;
    // An application with an id and no name is shown by its id rather than by
    // "Unknown application": the id is a fact and the placeholder is a guess,
    // and a person deciding a permission is owed the fact.
    const shown = name || id;
    return {
        name: shown,
        id,
        // Compared against what is actually drawn, not against the raw name. An
        // application with only an id was showing its id twice, once as the
        // name and once underneath it.
        showId: Boolean(id) && id !== shown,
    };
}

/**
 * The technical panel, behind Details. §28: technical detail belongs there and
 * not in the primary dialog.
 */
function detailsOf(source) {
    const rows = [];
    const add = (label, value) => {
        if (nonEmpty(value))
            rows.push({label, value: String(value)});
    };
    add('Request', source.requestId);
    add('Application', source.applicationId);
    add('Operation', source.operationId ?? source.action);
    add('Task', source.taskId);
    add('Plan', source.planId);
    add('Category', source.category);
    add('Destination', source.destinationDetail || source.destination);
    add('Data', source.dataClassification);
    add('Revocation', source.revocation);
    return rows;
}

/**
 * What a screen reader hears, for a prompt whose source did not supply one.
 *
 * The capability route gets `spoken` from the trust layer, built once so the
 * drawn and spoken forms cannot drift. The task route has no equivalent, so it
 * is assembled here from the same fields the surface draws — in the same order —
 * rather than from a second description of the question.
 */
function spokenFor(heading, body, confinement) {
    const parts = [heading];
    for (const line of body)
        parts.push(line.text);
    for (const row of confinement)
        parts.push(`${row.label}: ${row.value}`);
    parts.push('Allow, or deny. Deny is selected.');
    return parts.join(' ');
}

/**
 * The order the keyboard visits controls in.
 *
 * Deny first, then the allow options weakest-first, then the disclosure. Exposed
 * separately from buildPrompt so a test can assert the order without asserting
 * the whole model, and so a surface that lays out differently still has one
 * definition of what Tab does.
 */
export function focusOrder(model) {
    const deny = model.buttons.filter(button => button.verdict === 'deny').map(button => button.id);
    const allow = model.buttons.filter(button => button.verdict === 'allow').map(button => button.id);
    return [...deny, ...allow, 'advanced-disclosure'];
}
