import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {launchFixedAction} from '../services/fixedActions.js';

export class TopBar {
    constructor(state, extensionPath, settings) {
        this._state = state;
        this._extensionPath = extensionPath;
        this._settings = settings;
    }

    enable() {
        this._launcher = new PanelMenu.Button(0, 'Bunny launcher', false);
        const launcherBox = new St.BoxLayout({style_class: 'bunny-v1-top-button', spacing: 8});
        launcherBox.add_child(new St.Icon({
            gicon: Gio.icon_new_for_string(`${this._extensionPath}/icons/bunny-symbolic.svg`),
            icon_size: 18,
        }));
        launcherBox.add_child(new St.Label({text: 'Bunny', y_align: Clutter.ActorAlign.CENTER}));
        this._launcher.add_child(launcherBox);
        for (const [label, callback] of [
            ['Show workspace overview', () => Main.overview.toggle()],
            ['Open Control Center', () => launchFixedAction('control-center')],
            ['Open Assistant', () => launchFixedAction('assistant')],
            ['Open Approval Center', () => launchFixedAction('approvals')],
        ]) {
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', callback);
            this._launcher.menu.addMenuItem(item);
        }
        Main.panel.addToStatusArea('bunny-v1-launcher', this._launcher, 0, 'left');

        this._workspace = new PanelMenu.Button(0, 'Current workspace', false);
        this._workspaceLabel = new St.Label({text: 'Workspace 1', y_align: Clutter.ActorAlign.CENTER});
        this._workspace.add_child(this._workspaceLabel);
        Main.panel.addToStatusArea('bunny-v1-workspace', this._workspace, 1, 'left');
        this._workspaceManager = global.workspace_manager;
        this._workspaceSignal = this._workspaceManager.connect('active-workspace-changed', () => this._refreshWorkspace());
        this._focusSignal = global.display.connect('notify::focus-window', () => this._refreshWorkspace());
        this._refreshWorkspace();

        this._activity = new PanelMenu.Button(0, 'Bunny background activity and privacy', false);
        this._activityLabel = new St.Label({text: '', y_align: Clutter.ActorAlign.CENTER});
        this._activity.add_child(this._activityLabel);
        Main.panel.addToStatusArea('bunny-v1-activity', this._activity, 2, 'right');
        this._focusExit = new PanelMenu.Button(0, 'Exit FocusMode', false);
        this._focusExit.add_child(new St.Label({text: 'Exit Focus', y_align: Clutter.ActorAlign.CENTER}));
        const exitItem = new PopupMenu.PopupMenuItem('Exit FocusMode');
        exitItem.connect('activate', () => this._settings.set_string('layout-mode', 'normal'));
        this._focusExit.menu.addMenuItem(exitItem);
        this._focusExit.visible = false;
        Main.panel.addToStatusArea('bunny-v1-focus-exit', this._focusExit, 3, 'right');
        this._stateSignal = this._state.connect('changed', () => this._refreshState());
        this._refreshState();
    }

    _refreshWorkspace() {
        const index = this._workspaceManager.get_active_workspace_index() + 1;
        const application = global.display.focus_window?.get_wm_class();
        this._workspaceLabel.text = application ? `Workspace ${index} · ${application}` : `Workspace ${index}`;
        this._workspace.menu.removeAll();
        for (let i = 0; i < this._workspaceManager.n_workspaces; i++) {
            const workspace = this._workspaceManager.get_workspace_by_index(i);
            const item = new PopupMenu.PopupMenuItem(`Workspace ${i + 1}`);
            item.setOrnament(i === index - 1 ? PopupMenu.Ornament.DOT : PopupMenu.Ornament.NONE);
            item.connect('activate', () => workspace.activate(global.get_current_time()));
            this._workspace.menu.addMenuItem(item);
        }
    }

    _refreshState() {
        const state = this._state.snapshot;
        const uses = state.privacyUses.map(use => `${use.kind ?? 'device'}: ${use.application ?? 'unknown app'}`);
        const parts = [];
        if (uses.length)
            parts.push(`Privacy ${uses.length}`);
        if (state.backgroundTaskCount)
            parts.push(`Tasks ${state.backgroundTaskCount}`);
        if (state.mockMode)
            parts.push('VISUAL MOCK DATA');
        this._activityLabel.text = parts.join(' · ');
        this._activity.visible = parts.length > 0;
        this._activity.menu.removeAll();
        if (state.mockMode)
            this._activity.menu.addMenuItem(new PopupMenu.PopupMenuItem('VISUAL MOCK DATA — not observed system state', {reactive: false}));
        if (uses.length) {
            for (const use of uses)
                this._activity.menu.addMenuItem(new PopupMenu.PopupMenuItem(use, {reactive: false}));
        } else {
            this._activity.menu.addMenuItem(new PopupMenu.PopupMenuItem('No active privacy use reported', {reactive: false}));
        }
        this._activity.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        const privacy = new PopupMenu.PopupMenuItem('Open privacy settings');
        privacy.connect('activate', () => launchFixedAction('privacy'));
        this._activity.menu.addMenuItem(privacy);
    }

    applyPresentation(presentation) {
        this._mode = presentation.mode;
        this._launcher.visible = presentation.mode !== 'focus';
        this._focusExit.visible = presentation.mode === 'focus';
        this._refreshWorkspace();
        if (presentation.mode === 'compact')
            this._workspaceLabel.text = `WS ${this._workspaceManager.get_active_workspace_index() + 1}`;
        this._refreshState();
    }

    disable() {
        if (this._workspaceSignal)
            this._workspaceManager.disconnect(this._workspaceSignal);
        if (this._focusSignal)
            global.display.disconnect(this._focusSignal);
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this._launcher?.destroy();
        this._workspace?.destroy();
        this._activity?.destroy();
        this._focusExit?.destroy();
        this._launcher = this._workspace = this._activity = this._focusExit = null;
    }
}
