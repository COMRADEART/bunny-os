// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// PowerManager: what the battery is doing, and the four things a user may ask
// the session to do about power.
//
// Battery state is read from /sys/class/power_supply rather than UPower. Both
// are correct; sysfs is chosen because it is the source UPower itself reads, it
// needs no bus round trip on a 2-second timer, and it distinguishes "this
// machine has no battery" from "UPower is not running" — which UPower cannot,
// and which the brief specifically asks the widget to get right. A desktop with
// no battery must say AC Power, not 0%.
//
// The actions go the other way. Shutdown, restart, suspend and log out are
// session decisions with policy attached — inhibitors, other logged-in users,
// unsaved work — and reimplementing that policy against logind directly would
// mean reimplementing the warnings too. They are handed to
// org.gnome.SessionManager, which is the component that owns those questions
// and already asks them; the user sees GNOME's confirmation dialogue, which is
// the correct dialogue.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {listDirectory, readText, readInt, logOnce, logError_} from '../util.js';

const SUPPLY_ROOT = '/sys/class/power_supply';

const SESSION_MANAGER = {
    name: 'org.gnome.SessionManager',
    path: '/org/gnome/SessionManager',
    iface: 'org.gnome.SessionManager',
};

export class PowerManager {
    /**
     * @returns {{present: boolean, percentage: number|null, state: string,
     *            onAcPower: boolean|null}}
     *   `present: false` means the machine has no battery, which is a fact, not
     *   a failure. `percentage: null` with `present: true` means there is a
     *   battery whose charge could not be read, which is.
     */
    battery() {
        const names = listDirectory(SUPPLY_ROOT);
        const batteries = names.filter(name => {
            const type = (readText(`${SUPPLY_ROOT}/${name}/type`) ?? '').trim();
            return type === 'Battery';
        });
        const mains = names.filter(name => {
            const type = (readText(`${SUPPLY_ROOT}/${name}/type`) ?? '').trim();
            return type === 'Mains' || type === 'USB';
        });

        let onAcPower = null;
        for (const name of mains) {
            const online = readInt(`${SUPPLY_ROOT}/${name}/online`);
            if (online !== null)
                onAcPower = onAcPower === true || online === 1;
        }

        if (batteries.length === 0) {
            logOnce('battery-absent', 'no battery in /sys/class/power_supply; reporting AC Power');
            return {present: false, percentage: null, state: 'ac', onAcPower: onAcPower ?? true};
        }

        const name = batteries[0];
        let percentage = readInt(`${SUPPLY_ROOT}/${name}/capacity`);
        if (percentage === null) {
            // Some firmware exposes charge but not capacity. Deriving it is
            // reading the same battery a different way, not inventing a number.
            const now = readInt(`${SUPPLY_ROOT}/${name}/charge_now`) ??
                readInt(`${SUPPLY_ROOT}/${name}/energy_now`);
            const full = readInt(`${SUPPLY_ROOT}/${name}/charge_full`) ??
                readInt(`${SUPPLY_ROOT}/${name}/energy_full`);
            if (now !== null && full)
                percentage = Math.round((now / full) * 100);
        }
        const status = (readText(`${SUPPLY_ROOT}/${name}/status`) ?? '').trim().toLowerCase();
        const state = ['charging', 'discharging', 'full', 'not charging'].includes(status)
            ? status.replace(' ', '-')
            : 'unknown';
        return {
            present: true,
            percentage: percentage === null ? null : Math.min(100, Math.max(0, percentage)),
            state,
            onAcPower: onAcPower ?? (state === 'charging' || state === 'full'),
        };
    }

    /**
     * Log out. The `0` is GNOME's "ask me first" mode: the confirmation
     * dialogue, the inhibitor check and the list of applications with unsaved
     * work all belong to the session manager, and asking for mode 1 or 2 here
     * would skip them.
     */
    logOut() {
        this._session('Logout', new GLib.Variant('(u)', [0]));
    }

    restart() {
        this._session('Reboot', null);
    }

    shutdown() {
        this._session('Shutdown', null);
    }

    suspend() {
        // Suspend is logind's, not the session manager's: GNOME's session
        // manager has no Suspend method, and the inhibitor logic that matters
        // for shutdown does not apply to a resumable state. `true` is
        // interactive, so a polkit prompt appears rather than a silent refusal.
        try {
            Gio.DBus.system.call(
                'org.freedesktop.login1', '/org/freedesktop/login1',
                'org.freedesktop.login1.Manager', 'Suspend',
                new GLib.Variant('(b)', [true]),
                null, Gio.DBusCallFlags.NONE, -1, null,
                (connection, result) => this._finish(connection, result, 'Suspend'));
        } catch (error) {
            logError_('suspend refused', error);
        }
    }

    _session(method, argument) {
        try {
            Gio.DBus.session.call(
                SESSION_MANAGER.name, SESSION_MANAGER.path, SESSION_MANAGER.iface,
                method, argument, null, Gio.DBusCallFlags.NONE, -1, null,
                (connection, result) => this._finish(connection, result, method));
        } catch (error) {
            logError_(`session manager call ${method} failed`, error);
        }
    }

    _finish(connection, result, method) {
        try {
            connection.call_finish(result);
        } catch (error) {
            logError_(`${method} was refused`, error);
        }
    }
}
