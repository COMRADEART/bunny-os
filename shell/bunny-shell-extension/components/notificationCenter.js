import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const GROUPS = ['communication', 'system', 'Bunny activity'];
const STATES = new Set(['proposal', 'waiting for approval', 'running', 'completed', 'failed', 'rolled back']);

export class NotificationCenter {
    constructor(state) {
        this._state = state;
    }

    enable() {
        this._button = new PanelMenu.Button(0, 'Bunny notification center', false);
        this._button.add_child(new St.Icon({icon_name: 'notifications-symbolic', icon_size: 16}));
        Main.panel.addToStatusArea('bunny-v1-notifications', this._button, 1, 'right');
        this._stateSignal = this._state.connect('changed', () => this._refresh());
        this._refresh();
    }

    _refresh() {
        this._button.menu.removeAll();
        const notifications = this._state.snapshot.notifications.filter(item => this._visibleInMode(item));
        for (const group of GROUPS) {
            const title = new PopupMenu.PopupMenuItem(group, {reactive: false});
            title.label.add_style_class_name('bunny-v1-muted');
            this._button.menu.addMenuItem(title);
            const items = notifications.filter(item => (item.category ?? 'Bunny activity') === group);
            if (!items.length) {
                this._button.menu.addMenuItem(new PopupMenu.PopupMenuItem('No observed notifications', {reactive: false}));
                continue;
            }
            for (const item of items.slice(0, 5)) {
                const state = STATES.has(String(item.state)) ? item.state : 'state unavailable';
                const label = `${item.title ?? 'Untitled'} · ${state}`;
                this._button.menu.addMenuItem(new PopupMenu.PopupMenuItem(label, {reactive: false}));
            }
        }
    }

    _visibleInMode(item) {
        if (this._mode !== 'focus')
            return true;
        const severity = String(item.severity ?? '').toLocaleLowerCase();
        const state = String(item.state ?? '').toLocaleLowerCase();
        const kind = String(item.kind ?? '').toLocaleLowerCase();
        return ['critical', 'security', 'battery-critical'].includes(severity)
            || ['waiting for approval', 'failed'].includes(state)
            || ['approval', 'accessibility', 'system-error'].includes(kind);
    }

    applyPresentation(presentation) {
        this._mode = presentation.mode;
        this._refresh();
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this._button?.destroy();
        this._button = null;
    }
}
