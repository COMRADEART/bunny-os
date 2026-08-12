// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AssistantPanel: the persistent place to type, as a card.
//
// The brief is explicit that this does not replace the character. It is the
// surface for the things a bubble is bad at — a transcript you can scroll back
// through, a reply long enough to need wrapping, a text field that is always
// there. The character remains the representation; this is the keyboard.
//
// The microphone button starts *the companion's* speech input, not a capture
// stream of its own. companion/speech owns the microphone, the consent
// prompt, the recogniser and the confirmation step, all of which have been
// reviewed. A shell that opened a PipeWire stream to draw a level meter would
// be a second thing recording, on a privacy-reviewed image, with none of that.
// Where the speech service is not reachable the button is disabled and says so,
// which is the honest state.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {Card} from '../cards/base.js';
import {box} from '../widgets.js';
import {enter} from '../animation.js';
import {makeActivatable} from '../util.js';
import {Icons, themedIcon} from '../icons.js';

/** Transcript entries kept in the card. Older ones live in the companion store. */
const MAX_TURNS = 6;

export class AssistantPanel extends Card {
    /**
     * @param {{assistant, onSubmit, onVoice, blur, onOpenFull}} context
     */
    constructor(context) {
        super({
            title: 'Bunny',
            blur: context.blur,
            accessibleName: 'Bunny assistant',
            headerTrailing: Card.headerButton('Open', () => context.onOpenFull()),
        });
        this._context = context;
        this._turns = [];
        this._voiceAvailable = false;
        this._voiceActive = false;
        this._voiceStoppable = false;

        this._scroll = new St.ScrollView({
            style_class: 'bunny-assistant-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            y_expand: true,
        });
        this._transcript = box({vertical: true, style_class: 'bunny-assistant-transcript'});
        this._scroll.set_child(this._transcript);
        this.content.add_child(this._scroll);

        this._status = new St.Label({text: '', style_class: 'bunny-assistant-status'});
        this._status.visible = false;
        this.content.add_child(this._status);

        this._approval = box({vertical: true, style_class: 'bunny-assistant-approval'});
        this._approvalLabel = new St.Label({
            text: '', style_class: 'bunny-assistant-approval-label',
        });
        this._approvalLabel.clutter_text.line_wrap = true;
        this._approvalLabel.clutter_text.set_line_wrap_mode(2);
        this._approval.add_child(this._approvalLabel);
        const approvalActions = box({style_class: 'bunny-assistant-approval-actions'});
        this._approvalDeny = this._textButton('Deny', () => this._decideApproval('deny'));
        this._approvalAllow = this._textButton('Allow', () => this._decideApproval('allow'));
        this._approvalDeny.accessible_name = 'Deny this Bunny action';
        this._approvalAllow.accessible_name = 'Allow this Bunny action';
        approvalActions.add_child(this._approvalDeny);
        approvalActions.add_child(this._approvalAllow);
        this._approval.add_child(approvalActions);
        this._approval.visible = false;
        this._approvalRequestId = '';
        this._approvalDecision = null;
        this.content.add_child(this._approval);

        this._fileResultsScroll = new St.ScrollView({
            style_class: 'bunny-assistant-file-results-scroll',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
        });
        this._fileResults = box({vertical: true, style_class: 'bunny-assistant-file-results'});
        this._fileResultsScroll.set_child(this._fileResults);
        this._fileResultsScroll.visible = false;
        this._fileResultItems = [];
        this.content.add_child(this._fileResultsScroll);

        const inputRow = box({style_class: 'bunny-assistant-input-row'});
        this._entry = new St.Entry({
            style_class: 'bunny-assistant-entry',
            hint_text: 'Ask anything...',
            can_focus: true,
            x_expand: true,
        });
        this._entry.accessible_name = 'Ask Bunny';
        this._entry.clutter_text.connect('activate', () => this._submit());
        // Escape leaves. An input that traps focus is an input a keyboard user
        // has to guess their way out of, and this one is reachable from a
        // global shortcut — so it is reachable by accident, and getting out has
        // to be as cheap as getting in.
        this._entry.clutter_text.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() !== Clutter.KEY_Escape)
                return Clutter.EVENT_PROPAGATE;
            this._entry.set_text('');
            this._context.onDismiss?.();
            return Clutter.EVENT_STOP;
        });
        inputRow.add_child(this._entry);

        this._microphone = this._iconButton(Icons.MICROPHONE, 'Speak to Bunny',
            () => this._context.onVoice?.());
        inputRow.add_child(this._microphone);

        this._send = this._iconButton(Icons.SEND, 'Send', () => this._submit());
        inputRow.add_child(this._send);
        this.content.add_child(inputRow);
    }

    /** Focus the text field. Bound to the sidebar's AI Assistant destination. */
    focusInput() {
        this._entry.grab_key_focus();
    }

    /** Put text in the field and send it, for a suggestion chip. */
    submitText(text) {
        this._entry.set_text(text);
        this._submit();
    }

    /** @param {'user'|'bunny'} who */
    addTurn(who, text, {tone = 'normal'} = {}) {
        const bubble = box({vertical: true, style_class: `bunny-turn bunny-turn-${who}`});
        const label = new St.Label({text, style_class: 'bunny-turn-text'});
        label.clutter_text.line_wrap = true;
        label.clutter_text.set_line_wrap_mode(2);
        bubble.add_child(label);
        if (tone === 'error')
            bubble.add_style_class_name('bunny-turn-error');
        bubble.accessible_name = `${who === 'user' ? 'You' : 'Bunny'}: ${text}`;

        this._transcript.add_child(bubble);
        enter(bubble, {rise: 6});
        this._turns.push(bubble);
        while (this._turns.length > MAX_TURNS)
            this._turns.shift().destroy();

        // Scroll to the newest turn. Done on the adjustment rather than by
        // grabbing focus, which would steal the caret out of the entry field
        // mid-conversation.
        const adjustment = this._scroll.vscroll?.adjustment ?? this._scroll.get_vadjustment?.();
        if (adjustment)
            adjustment.value = adjustment.upper;
    }

    /** A one-line transient status under the transcript: "Thinking…", errors. */
    setStatus(text, {tone = 'normal'} = {}) {
        this._status.visible = text !== '';
        this._status.text = text;
        this._status.remove_style_class_name('bunny-assistant-status-error');
        if (tone === 'error')
            this._status.add_style_class_name('bunny-assistant-status-error');
    }

    /** Disable input while a request is in flight, so two cannot overlap. */
    setBusy(busy) {
        this._entry.reactive = !busy;
        this._entry.can_focus = !busy;
        this._send.reactive = !busy;
        this.actor.remove_style_class_name('bunny-assistant-busy');
        if (busy)
            this.actor.add_style_class_name('bunny-assistant-busy');
    }

    /** Display one exact permission question from the canonical task state. */
    showApproval(approval, onDecision) {
        const requestId = String(approval?.requestId ?? '');
        if (!requestId)
            return;
        this._approvalRequestId = requestId;
        this._approvalDecision = typeof onDecision === 'function' ? onDecision : null;
        this._approvalLabel.text = String(
            approval?.reason ?? 'Allow Bunny to perform this action?');
        this._approvalAllow.reactive = true;
        this._approvalAllow.can_focus = true;
        this._approvalDeny.reactive = true;
        this._approvalDeny.can_focus = true;
        this._approval.visible = true;
        this.actor.add_style_class_name('bunny-assistant-approval-active');

        // Focus moves to the question, and lands on the *safe* answer.
        //
        // The buttons were focusable and nothing focused them, so the entry kept
        // the focus it took when the panel opened. A keyboard user had to guess
        // that a question had appeared and then Tab to find it; a screen reader
        // announced nothing at all, because nothing had changed focus. For an
        // ordinary control that is an inconvenience. For the surface that
        // decides whether an application may read someone's files, it is the
        // difference between being asked and being bypassed.
        //
        // Deny, unless the request says otherwise. The trust layer's oldest rule
        // is that an unanswered question is a denial, and the button under the
        // finger — the one a reflexive Return presses — has to agree with it.
        // `safeDefault` travels with every approval for exactly this reason.
        const safe = String(approval?.safeDefault ?? 'denied');
        const target = safe === 'allowed' ? this._approvalAllow : this._approvalDeny;
        target.grab_key_focus();
    }

    clearApproval(requestId = '') {
        if (requestId && requestId !== this._approvalRequestId)
            return;
        this._approval.visible = false;
        this._approvalRequestId = '';
        this._approvalDecision = null;
        this.actor.remove_style_class_name('bunny-assistant-approval-active');
    }

    approvalDecisionFailed(requestId) {
        if (requestId !== this._approvalRequestId)
            return;
        this._approvalAllow.reactive = true;
        this._approvalAllow.can_focus = true;
        this._approvalDeny.reactive = true;
        this._approvalDeny.can_focus = true;
    }

    /** Grey the microphone when the companion's speech service cannot be reached. */
    setVoiceAvailable(available, reason = '') {
        this._voiceAvailable = available;
        const enabled = available || this._voiceActive || this._voiceStoppable;
        this._microphone.reactive = enabled;
        this._microphone.can_focus = enabled;
        this._microphone.opacity = enabled ? 255 : 110;
        this._microphone.accessible_name = this._voiceStoppable
            ? 'Stop Bunny speaking'
            : enabled ? 'Speak to Bunny' : `Speak to Bunny. Unavailable: ${reason}`;
    }

    /** Make recording and stop semantics unambiguous on the button itself. */
    setVoiceState(active, phase = '') {
        this._voiceActive = active;
        this._voiceStoppable = phase === 'speaking';
        this._microphone.remove_style_class_name('bunny-assistant-microphone-active');
        if (active)
            this._microphone.add_style_class_name('bunny-assistant-microphone-active');
        const enabled = this._voiceAvailable || active || this._voiceStoppable;
        this._microphone.reactive = enabled;
        this._microphone.can_focus = enabled;
        this._microphone.opacity = enabled ? 255 : 110;
        this._microphone.accessible_name = active
            ? 'Stop listening to Bunny'
            : phase === 'speaking' ? 'Stop Bunny speaking' : 'Speak to Bunny';
    }

    /** Numbered, bounded results. Paths are display labels, never launch input. */
    showFileResults(results) {
        this._fileResultItems = Array.isArray(results) ? results.slice(0, 24) : [];
        this._renderFileResults(false);
    }

    _renderFileResults(expanded) {
        this._fileResults.destroy_all_children();
        const safe = expanded ? this._fileResultItems : this._fileResultItems.slice(0, 6);
        this._fileResultsScroll.visible = safe.length > 0;
        safe.forEach((result, index) => {
            const row = box({style_class: 'bunny-assistant-file-result'});
            const text = box({vertical: true, x_expand: true});
            const title = new St.Label({
                text: `${index + 1}. ${result.name ?? 'File'}`,
                style_class: 'bunny-assistant-file-title',
            });
            title.clutter_text.ellipsize = 3;
            const location = new St.Label({
                text: result.display ?? '',
                style_class: 'bunny-assistant-file-location',
            });
            location.clutter_text.ellipsize = 3;
            text.add_child(title);
            text.add_child(location);
            row.add_child(text);
            row.add_child(this._textButton('Open', () =>
                this._context.onFileResult?.(index + 1, 'open')));
            row.add_child(this._textButton('Folder', () =>
                this._context.onFileResult?.(index + 1, 'show_containing_folder')));
            this._fileResults.add_child(row);
        });
        if (!expanded && this._fileResultItems.length > safe.length) {
            this._fileResults.add_child(this._textButton(
                `Show all ${this._fileResultItems.length} results`,
                () => this._renderFileResults(true)));
        }
    }

    _submit() {
        const text = this._entry.get_text().trim();
        if (text === '')
            return;
        this._entry.set_text('');
        this._context.onSubmit?.(text);
    }

    _decideApproval(decision) {
        if (!this._approvalRequestId || !this._approvalDecision)
            return;
        this._approvalAllow.reactive = false;
        this._approvalAllow.can_focus = false;
        this._approvalDeny.reactive = false;
        this._approvalDeny.can_focus = false;
        this._approvalDecision(decision, this._approvalRequestId);
    }

    _iconButton(iconName, accessibleName, onActivate) {
        const button = box({style_class: 'bunny-assistant-icon-button'});
        button.add_child(themedIcon(iconName, {size: 16}));
        button.y_align = Clutter.ActorAlign.CENTER;
        makeActivatable(button, onActivate, {accessibleName});
        return button;
    }

    _textButton(label, onActivate) {
        const button = new St.Label({text: label, style_class: 'bunny-assistant-file-action'});
        makeActivatable(button, onActivate, {accessibleName: `${label} file result`});
        return button;
    }
}
