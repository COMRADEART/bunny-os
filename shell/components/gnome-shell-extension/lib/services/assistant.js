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

import {logError_, logOnce, timeout} from '../util.js';

const BRIDGE = 'bunny-shell-assistant';

/**
 * How long the desktop waits before it stops believing an answer is coming.
 *
 * Longer than the bridge's own 180-second deadline, on purpose: the bridge
 * reports its own timeout as an `error` event and that is a better message
 * than this one. This fires only when the bridge itself never speaks — it
 * failed to exec, or it died without writing — and its job is to make sure
 * the character cannot be left in THINKING for ever by a process that is no
 * longer there.
 */
const WATCHDOG_MS = 200000;

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
        //: Monotonic, per session. Zero means nothing has been asked.
        this._sequence = 0;
        this._activeRequestId = 0;
        this._watchdog = null;
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
            return null;
        }

        // Every request gets an id and every callback carries it.
        //
        // The bridge is a subprocess and cancelling one is not instantaneous:
        // a reply already written to the pipe arrives after `force_exit`, and
        // the reader is an async callback that has already been scheduled. So
        // a second question can be in flight while the first one's `finished`
        // is still on its way, and without an id the first would set the
        // character to SUCCESS and then IDLE underneath the second — the
        // character going calm while it is still working.
        //
        // `requestId` is compared by the caller, not here, because the
        // interesting decision ("is this still the request I am showing?")
        // belongs to whatever is showing it.
        this._sequence += 1;
        const requestId = this._sequence;
        this._activeRequestId = requestId;

        const stillCurrent = () => this._activeRequestId === requestId;

        // A request that produces nothing at all still has to end. The runtime
        // has its own deadline and the bridge has another; this is the third,
        // and it exists because neither of those can fire if the *bridge* never
        // starts or dies without writing a line. Without it the character sits
        // in THINKING for ever, which is the one state the brief names twice.
        let settled = false;
        const finish = () => {
            if (settled)
                return;
            settled = true;
            this._watchdog?.stop();
            this._watchdog = null;
        };
        this._watchdog?.stop();
        this._watchdog = timeout(WATCHDOG_MS, () => {
            if (!stillCurrent() || settled)
                return;
            logOnce('assistant-watchdog',
                `no answer within ${Math.round(WATCHDOG_MS / 1000)}s; the request was abandoned`);
            finish();
            this.cancelWatch();
            handlers.onError?.(
                'The assistant did not answer in time. It may still be working — ' +
                'the Tasks window will show it.',
                {requestId});
        });

        this._current = this._run(['ask', trimmed], line => {
            if (!stillCurrent())
                return;
            switch (line.event) {
            case 'accepted':
                handlers.onAccepted?.(line.taskId, {requestId});
                break;
            case 'phase':
                handlers.onPhase?.(line.phase, line.statusText ?? '', {requestId});
                break;
            case 'reply':
                handlers.onReply?.(line.text, line.kind === 'error', {requestId});
                break;
            case 'finished':
                finish();
                handlers.onFinished?.(line.phase, {requestId});
                break;
            case 'error':
                this._available = false;
                this._availabilityReason = line.reason;
                finish();
                handlers.onError?.(line.reason, {requestId});
                break;
            default:
                break;
            }
        }, () => {
            this._current = null;
            // The bridge closed its pipe. If nothing terminal arrived first,
            // that is a crash or an exec failure, and it is terminal now — a
            // process that has gone is not going to answer.
            if (stillCurrent() && !settled) {
                finish();
                handlers.onError?.(
                    'The assistant service stopped before answering.', {requestId});
            }
            finish();
        });
        return requestId;
    }

    /** The id of the request the desktop should still be showing, or 0. */
    get activeRequestId() {
        return this._activeRequestId;
    }

    /**
     * Stop watching the current request.
     *
     * Force-terminates the bridge process, not the task. The distinction is in
     * the bridge's docstring and matters: the runtime keeps working and the
     * result is still recorded.
     */
    cancelWatch() {
        this._watchdog?.stop();
        this._watchdog = null;
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
