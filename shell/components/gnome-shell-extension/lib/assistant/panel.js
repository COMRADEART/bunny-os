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

    /** Grey the microphone when the companion's speech service cannot be reached. */
    setVoiceAvailable(available, reason = '') {
        this._microphone.reactive = available;
        this._microphone.can_focus = available;
        this._microphone.opacity = available ? 255 : 110;
        this._microphone.accessible_name = available
            ? 'Speak to Bunny'
            : `Speak to Bunny. Unavailable: ${reason}`;
    }

    _submit() {
        const text = this._entry.get_text().trim();
        if (text === '')
            return;
        this._entry.set_text('');
        this._context.onSubmit?.(text);
    }

    _iconButton(iconName, accessibleName, onActivate) {
        const button = box({style_class: 'bunny-assistant-icon-button'});
        button.add_child(themedIcon(iconName, {size: 16}));
        button.y_align = Clutter.ActorAlign.CENTER;
        makeActivatable(button, onActivate, {accessibleName});
        return button;
    }
}
