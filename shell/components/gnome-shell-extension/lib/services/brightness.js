// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// BrightnessManager: the panel backlight, through gnome-settings-daemon.
//
// Writing /sys/class/backlight/*/brightness directly needs root, and the reason
// it needs root is that the kernel has no way to tell one unprivileged process
// from another. gnome-settings-daemon holds that privilege for the session and
// exposes it on the session bus with a percentage; going through it is not a
// detour around a simpler mechanism, it is the mechanism.
//
// A desktop machine with an external monitor has no backlight at all, and the
// daemon reports -1 for that. `available()` is false there, and the top bar
// omits the control rather than showing one that does nothing — which is the
// same rule the battery widget follows.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {clamp, logOnce, logError_} from '../util.js';

const BUS = 'org.gnome.SettingsDaemon.Power';
const PATH = '/org/gnome/SettingsDaemon/Power';
const IFACE = 'org.gnome.SettingsDaemon.Power.Screen';

export class BrightnessManager {
    constructor() {
        this._proxy = null;
        try {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                BUS, PATH, IFACE, null);
        } catch (error) {
            logOnce('brightness-absent',
                `gnome-settings-daemon Screen is unavailable (${error.message}); ` +
                'the brightness control is hidden');
        }
    }

    available() {
        return this.percentage() !== null;
    }

    /** 0..100, or null when this machine has no controllable backlight. */
    percentage() {
        if (this._proxy === null)
            return null;
        try {
            const value = this._proxy.get_cached_property('Brightness')?.unpack();
            // -1 is the daemon's documented "no backlight on this system".
            if (typeof value !== 'number' || value < 0)
                return null;
            return clamp(value, 0, 100);
        } catch (_error) {
            return null;
        }
    }

    /**
     * Set the backlight to a percentage.
     *
     * Written through org.freedesktop.DBus.Properties.Set rather than through
     * the proxy's cached property: the cache is a local copy, and setting it
     * changes what this process believes without changing the screen. The
     * daemon signals the real value back and the proxy updates itself, so the
     * slider follows the hardware rather than leading it.
     */
    setPercentage(value) {
        if (this._proxy === null)
            return;
        try {
            Gio.DBus.session.call(
                BUS, PATH, 'org.freedesktop.DBus.Properties', 'Set',
                new GLib.Variant('(ssv)', [
                    IFACE, 'Brightness',
                    GLib.Variant.new_int32(Math.round(clamp(value, 0, 100))),
                ]),
                null, Gio.DBusCallFlags.NONE, -1, null,
                (connection, result) => {
                    try {
                        connection.call_finish(result);
                    } catch (error) {
                        logError_('brightness change refused', error);
                    }
                });
        } catch (error) {
            logError_('brightness call failed', error);
        }
    }

    destroy() {
        this._proxy = null;
    }
}
