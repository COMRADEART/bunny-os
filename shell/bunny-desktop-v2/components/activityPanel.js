import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';

export class ActivityPanel {
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
        this.actor.add_child(new St.Label({text: 'Activity and privacy', style_class: 'bunny-v2-title'}));
        this.actor.add_child(new St.Label({text: `Privacy state: ${state.privacyState}`, style_class: 'bunny-v2-card'}));
        for (const use of state.privacyUses)
            this.actor.add_child(new St.Label({text: `${use.kind ?? 'Device'} · ${use.application ?? 'Unknown application'}`, style_class: 'bunny-v2-card'}));
        if (!state.privacyUses.length)
            this.actor.add_child(new St.Label({text: 'No active microphone, camera, screen-sharing, location, or clipboard use reported.', style_class: 'bunny-v2-muted'}));
        for (const notification of state.notifications)
            this.actor.add_child(new St.Label({text: `${notification.title ?? 'Notification'} · ${notification.body ?? ''}`, style_class: 'bunny-v2-card'}));
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this.actor.destroy();
    }
}
