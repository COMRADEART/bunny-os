// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// VoiceService is the shell's control surface for the canonical companion
// speech subsystem.  It never opens an audio device and never runs inference;
// those live in bunny-companion, outside GNOME Shell.  This class only starts
// an explicit bounded interaction, renders NDJSON events, and sends stop or
// cancellation requests carrying the identifiers the companion issued.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {logError_, logOnce, timeout} from '../util.js';

const BRIDGE = 'bunny-shell-assistant';
const WATCHDOG_MS = 330000;

export class VoiceService {
    constructor() {
        this._current = null;
        this._health = null;
        this._sequence = 0;
        this._activeInteraction = 0;
        this._requestId = '';
        this._cancellationToken = '';
        this._taskId = '';
        this._microphoneActive = false;
        this._watchdog = null;
        this._settled = true;
        this._cancelPending = false;
        this._cancelControlStarted = false;
        this._cancelCallbacks = [];
    }

    get available() {
        return this._health?.available ?? null;
    }

    get availabilityReason() {
        return this._health?.reason ?? 'speech input has not been checked yet';
    }

    get active() {
        return this._current !== null;
    }

    get microphoneActive() {
        return this._microphoneActive;
    }

    get cancellationPending() {
        return this._cancelPending;
    }

    checkHealth(onSettled = null) {
        let reported = false;
        const settle = (available, reason, line) => {
            if (reported)
                return;
            reported = true;
            onSettled?.(available, reason, line);
        };
        this._run(['voice-health'], line => {
            if (line.event !== 'voice_health')
                return;
            this._health = line;
            if (!line.available)
                logOnce('voice-unavailable', `voice input unavailable: ${line.reason}`);
            settle(Boolean(line.available), line.reason ?? '', line);
        }, () => settle(
            Boolean(this._health?.available), this.availabilityReason, this._health));
    }

    start(activationSource = 'push-to-talk-button', handlers = {}) {
        if (this._cancelPending)
            return 0;
        this.cancel({notify: false});
        if (this._cancelPending)
            return 0;
        this._sequence += 1;
        const interactionId = this._sequence;
        this._activeInteraction = interactionId;
        const stillCurrent = () => this._activeInteraction === interactionId;
        const meta = () => ({interactionId});
        this._settled = false;
        this._requestId = '';
        this._cancellationToken = '';
        this._taskId = '';
        this._microphoneActive = false;
        this._cancelControlStarted = false;

        this._watchdog?.stop();
        this._watchdog = timeout(WATCHDOG_MS, () => {
            if (!stillCurrent() || this._settled)
                return;
            this.cancel({
                notify: false,
                onMicrophoneClosed: () => handlers.onMicrophone?.(false, meta()),
            });
            handlers.onError?.('Voice interaction did not finish in time.', meta());
        });

        const finish = () => {
            if (this._settled)
                return;
            this._settled = true;
            this._watchdog?.stop();
            this._watchdog = null;
            this._microphoneActive = false;
        };

        this._current = this._run(
            [
                'listen', '--activation-source', activationSource,
                '--presentation-revision', String(interactionId),
            ],
            line => {
                // Cancellation can arrive in the short interval after the
                // service accepted capture but before this reader received its
                // request id. Keep reading just enough to learn the id and to
                // observe confirmed microphone closure; suppress every normal
                // interaction callback meanwhile.
                if (this._cancelPending) {
                    this._handleCancellationLine(line);
                    return;
                }
                if (!stillCurrent())
                    return;
                switch (line.event) {
                case 'voice_started':
                    this._requestId = line.requestId ?? '';
                    this._cancellationToken = line.cancellationToken ?? '';
                    handlers.onStarted?.(line, meta());
                    break;
                case 'microphone':
                    this._microphoneActive = Boolean(line.active);
                    handlers.onMicrophone?.(this._microphoneActive, meta());
                    break;
                case 'voice_phase':
                case 'phase':
                    handlers.onPhase?.(line.phase, line.statusText ?? '', meta());
                    break;
                case 'partial':
                    handlers.onPartial?.(line.text ?? '', meta());
                    break;
                case 'transcript':
                    handlers.onTranscript?.(line, meta());
                    break;
                case 'accepted':
                    this._taskId = line.taskId ?? '';
                    handlers.onAccepted?.(this._taskId, meta());
                    break;
                case 'approval':
                    handlers.onApproval?.(line, meta());
                    break;
                case 'reply':
                    handlers.onReply?.(line.text ?? '', line.kind === 'error', meta());
                    break;
                case 'file_results':
                    handlers.onFileResults?.(line.results ?? [], meta());
                    break;
                case 'speech_started':
                    handlers.onSpeechStarted?.(line, meta());
                    break;
                case 'speech_finished':
                    handlers.onSpeechFinished?.(line, meta());
                    break;
                case 'speech_error':
                    handlers.onSpeechError?.(line.reason ?? 'Speech output is unavailable.', meta());
                    break;
                case 'warning':
                    handlers.onWarning?.(line.reason ?? 'I did not catch that.', meta());
                    break;
                case 'finished':
                    finish();
                    handlers.onMicrophone?.(false, meta());
                    handlers.onFinished?.(line.phase ?? 'idle', meta());
                    break;
                case 'error':
                    // A bridge/transport error is not evidence that a recorder
                    // in the companion process has closed. Request cancellation
                    // and keep the indicator up until a terminal worker status
                    // is observed by the cancellation bridge.
                    this.cancel({
                        notify: false,
                        onMicrophoneClosed: () => handlers.onMicrophone?.(false, meta()),
                    });
                    handlers.onError?.(line.reason ?? 'Voice interaction failed.', meta());
                    break;
                default:
                    break;
                }
            },
            () => {
                if (stillCurrent() && !this._settled) {
                    this.cancel({
                        notify: false,
                        onMicrophoneClosed: () => handlers.onMicrophone?.(false, meta()),
                    });
                    handlers.onError?.('The voice service stopped before finishing.', meta());
                }
                this._current = null;
            });
        return interactionId;
    }

    /** End recording now, preserving captured audio for transcription. */
    stopCapture() {
        if (!this._requestId || !this._microphoneActive)
            return false;
        this._control(['speech-stop', this._requestId]);
        // Keep the local state true until the main watcher receives the
        // companion's microphone=false event. Sending a stop request is not
        // evidence that the device has closed, and the privacy indicator must
        // cover that interval too.
        return true;
    }

    /** Interrupt output speech for the task currently shown. */
    interruptSpeech() {
        if (!this._taskId)
            return false;
        this._control(['voice-cancel', this._taskId]);
        return true;
    }

    /** Resolve one approval while the main voice watcher keeps running. */
    resolveApproval(taskId, approvalRequestId, decision, onSettled = null) {
        if (!taskId || !approvalRequestId || !['allow', 'deny'].includes(decision))
            return false;
        let reported = false;
        const settle = (resolved, line) => {
            if (reported)
                return;
            reported = true;
            onSettled?.(resolved, line);
        };
        this._run(
            ['approval', taskId, approvalRequestId, decision],
            line => settle(line.event === 'approval_resolved', line),
            () => settle(false, {
                reason: 'The voice approval control stopped before recording an answer.',
            }),
        );
        return true;
    }

    /** Cancel capture/transcript and any output speech, then drop the watcher. */
    cancel({notify = true, onMicrophoneClosed = null} = {}) {
        const hadWork = this._current !== null || this._requestId !== '' || this._taskId !== '';
        if (typeof onMicrophoneClosed === 'function')
            this._cancelCallbacks.push(onMicrophoneClosed);
        if (this._cancelPending)
            return hadWork;

        if (this._taskId)
            this._control(['voice-cancel', this._taskId]);
        const mayStillOpen = this._current !== null && !this._settled &&
            this._requestId === '' && this._taskId === '';
        const closureMustBeObserved = this._microphoneActive || mayStillOpen;
        this._activeInteraction = ++this._sequence;
        this._watchdog?.stop();
        this._watchdog = null;
        this._settled = true;

        if (closureMustBeObserved) {
            this._cancelPending = true;
            this._requestCaptureCancellation();
            return hadWork;
        }

        if (this._requestId)
            this._requestCaptureCancellation();
        this._microphoneActive = false;
        if (this._current !== null) {
            try {
                this._current.subprocess.force_exit();
            } catch (_error) {
                // Already exited.
            }
        }
        this._current = null;
        this._requestId = '';
        this._cancellationToken = '';
        this._taskId = '';
        this._notifyMicrophoneClosed();
        if (notify && hadWork)
            return true;
        return hadWork;
    }

    destroy() {
        this.cancel({notify: false});
    }

    _requestCaptureCancellation() {
        if (!this._requestId || this._cancelControlStarted)
            return;
        this._cancelControlStarted = true;
        // No '--' before the id: it is runtime-issued (never option-shaped) and
        // an option follows, which argparse would read as a positional if it
        // came after the separator.
        this._control([
            'speech-cancel', this._requestId,
            '--cancellation-token', this._cancellationToken,
        ], line => {
            if (line.event === 'speech_cancelled' && line.microphoneClosed === true)
                this._completePendingCancellation();
        });
    }

    _handleCancellationLine(line) {
        switch (line.event) {
        case 'voice_started':
            this._requestId = line.requestId ?? '';
            this._cancellationToken = line.cancellationToken ?? '';
            this._requestCaptureCancellation();
            break;
        case 'microphone':
            this._microphoneActive = Boolean(line.active);
            if (!this._microphoneActive)
                this._completePendingCancellation();
            break;
        case 'finished':
            // A bridge finishes only after the speech worker records a terminal
            // disposition; its teardown has closed capture and cleared the
            // companion-side indicator by then.
            this._completePendingCancellation();
            break;
        case 'error':
            logOnce('voice-cancel-unconfirmed',
                line.reason ?? 'microphone closure could not be confirmed');
            break;
        default:
            break;
        }
    }

    _completePendingCancellation() {
        if (!this._cancelPending)
            return;
        this._cancelPending = false;
        this._cancelControlStarted = false;
        this._microphoneActive = false;
        if (this._current !== null) {
            try {
                this._current.subprocess.force_exit();
            } catch (_error) {
                // Already exited.
            }
        }
        this._current = null;
        this._requestId = '';
        this._cancellationToken = '';
        this._taskId = '';
        this._notifyMicrophoneClosed();
    }

    _notifyMicrophoneClosed() {
        const callbacks = this._cancelCallbacks.splice(0);
        for (const callback of callbacks) {
            try {
                callback();
            } catch (error) {
                logError_('voice cancellation callback failed', error);
            }
        }
    }

    // The parameter is `argumentList` and not `arguments` for a reason that cost
    // a whole desktop: an ES module is strict-mode code, binding the name
    // `arguments` in it is a SyntaxError, and GJS reports that when it *loads*
    // the module — before enable() runs, so extension.js's try/catch never sees
    // it. The extension went to state ERROR, GNOME Shell carried on with its
    // own desktop, and the session looked like an ordinary GNOME login.
    _control(argumentList, onLine = null) {
        this._run(argumentList, line => {
            if (line.event === 'error')
                logOnce(`voice-control-${argumentList[0]}`,
                    line.reason ?? `${argumentList[0]} failed`);
            onLine?.(line);
        }, null);
    }

    _run(argumentList, onLine, onDone) {
        let subprocess;
        try {
            subprocess = Gio.Subprocess.new(
                [BRIDGE, ...argumentList],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE);
        } catch (error) {
            logOnce('voice-bridge-missing',
                `${BRIDGE} could not be started (${error.message}); voice is unavailable`);
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                onDone?.();
                return GLib.SOURCE_REMOVE;
            });
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
                    logError_('voice bridge read failed', error);
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
                        logError_(`voice bridge emitted invalid JSON: ${text}`, error);
                    }
                }
                readNext();
            });
        };
        readNext();
        return {subprocess, stream};
    }
}
