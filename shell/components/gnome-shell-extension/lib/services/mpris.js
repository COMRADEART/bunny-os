// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// MediaService: whatever is playing, over MPRIS.
//
// MPRIS is the only cross-application answer to "what is playing". Firefox
// exports it, Totem exports it, every Spotify client exports it, and a player
// that does not is a player this widget honestly cannot see — which is stated
// in the card rather than worked around.
//
// Picking *which* player is the interesting part. A session can easily have
// three: a video paused in a browser tab, a music player, and a notification
// sound daemon. The rule here is that a Playing player always wins over a
// Paused one, and among equals the one that started most recently wins, because
// the thing the user last pressed play on is the thing they mean. Ties are
// broken by bus name so the card does not flicker between two idle players on
// consecutive polls.

import Gio from 'gi://Gio';

import {logError_, logOnce} from '../util.js';

const PREFIX = 'org.mpris.MediaPlayer2.';
const OBJECT = '/org/mpris/MediaPlayer2';
const PLAYER_IFACE = 'org.mpris.MediaPlayer2.Player';

export class MediaService {
    constructor() {
        this._proxies = new Map();
        this._order = [];
        this._watchId = 0;
        this._listeners = new Set();
        this._scan();
        this._watch();
    }

    /**
     * @returns {{title, artist, artUrl, status, positionSeconds, lengthSeconds,
     *            canGoNext, canGoPrevious, busName}|null}
     *   null when no MPRIS player is on the bus at all — the card collapses.
     */
    current() {
        const chosen = this._chooseBusName();
        if (chosen === null)
            return null;
        const proxy = this._proxies.get(chosen);
        try {
            const metadata = proxy.get_cached_property('Metadata')?.deepUnpack() ?? {};
            const unpack = key => metadata[key]?.deepUnpack?.() ?? null;
            const artists = unpack('xesam:artist');
            const lengthMicroseconds = unpack('mpris:length');
            const status = proxy.get_cached_property('PlaybackStatus')?.unpack() ?? 'Stopped';
            return {
                busName: chosen,
                title: unpack('xesam:title'),
                artist: Array.isArray(artists) ? artists.filter(Boolean).join(', ') || null : artists,
                artUrl: unpack('mpris:artUrl'),
                status,
                // Position is not a property that changes by signal; it has to
                // be asked for. Doing it here rather than caching means the
                // progress bar is right when it is drawn and costs one bus call
                // per refresh, only while something is playing.
                positionSeconds: this._position(proxy),
                lengthSeconds: typeof lengthMicroseconds === 'number' ? lengthMicroseconds / 1e6 : null,
                canGoNext: proxy.get_cached_property('CanGoNext')?.unpack() ?? false,
                canGoPrevious: proxy.get_cached_property('CanGoPrevious')?.unpack() ?? false,
                canPlay: proxy.get_cached_property('CanPlay')?.unpack() ?? false,
            };
        } catch (error) {
            logError_(`MPRIS metadata unreadable from ${chosen}`, error);
            return null;
        }
    }

    playPause() {
        this._call('PlayPause');
    }

    next() {
        this._call('Next');
    }

    previous() {
        this._call('Previous');
    }

    onChange(callback) {
        this._listeners.add(callback);
        return () => this._listeners.delete(callback);
    }

    destroy() {
        if (this._watchId)
            Gio.bus_unwatch_name(this._watchId);
        this._watchId = 0;
        this._proxies.clear();
        this._order = [];
        this._listeners.clear();
    }

    _call(method) {
        const chosen = this._chooseBusName();
        if (chosen === null)
            return;
        try {
            this._proxies.get(chosen).call(method, null, Gio.DBusCallFlags.NONE, -1, null, null);
        } catch (error) {
            logError_(`MPRIS ${method} refused by ${chosen}`, error);
        }
    }

    _position(proxy) {
        try {
            const value = proxy.get_cached_property('Position')?.unpack();
            return typeof value === 'number' ? value / 1e6 : null;
        } catch (_error) {
            return null;
        }
    }

    _chooseBusName() {
        const names = [...this._proxies.keys()];
        if (names.length === 0)
            return null;
        const rank = name => {
            const status = this._proxies.get(name)?.get_cached_property('PlaybackStatus')?.unpack();
            return status === 'Playing' ? 0 : status === 'Paused' ? 1 : 2;
        };
        names.sort((a, b) => {
            const byStatus = rank(a) - rank(b);
            if (byStatus !== 0)
                return byStatus;
            const byRecency = this._order.indexOf(b) - this._order.indexOf(a);
            return byRecency !== 0 ? byRecency : a.localeCompare(b);
        });
        return names[0];
    }

    _watch() {
        try {
            // One watcher for the whole namespace would be ideal; DBus has no
            // prefix watch, so appearance is caught by watching NameOwnerChanged
            // and filtering. Cheaper than rescanning on a timer, and it is what
            // makes the card appear the instant a player starts.
            this._watchId = Gio.DBus.session.signal_subscribe(
                'org.freedesktop.DBus', 'org.freedesktop.DBus', 'NameOwnerChanged',
                '/org/freedesktop/DBus', null, Gio.DBusSignalFlags.NONE,
                (_connection, _sender, _path, _iface, _signal, parameters) => {
                    const [name, oldOwner, newOwner] = parameters.deepUnpack();
                    if (!name.startsWith(PREFIX))
                        return;
                    if (newOwner && !oldOwner)
                        this._add(name);
                    else if (!newOwner)
                        this._remove(name);
                    this._emit();
                });
        } catch (error) {
            logOnce('mpris-watch', `MPRIS players cannot be watched (${error.message}); the media card will not update live`);
        }
    }

    _scan() {
        try {
            const reply = Gio.DBus.session.call_sync(
                'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'ListNames', null, null, Gio.DBusCallFlags.NONE, -1, null);
            for (const name of reply.deepUnpack()[0]) {
                if (name.startsWith(PREFIX))
                    this._add(name);
            }
        } catch (error) {
            logOnce('mpris-scan', `the session bus could not be listed (${error.message}); the media card stays collapsed`);
        }
    }

    _add(busName) {
        if (this._proxies.has(busName))
            return;
        try {
            const proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                busName, OBJECT, PLAYER_IFACE, null);
            proxy.connect('g-properties-changed', () => this._emit());
            this._proxies.set(busName, proxy);
            this._order.push(busName);
        } catch (error) {
            logError_(`could not attach to ${busName}`, error);
        }
    }

    _remove(busName) {
        this._proxies.delete(busName);
        this._order = this._order.filter(name => name !== busName);
    }

    _emit() {
        for (const listener of this._listeners) {
            try {
                listener();
            } catch (error) {
                logError_('media listener failed', error);
            }
        }
    }
}
