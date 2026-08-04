import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

const FIXED_ACTIONS = new Map([
    ['launcher', ['/usr/bin/bunny-launcher']],
    ['command', ['/usr/bin/bunny-command']],
    ['workspaces', ['/usr/bin/bunny-workspace']],
    ['approvals', ['/usr/bin/bunny-approvals']],
    ['tasks', ['/usr/bin/bunny-tasks']],
    ['terminal', ['/usr/bin/bunny-terminal']],
    ['files', ['/usr/bin/nautilus', '--new-window']],
    ['settings', ['/usr/bin/bunny-settings']],
    ['privacy', ['/usr/bin/bunny-privacy']],
    ['notifications', ['/usr/bin/bunny-notifications']],
    ['quick-settings', ['/usr/bin/bunny-quick-settings']],
    ['companion', ['/usr/bin/bunny-companion']],
]);

function launch(name) {
    const argv = FIXED_ACTIONS.get(name);
    if (!argv)
        throw new Error('Unknown Bunny Shell action');
    try {
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
    } catch (error) {
        console.error(`Bunny Shell could not open ${name}: ${error.message}`);
    }
}

export default class BunnyShellExtension extends Extension {
    enable() {
        if (GLib.getenv('BUNNY_SHELL_MODE') !== 'normal')
            return;

        this._indicator = new PanelMenu.Button(0.0, 'Bunny Shell', false);
        this._indicator.add_child(new St.Icon({
            icon_name: 'bunny-shell-symbolic',
            style_class: 'system-status-icon bunny-shell-icon',
        }));
        this._statusItem = new PopupMenu.PopupMenuItem('Bunny OS · status not yet verified', {reactive: false});
        const title = this._statusItem;
        title.add_style_class_name('bunny-shell-status');
        this._indicator.menu.addMenuItem(title);
        this._activityItem = new PopupMenu.PopupMenuItem('Tasks 0 · approvals 0 · local model unavailable', {reactive: false});
        this._systemItem = new PopupMenu.PopupMenuItem('Update unknown · sandbox unknown', {reactive: false});
        this._indicator.menu.addMenuItem(this._activityItem);
        this._indicator.menu.addMenuItem(this._systemItem);
        this._indicator.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        for (const [label, action] of [
            ['Open launcher', 'launcher'],
            ['Quick settings', 'quick-settings'],
            ['Ask Bunny', 'command'],
            ['Open companion', 'companion'],
            ['Workspaces', 'workspaces'],
            ['Approvals', 'approvals'],
            ['Tasks', 'tasks'],
            ['Notifications', 'notifications'],
            ['Privacy dashboard', 'privacy'],
            ['Terminal', 'terminal'],
            ['Files', 'files'],
            ['Settings', 'settings'],
        ]) {
            const item = new PopupMenu.PopupMenuItem(label);
            item.connect('activate', () => launch(action));
            this._indicator.menu.addMenuItem(item);
        }
        Main.panel.addToStatusArea(this.uuid, this._indicator, 0, 'right');
        this._refreshStatus();
        this._statusTimer = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 5, () => {
            this._refreshStatus();
            return GLib.SOURCE_CONTINUE;
        });

        this._settings = this.getSettings();
        for (const [key, action] of [
            ['open-launcher', 'launcher'], ['open-bunny', 'command'], ['open-terminal', 'terminal'],
            ['open-files', 'files'], ['open-approvals', 'approvals'], ['open-tasks', 'tasks'],
            ['open-workspaces', 'workspaces'],
        ]) {
            Main.wm.addKeybinding(
                key,
                this._settings,
                Meta.KeyBindingFlags.NONE,
                Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
                () => launch(action),
            );
        }
    }

    disable() {
        for (const key of ['open-launcher', 'open-bunny', 'open-terminal', 'open-files', 'open-approvals', 'open-tasks', 'open-workspaces'])
            Main.wm.removeKeybinding(key);
        this._indicator?.destroy();
        if (this._statusTimer)
            GLib.source_remove(this._statusTimer);
        this._statusTimer = null;
        this._statusItem = null;
        this._activityItem = null;
        this._systemItem = null;
        this._indicator = null;
        this._settings = null;
    }

    _refreshStatus() {
        const runtime = GLib.getenv('XDG_RUNTIME_DIR');
        if (!runtime || !this._statusItem)
            return;
        try {
            const [ok, bytes] = Gio.File.new_for_path(`${runtime}/bunny-shell/status.json`).load_contents(null);
            if (!ok)
                return;
            const value = JSON.parse(new TextDecoder().decode(bytes));
            const bunny = value.bunny === 'available' ? 'available' : 'unavailable';
            const broker = value.broker === 'available' ? 'available' : 'unavailable';
            const tasks = Number.isInteger(value.taskCount) ? value.taskCount : 0;
            const approvals = Number.isInteger(value.pendingApprovalCount) ? value.pendingApprovalCount : 0;
            this._statusItem.label.text = `Bunny ${bunny} · broker ${broker} · security unknown`;
            this._activityItem.label.text = `Tasks ${tasks} · approvals ${approvals} · local model ${value.localModel ?? 'unknown'}`;
            this._systemItem.label.text = `Update ${value.update ?? 'unknown'} · sandbox ${value.sandbox ?? 'unknown'}`;
        } catch (error) {
            this._statusItem.label.text = 'Bunny OS · status unavailable · security unknown';
            this._activityItem.label.text = 'Tasks unknown · approvals unknown · local model unknown';
            this._systemItem.label.text = 'Update unknown · sandbox unknown';
        }
    }
}
