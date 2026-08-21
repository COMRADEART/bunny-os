// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The small shared helpers. Two rules shaped this file.
//
// **A reader returns null, never a guess.** Every accessor here that consults
// the kernel returns `null` when the value is not there, and no caller is
// permitted to substitute a plausible number for it. The widgets render the
// word "Unavailable" instead. A dashboard that invents 48°C on a machine with
// no thermal zone is worse than one that admits it cannot tell, because the
// invented number is indistinguishable from a measured one.
//
// **Failure is logged once, not every tick.** These are called on 2-second
// timers. `logOnce` exists so a missing sysfs path produces one journal line
// per session rather than 1,800 an hour, which is how a real fault becomes
// invisible.

import Atk from 'gi://Atk';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';
import Clutter from 'gi://Clutter';

const _seenMessages = new Set();

export function log_(message) {
    console.log(`bunny-desktop: ${message}`);
}

export function logOnce(key, message) {
    if (_seenMessages.has(key))
        return;
    _seenMessages.add(key);
    console.log(`bunny-desktop: ${message}`);
}

export function logError_(message, error) {
    console.error(`bunny-desktop: ${message}: ${error?.message ?? error}`);
}

/** Read a small text file, or null. Never throws. */
export function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        if (!ok)
            return null;
        return new TextDecoder().decode(bytes);
    } catch (_error) {
        return null;
    }
}

/** Read a file whose whole content is one integer, or null. */
export function readInt(path) {
    const text = readText(path);
    if (text === null)
        return null;
    const value = Number.parseInt(text.trim(), 10);
    return Number.isFinite(value) ? value : null;
}

/** List a directory's entries, or an empty array. Never throws. */
export function listDirectory(path) {
    const names = [];
    let enumerator = null;
    try {
        enumerator = Gio.File.new_for_path(path).enumerate_children(
            'standard::name', Gio.FileQueryInfoFlags.NONE, null);
    } catch (_error) {
        return names;
    }
    let info;
    while ((info = enumerator.next_file(null)) !== null)
        names.push(info.get_name());
    enumerator.close(null);
    return names.sort();
}

export function fileExists(path) {
    return GLib.file_test(path, GLib.FileTest.EXISTS);
}

/**
 * Is this session drawing through a software rasteriser?
 *
 * Asked so the blur effect can default off where it would cost more than it is
 * worth. The signal is the presence of a DRM render node: llvmpipe leaves
 * /dev/dri empty, and every hardware and paravirtual driver that Mesa can use
 * for GL creates one. It is a heuristic and is named as one — it decides a
 * default the user can override, and nothing else.
 */
export function isLikelySoftwareRendering() {
    return !listDirectory('/dev/dri').some(name => name.startsWith('renderD'));
}

// The pure formatters live in format.js so they can be tested under node; see
// the note at the top of that file. Re-exported here because every caller in
// the desktop imports them from util.js and there is no reason to make the
// split their problem.
export * from './format.js';

// -- poller instrumentation ---------------------------------------------------
//
// §9 of the Phase 5 directive asks which poller contributes most to idle CPU,
// and says: do not guess. The desktop's idle CPU rose from 0.80% to 2.07%
// between 7edd3fd and the Alpha RC, and the recorded hypothesis — the System
// overview card's 2-second refresh — had never been measured.
//
// Half of it has now been measured outside the shell, and that half is cleared:
// the four /proc and /sys reads the card performs cost 117 microseconds per
// tick, which is 0.006% of one core against a 1.27-point regression, smaller by
// a factor of two hundred (qualification/phase5/performance/).
//
// What that benchmark cannot see is the redraw. In the qualification guest
// there is no GPU; Mutter composites through llvmpipe, in software, on the CPU,
// so a Cairo arc repainted every two seconds is paid for by the processor there
// in a way it is not on a machine with one. That has to be measured inside a
// running shell, which is what this is for.
//
// Cost when nothing asks for a report: one counter increment and two
// monotonic-clock reads per tick. GLib.get_monotonic_time is a vDSO call.

const _pollers = new Map();
let _pollerEpoch = GLib.get_monotonic_time();

/**
 * Every named poller's accumulated cost since the last reset.
 *
 * `wallMicroseconds` is measured directly. CPU time is deliberately *not*
 * measured per tick: the only in-process source is /proc/self/stat, whose
 * resolution is a 10 ms clock tick, so almost every individual tick would read
 * zero — and reading it costs 19 microseconds against a 117-microsecond tick,
 * which is a 16% instrument overhead on the thing being measured. A caller that
 * wants CPU should sample the process once around a window and attribute it by
 * each poller's share of `wallMicroseconds`, which is what the guest probe does
 * and what its evidence says it did.
 *
 * `changes` counts the ticks on which the poller reported that the data it read
 * had actually changed — the number §10 turns on. A poller whose data changes
 * on 3 ticks in 1800 is a poller whose cadence is buying nothing, and a poller
 * whose data changes every tick cannot be made cheaper by change detection
 * however slow it is.
 */
export function pollerMetrics() {
    const now = GLib.get_monotonic_time();
    const entries = [];
    let totalWall = 0;
    for (const record of _pollers.values())
        totalWall += record.wallMicroseconds;
    for (const [name, record] of _pollers) {
        entries.push({
            name,
            intervalSeconds: record.intervalSeconds,
            ticks: record.ticks,
            changes: record.changes,
            errors: record.errors,
            wallMicroseconds: record.wallMicroseconds,
            slowestTickMicroseconds: record.slowestTickMicroseconds,
            meanTickMicroseconds: record.ticks === 0
                ? null
                : Math.round(record.wallMicroseconds / record.ticks),
            // Stated as a share rather than as a CPU figure, because a share is
            // what this can honestly report. See the note above.
            wallShare: totalWall === 0 ? null : record.wallMicroseconds / totalWall,
        });
    }
    entries.sort((a, b) => b.wallMicroseconds - a.wallMicroseconds);
    return {
        schemaVersion: 1,
        windowMicroseconds: now - _pollerEpoch,
        totalWallMicroseconds: totalWall,
        pollers: entries,
    };
}

/** Start a fresh measurement window. Called by the probe before it idles. */
export function resetPollerMetrics() {
    for (const record of _pollers.values()) {
        record.ticks = 0;
        record.changes = 0;
        record.errors = 0;
        record.wallMicroseconds = 0;
        record.slowestTickMicroseconds = 0;
    }
    _pollerEpoch = GLib.get_monotonic_time();
}

/**
 * A repeating timer that unregisters itself cleanly.
 *
 * Returns a handle with `.stop()`. Every periodic reader in the desktop uses
 * one, and DesktopShell.destroy() stops all of them, because a GLib source that
 * outlives the actor it updates is the classic way an extension keeps a
 * disabled session alive.
 *
 * `name` is optional and only affects instrumentation. An unnamed timer is
 * recorded under `unnamed:<seconds>s`, so an uninstrumented caller still shows
 * up in the report rather than vanishing from it — a poller that is invisible
 * to the measurement is the one that will be blamed last.
 *
 * A callback may return `true` to say the data it read had changed. Returning
 * nothing means "not reported", which is counted separately from "did not
 * change": §10 asks whether an update was necessary, and a poller that has
 * never been asked to answer must not be recorded as having answered no.
 *
 * @param {number} seconds
 * @param {Function} callback returns true when the data changed, or undefined
 * @param {{name?: string}} [options]
 */
export function interval(seconds, callback, options = {}) {
    const name = options.name ?? `unnamed:${seconds}s`;
    let record = _pollers.get(name);
    if (record === undefined) {
        record = {
            intervalSeconds: seconds,
            ticks: 0,
            changes: 0,
            errors: 0,
            wallMicroseconds: 0,
            slowestTickMicroseconds: 0,
        };
        _pollers.set(name, record);
    }
    let id = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, seconds, () => {
        const started = GLib.get_monotonic_time();
        try {
            const changed = callback();
            if (changed === true)
                record.changes += 1;
        } catch (error) {
            record.errors += 1;
            logError_('periodic update failed', error);
        }
        // Accounted in `finally`-equivalent position rather than inside the
        // try: a tick that threw still cost the time it took, and a poller
        // whose cost only appears when it succeeds hides the expensive failure.
        const elapsed = GLib.get_monotonic_time() - started;
        record.ticks += 1;
        record.wallMicroseconds += elapsed;
        if (elapsed > record.slowestTickMicroseconds)
            record.slowestTickMicroseconds = elapsed;
        return GLib.SOURCE_CONTINUE;
    });
    return {
        stop() {
            if (id !== null) {
                GLib.source_remove(id);
                id = null;
            }
        },
    };
}

/** A one-shot timer with the same disposal contract as interval(). */
export function timeout(milliseconds, callback) {
    let id = GLib.timeout_add(GLib.PRIORITY_DEFAULT, milliseconds, () => {
        id = null;
        try {
            callback();
        } catch (error) {
            logError_('deferred action failed', error);
        }
        return GLib.SOURCE_REMOVE;
    });
    return {
        stop() {
            if (id !== null) {
                GLib.source_remove(id);
                id = null;
            }
        },
    };
}

/**
 * Set an actor's accessible role, and never take the desktop down doing it.
 *
 * `accessible-role` is an Atk.Role, not a Clutter one. Getting that wrong cost
 * a boot: `Clutter.AccessibleRole.PUSH_BUTTON` is `undefined.PUSH_BUTTON`,
 * which throws a TypeError, which propagated out of the first widget the top
 * bar built and out of DesktopShell's constructor, and the whole desktop
 * refused to start over a screen-reader hint.
 *
 * So the lookup is by name against Atk.Role and a miss is logged and skipped.
 * A missing role costs Orca one label; it must not cost the user their desktop.
 * The consequence is stated rather than swallowed, which is why this logs.
 */
export function setAccessibleRole(actor, roleName) {
    const role = Atk?.Role?.[roleName];
    if (role === undefined) {
        logOnce(`atk-role-${roleName}`,
            `Atk.Role.${roleName} is not available; the role is left unset and screen readers ` +
            'will announce the generic role for this control');
        return false;
    }
    try {
        actor.accessible_role = role;
        return true;
    } catch (error) {
        logOnce(`atk-role-set-${roleName}`,
            `setting Atk.Role.${roleName} was refused (${error.message})`);
        return false;
    }
}

/**
 * Make an actor operable from the keyboard as well as the pointer.
 *
 * St gives buttons this for free and gives plain widgets none of it. Several
 * things in the desktop are neither — a card that opens a panel, a dock tile, a
 * suggestion row — and each of them needs the same four properties and the same
 * Enter/Space handling. Written once so a control cannot be added without it.
 */
export function makeActivatable(actor, onActivate, {accessibleName = null} = {}) {
    actor.reactive = true;
    actor.can_focus = true;
    actor.track_hover = true;
    setAccessibleRole(actor, 'PUSH_BUTTON');
    if (accessibleName)
        actor.accessible_name = accessibleName;
    actor.connect('button-release-event', () => {
        onActivate();
        return Clutter.EVENT_STOP;
    });
    actor.connect('key-press-event', (_actor, event) => {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter ||
            symbol === Clutter.KEY_space) {
            onActivate();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    });
    return actor;
}

/** A label that never widens its parent past `width`. */
export function ellipsisLabel(text, styleClass, width) {
    const label = new St.Label({text, style_class: styleClass});
    label.clutter_text.ellipsize = 3; // Pango.EllipsizeMode.END
    if (width)
        label.set_width(width);
    return label;
}
