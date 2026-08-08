// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AssistantService: the desktop's half of the conversation.
//
// It spawns /usr/bin/bunny-shell-assistant and reads newline-delimited JSON
// from it. Everything about the companion's wire protocol — the socket, the
// schema version, the operation table, the session — lives in that program and
// not here. See its docstring for why there is exactly one client.
//
// Reading is asynchronous throughout. A synchronous read on the GNOME Shell
// main loop is a frozen compositor, and this is a request that can legitimately
// take a minute: the whole point of the character's WORKING state is that the
// desktop stays alive while the runtime works.
//
// One request at a time. A second `ask` while one is in flight cancels the
// first *watcher* and starts a new one; it does not cancel the first task,
// which the runtime owns and the Tasks surface can still show. Killing work
// because the user asked a second question would lose results nobody asked to
// discard.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {logError_, logOnce} from '../util.js';

const BRIDGE = 'bunny-shell-assistant';

/** Companion presentation phase -> character state. The only place this maps. */
export const PHASE_TO_STATE = {
    idle: 'idle',
    starting: 'thinking',
    recovering: 'thinking',
    understanding: 'thinking',
    planning: 'thinking',
    reviewing: 'thinking',
    waiting_for_approval: 'warning',
    listening: 'listening',
    speaking: 'talking',
    presenting_result: 'talking',
    working: 'working',
    success: 'success',
    cancelling: 'warning',
    cancelled: 'idle',
    paused: 'warning',
    blocked: 'warning',
    error: 'error',
    disconnected: 'sleeping',
};

export class AssistantService {
    constructor() {
        this._current = null;
        this._available = null; // null = not yet asked
        this._availabilityReason = 'the companion runtime has not been contacted yet';
    }

    /**
     * Has the runtime answered a health check?
     *
     * Tri-state on purpose. `null` means unknown, and the assistant card says
     * "Checking…" rather than claiming either way before it has asked.
     */
    get available() {
        return this._available;
    }

    get availabilityReason() {
        return this._availabilityReason;
    }

    /** Ask once, at startup, and whenever a request fails to connect. */
    checkHealth(onSettled = null) {
        this._run(['health'], line => {
            if (line.event !== 'health')
                return;
            this._available = Boolean(line.available);
            this._availabilityReason = line.available
                ? `connected to ${line.endpoint}`
                : `${line.reason} — ${line.hint ?? ''}`.trim();
            if (!line.available)
                logOnce('assistant-unavailable', `assistant unavailable: ${this._availabilityReason}`);
            onSettled?.(this._available, this._availabilityReason);
        }, () => onSettled?.(this._available, this._availabilityReason));
    }

    /**
     * Submit a request.
     *
     * @param {string} text
     * @param {{onPhase, onReply, onFinished, onError}} handlers
     *   `onPhase` receives the companion's own phase string. Translating it to
     *   a character state is CharacterStateManager's job, through
     *   PHASE_TO_STATE above; doing it here would put the mapping in two files.
     */
    ask(text, handlers = {}) {
        this.cancelWatch();
        const trimmed = text.trim();
        if (trimmed === '') {
            handlers.onError?.('nothing was typed');
            return;
        }
        this._current = this._run(['ask', trimmed], line => {
            switch (line.event) {
            case 'accepted':
                handlers.onAccepted?.(line.taskId);
                break;
            case 'phase':
                handlers.onPhase?.(line.phase, line.statusText ?? '');
                break;
            case 'reply':
                handlers.onReply?.(line.text, line.kind === 'error');
                break;
            case 'finished':
                handlers.onFinished?.(line.phase);
                break;
            case 'error':
                this._available = false;
                this._availabilityReason = line.reason;
                handlers.onError?.(line.reason);
                break;
            default:
                break;
            }
        }, () => {
            this._current = null;
        });
    }

    /**
     * Stop watching the current request.
     *
     * Force-terminates the bridge process, not the task. The distinction is in
     * the bridge's docstring and matters: the runtime keeps working and the
     * result is still recorded.
     */
    cancelWatch() {
        if (this._current === null)
            return;
        try {
            this._current.subprocess.force_exit();
        } catch (_error) {
            // Already gone. Nothing to do and nothing to report.
        }
        this._current = null;
    }

    destroy() {
        this.cancelWatch();
    }

    _run(argumentList, onLine, onDone) {
        let subprocess;
        try {
            subprocess = Gio.Subprocess.new(
                [BRIDGE, ...argumentList],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (error) {
            // The bridge is installed by the same route as every other
            // bunny-* command, so its absence means a broken image rather than
            // a missing optional feature. Said once, with the reason.
            logOnce('assistant-bridge-missing',
                `${BRIDGE} could not be started (${error.message}); the assistant is unavailable`);
            this._available = false;
            this._availabilityReason = `${BRIDGE} is not installed`;
            onDone?.();
            return null;
        }

        const stream = new Gio.DataInputStream({
            base_stream: subprocess.get_stdout_pipe(),
            close_base_stream: true,
        });

        const readNext = () => {
            stream.read_line_async(GLib.PRIORITY_DEFAULT, null, (source, result) => {
                let raw = null;
                try {
                    [raw] = source.read_line_finish(result);
                } catch (error) {
                    logError_('assistant bridge read failed', error);
                    onDone?.();
                    return;
                }
                if (raw === null) {
                    onDone?.();
                    return;
                }
                const text = raw instanceof Uint8Array ? new TextDecoder().decode(raw) : String(raw);
                if (text.trim() !== '') {
                    try {
                        onLine(JSON.parse(text));
                    } catch (error) {
                        logError_(`assistant bridge emitted a line that is not JSON: ${text}`, error);
                    }
                }
                readNext();
            });
        };
        readNext();

        return {subprocess, stream};
    }
}
