// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Trust component: the permission question, drawn.
//
// ## What this replaced
//
// A strip inside the assistant card with one label and two buttons:
//
//     this._approvalLabel.text = String(approval?.reason ?? 'Allow Bunny to …');
//
// The label held three sentences that `capsule_task_bridge` had concatenated
// specifically so that one label could hold them. Meanwhile the structured form
// of the same facts — application identity, the resource, the effect, the file
// access, whether the network is on — was built by `prompt_for()` and had no
// caller, and `lib/trustPrompt.js` built a drawable model from it and had no
// caller either. Both ends of §18's component existed; the wire did not.
//
// ## What it does not do
//
// It does not decide anything. `model` comes from `lib/trustPrompt.js`, which
// comes from a projection of runtime state, and every string in it was written
// by the trust layer or the capsule bridge. This module chooses widgets. §2: a
// visual component may project state and must not own it, and the specific
// failure that rule exists to prevent is a dialog that can say "allowed" about a
// permission the runtime has not granted.
//
// It also does not own the answer. `onDecision(verdict, requestId)` hands the
// verdict back to the caller, which sends it over the protocol, and the runtime
// checks it against the question it issued. A compromised surface can lie about
// what a person said; it cannot answer a question that was not asked.
//
// ## The three properties the harness depends on
//
// The booted-guest slices press these controls with a virtio-tablet event at the
// button's own accessibility extents, so:
//
// * the accessible names stay exactly `Allow this Bunny action` and
//   `Deny this Bunny action`;
// * both buttons stay reactive, focusable and on screen;
// * focus lands on the safe answer when the question appears.
//
// A refactor that changed any of the three would leave the slices unable to
// press anything, and §40 lists the visible prompt and its routing among the
// behaviours a visual refactor must not regress.

import St from 'gi://St';

import {box} from '../widgets.js';
import {Icons, themedIcon} from '../icons.js';
import {currentTheme} from '../design/current.js';
import {makeActivatable} from '../util.js';
import {STANDING} from '../design/tokens.js';

/** Glyph names for the standing vocabulary, resolved through the icon layer. */
const STANDING_ICONS = {
    check: Icons.SUCCESS,
    slash: Icons.BLOCKED,
    block: Icons.BLOCKED,
    dash: Icons.UNKNOWN,
    warning: Icons.WARNING,
};

/**
 * An icon at a theme-derived size, with its style class.
 *
 * `themedIcon`'s second parameter is an options object, and passing a bare
 * class name to it destructures to nothing: the icon silently keeps the default
 * 16px and loses its class, which is how an icon ends up the wrong size on a
 * 200 % desktop and the wrong colour at high contrast. The size is passed
 * explicitly because St.Icon's `icon-size` property overrides the stylesheet's
 * `icon-size` once it is set, and `themedIcon` always sets it.
 */
function glyph(name, styleClass, size = null) {
    return themedIcon(name, {size: size ?? currentTheme().icon.medium, styleClass});
}

function wrapping(label) {
    label.clutter_text.line_wrap = true;
    // PangoWrapMode.WORD_CHAR: wrap on words, and break inside a word rather
    // than overflow when a single token is wider than the card. A file name
    // with no spaces is exactly that token, and this is a security dialog, so
    // running off the edge is not an option.
    label.clutter_text.set_line_wrap_mode(2);
    return label;
}

export class TrustComponent {
    /**
     * @param {object} options
     * @param {(verdict: string, requestId: string) => void} options.onDecision
     */
    constructor({onDecision = null} = {}) {
        this._onDecision = onDecision;
        this._model = null;
        this._requestId = '';

        this.actor = box({vertical: true, style_class: 'bunny-trust'});
        this._column = box({vertical: true, style_class: 'bunny-trust-column'});
        this.actor.add_child(this._column);

        // --- identity -----------------------------------------------------
        this._identity = box({style_class: 'bunny-trust-identity'});
        this._identityIcon = glyph(Icons.APPLICATION, 'bunny-trust-risk-glyph');
        this._identityText = box({vertical: true});
        this._identityName = new St.Label({style_class: 'bunny-trust-identity-name'});
        this._identityOrigin = new St.Label({style_class: 'bunny-trust-identity-origin'});
        this._identityText.add_child(this._identityName);
        this._identityText.add_child(this._identityOrigin);
        this._identity.add_child(this._identityIcon);
        this._identity.add_child(this._identityText);
        this._column.add_child(this._identity);

        // --- the question -------------------------------------------------
        this._heading = wrapping(new St.Label({style_class: 'bunny-trust-heading'}));
        this._column.add_child(this._heading);

        this._risk = box({style_class: 'bunny-trust-risk'});
        this._riskGlyph = glyph(Icons.WARNING, 'bunny-trust-risk-glyph');
        this._riskLabel = new St.Label({style_class: 'bunny-trust-risk-label'});
        this._risk.add_child(this._riskGlyph);
        this._risk.add_child(this._riskLabel);
        this._risk.visible = false;
        this._column.add_child(this._risk);

        this._body = box({vertical: true, style_class: 'bunny-trust-body'});
        this._column.add_child(this._body);

        // --- what the confinement will and will not allow ------------------
        this._confinement = box({vertical: true, style_class: 'bunny-trust-body'});
        this._column.add_child(this._confinement);

        // --- the answer ---------------------------------------------------
        const actions = box({style_class: 'bunny-trust-actions'});
        this._deny = this._action('Deny', 'deny');
        this._allow = this._action('Allow', 'allow');
        // Reading order is deny-last so the eye reads the options in escalating
        // order; focus order starts on deny. See focusOrder() in trustPrompt.js.
        actions.add_child(this._allow);
        actions.add_child(this._deny);
        this._column.add_child(actions);

        // --- technical details, behind a disclosure ------------------------
        // §22 and §28: an audit trail does not belong in the primary dialog,
        // and it does belong somewhere. Collapsed by default, and the state is
        // not remembered between questions — a person who opened the details
        // once has not asked to be shown a fingerprint every time.
        this._disclosure = this._link('Details', () => this._toggleDetails());
        this._column.add_child(this._disclosure);
        this._details = box({vertical: true, style_class: 'bunny-trust-details'});
        this._details.visible = false;
        this._column.add_child(this._details);

        this.actor.visible = false;
    }

    _action(label, verdict) {
        const button = new St.Button({
            label,
            style_class: `bunny-trust-action bunny-trust-action-${verdict === 'deny' ? 'safe' : 'allow'}`,
            can_focus: true,
            x_expand: true,
        });
        button.connect('clicked', () => this._decide(verdict));
        return button;
    }

    _link(label, onActivate) {
        const button = new St.Label({text: label, style_class: 'bunny-trust-disclosure'});
        makeActivatable(button, onActivate);
        return button;
    }

    // ------------------------------------------------------------- drawing

    /**
     * Draw one question.
     *
     * @param {object} model  from buildApproval() or buildPrompt()
     */
    show(model) {
        if (!model || !model.requestId)
            return false;
        this._model = model;
        this._requestId = model.requestId;

        this._drawIdentity(model.identity);
        this._heading.text = String(model.heading ?? '');
        this._drawRisk(model);
        this._drawLines(this._body, model.body ?? []);
        this._drawConfinement(model.confinement ?? []);
        this._drawButtons(model.buttons ?? []);
        this._drawDetails(model.details ?? []);

        // A new question closes the previous one's details. See the comment on
        // the disclosure above.
        this._details.visible = false;
        this._disclosure.text = 'Details';
        this._disclosure.visible = (model.details ?? []).length > 0;

        this.actor.visible = true;
        this.actor.accessible_name = model.announcement || model.heading || 'Bunny needs permission';

        this._focusSafeAnswer(model);
        return true;
    }

    _drawIdentity(identity) {
        if (!identity) {
            this._identity.visible = false;
            return;
        }
        this._identity.visible = true;
        this._identityName.text = identity.name;
        this._identityOrigin.text = identity.showId ? identity.id : '';
        this._identityOrigin.visible = Boolean(identity.showId);
        // Spoken as one phrase. Two labels in a row are announced as two
        // fragments, and "GIMP" then "org.gimp.GIMP" is not what a person
        // needs to hear first from a permission dialog.
        this._identity.accessible_name = identity.showId
            ? `${identity.name}, ${identity.id}` : identity.name;
    }

    _drawRisk(model) {
        // §19: the marker is a glyph and a word. The colour is the third cue,
        // not the only one — a person who cannot distinguish it is still being
        // asked to make a security decision.
        for (const token of ['accent', 'warning', 'danger'])
            this._risk.remove_style_class_name(`bunny-trust-risk-${token}`);
        if (!model.marked && model.enforced) {
            this._risk.visible = false;
            return;
        }
        this._risk.visible = true;
        this._risk.add_style_class_name(`bunny-trust-risk-${model.riskToken ?? 'accent'}`);
        this._riskLabel.text = model.enforced
            ? `${String(model.risk ?? '').toUpperCase()} RISK`
            : 'DECLARED, NOT ENFORCED';
        this._risk.accessible_name = this._riskLabel.text;
    }

    _drawLines(container, lines) {
        container.destroy_all_children();
        container.visible = lines.length > 0;
        for (const line of lines) {
            const label = wrapping(new St.Label({
                text: String(line.text ?? ''),
                style_class: `bunny-trust-line-${line.emphasis ?? 'normal'}`,
            }));
            container.add_child(label);
        }
    }

    _drawConfinement(rows) {
        this._confinement.destroy_all_children();
        this._confinement.visible = rows.length > 0;
        for (const row of rows) {
            const standing = STANDING[row.standing] ?? STANDING.unavailable;
            const line = box({style_class: `bunny-standing bunny-standing-${row.standing}`});
            line.add_child(glyph(
                STANDING_ICONS[standing.glyph] ?? Icons.UNKNOWN, 'bunny-standing-glyph',
                currentTheme().icon.small));
            const text = `${row.label}: ${row.value}`;
            line.add_child(new St.Label({text, style_class: 'bunny-standing-label'}));
            // "Network: Off — enforced" versus "declared, not enforced". §19
            // requires a person to tell those apart without documentation, and
            // this is the sentence that does it.
            const enforcement = row.enforced ? 'enforced' : 'declared, not enforced';
            line.accessible_name = `${text}, ${enforcement}`;
            if (!row.enforced)
                line.add_style_class_name('bunny-standing-unenforced');
            this._confinement.add_child(line);
        }
    }

    _drawButtons(buttons) {
        const allow = buttons.find(button => button.verdict === 'allow');
        const deny = buttons.find(button => button.verdict === 'deny');
        for (const [widget, spec, fallback] of [
            [this._allow, allow, 'Allow this Bunny action'],
            [this._deny, deny, 'Deny this Bunny action'],
        ]) {
            widget.label = spec?.label ?? widget.label;
            // The accessible name is the contract with the screen reader and
            // with the qualification harness. It comes from the model when the
            // model has one and never becomes empty.
            widget.accessible_name = spec?.accessibleName ?? fallback;
            widget.reactive = true;
            widget.can_focus = true;
            widget.visible = true;
        }
    }

    _drawDetails(rows) {
        this._details.destroy_all_children();
        for (const row of rows) {
            const label = wrapping(new St.Label({
                text: `${row.label}: ${row.value}`,
                style_class: 'bunny-trust-detail',
            }));
            this._details.add_child(label);
        }
    }

    _toggleDetails() {
        const showing = !this._details.visible;
        this._details.visible = showing;
        this._disclosure.text = showing ? 'Hide details' : 'Details';
    }

    /**
     * Focus the safe answer.
     *
     * The buttons were focusable and nothing focused them, so the entry kept the
     * focus it took when the panel opened: a keyboard user had to guess that a
     * question had appeared and then Tab to find it, and a screen reader
     * announced nothing at all because nothing had changed focus. For an
     * ordinary control that is an inconvenience. For the surface that decides
     * whether an application may read someone's files, it is the difference
     * between being asked and being bypassed.
     */
    _focusSafeAnswer(model) {
        const target = model.initialFocus === 'allow' ? this._allow : this._deny;
        target.grab_key_focus();
    }

    // ------------------------------------------------------------- answering

    _decide(verdict) {
        if (!this._requestId)
            return;
        // Both controls go inert on the first press. Two answers to one
        // question is a race whose loser is whichever the runtime rejects, and
        // a person who pressed Deny and saw Allow win would be right to stop
        // trusting the dialog.
        this._allow.reactive = false;
        this._allow.can_focus = false;
        this._deny.reactive = false;
        this._deny.can_focus = false;
        this._onDecision?.(verdict, this._requestId);
    }

    /** Re-arm after a decision the runtime could not record. */
    decisionFailed(requestId) {
        if (requestId !== this._requestId)
            return;
        for (const widget of [this._allow, this._deny]) {
            widget.reactive = true;
            widget.can_focus = true;
        }
    }

    get requestId() {
        return this._requestId;
    }

    hide(requestId = '') {
        if (requestId && requestId !== this._requestId)
            return;
        this.actor.visible = false;
        this._model = null;
        this._requestId = '';
    }
}
