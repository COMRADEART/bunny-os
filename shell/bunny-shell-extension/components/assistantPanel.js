import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {launchFixedAction} from '../services/fixedActions.js';

const PROVIDER_LABELS = new Map([
    ['local', 'Local model active'], ['cloud', 'Cloud provider active'],
    ['offline', 'Offline'], ['unavailable', 'Provider unavailable'],
    ['disabled', 'Bunny disabled'], ['privacy-restricted', 'Privacy restricted'],
]);

export class AssistantPanel {
    constructor(state, settings) {
        this._state = state;
        this._settings = settings;
    }

    enable() {
        this.actor = new St.BoxLayout({vertical: true, style_class: 'bunny-v1-panel', spacing: 12, visible: false, reactive: true, can_focus: true});
        this.actor.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() === Clutter.KEY_Escape) {
                this.hide();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        const header = new St.BoxLayout({spacing: 8});
        header.add_child(new St.Label({text: 'Bunny Assistant', style_class: 'title-1', x_expand: true}));
        const openApp = new St.Button({label: 'Open full view', can_focus: true, style_class: 'bunny-v1-action'});
        openApp.connect('clicked', () => launchFixedAction('assistant'));
        header.add_child(openApp);
        const close = new St.Button({icon_name: 'window-close-symbolic', can_focus: true, accessible_name: 'Close Assistant panel'});
        close.connect('clicked', () => this.hide());
        header.add_child(close);
        this.actor.add_child(header);
        this._content = new St.BoxLayout({vertical: true, spacing: 8});
        this.actor.add_child(this._content);
        Main.layoutManager.addChrome(this.actor, {affectsStruts: false, trackFullscreen: true});
        Main.wm.addKeybinding('open-assistant', this._settings, Meta.KeyBindingFlags.NONE, Shell.ActionMode.NORMAL, () => this.toggle());
        this._stateSignal = this._state.connect('changed', () => this._refresh());
        this._monitorSignal = Main.layoutManager.connect('monitors-changed', () => this._place());
        this._refresh();
        this._place();
    }

    _section(title, values, empty) {
        this._content.add_child(new St.Label({text: title, style_class: 'bunny-v1-muted'}));
        if (!values.length)
            this._content.add_child(new St.Label({text: empty}));
        for (const value of values.slice(0, 4))
            this._content.add_child(new St.Label({text: value, style_class: 'bunny-v1-card'}));
    }

    _refresh() {
        this._content.destroy_all_children();
        const state = this._state.snapshot;
        if (state.mockMode)
            this._content.add_child(new St.Label({text: 'VISUAL MOCK DATA', style_class: 'bunny-v1-mock'}));
        this._content.add_child(new St.Label({text: PROVIDER_LABELS.get(state.provider) ?? `Provider: ${state.provider}`, style_class: 'bunny-v1-badge'}));
        const focused = global.display.focus_window;
        this._section('SYSTEM CONTEXT', [`Bunny: ${state.bunny}`, `Provider: ${state.provider}`], 'System context unavailable');
        this._section('ACTIVE APPLICATION', focused ? [`${focused.get_wm_class() ?? 'Application'} · ${focused.get_title()}`] : [], 'No focused application observed');
        this._section('CURRENT TASK', state.tasks.map(item => `${item.title ?? 'Untitled'} · ${item.state ?? 'state unavailable'}`), 'No current task observed');
        this._content.add_child(new St.Label({text: 'CONVERSATION', style_class: 'bunny-v1-muted'}));
        if (!state.conversation.length)
            this._content.add_child(new St.Label({text: 'No conversation observed'}));
        for (const item of state.conversation.slice(0, 4)) {
            const role = item.role === 'user' ? 'user' : 'assistant';
            const actionState = String(item.state ?? 'response').replaceAll(' ', '-');
            this._content.add_child(new St.Label({
                text: `${role} · ${item.state ?? 'response'}\n${item.text ?? 'No text'}`,
                style_class: `bunny-v1-card bunny-v1-role-${role} bunny-v1-state-${actionState}`,
            }));
        }
        this._section('PLAN', state.plan.map(item => `${item.title ?? item.step ?? 'Untitled step'} · ${item.state ?? 'state unavailable'}`), 'No plan observed');
        this._section('TOOL ACTIVITY', state.toolActivity.map(item => `${item.name ?? 'Tool'} · ${item.state ?? 'state unavailable'}`), 'No tool activity observed');
        this._section('RECENT FILES', state.recentFiles.map(item => String(item.name ?? item.path ?? 'Unavailable')), 'No recent files shared');
        this._section('RESULT HISTORY', state.results.map(item => `${item.title ?? 'Result'} · ${item.state ?? 'state unavailable'}`), 'No results observed');
        this._section('APPROVAL REQUESTS', state.approvals.map(item => `${item.operation ?? item.action ?? 'Request'} · ${item.severity ?? item.risk ?? 'severity unavailable'}`), 'No approval requests observed');
    }

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = Math.min(430, Math.floor(monitor.width * 0.36));
        this.actor.set_position(monitor.x + monitor.width - width - 18, monitor.y + 48);
        this.actor.set_size(width, monitor.height - 72);
    }

    toggle() {
        this.actor.visible ? this.hide() : this.show();
    }

    show() {
        this._place();
        this.actor.show();
        global.stage.set_key_focus(this.actor);
    }

    hide() {
        this.actor.hide();
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        for (const [name, enabled] of [
            ['bunny-v1-compact', presentation.mode === 'compact'], ['bunny-v1-light', presentation.theme === 'light'],
            ['bunny-v1-high-contrast', presentation.highContrast], ['bunny-v1-reduced-motion', presentation.reducedMotion],
        ])
            enabled ? this.actor.add_style_class_name(name) : this.actor.remove_style_class_name(name);
        this._place();
    }

    disable() {
        Main.wm.removeKeybinding('open-assistant');
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        if (this._monitorSignal)
            Main.layoutManager.disconnect(this._monitorSignal);
        this.actor?.destroy();
        this.actor = this._content = null;
    }
}
