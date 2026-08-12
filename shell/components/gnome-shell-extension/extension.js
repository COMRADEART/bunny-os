// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The Bunny Shell extension: a panel indicator, and the Bunny desktop.
//
// Both halves are here because they answer to the same session mode and the
// same settings, but they are independent. The indicator is the small, safe
// thing that has always worked: a menu of entry points that needs no services
// and cannot fail in a way that costs the user their session. The desktop is
// the whole interface — top bar, sidebar, dock, dashboard and character.
//
// The desktop is behind a setting and behind a try/catch, and the order matters.
// If constructing it throws — a missing icon theme, a Shell API that moved, a
// service that refuses on unusual hardware — the catch tears down whatever was
// built, restores GNOME's own panel and leaves the indicator running. The user
// gets a normal GNOME session with a Bunny menu and a journal line naming the
// fault, rather than a black screen and no way to reach a terminal. That is the
// difference between a bug and an unbootable desktop, and it is worth the
// clumsiness of a top-level catch.
//
// BUNNY_SHELL_MODE is set by /usr/libexec/bunny-shell-session. Safe Shell sets
// it to "safe" and neither half runs, which is what makes the safe session a
// recovery path rather than the same code with fewer features.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {DesktopShell} from './lib/desktopShell.js';
import {Icons} from './lib/icons.js';

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

        this._settings = this.getSettings();
        this._enableIndicator();
        this._enableDesktop();
    }

    disable() {
        this._disableDesktop();
        this._disableIndicator();
        this._settings = null;
    }

    // ------------------------------------------------------------- desktop

    _enableDesktop() {
        if (!this._settings.get_boolean('desktop-enabled')) {
            console.log('bunny-desktop: disabled by setting; the GNOME desktop is left in place');
            return;
        }
        try {
            // `dir` is how the theme manager finds the shipped stylesheet it
            // has to unload — and reload if it is ever torn down.
            this._desktop = new DesktopShell({settings: this._settings, dir: this.dir});
            console.log('bunny-desktop: the Bunny desktop is up');
        } catch (error) {
            this._desktop = null;
            console.error(`bunny-desktop: failed to start (${error.message})\n${error.stack}`);
            // Whatever was half-built has to go, and the panel has to come back,
            // or the user is left with fragments over a hidden GNOME top bar.
            this._recoverToGnomeDesktop();
        }
    }

    _disableDesktop() {
        if (!this._desktop)
            return;
        try {
            this._desktop.destroy();
        } catch (error) {
            console.error(`bunny-desktop: teardown failed (${error.message})`);
            this._recoverToGnomeDesktop();
        }
        this._desktop = null;
    }

    /**
     * Put the session back the way GNOME expects it.
     *
     * Called only on a failure path. Every step is individually guarded because
     * this runs when something has already gone wrong and a second exception
     * here would leave the session in the state this method exists to escape.
     */
    _recoverToGnomeDesktop() {
        try {
            Main.layoutManager.panelBox.show();
        } catch (error) {
            console.error(`bunny-desktop: could not restore the GNOME panel: ${error.message}`);
        }
        for (const key of ['focus-desktop-search', 'focus-desktop-sidebar', 'focus-desktop-assistant']) {
            try {
                Main.wm.removeKeybinding(key);
            } catch (_error) {
                // Never registered, or already gone.
            }
        }
    }

    // ----------------------------------------------------------- indicator

    _enableIndicator() {
        this._indicator = new PanelMenu.Button(0.0, 'Bunny Shell', false);
        this._indicator.add_child(new St.Icon({
            icon_name: Icons.BUNNY,
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

    _disableIndicator() {
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
