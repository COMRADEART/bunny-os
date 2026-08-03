import Clutter from 'gi://Clutter';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

export class OverviewRail {
    constructor(state) {
        this._state = state;
        this._signals = [];
    }

    enable() {
        this.actor = new St.BoxLayout({
            vertical: true,
            style_class: 'bunny-v1-panel',
            spacing: 12,
            visible: false,
            reactive: true,
        });
        this.actor.add_child(new St.Label({text: 'Bunny overview', style_class: 'title-2'}));
        this._search = new St.Entry({
            hint_text: 'Search applications and windows',
            style_class: 'bunny-v1-entry',
            can_focus: true,
            accessible_name: 'Search applications and open windows',
        });
        this._search.clutter_text.connect('text-changed', () => {
            Main.overview.searchEntry?.set_text(this._search.get_text());
        });
        this.actor.add_child(this._search);
        this._content = new St.BoxLayout({vertical: true, spacing: 8});
        this.actor.add_child(this._content);
        Main.layoutManager.addChrome(this.actor, {affectsStruts: false, trackFullscreen: true});
        this._signals.push([Main.overview, Main.overview.connect('showing', () => {
            this._rebuild();
            this._place();
            this.actor.show();
        })]);
        this._signals.push([Main.overview, Main.overview.connect('hidden', () => this.actor.hide())]);
        this._signals.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => this._place())]);
        this._signals.push([this._state, this._state.connect('changed', () => this._rebuild())]);
    }

    _heading(text) {
        return new St.Label({text, style_class: 'bunny-v1-muted'});
    }

    _rebuild() {
        this._content.destroy_all_children();
        this._content.add_child(this._heading('WORKSPACES'));
        const manager = global.workspace_manager;
        for (let i = 0; i < manager.n_workspaces; i++) {
            const workspace = manager.get_workspace_by_index(i);
            const windows = workspace.list_windows().filter(window => !window.skip_taskbar);
            const button = new St.Button({
                label: `Workspace ${i + 1} · ${windows.length} window${windows.length === 1 ? '' : 's'}`,
                style_class: 'bunny-v1-result', can_focus: true,
                accessible_name: `Switch to workspace ${i + 1}`,
            });
            button.connect('clicked', () => workspace.activate(global.get_current_time()));
            this._content.add_child(button);
        }
        this._content.add_child(this._heading('OPEN WINDOWS'));
        const windows = global.get_window_actors().map(actor => actor.meta_window).filter(window => !window.skip_taskbar);
        for (const window of windows.slice(0, 6)) {
            const button = new St.Button({label: window.get_title(), style_class: 'bunny-v1-result', can_focus: true});
            button.connect('clicked', () => Main.activateWindow(window));
            this._content.add_child(button);
        }
        if (!windows.length)
            this._content.add_child(new St.Label({text: 'No open windows', style_class: 'bunny-v1-muted'}));
        this._content.add_child(this._heading('RECENT TASKS'));
        const tasks = this._state.snapshot.tasks;
        for (const task of tasks.slice(0, 3))
            this._content.add_child(new St.Label({text: String(task.title ?? task.objective ?? 'Untitled task')}));
        if (!tasks.length)
            this._content.add_child(new St.Label({text: 'No Bunny task state observed', style_class: 'bunny-v1-muted'}));
    }

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = Math.min(360, Math.floor(monitor.width * 0.28));
        this.actor.set_position(monitor.x + 24, monitor.y + 64);
        this.actor.set_size(width, Math.min(640, monitor.height - 112));
    }

    disable() {
        for (const [object, signal] of this._signals)
            object.disconnect(signal);
        this._signals = [];
        this.actor?.destroy();
        this.actor = this._content = this._search = null;
    }
}
