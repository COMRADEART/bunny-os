// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// FileSearch, and the universal search that sits above it.
//
// Files are not searched here. `/usr/bin/bunny-search query <text> --limit N`
// already exists on this image, already has an index that
// bunny-search-index.timer keeps current, and already emits JSON. Walking the
// home directory from the compositor process would be a second index, a
// slower answer, and a stall in the main loop on the first cold directory.
//
// Applications, settings and the assistant are matched in process, because
// Shell.AppSystem is already in memory and a bus round trip to ask it what it
// knows would be slower than the answer.
//
// Ordering is fixed rather than scored: an exact application-name match, then
// prefix matches, then the assistant, then files. A relevance score across four
// kinds of result would need tuning nobody has data for, and a search box whose
// first result moves between runs is one users stop trusting.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {logError_, logOnce} from '../util.js';

const FILE_SEARCH = 'bunny-search';

/** Settings panels worth reaching by name. Kept short: this is not a sitemap. */
const SETTINGS_PANELS = [
    {name: 'Wi-Fi', panel: 'wifi', keywords: ['wifi', 'wireless', 'network', 'internet']},
    {name: 'Sound', panel: 'sound', keywords: ['sound', 'audio', 'volume', 'speaker', 'microphone']},
    {name: 'Displays', panel: 'display', keywords: ['display', 'screen', 'monitor', 'resolution', 'brightness']},
    {name: 'Power', panel: 'power', keywords: ['power', 'battery', 'suspend', 'sleep']},
    {name: 'Bluetooth', panel: 'bluetooth', keywords: ['bluetooth', 'pair']},
    {name: 'Printers', panel: 'printers', keywords: ['print', 'printer', 'scanner']},
    {name: 'Accessibility', panel: 'universal-access', keywords: ['accessibility', 'contrast', 'zoom', 'reader']},
    {name: 'Users', panel: 'user-accounts', keywords: ['user', 'account', 'password', 'login']},
    {name: 'Date & Time', panel: 'datetime', keywords: ['date', 'time', 'clock', 'timezone']},
];

export class FileSearch {
    /**
     * @param {string} text
     * @param {(results: Array<{name: string, path: string}>) => void} onResults
     *   Called once, asynchronously. A query that fails calls back with an
     *   empty list and logs the reason: an empty file section is a true
     *   statement about what was found, and the search box must not hang
     *   waiting for a program that is not going to answer.
     */
    query(text, limit, onResults) {
        let subprocess;
        try {
            subprocess = Gio.Subprocess.new(
                [FILE_SEARCH, 'query', text, '--limit', String(limit)],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (error) {
            logOnce('file-search-missing',
                `${FILE_SEARCH} could not be started (${error.message}); file results are omitted`);
            onResults([]);
            return null;
        }
        subprocess.communicate_utf8_async(null, null, (source, result) => {
            let stdout = '';
            try {
                [, stdout] = source.communicate_utf8_finish(result);
            } catch (error) {
                logError_('file search failed', error);
                onResults([]);
                return;
            }
            onResults(this._parse(stdout));
        });
        return subprocess;
    }

    _parse(stdout) {
        let document;
        try {
            document = JSON.parse(stdout);
        } catch (_error) {
            // bunny-search prints a usage error rather than JSON when the index
            // has never been built. That is a real state, not a crash.
            logOnce('file-search-output', 'bunny-search did not return JSON; file results are omitted');
            return [];
        }
        const rows = Array.isArray(document) ? document : document?.results ?? document?.matches ?? [];
        if (!Array.isArray(rows))
            return [];
        return rows
            .map(row => ({
                name: String(row.name ?? row.title ?? GLib.path_get_basename(String(row.path ?? ''))),
                path: String(row.path ?? ''),
            }))
            .filter(row => row.path !== '');
    }
}

/**
 * Universal search over applications, settings, files and the assistant.
 *
 * Application and settings matches are returned synchronously because they are
 * already in memory; files arrive later through `onFileResults`. The search
 * list therefore fills in two stages, which is deliberate — a search box that
 * shows nothing until the slowest source answers feels broken.
 */
export class UniversalSearch {
    constructor(launcher, fileSearch = new FileSearch()) {
        this._launcher = launcher;
        this._files = fileSearch;
        this._pending = null;
    }

    /** @returns {Array<{kind, title, subtitle, iconName, activate}>} */
    immediate(text) {
        const query = text.trim().toLowerCase();
        if (query === '')
            return [];
        const results = [];

        const apps = this._launcher.listAll();
        const scored = [];
        for (const app of apps) {
            const name = app.get_name();
            const lower = name.toLowerCase();
            if (lower === query)
                scored.push({rank: 0, app, name});
            else if (lower.startsWith(query))
                scored.push({rank: 1, app, name});
            else if (lower.includes(query))
                scored.push({rank: 2, app, name});
        }
        scored.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
        for (const {app, name} of scored.slice(0, 5)) {
            results.push({
                kind: 'application',
                title: name,
                subtitle: 'Application',
                gicon: app.get_icon(),
                activate: () => app.activate(),
            });
        }

        for (const entry of SETTINGS_PANELS) {
            if (!entry.keywords.some(word => word.startsWith(query) || query.startsWith(word)))
                continue;
            results.push({
                kind: 'setting',
                title: entry.name,
                subtitle: 'Settings',
                iconName: 'preferences-system-symbolic',
                activate: () => this._launcher.spawn(['gnome-control-center', entry.panel]),
            });
            if (results.filter(row => row.kind === 'setting').length >= 3)
                break;
        }

        return results;
    }

    /** Kick off the file half. Cancels any query still in flight. */
    files(text, limit, onFileResults) {
        if (this._pending) {
            try {
                this._pending.force_exit();
            } catch (_error) {
                // Already finished.
            }
            this._pending = null;
        }
        const trimmed = text.trim();
        if (trimmed.length < 2) {
            // One character matches most of a home directory. Not a useful
            // answer, and an expensive one to produce on every keystroke.
            onFileResults([]);
            return;
        }
        this._pending = this._files.query(trimmed, limit, rows => {
            this._pending = null;
            onFileResults(rows);
        });
    }

    destroy() {
        if (this._pending) {
            try {
                this._pending.force_exit();
            } catch (_error) {
                // Already finished.
            }
        }
        this._pending = null;
    }
}
