import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {launchFixedAction} from '../services/fixedActions.js';

const SETTINGS_RESULTS = [
    ['Appearance', 'control-center', 'opens'],
    ['Layout mode', 'control-center', 'changes a setting'],
    ['Privacy', 'privacy', 'opens'],
    ['Accessibility', 'accessibility', 'opens'],
    ['Diagnostics', 'diagnostics', 'opens'],
    ['Approval Center', 'approvals', 'requires approval'],
];

export class CommandPalette {
    constructor(state, settings) {
        this._state = state;
        this._settings = settings;
        this._selectedIndex = 0;
    }

    enable() {
        this._dialog = new ModalDialog.ModalDialog({styleClass: 'bunny-v1-palette'});
        const panel = new St.BoxLayout({vertical: true, style_class: 'bunny-v1-panel', spacing: 12, width: 680});
        this._panel = panel;
        const heading = new St.BoxLayout({spacing: 8});
        heading.add_child(new St.Label({text: 'Bunny Command Palette', style_class: 'title-1'}));
        heading.add_child(new St.Label({text: 'Super + Space', style_class: 'bunny-v1-badge'}));
        panel.add_child(heading);
        this._entry = new St.Entry({
            hint_text: 'Open, switch, or change…',
            style_class: 'bunny-v1-entry',
            can_focus: true,
            accessible_name: 'Search Bunny commands, applications, windows, workspaces, and settings',
        });
        this._entry.clutter_text.connect('text-changed', () => this._refresh());
        this._entry.clutter_text.connect('key-press-event', (_actor, event) => this._onKeyPress(event));
        panel.add_child(this._entry);
        this._results = new St.BoxLayout({vertical: true, spacing: 4});
        panel.add_child(this._results);
        panel.add_child(new St.Label({
            text: 'Privileged and approval-bound results open Approval Center; they do not execute here.',
            style_class: 'bunny-v1-muted',
        }));
        this._dialog.contentLayout.add_child(panel);
        Main.wm.addKeybinding(
            'open-command-palette', this._settings, Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this.open(),
        );
    }

    applyPresentation(presentation) {
        this._panel.width = presentation.mode === 'compact' ? 600 : 680;
        for (const [name, enabled] of [
            ['bunny-v1-compact', presentation.mode === 'compact'], ['bunny-v1-light', presentation.theme === 'light'],
            ['bunny-v1-high-contrast', presentation.highContrast], ['bunny-v1-reduced-motion', presentation.reducedMotion],
        ])
            enabled ? this._panel.add_style_class_name(name) : this._panel.remove_style_class_name(name);
    }

    open() {
        this._entry.set_text('');
        this._refresh();
        this._dialog.open(global.get_current_time());
        global.stage.set_key_focus(this._entry.clutter_text);
    }

    _collect(query) {
        const needle = query.toLocaleLowerCase();
        const matches = text => !needle || text.toLocaleLowerCase().includes(needle);
        const groups = [];
        const windows = global.get_window_actors()
            .map(actor => actor.meta_window)
            .filter(window => !window.skip_taskbar && matches(window.get_title()))
            .slice(0, 4)
            .map(window => ({label: window.get_title(), detail: window.get_wm_class() ?? 'Open window', verb: 'switches', activate: () => Main.activateWindow(window)}));
        groups.push(['WINDOWS', windows]);

        const apps = Shell.AppSystem.get_default().get_installed()
            .filter(app => app.should_show() && matches(`${app.get_name()} ${app.get_description() ?? ''}`))
            .sort((a, b) => a.get_name().localeCompare(b.get_name()))
            .slice(0, 5)
            .map(app => ({label: app.get_name(), detail: app.get_description() ?? 'Application', verb: 'opens', activate: () => app.activate()}));
        groups.push(['APPLICATIONS', apps]);

        const workspaces = [];
        for (let i = 0; i < global.workspace_manager.n_workspaces; i++) {
            const workspace = global.workspace_manager.get_workspace_by_index(i);
            const label = `Workspace ${i + 1}`;
            if (matches(label))
                workspaces.push({label, detail: `${workspace.list_windows().length} open windows`, verb: 'switches', activate: () => workspace.activate(global.get_current_time())});
        }
        groups.push(['WORKSPACES', workspaces]);

        const settings = SETTINGS_RESULTS
            .filter(([label]) => matches(label))
            .map(([label, action, verb]) => ({label, detail: 'Bunny and system settings', verb, activate: () => launchFixedAction(action)}));
        groups.push(['SETTINGS & SYSTEM', settings]);

        const recent = this._state.snapshot.recentFiles
            .filter(item => matches(String(item.name ?? item.path ?? '')))
            .slice(0, 3)
            .map(item => ({
                label: String(item.name ?? 'Recent file'),
                detail: String(item.path ?? 'Path unavailable'),
                verb: 'opens',
                activate: () => {
                    if (typeof item.path === 'string' && GLib.path_is_absolute(item.path))
                        Gio.AppInfo.launch_default_for_uri(GLib.filename_to_uri(item.path, null), null);
                },
            }));
        groups.push(['RECENT', recent]);
        if (matches('Power options')) {
            groups.push(['POWER', [{
                label: 'Power options', detail: 'GNOME confirmation menu', verb: 'opens confirmation',
                activate: () => Main.panel.statusArea.quickSettings?.menu.open(),
            }]]);
        }
        return groups;
    }

    _refresh() {
        this._results.destroy_all_children();
        this._resultButtons = [];
        for (const [group, results] of this._collect(this._entry.get_text())) {
            if (!results.length)
                continue;
            this._results.add_child(new St.Label({text: group, style_class: 'bunny-v1-muted'}));
            for (const result of results) {
                const row = new St.BoxLayout({spacing: 8});
                const text = new St.BoxLayout({vertical: true, x_expand: true});
                text.add_child(new St.Label({text: result.label, x_align: Clutter.ActorAlign.START}));
                text.add_child(new St.Label({text: result.detail, style_class: 'bunny-v1-muted', x_align: Clutter.ActorAlign.START}));
                row.add_child(text);
                row.add_child(new St.Label({text: result.verb, style_class: 'bunny-v1-badge'}));
                const button = new St.Button({
                    child: row, style_class: 'bunny-v1-result', can_focus: true,
                    accessible_name: `${result.label}; ${result.verb}; ${result.detail}`,
                });
                button.connect('clicked', () => {
                    this._dialog.close(global.get_current_time());
                    result.activate();
                });
                this._results.add_child(button);
                this._resultButtons.push(button);
            }
        }
        if (!this._resultButtons.length)
            this._results.add_child(new St.Label({text: 'No matching results', style_class: 'bunny-v1-muted'}));
        this._selectedIndex = 0;
    }

    _onKeyPress(event) {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Escape) {
            this._dialog.close(global.get_current_time());
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Down || symbol === Clutter.KEY_Up) {
            if (!this._resultButtons.length)
                return Clutter.EVENT_STOP;
            const direction = symbol === Clutter.KEY_Down ? 1 : -1;
            this._selectedIndex = (this._selectedIndex + direction + this._resultButtons.length) % this._resultButtons.length;
            global.stage.set_key_focus(this._resultButtons[this._selectedIndex]);
            return Clutter.EVENT_STOP;
        }
        if (symbol === Clutter.KEY_Return && this._resultButtons.length) {
            this._resultButtons[this._selectedIndex].emit('clicked');
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    disable() {
        Main.wm.removeKeybinding('open-command-palette');
        this._dialog?.destroy();
        this._dialog = this._entry = this._results = this._panel = null;
        this._resultButtons = [];
    }
}
