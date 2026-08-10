// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// ApplicationLauncher: .desktop entries, resolved and started.
//
// Shell.AppSystem is GNOME Shell's own index of installed applications. It is
// used here instead of Gio.AppInfo for one property Gio does not have: it
// tracks which applications are *running*, and which windows belong to them, so
// the dock's running indicator is the truth rather than a guess maintained by
// the dock. It also means an application launched from the dock and the same
// application launched from the overview are one entry, not two.
//
// The brief's dock and quick-access lists name applications this image does not
// necessarily install — VS Code, OBS, Blender, Discord, Spotify. `resolve`
// returns null for those, and the widgets omit or disable the tile rather than
// showing an icon that does nothing. Which of the two they do is the widget's
// decision and is recorded there.

import Gio from 'gi://Gio';
import Shell from 'gi://Shell';

import {logError_, logOnce} from '../util.js';

/**
 * Candidate desktop IDs per logical application, most preferred first.
 *
 * A logical name maps to several IDs because the same program arrives under
 * different identifiers depending on how it was installed: Flatpak IDs are
 * reverse-DNS, RPM IDs usually are not, and the brief names products by their
 * marketing name. Listing them is honest about the ambiguity; guessing from a
 * substring match would launch the wrong thing.
 */
export const KNOWN_APPLICATIONS = {
    files: ['org.gnome.Nautilus.desktop'],
    terminal: ['org.gnome.Terminal.desktop', 'org.gnome.Console.desktop'],
    browser: ['firefox.desktop', 'org.mozilla.firefox.desktop'],
    editor: ['org.gnome.TextEditor.desktop'],
    software: ['org.gnome.Software.desktop'],
    settings: ['org.gnome.Settings.desktop', 'gnome-control-center.desktop'],
    documents: ['org.gnome.Evince.desktop'],
    images: ['org.gnome.Loupe.desktop'],
    video: ['org.gnome.Totem.desktop'],
    archives: ['org.gnome.FileRoller.desktop'],
    vscode: ['code.desktop', 'com.visualstudio.code.desktop'],
    obs: ['com.obsproject.Studio.desktop', 'obs-studio.desktop'],
    blender: ['org.blender.Blender.desktop', 'blender.desktop'],
    discord: ['com.discordapp.Discord.desktop', 'discord.desktop'],
    spotify: ['com.spotify.Client.desktop', 'spotify.desktop'],
    bunnyAssistant: ['art.comrade.BunnyCompanion.desktop'],
    bunnyLauncher: ['art.comrade.BunnyLauncher.desktop'],
    bunnySettings: ['art.comrade.BunnySettings.desktop'],
    bunnyApprovals: ['art.comrade.BunnyApprovals.desktop'],
};

export class ApplicationLauncher {
    constructor() {
        this._system = Shell.AppSystem.get_default();
        this._cache = new Map();
    }

    /** @returns {Shell.App|null} */
    resolve(logicalName) {
        if (this._cache.has(logicalName))
            return this._cache.get(logicalName);
        const candidates = KNOWN_APPLICATIONS[logicalName] ?? [logicalName];
        let found = null;
        for (const id of candidates) {
            const app = this._system.lookup_app(id);
            if (app !== null) {
                found = app;
                break;
            }
        }
        if (found === null)
            logOnce(`missing-app-${logicalName}`, `${logicalName} is not installed (tried ${candidates.join(', ')})`);
        this._cache.set(logicalName, found);
        return found;
    }

    available(logicalName) {
        return this.resolve(logicalName) !== null;
    }

    /** True when the application has at least one window on this session. */
    running(logicalName) {
        const app = this.resolve(logicalName);
        return app !== null && app.get_n_windows() > 0;
    }

    /**
     * Start it, or raise it if it is already running.
     *
     * `activate` is the right verb for both: Shell.App raises the existing
     * window rather than starting a second copy, which is what a user pressing
     * a dock tile for an open application means.
     */
    launch(logicalName) {
        const app = this.resolve(logicalName);
        if (app === null)
            return false;
        try {
            app.activate();
            return true;
        } catch (error) {
            logError_(`could not start ${logicalName}`, error);
            return false;
        }
    }

    /**
     * Run one of the shell's own commands.
     *
     * These are the /usr/bin/bunny-* programs the existing extension already
     * launches. They are not .desktop applications and deliberately are not:
     * they are session surfaces, and putting them in the applications index
     * would put them in the overview and the software list too.
     */
    spawn(argv) {
        try {
            Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
            return true;
        } catch (error) {
            logError_(`could not run ${argv[0]}`, error);
            return false;
        }
    }

    /** Every installed application, for the launcher grid and search. */
    listAll() {
        return this._system.get_installed()
            .filter(info => info.should_show())
            .map(info => this._system.lookup_app(info.get_id()))
            .filter(app => app !== null);
    }

    /** Applications the session has started, most recently used first. */
    listRunning() {
        return Shell.AppSystem.get_default().get_running();
    }

    /** Drop the resolution cache when the installed set changes. */
    invalidate() {
        this._cache.clear();
    }

    connectInstalledChanged(callback) {
        return this._system.connect('installed-changed', () => {
            this.invalidate();
            callback();
        });
    }

    disconnect(id) {
        if (id)
            this._system.disconnect(id);
    }
}
