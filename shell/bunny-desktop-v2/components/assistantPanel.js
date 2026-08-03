import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';
import {CharacterIllustration} from './characterIllustration.js';


function section(title, items, emptyText) {
    const card = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-card', spacing: TOKENS.spacing.sm});
    card.add_child(new St.Label({text: title, style_class: 'bunny-v2-heading'}));
    if (!items.length)
        card.add_child(new St.Label({text: emptyText, style_class: 'bunny-v2-muted'}));
    for (const item of items) {
        const label = String(item.label ?? item.title ?? item.text ?? 'Observed item');
        const detail = String(item.detail ?? item.state ?? 'State unavailable');
        card.add_child(new St.Label({text: `${label} · ${detail}`, style_class: 'bunny-v2-body'}));
    }
    return card;
}


export class AssistantPanel {
    constructor(state, extensionPath, openTab) {
        this._state = state;
        this._openTab = openTab;
        this._presentation = null;
        this.actor = new St.BoxLayout({vertical: true, spacing: TOKENS.spacing.md});
        this._character = new CharacterIllustration(state, extensionPath);
        this._composer = new St.Entry({
            hint_text: 'Ask Bunny…',
            can_focus: true,
            style_class: 'bunny-v2-control bunny-v2-focus',
            accessible_name: 'Ask Bunny',
        });
    }

    enable() {
        this._character.enable();
        this._stateSignal = this._state.connect('changed', () => this._rebuild());
        this._rebuild();
    }

    _clearLayout() {
        for (const child of this.actor.get_children())
            this.actor.remove_child(child);
    }

    _rebuild() {
        this._clearLayout();
        const state = this._state.snapshot;
        this.actor.add_child(new St.Label({text: `Assistant · ${state.assistantState}`, style_class: 'bunny-v2-title'}));
        this.actor.add_child(new St.Label({text: `Provider: ${state.providerState}`, style_class: 'bunny-v2-muted'}));

        if (this._presentation?.visualMode === 'character') {
            const message = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-card', spacing: TOKENS.spacing.sm});
            message.add_child(new St.Label({text: 'Bunny guidance', style_class: 'bunny-v2-heading'}));
            message.add_child(new St.Label({
                text: state.assistantState === 'Waiting for approval'
                    ? 'An action needs your explicit decision. Review the operation and consequences before continuing.'
                    : 'I can help with tasks, explain features, and keep observed system state understandable.',
                style_class: 'bunny-v2-body',
            }));
            this.actor.add_child(message);
            if (state.approvals.length) {
                const approval = new St.Button({
                    label: `${state.approvals.length} approval request${state.approvals.length === 1 ? '' : 's'} · Open controls`,
                    can_focus: true,
                    style_class: 'bunny-v2-card bunny-v2-focus',
                    accessible_name: 'Open the real Approval Center controls',
                });
                approval.connect('clicked', () => this._openTab('approvals'));
                this.actor.add_child(approval);
            }
            if (this._character.active)
                this.actor.add_child(this._character.actor);
            else
                this.actor.add_child(section('Recent activity', state.recentActions.slice(0, 2), 'No recent actions observed.'));
        } else {
            this.actor.add_child(section('Recent activity', state.recentActions, 'No recent Bunny actions observed.'));
            this.actor.add_child(section('System context', state.systemContext, 'No additional system context observed.'));
            this.actor.add_child(section('Suggested actions', state.suggestions, 'No suggestions available.'));
            this.actor.add_child(section('Privacy summary', [{label: state.privacyState, detail: `${state.privacyUses.length} active device uses`}], 'Privacy state unavailable.'));
        }
        this.actor.add_child(this._composer);
    }

    setAvailableHeight(height) {
        this._character.setAvailableHeight(height);
        this._rebuild();
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        this._character.applyPresentation(presentation);
        this._rebuild();
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        if (this._composer.get_parent())
            this._composer.get_parent().remove_child(this._composer);
        if (this._character.actor.get_parent())
            this._character.actor.get_parent().remove_child(this._character.actor);
        this._character.disable();
        this._composer.destroy();
        this.actor.destroy();
    }
}
