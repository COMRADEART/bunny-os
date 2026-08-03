import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';
import {launchFixedAction} from '../services/fixedActions.js';


export class QuickSettings {
    constructor(state, settings, openTab) {
        this._state = state;
        this._settings = settings;
        this._openTab = openTab;
        this.actor = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-quick-grid', spacing: TOKENS.spacing.md});
    }

    enable() {
        this._stateSignal = this._state.connect('changed', () => this._rebuild());
        this._rebuild();
    }

    _tile(title, state, callback, icon) {
        const button = new St.Button({
            style_class: 'bunny-v2-card bunny-v2-quick-tile bunny-v2-focus',
            can_focus: true,
            accessible_name: `${title}. ${state}`,
        });
        const box = new St.BoxLayout({vertical: true, spacing: TOKENS.spacing.xs});
        box.add_child(new St.Icon({icon_name: icon, icon_size: TOKENS.layout.iconStandard}));
        box.add_child(new St.Label({text: title, style_class: 'bunny-v2-label'}));
        box.add_child(new St.Label({text: state, style_class: 'bunny-v2-caption bunny-v2-muted'}));
        button.set_child(box);
        button.connect('clicked', callback);
        return button;
    }

    _rebuild() {
        this.actor.destroy_all_children();
        const state = this._state.snapshot;
        const characterMode = this._settings.get_string('visual-mode') === 'character';
        const focus = this._settings.get_string('layout-mode') === 'focus';
        const dark = this._settings.get_string('color-scheme') !== 'light';
        const tiles = [
            ['Wi-Fi', state.networkState, () => launchFixedAction('wifi'), 'network-wireless-symbolic'],
            ['Bluetooth', state.bluetoothState, () => launchFixedAction('bluetooth'), 'bluetooth-symbolic'],
            ['Focus', focus ? 'On' : 'Default', () => this._settings.set_string('layout-mode', focus ? 'normal' : 'focus'), 'weather-clear-night-symbolic'],
            ['Privacy', state.privacyState, () => launchFixedAction('privacy'), 'changes-prevent-symbolic'],
            ['Local Only', state.privacyState === 'Local Only' ? 'On' : 'Off', () => this._openTab('activity'), 'network-offline-symbolic'],
            ['Dark Mode', dark ? 'On' : 'Off', () => this._settings.set_string('color-scheme', dark ? 'light' : 'dark'), 'weather-clear-symbolic'],
            ['Character Mode', characterMode ? 'On' : 'Off', () => {
                this._settings.set_string('visual-mode', characterMode ? 'regular' : 'character');
                this._settings.set_boolean('character-enabled', !characterMode);
            }, 'avatar-default-symbolic'],
            ['Assistant', state.assistantState, () => this._openTab('assistant'), 'system-run-symbolic'],
            ['Accessibility', 'Open settings', () => launchFixedAction('accessibility'), 'preferences-desktop-accessibility-symbolic'],
        ];
        for (let index = 0; index < tiles.length; index += this._singleColumn ? 1 : 2) {
            const row = new St.BoxLayout({spacing: TOKENS.spacing.md, x_expand: true});
            for (const tile of tiles.slice(index, index + (this._singleColumn ? 1 : 2))) {
                const child = this._tile(...tile);
                child.x_expand = true;
                row.add_child(child);
            }
            this.actor.add_child(row);
        }

        const output = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-card', spacing: TOKENS.spacing.sm});
        output.add_child(new St.Label({text: `Output · ${state.audioState}`, style_class: 'bunny-v2-heading'}));
        output.add_child(new St.Label({text: 'Volume is controlled by the existing GNOME audio service.', style_class: 'bunny-v2-muted'}));
        this.actor.add_child(output);
        if (state.media) {
            const media = new St.Label({text: `${state.media.title ?? 'Media'} · ${state.media.artist ?? 'Unknown artist'}`, style_class: 'bunny-v2-card'});
            this.actor.add_child(media);
        }
        this.actor.add_child(new St.Label({text: `Updates · ${state.updates}`, style_class: 'bunny-v2-card'}));
    }

    applyPresentation(presentation) {
        this._singleColumn = presentation.compact || presentation.assistantPanelWidth < 360;
        this._rebuild();
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this.actor.destroy();
    }
}
