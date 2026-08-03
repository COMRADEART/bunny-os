import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {launchFixedAction} from '../services/fixedActions.js';

export class QuickSettings {
    constructor(state, settings) {
        this._state = state;
        this._settings = settings;
    }

    enable() {
        this._button = new PanelMenu.Button(0, 'Bunny quick settings', false);
        this._button.add_child(new St.Icon({icon_name: 'preferences-system-symbolic', icon_size: 16}));
        Main.panel.addToStatusArea('bunny-v1-quick-settings', this._button, 0, 'right');

        const privacy = new PopupMenu.PopupMenuItem('Privacy use: none reported', {reactive: false});
        privacy.label.add_style_class_name('bunny-v1-privacy');
        this._privacyItem = privacy;
        this._button.menu.addMenuItem(privacy);
        this._button.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        for (const [label, action] of [
            ['Wi-Fi', 'wifi'], ['Bluetooth', 'bluetooth'], ['Audio & microphone', 'sound'],
            ['Display & brightness', 'display'], ['Power mode & night light', 'power'],
            ['Accessibility', 'accessibility'], ['VPN', 'vpn'],
        ]) {
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', () => launchFixedAction(action));
            this._button.menu.addMenuItem(item);
        }
        this._button.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._localOnly = new PopupMenu.PopupSwitchMenuItem('Bunny local-only mode', false);
        this._localOnly.setSensitive(false);
        this._localOnly.label.text = 'Bunny local-only mode · managed by Bunny settings';
        this._button.menu.addMenuItem(this._localOnly);
        this._modeToggles = new Map();
        for (const [label, mode] of [['FocusMode', 'focus'], ['CompactLayout', 'compact']]) {
            const toggle = new PopupMenu.PopupSwitchMenuItem(label, this._settings.get_string('layout-mode') === mode);
            toggle.connect('toggled', (_item, active) => this._settings.set_string('layout-mode', active ? mode : 'normal'));
            this._button.menu.addMenuItem(toggle);
            this._modeToggles.set(mode, toggle);
        }
        this._stateSignal = this._state.connect('changed', () => this._refresh());
        this._refresh();
    }

    _refresh() {
        const uses = this._state.snapshot.privacyUses;
        this._privacyItem.label.text = uses.length
            ? `Privacy active · ${uses.map(use => use.kind ?? 'device').join(', ')}`
            : 'Privacy use: none reported';
    }

    applyPresentation(presentation) {
        for (const [mode, toggle] of this._modeToggles)
            toggle.setToggleState(presentation.mode === mode);
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this._button?.destroy();
        this._button = null;
    }
}
