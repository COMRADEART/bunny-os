// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// CharacterStateManager: what the assistant is doing, as one value.
//
// Everything that wants to show assistant activity — the figure, the floor
// glow, the speech bubble, the assistant card's spinner — subscribes here
// rather than being told separately by whatever caused the change. That is not
// tidiness: the failure it prevents is the one where a request fails, the card
// shows an error and the character is still cheerfully working, because the
// error path updated one and forgot the other.
//
// Two rules that are easy to get wrong and are therefore enforced here rather
// than left to callers:
//
// **Transient states return by themselves.** success, celebrating and warning
// are reactions, not conditions. Each carries a dwell time and the manager
// schedules the return to idle when it enters one. A caller that had to
// remember to set idle afterwards would eventually not, and the character would
// grin at an empty desktop until the next request.
//
// **error does not.** An error is a condition and stays until something else
// happens, because a figure that shrugs off a failure after two seconds tells
// the user the failure did not matter.

import {timeout} from '../util.js';

export const STATES = [
    'idle', 'listening', 'thinking', 'working', 'success',
    'warning', 'error', 'talking', 'sleeping', 'celebrating',
];

/** Milliseconds a transient state holds before returning to idle. */
const DWELL = {
    success: 3200,
    celebrating: 4200,
    warning: 5000,
};

/**
 * Idle for this long with no request and the character goes to sleep. Long
 * enough that it does not happen while someone is reading the screen; short
 * enough that a machine left alone stops animating and stops drawing power.
 */
const SLEEP_AFTER_MS = 5 * 60 * 1000;

export class CharacterStateManager {
    constructor() {
        this._state = 'idle';
        this._reason = '';
        this._listeners = new Set();
        this._dwellTimer = null;
        this._sleepTimer = null;
        this._armSleep();
    }

    get state() {
        return this._state;
    }

    /** Why the state was last set. Shown in the accessible description. */
    get reason() {
        return this._reason;
    }

    /**
     * @param {string} state one of STATES
     * @param {{reason?: string}} options
     * @returns {boolean} false when the state is not one this manager has,
     *   which is a programming error the caller can assert on rather than a
     *   silent no-op.
     */
    setState(state, {reason = ''} = {}) {
        if (!STATES.includes(state))
            return false;
        this._cancelDwell();
        const changed = this._state !== state;
        this._state = state;
        this._reason = reason;

        if (state === 'sleeping')
            this._cancelSleep();
        else
            this._armSleep();

        if (DWELL[state] !== undefined) {
            this._dwellTimer = timeout(DWELL[state], () => {
                this._dwellTimer = null;
                this.setState('idle', {reason: 'returned from a transient state'});
            });
        }

        if (changed || reason !== '')
            this._emit();
        return true;
    }

    /**
     * Adopt the state implied by a companion presentation phase.
     *
     * The mapping table lives in services/assistant.js beside the bridge that
     * produces the phases, so the vocabulary and its translation stay in one
     * place. This method exists so callers pass a phase and get the right
     * behaviour including the dwell rules above, rather than looking the phase
     * up and calling setState themselves.
     */
    adoptPhase(phase, mapping, {statusText = ''} = {}) {
        const state = mapping[phase];
        if (state === undefined)
            return false;
        return this.setState(state, {reason: statusText || `companion phase ${phase}`});
    }

    /** @returns {() => void} an unsubscribe function */
    subscribe(callback) {
        this._listeners.add(callback);
        // Fire immediately so a widget created mid-request shows the current
        // state rather than idle until the next change.
        callback(this._state, this._reason);
        return () => this._listeners.delete(callback);
    }

    /** Reset the sleep countdown without changing state. Called on any input. */
    noteActivity() {
        if (this._state === 'sleeping')
            this.setState('idle', {reason: 'woken by activity'});
        else
            this._armSleep();
    }

    destroy() {
        this._cancelDwell();
        this._cancelSleep();
        this._listeners.clear();
    }

    _armSleep() {
        this._cancelSleep();
        this._sleepTimer = timeout(SLEEP_AFTER_MS, () => {
            this._sleepTimer = null;
            this.setState('sleeping', {reason: 'no activity for five minutes'});
        });
    }

    _cancelSleep() {
        this._sleepTimer?.stop();
        this._sleepTimer = null;
    }

    _cancelDwell() {
        this._dwellTimer?.stop();
        this._dwellTimer = null;
    }

    _emit() {
        for (const listener of this._listeners) {
            try {
                listener(this._state, this._reason);
            } catch (error) {
                console.error(`bunny-desktop: a character state listener failed: ${error.message}`);
            }
        }
    }
}
