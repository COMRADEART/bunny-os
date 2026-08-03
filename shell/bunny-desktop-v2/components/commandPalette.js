import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';

import {TOKENS} from '../generatedTokens.js';
import {commandActions} from '../services/actionRegistry.js';
import {applyPresentationClasses} from './presentation.js';


export class CommandPalette {
    constructor(settings, systemPanel, performance) {
        this._settings = settings;
        this._systemPanel = systemPanel;
        this._performance = performance;
        this._selected = 0;
        this._visibleResults = [];
    }

    enable() {
        this._dialog = new ModalDialog.ModalDialog({styleClass: 'bunny-v2-palette-dialog'});
        this._panel = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-panel bunny-v2-modal', spacing: TOKENS.spacing.md, width: TOKENS.layout.paletteWidth});
        this._panel.add_child(new St.Label({text: 'Bunny Command Palette', style_class: 'bunny-v2-title'}));
        this._entry = new St.Entry({
            hint_text: 'Open, switch, or change…',
            style_class: 'bunny-v2-control bunny-v2-focus',
            can_focus: true,
            accessible_name: 'Search applications, windows, workspaces, settings, and fixed Bunny actions',
        });
        this._entry.clutter_text.connect('text-changed', () => this._refresh());
        this._entry.clutter_text.connect('key-press-event', (_actor, event) => this._keyPress(event));
        this._panel.add_child(this._entry);
        this._results = new St.BoxLayout({vertical: true, spacing: TOKENS.spacing.xs});
        this._panel.add_child(this._results);
        this._panel.add_child(new St.Label({
            text: 'Privileged and power actions open Approval Center. Search text is never executed.',
            style_class: 'bunny-v2-caption bunny-v2-muted',
        }));
        this._dialog.contentLayout.add_child(this._panel);
        Main.wm.addKeybinding(
            'command-palette-shortcut',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this.open(),
        );
    }

    _collect(query) {
        const needle = query.toLocaleLowerCase();
        const matches = value => !needle || value.toLocaleLowerCase().includes(needle);
        const results = commandActions(this._settings, this._systemPanel).filter(action => matches(action.label));
        const appSystem = Shell.AppSystem.get_default();
        for (const app of appSystem.get_installed().filter(app => matches(app.get_name())).slice(0, 4))
            results.push({label: app.get_name(), type: 'Open', run: () => app.activate()});
        for (const actor of global.get_window_actors()) {
            const window = actor.meta_window;
            if (!window.skip_taskbar && matches(window.get_title()))
                results.push({label: window.get_title(), type: 'Switch', run: () => Main.activateWindow(window)});
        }
        for (let index = 0; index < global.workspace_manager.n_workspaces; index++) {
            const label = `Workspace ${index + 1}`;
            if (matches(label)) {
                const workspace = global.workspace_manager.get_workspace_by_index(index);
                results.push({label, type: 'Switch', run: () => workspace.activate(global.get_current_time())});
            }
        }
        return results.slice(0, 9);
    }

    _refresh() {
        this._results.destroy_all_children();
        this._visibleResults = this._collect(this._entry.get_text());
        this._selected = Math.min(this._selected, Math.max(0, this._visibleResults.length - 1));
        for (const [index, result] of this._visibleResults.entries()) {
            const button = new St.Button({
                style_class: `bunny-v2-palette-result bunny-v2-focus${index === this._selected ? ' selected' : ''}`,
                can_focus: true,
                accessible_name: `${result.label}. ${result.type}`,
            });
            const row = new St.BoxLayout({spacing: TOKENS.spacing.md});
            row.add_child(new St.Label({text: result.label, x_expand: true, x_align: Clutter.ActorAlign.START}));
            row.add_child(new St.Label({text: result.type, style_class: 'bunny-v2-caption bunny-v2-muted'}));
            button.set_child(row);
            button.connect('clicked', () => this._activate(index));
            this._results.add_child(button);
        }
    }

    _keyPress(event) {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Down)
            this._selected = Math.min(this._selected + 1, this._visibleResults.length - 1);
        else if (symbol === Clutter.KEY_Up)
            this._selected = Math.max(this._selected - 1, 0);
        else if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter) {
            this._activate(this._selected);
            return Clutter.EVENT_STOP;
        } else
            return Clutter.EVENT_PROPAGATE;
        this._refresh();
        return Clutter.EVENT_STOP;
    }

    _activate(index) {
        const result = this._visibleResults[index];
        if (!result)
            return;
        if (result.applicationId) {
            Shell.AppSystem.get_default().lookup_app(result.applicationId)?.activate();
        } else if (result.privileged) {
            this._systemPanel.open('approvals');
        } else {
            result.run?.();
        }
        this._dialog.close(global.get_current_time());
    }

    open() {
        const started = this._performance?.begin('command-palette-open');
        this._entry.set_text('');
        this._selected = 0;
        this._refresh();
        this._dialog.open(global.get_current_time());
        global.stage.set_key_focus(this._entry.clutter_text);
        if (started !== undefined)
            this._performance.end('command-palette-open', started);
    }

    applyPresentation(presentation) {
        applyPresentationClasses(this._panel, presentation);
        this._panel.width = presentation.compact ? TOKENS.layout.paletteWidthCompact : TOKENS.layout.paletteWidth;
    }

    disable() {
        Main.wm.removeKeybinding('command-palette-shortcut');
        this._dialog?.close(global.get_current_time());
        this._dialog?.destroy();
        this._dialog = null;
    }
}
