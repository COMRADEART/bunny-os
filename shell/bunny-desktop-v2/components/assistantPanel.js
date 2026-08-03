import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';

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
    constructor(state) {
        this._state = state;
        this.actor = new St.BoxLayout({vertical: true, spacing: TOKENS.spacing.md});
    }

    enable() {
        this._stateSignal = this._state.connect('changed', () => this._rebuild());
        this._rebuild();
    }

    _rebuild() {
        this.actor.destroy_all_children();
        const state = this._state.snapshot;
        this.actor.add_child(new St.Label({text: `Assistant · ${state.assistantState}`, style_class: 'bunny-v2-title'}));
        this.actor.add_child(new St.Label({text: `Provider: ${state.providerState}`, style_class: 'bunny-v2-muted'}));
        this.actor.add_child(section('Recent activity', state.recentActions, 'No recent Bunny actions observed.'));
        this.actor.add_child(section('System context', state.systemContext, 'No additional system context observed.'));
        this.actor.add_child(section('Suggested actions', state.suggestions, 'No suggestions available.'));
        this.actor.add_child(section('Privacy summary', [{label: state.privacyState, detail: `${state.privacyUses.length} active device uses`}], 'Privacy state unavailable.'));
        const input = new St.Entry({
            hint_text: 'Ask Bunny…',
            can_focus: true,
            style_class: 'bunny-v2-control bunny-v2-focus',
            accessible_name: 'Ask Bunny',
        });
        this.actor.add_child(input);
    }

    applyPresentation(_presentation) {}

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this.actor.destroy();
    }
}
