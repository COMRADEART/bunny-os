// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A permission question turned into something drawable, and nothing else.
//
// The record this takes comes from trust.explain.TrustPrompt.as_record(). It
// already contains every sentence, in final wording, with the reason attributed
// and the enforcement note present or absent. This module does not compose
// sentences: it decides order, focus, grouping and emphasis. That split is the
// point — a surface that could write the words could write different words from
// the ones the policy engine authorised.
//
// Four properties, each of which is a way a permission dialog goes wrong.
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
// person who most needs to know.
//
// **Nothing is truncated silently.** A resource string longer than the field is
// elided by the trust layer, which knows what part matters (the file name).
// If a value arrives longer than this module expects, it is shown in full and
// the layout wraps, because a path truncated in the middle of a directory name
// is a different path.

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

function nonEmpty(value) {
    return typeof value === 'string' && value.trim().length > 0;
}

/**
 * Build the drawable model for one prompt record.
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

    return {
        requestId: record.requestId,
        category: record.category,
        heading: record.headline,
        subheading: record.categoryTitle,
        risk: record.risk,
        riskToken: RISK_TOKENS[record.risk] || 'accent',
        marked: MARKED_RISKS.includes(record.risk),
        body,
        buttons,
        // Focus starts on the safe option. Reading order is the array above;
        // focus order starts at the end of it and wraps.
        initialFocus: 'deny',
        defaultAction: 'deny',
        escapeAction: 'deny',
        // Closing the window is an answer, and the answer is no.
        closeAction: 'deny',
        enforced: !nonEmpty(record.enforcementNote),
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
