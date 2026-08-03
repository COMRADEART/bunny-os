import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {launchFixedAction} from '../services/fixedActions.js';
import {TOKENS} from '../generatedTokens.js';
import {applyPresentationClasses} from './presentation.js';


export class TopBar {
    constructor(state, extensionPath, settings, systemPanel) {
        this._state = state;
        this._extensionPath = extensionPath;
        this._settings = settings;
        this._systemPanel = systemPanel;
    }

    enable() {
        this._identity = new PanelMenu.Button(0, 'Bunny OS menu', false);
        const box = new St.BoxLayout({style_class: 'bunny-v2-top-button', spacing: TOKENS.spacing.sm});
        box.add_child(new St.Icon({
            gicon: Gio.icon_new_for_string(`${this._extensionPath}/icons/bunny-symbolic.svg`),
            icon_size: TOKENS.layout.iconIdentity,
        }));
        box.add_child(new St.Label({text: 'Bunny OS', y_align: Clutter.ActorAlign.CENTER}));
        this._identity.add_child(box);
        for (const [label, callback] of [
            ['Activities and workspaces', () => Main.overview.toggle()],
            ['Bunny Control Center', () => launchFixedAction('control-center')],
            ['Bunny Welcome', () => launchFixedAction('welcome')],
            ['Diagnostics', () => launchFixedAction('diagnostics')],
        ]) {
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', callback);
            this._identity.menu.addMenuItem(item);
        }
        Main.panel.addToStatusArea('bunny-v2-identity', this._identity, 0, 'left');

        this._panelButton = new PanelMenu.Button(0, 'Open Bunny system panel', false);
        this._panelButton.add_child(new St.Icon({icon_name: 'view-grid-symbolic', icon_size: TOKENS.layout.iconSmall}));
        const openPanel = new PopupMenu.PopupMenuItem('Open Quick Settings');
        openPanel.connect('activate', () => this._systemPanel.open('quick'));
        this._panelButton.menu.addMenuItem(openPanel);
        for (const [label, tab] of [['Assistant', 'assistant'], ['Approval Center', 'approvals'], ['Activity', 'activity']]) {
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', () => this._systemPanel.open(tab));
            this._panelButton.menu.addMenuItem(item);
        }
        Main.panel.addToStatusArea('bunny-v2-panel', this._panelButton, 0, 'right');

        this._privacy = new PanelMenu.Button(0, 'Bunny privacy activity', false);
        this._privacyLabel = new St.Label({text: '', y_align: Clutter.ActorAlign.CENTER});
        this._privacy.add_child(this._privacyLabel);
        Main.panel.addToStatusArea('bunny-v2-privacy', this._privacy, 1, 'right');

        this._focusExit = new PanelMenu.Button(0, 'Exit FocusMode', false);
        this._focusExit.add_child(new St.Label({text: 'Exit Focus', y_align: Clutter.ActorAlign.CENTER}));
        const exit = new PopupMenu.PopupMenuItem('Exit FocusMode');
        exit.connect('activate', () => this._settings.set_string('layout-mode', 'normal'));
        this._focusExit.menu.addMenuItem(exit);
        Main.panel.addToStatusArea('bunny-v2-focus-exit', this._focusExit, 2, 'right');

        this._stateSignal = this._state.connect('changed', () => this._refreshPrivacy());
        this._refreshPrivacy();
    }

    _refreshPrivacy() {
        const uses = this._state.snapshot.privacyUses;
        const kinds = [...new Set(uses.map(use => String(use.kind ?? 'device')))];
        const parts = this._state.snapshot.mockMode ? ['VISUAL MOCK DATA'] : [];
        if (kinds.length)
            parts.push(`Privacy · ${kinds.join(' · ')}`);
        this._privacyLabel.text = parts.join(' · ');
        this._privacy.visible = !this._presentation?.focus && (kinds.length > 0 || this._state.snapshot.mockMode);
        this._privacy.menu.removeAll();
        if (this._state.snapshot.mockMode)
            this._privacy.menu.addMenuItem(new PopupMenu.PopupMenuItem('VISUAL MOCK DATA', {reactive: false}));
        for (const use of uses) {
            const kind = String(use.kind ?? 'Device');
            const application = String(use.application ?? 'Unknown application');
            this._privacy.menu.addMenuItem(new PopupMenu.PopupMenuItem(`${kind}: ${application}`, {reactive: false}));
        }
        const settings = new PopupMenu.PopupMenuItem('Open privacy settings');
        settings.connect('activate', () => launchFixedAction('privacy'));
        this._privacy.menu.addMenuItem(settings);
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        for (const actor of [this._identity, this._panelButton, this._privacy, this._focusExit])
            applyPresentationClasses(actor, presentation);
        this._identity.visible = !presentation.focus;
        this._panelButton.visible = !presentation.focus;
        this._focusExit.visible = presentation.focus;
        this._refreshPrivacy();
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this._identity?.destroy();
        this._panelButton?.destroy();
        this._privacy?.destroy();
        this._focusExit?.destroy();
        this._identity = this._panelButton = this._privacy = this._focusExit = null;
    }
}
