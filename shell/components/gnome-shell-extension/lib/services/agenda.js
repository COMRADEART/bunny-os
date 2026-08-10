// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AgendaService: today's events, from whichever provider can answer.
//
// The brief asks for a provider abstraction and for the UI not to be coupled to
// one calendar service. It also allows demo data. This implements the
// abstraction and declines the demo data, for a reason worth stating: a desktop
// that prints "01:00 PM Project Meeting" on a machine with no calendar has told
// the user something false about their day, and there is no visual convention
// that reliably marks a fake appointment as fake. The empty state says there is
// nothing today and offers to open the calendar, which is true on a new install
// and stops being the state shown the moment a real event exists.
//
// Two providers, tried in order:
//
// **shell-calendar-server** — org.gnome.Shell.CalendarServer, the Evolution
// Data Server bridge GNOME's own calendar popover reads. Every account the user
// has added in Settings appears here, Google and CalDAV included, without this
// code knowing that any of them exist. That is what "not coupled to a
// proprietary service" means in practice.
//
// **local-file** — a JSON array at $XDG_DATA_HOME/bunny/agenda.json, for
// machines with no Evolution and for anything that wants to publish events
// without an account. Documented in docs/BUNNY_SHELL.md.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {logOnce, logError_, readText} from '../util.js';

const CALENDAR_BUS = 'org.gnome.Shell.CalendarServer';
const CALENDAR_PATH = '/org/gnome/Shell/CalendarServer';
const CALENDAR_IFACE = 'org.gnome.Shell.CalendarServer';

/** @typedef {{id: string, summary: string, start: Date, allDay: boolean}} AgendaEvent */

export class AgendaService {
    constructor() {
        this._events = [];
        this._providerName = 'none';
        this._listeners = new Set();
        this._proxy = null;
        this._signalId = 0;
        this._connectCalendarServer();
        this.refresh();
    }

    /** Which provider produced the current list. Shown in the card's tooltip. */
    get providerName() {
        return this._providerName;
    }

    /** @returns {AgendaEvent[]} today's events, earliest first. */
    events() {
        return this._events;
    }

    refresh() {
        if (this._proxy !== null && this._requestToday())
            return;
        this._events = this._readLocalFile();
        this._providerName = this._events.length > 0 ? 'local-file' : 'none';
        this._emit();
    }

    openCalendar() {
        // GNOME Calendar if it is installed, the Settings date panel if it is
        // not. Neither is guaranteed on this image, so the failure is logged
        // rather than thrown at a button press.
        const app = Gio.DesktopAppInfo.new('org.gnome.Calendar.desktop');
        try {
            if (app !== null)
                app.launch([], null);
            else
                Gio.Subprocess.new(['gnome-control-center', 'datetime'], Gio.SubprocessFlags.NONE);
        } catch (error) {
            logError_('could not open a calendar', error);
        }
    }

    onChange(callback) {
        this._listeners.add(callback);
        return () => this._listeners.delete(callback);
    }

    destroy() {
        if (this._proxy !== null && this._signalId)
            this._proxy.disconnect(this._signalId);
        this._signalId = 0;
        this._proxy = null;
        this._listeners.clear();
    }

    _connectCalendarServer() {
        try {
            this._proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION, Gio.DBusProxyFlags.NONE, null,
                CALENDAR_BUS, CALENDAR_PATH, CALENDAR_IFACE, null);
            // The server has no "get events" call. It answers a time range by
            // signalling, which is why this is a subscription and not a query.
            this._signalId = this._proxy.connectSignal('EventsAddedOrUpdated',
                (_proxy, _sender, [rows]) => this._absorb(rows));
        } catch (error) {
            this._proxy = null;
            logOnce('calendar-server',
                `${CALENDAR_BUS} is unavailable (${error.message}); the agenda falls back to ` +
                '$XDG_DATA_HOME/bunny/agenda.json');
        }
    }

    _requestToday() {
        const start = new Date();
        start.setHours(0, 0, 0, 0);
        const end = new Date(start);
        end.setDate(end.getDate() + 1);
        try {
            this._proxy.call(
                'SetTimeRange',
                new GLib.Variant('(xxb)', [
                    Math.floor(start.getTime() / 1000),
                    Math.floor(end.getTime() / 1000),
                    false,
                ]),
                Gio.DBusCallFlags.NONE, -1, null, null);
            return true;
        } catch (error) {
            logError_('the calendar server refused a time range', error);
            return false;
        }
    }

    _absorb(rows) {
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        const tomorrow = new Date(midnight);
        tomorrow.setDate(tomorrow.getDate() + 1);

        const events = [];
        for (const row of rows ?? []) {
            // (s id, s summary, b allDay, x start, x end, a{sv} extras)
            const [id, summary, allDay, startSeconds] = row;
            const start = new Date(Number(startSeconds) * 1000);
            if (start >= tomorrow)
                continue;
            events.push({
                id: String(id),
                summary: String(summary || 'Untitled event'),
                start,
                allDay: Boolean(allDay),
            });
        }
        events.sort((a, b) => a.start - b.start);
        this._events = events;
        this._providerName = 'shell-calendar-server';
        this._emit();
    }

    /**
     * The fallback provider.
     *
     * Format: an array of {"summary": string, "start": ISO-8601, "allDay":
     * bool}. Anything unparseable is skipped with one log line rather than
     * failing the whole file, so one bad row cannot empty a real agenda.
     */
    _readLocalFile() {
        const path = GLib.build_filenamev([
            GLib.get_user_data_dir(), 'bunny', 'agenda.json',
        ]);
        const text = readText(path);
        if (text === null)
            return [];
        let document;
        try {
            document = JSON.parse(text);
        } catch (error) {
            logOnce('agenda-file', `${path} is not valid JSON (${error.message}); the agenda is empty`);
            return [];
        }
        const rows = Array.isArray(document) ? document : document?.events;
        if (!Array.isArray(rows))
            return [];
        const midnight = new Date();
        midnight.setHours(0, 0, 0, 0);
        const tomorrow = new Date(midnight);
        tomorrow.setDate(tomorrow.getDate() + 1);

        const events = [];
        for (const [index, row] of rows.entries()) {
            const start = new Date(String(row?.start ?? ''));
            if (Number.isNaN(start.getTime())) {
                logOnce(`agenda-row-${index}`, `${path} row ${index} has no parseable start; skipped`);
                continue;
            }
            if (start < midnight || start >= tomorrow)
                continue;
            events.push({
                id: `local-${index}`,
                summary: String(row.summary ?? 'Untitled event'),
                start,
                allDay: Boolean(row.allDay),
            });
        }
        events.sort((a, b) => a.start - b.start);
        return events;
    }

    _emit() {
        for (const listener of this._listeners) {
            try {
                listener();
            } catch (error) {
                logError_('agenda listener failed', error);
            }
        }
    }
}
