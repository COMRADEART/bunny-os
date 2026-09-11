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

/** Security #47: this build can only hold Off or On (full internet). */
export const NETWORK_OFF = 'Off';
export const NETWORK_FULL_INTERNET = 'On (full internet)';
export const NETWORK_ALLOWLIST_NOTE =
    "Site allowlists aren’t available yet — Full internet or Off.";

/** Allowlisted ceiling (LibreOffice, named destinations): denied, not a pending filter. */
export const ALLOWLISTED_CEILING_NOTE =
    'No network until a real filter ships, or you allow the full internet. '
    + 'Bunny is not waiting for a site list.';

/** Clipboard / Bluetooth: deny-before-prompt. Do not imply mediation. */
export const CLIPBOARD_BLUETOOTH_NOTE =
    'Clipboard and Bluetooth are not mediated in this build. Requests are denied '
    + 'before a prompt — Bunny cannot watch the clipboard or pair devices for an app.';

/** Privacy cloud_context=none. Distinct from the remote_dispatch TrustPrompt line. */
export const CLOUD_MEMORY_IS_OFF =
    'Cloud memory is off. Bunny won’t send saved memory, session memory, '
    + 'or a conversation summary online.';

/** Security #52: remote_dispatch is not cloud memory. */
export const CLOUD_MEMORY_STAYS_OFF =
    'Cloud memory stays off. Allowing this sends only what you asked this time '
    + 'to that online service — not your saved memory, session memory, or a conversation summary.';

/** “Never go online for models” is AI mode Local only, not Cloud memory off. */
export const NO_ONLINE_MODELS_IS_LOCAL_ONLY =
    'No online models ever is Local only — not Cloud memory off.';

export const ALLOW_ONCE_LABEL = 'Allow once';
export const DONT_ALLOW_LABEL = "Don't allow";
export const ALLOW_ACCESSIBLE_NAME = 'Allow this Bunny action';
export const DENY_ACCESSIBLE_NAME = 'Deny this Bunny action';

/** Phase 4: opening a file in an application is a Trust question. */
export const FILE_OPEN_HEADLINE = 'Bunny wants to open this file';
export const FILE_OPEN_BUBBLE = 'Review this open request.';
export const FILE_NOT_UPLOADED = 'No file is uploaded automatically.';
/** P4.1: Allow once executes the open. Don't allow opens nothing. */
export const FILE_OPEN_GRANTED = 'Allow once. Bunny opened this file. Nothing was uploaded.';
export const FILE_OPEN_DENIED =
    "Don't allow. The file was not opened. "
    + 'Ask again and choose Allow once if that was a mistake.';
export const FILE_OPEN_FAILED = 'Allow once was recorded, but Bunny could not open this file.';

function nonEmpty(value) {
    return typeof value === 'string' && value.trim().length > 0;
}

function networkToken(value) {
    return String(value ?? '').trim().toLowerCase();
}

function isExplicitNetworkOff(lower) {
    return lower === 'off' || lower === 'none' || lower === 'blocked'
        || lower === 'nothing on the network';
}

function isExplicitFullInternet(lower) {
    return lower === 'on' || lower === 'internet' || lower === 'full internet'
        || lower === 'on (full internet)' || lower === 'the internet'
        || lower === 'granted';
}

/**
 * Catalogue declarations this build cannot filter: allowlisted ceilings
 * (LibreOffice), loopback, local-network, hostnames. Fail-closed Off —
 * never “waiting for domains”.
 */
export function networkIsDeclaredOnly(value) {
    const lower = networkToken(value);
    if (!lower)
        return false;
    if (isExplicitNetworkOff(lower) || isExplicitFullInternet(lower))
        return false;
    return true;
}

/**
 * Person-facing network label. Only Off or On (full internet).
 *
 * An allowlisted ceiling or a hostname is Off until a real filter ships or
 * the person explicitly raises the ceiling. Domain lists are never reprinted.
 */
export function networkFacingLabel(value) {
    const text = String(value ?? '').trim();
    if (!text)
        return '';
    const lower = networkToken(text);
    if (isExplicitFullInternet(lower))
        return NETWORK_FULL_INTERNET;
    return NETWORK_OFF;
}

function isUnboundedGrant(option) {
    const scope = String(option?.scope ?? '').toLowerCase();
    const label = String(option?.label ?? '').toLowerCase();
    if (scope === '*' || scope === 'everything' || scope === 'unbounded')
        return true;
    return label.includes('everything') || label.includes('unbounded')
        || label.includes('always allow all');
}

/**
 * Buttons a person may press. Never “Always allow everything”. Network never
 * offers Always — that would be an unbounded internet grant.
 */
export function boundedAllowOptions(options, category = '') {
    const cat = String(category ?? '').toLowerCase();
    return (Array.isArray(options) ? options : []).filter(option => {
        if (!option || typeof option !== 'object')
            return false;
        if (isUnboundedGrant(option))
            return false;
        if (cat === 'network' && String(option.scope ?? '').toLowerCase() === 'always')
            return false;
        return true;
    });
}

export function remoteDispatchDisclosure({
    cloudContext = 'none', offeringRemoteDispatch = false,
} = {}) {
    if (!offeringRemoteDispatch)
        return '';
    const cloud = String(cloudContext ?? 'none').trim().toLowerCase();
    if (cloud === 'none' || cloud === '')
        return CLOUD_MEMORY_STAYS_OFF;
    return '';
}

function offersRemoteDispatch(approval, prompt) {
    if (approval?.offeringRemoteDispatch === true || prompt?.offeringRemoteDispatch === true)
        return true;
    const tokens = [
        approval?.action, approval?.capability, approval?.category,
        prompt?.kind, prompt?.operationId, prompt?.capability,
    ].map(value => String(value ?? '').toLowerCase().replace(/-/g, '_'));
    return tokens.some(token => token.includes('remote_dispatch'));
}

function cloudContextOf(approval, prompt) {
    const raw = approval?.cloudContext ?? prompt?.cloudContext
        ?? approval?.cloud_context ?? prompt?.cloud_context ?? 'none';
    return String(raw ?? 'none').trim().toLowerCase() || 'none';
}

function standingFor(key, value) {
    const text = String(value ?? '').trim();
    if (!text)
        return 'unavailable';
    if (key === 'network')
        return networkFacingLabel(text) === NETWORK_OFF ? 'blocked' : 'granted';
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
    const capabilityDisclosure = remoteDispatchDisclosure({
        cloudContext: cloudContextOf(record, record),
        offeringRemoteDispatch: offersRemoteDispatch(record, record),
    });
    if (capabilityDisclosure)
        body.push({key: 'remote-dispatch', text: capabilityDisclosure, emphasis: 'warning'});
    const category = String(record.category || '').toLowerCase();
    if ((category === 'clipboard' || category === 'bluetooth')
            && !body.some(line => line.text === CLIPBOARD_BLUETOOTH_NOTE))
        body.push({key: 'enforcement', text: CLIPBOARD_BLUETOOTH_NOTE, emphasis: 'warning'});
    if (category === 'network' && networkIsDeclaredOnly(record.resource))
        body.push({key: 'enforcement', text: ALLOWLISTED_CEILING_NOTE, emphasis: 'warning'});

    // Reading order: the allow options in escalating order, then deny.
    const buttons = boundedAllowOptions(record.options, record.category).map((option, index) => ({
        id: option.scope,
        label: option.label,
        verdict: 'allow',
        scope: option.scope,
        role: index === 0 ? 'suggested-weak' : 'normal',
        accessibleName: index === 0 ? ALLOW_ACCESSIBLE_NAME : option.label,
    }));
    buttons.push({
        id: 'deny',
        label: (record.denyOption && record.denyOption.label) || DONT_ALLOW_LABEL,
        verdict: 'deny',
        scope: null,
        role: 'safe-default',
        accessibleName: DENY_ACCESSIBLE_NAME,
    });

    const enforced = !nonEmpty(record.enforcementNote)
        && category !== 'clipboard' && category !== 'bluetooth';

    const allowButtons = buttons.filter(button => button.verdict === 'allow');
    const firstAllowScope = (allowButtons[0] && allowButtons[0].scope) || 'once';
    const identity = identityOf(record);

    return {
        source: 'capability',
        requestId: record.requestId,
        category: record.category,
        heading: record.headline,
        subheading: record.categoryTitle,
        identity,
        risk: record.risk,
        riskToken: RISK_TOKENS[record.risk] || 'accent',
        marked: MARKED_RISKS.includes(record.risk),
        body,
        confinement: [],
        buttons,
        facts: factsOf({
            who: identity ? identity.name : '',
            what: record.capabilityNote || record.categoryTitle || '',
            why: record.reason || record.reasonNote || '',
            scope: firstAllowScope,
        }),
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

    const networkShown = nonEmpty(prompt.network);
    if (networkShown)
        body.push({key: 'enforcement', text: NETWORK_ALLOWLIST_NOTE, emphasis: 'warning'});
    if (networkIsDeclaredOnly(prompt.network))
        body.push({key: 'enforcement', text: ALLOWLISTED_CEILING_NOTE, emphasis: 'warning'});
    const disclosure = remoteDispatchDisclosure({
        cloudContext: cloudContextOf(approval, prompt),
        offeringRemoteDispatch: offersRemoteDispatch(approval, prompt),
    });
    if (disclosure)
        body.push({key: 'remote-dispatch', text: disclosure, emphasis: 'warning'});

    const confinement = CONFINEMENT_ROWS
        .filter(row => nonEmpty(prompt[row.key]))
        .map(row => ({
            key: row.key,
            label: row.label,
            value: row.key === 'network' ? networkFacingLabel(prompt[row.key]) : prompt[row.key],
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
            label: ALLOW_ONCE_LABEL,
            verdict: 'allow',
            scope: 'once',
            role: 'suggested-weak',
            // The name the harness presses and the name Orca speaks. It says
            // what pressing does, because "Allow" alone in a list of buttons is
            // not a sentence a screen reader user can act on.
            accessibleName: ALLOW_ACCESSIBLE_NAME,
        },
        {
            id: 'deny',
            label: DONT_ALLOW_LABEL,
            verdict: 'deny',
            scope: null,
            role: 'safe-default',
            accessibleName: DENY_ACCESSIBLE_NAME,
        },
    ];

    const identity = identityOf(prompt);

    return {
        source: 'task',
        requestId: String(approval.requestId ?? ''),
        taskId: String(approval.taskId ?? ''),
        category: nonEmpty(prompt.kind) ? prompt.kind : 'task',
        heading,
        subheading: nonEmpty(prompt.operationId) ? prompt.operationId : (approval.action || ''),
        identity,
        risk: 'medium',
        riskToken: RISK_TOKENS.medium,
        marked: false,
        body,
        confinement,
        buttons,
        facts: factsOf({
            who: identity ? identity.name : '',
            what: prompt.expectedEffect || heading,
            why: nonEmpty(prompt.disclosure)
                ? `You asked Bunny to use ${prompt.disclosure}.`
                : (nonEmpty(approval.reason) ? approval.reason : ''),
            scope: 'once',
        }),
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
    parts.push('Allow once, or don\'t allow. Don\'t allow is selected.');
    return parts.join(' ');
}

/**
 * How long an allow lasts, in words a person can use. Never a capability id.
 */
export function durationFor(scope) {
    if (scope === 'once')
        return 'This time only';
    if (scope === 'session')
        return 'Until you close this app';
    if (scope === 'always')
        return 'Until you change it in Permissions';
    return 'Only for this request';
}

function factsOf({who, what, why, scope}) {
    return {
        who: who || '',
        what: what || '',
        why: why || '',
        duration: durationFor(scope),
    };
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
