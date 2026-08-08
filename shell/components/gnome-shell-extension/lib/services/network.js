// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// NetworkManagerService: throughput from the kernel, connection identity from
// NetworkManager.
//
// Two questions with two right answers. "How fast is traffic moving" is
// counters, and /proc/net/dev has them for nothing; going to NM for a rate
// would mean polling a bus to read numbers the kernel will hand over directly.
// "What am I connected to" is state NM owns — the SSID, whether the link is
// metered, whether a portal is in the way — and deriving that from sysfs would
// mean reimplementing NM badly.
//
// Loopback and virtual interfaces are excluded from the rate. Including `lo`
// makes a machine talking to itself look like a machine downloading, and on
// this image the companion, the broker and the portal all talk over local
// sockets; the graph would never be at rest.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {readText, logOnce, logError_} from '../util.js';

const EXCLUDED = /^(lo|docker|veth|br-|virbr|podman|cni|tun|tap|wg)/;

export class NetworkManagerService {
    constructor() {
        this._previous = null;
        this._proxy = null;
        this._connect();
    }

    /**
     * @returns {{upBytesPerSecond: number, downBytesPerSecond: number}|null}
     *   null on the first sample, because a rate needs two.
     */
    rates() {
        const text = readText('/proc/net/dev');
        if (text === null) {
            logOnce('proc-net-dev', '/proc/net/dev is unreadable; network rates report Unavailable');
            return null;
        }
        let received = 0;
        let transmitted = 0;
        for (const line of text.split('\n').slice(2)) {
            const [name, rest] = line.split(':');
            if (rest === undefined)
                continue;
            const iface = name.trim();
            if (EXCLUDED.test(iface))
                continue;
            const fields = rest.trim().split(/\s+/).map(Number);
            if (fields.length < 9)
                continue;
            received += fields[0];
            transmitted += fields[8];
        }
        // Monotonic, not wall clock. A rate divided by an interval that a clock
        // step or a DST change moved is a spike in the graph that never
        // happened on the wire.
        const now = GLib.get_monotonic_time() / 1e6;
        const sample = {received, transmitted, at: now};
        const previous = this._previous;
        this._previous = sample;
        if (previous === null)
            return null;
        const elapsed = sample.at - previous.at;
        if (elapsed <= 0)
            return null;
        // A counter that went backwards means an interface was removed or the
        // 32-bit counter wrapped. Reporting a negative rate, or an enormous
        // positive one, is worse than skipping the sample.
        const down = (sample.received - previous.received) / elapsed;
        const up = (sample.transmitted - previous.transmitted) / elapsed;
        if (down < 0 || up < 0)
            return null;
        return {upBytesPerSecond: up, downBytesPerSecond: down};
    }

    /**
     * @returns {{state: string, kind: string, name: string|null}}
     *   `state` is one of connected, limited, disconnected, unknown.
     */
    connection() {
        if (this._proxy === null)
            return this._fromNetworkMonitor();
        try {
            const connectivity = this._proxy.get_cached_property('Connectivity')?.unpack();
            if (typeof connectivity !== 'number') {
                // NM is on the bus but has not published the property yet. That
                // is "not known", and it is answered by the thing that can
                // answer it rather than by defaulting the enum to zero.
                return this._fromNetworkMonitor();
            }
            const primaryType = this._proxy.get_cached_property('PrimaryConnectionType')?.unpack() ?? '';
            const state = {4: 'connected', 3: 'limited', 2: 'limited', 1: 'disconnected'}[connectivity] ?? 'unknown';
            const kind = primaryType.startsWith('802-11') ? 'wifi'
                : primaryType.startsWith('802-3') ? 'wired'
                    : primaryType ? 'other' : 'none';
            return {state, kind, name: primaryType || null};
        } catch (error) {
            logError_('NetworkManager properties unreadable', error);
            return this._fromNetworkMonitor();
        }
    }

    /** Open the place a user changes this. GNOME owns the Wi-Fi list; we do not. */
    openSettings() {
        try {
            Gio.AppInfo.create_from_commandline(
                'gnome-control-center wifi', null,
                Gio.AppInfoCreateFlags.NONE).launch([], null);
        } catch (error) {
            logError_('could not open network settings', error);
        }
    }

    destroy() {
        this._proxy = null;
    }

    _connect() {
        try {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, null,
                'org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager',
                'org.freedesktop.NetworkManager', null);
        } catch (error) {
            this._proxy = null;
            logOnce('nm-absent',
                `NetworkManager is not on the system bus (${error.message}); ` +
                'connection state falls back to Gio.NetworkMonitor');
        }
    }

    /**
     * The fallback. It knows whether there is a route to the internet and
     * nothing about what carries it, so `kind` is honestly 'unknown' rather
     * than guessed from an interface name.
     */
    _fromNetworkMonitor() {
        try {
            const monitor = Gio.NetworkMonitor.get_default();
            const available = monitor.get_network_available();
            const full = monitor.get_connectivity() === Gio.NetworkConnectivity.FULL;
            return {
                state: !available ? 'disconnected' : full ? 'connected' : 'limited',
                kind: 'unknown',
                name: null,
            };
        } catch (_error) {
            return {state: 'unknown', kind: 'unknown', name: null};
        }
    }
}
