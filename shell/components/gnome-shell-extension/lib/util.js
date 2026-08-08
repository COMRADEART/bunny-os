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

/** Clamp, because three widgets wanted it and JavaScript has no Math.clamp. */
export function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
}

export function formatBytes(bytes, {decimals = 1} = {}) {
    if (bytes === null || !Number.isFinite(bytes))
        return null;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = bytes;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
        value /= 1024;
        index += 1;
    }
    const places = index <= 1 ? 0 : decimals;
    return `${value.toFixed(places)} ${units[index]}`;
}

export function formatRate(bytesPerSecond) {
    if (bytesPerSecond === null || !Number.isFinite(bytesPerSecond))
        return null;
    const formatted = formatBytes(bytesPerSecond, {decimals: 1});
    return formatted === null ? null : `${formatted}/s`;
}

/**
 * A repeating timer that unregisters itself cleanly.
 *
 * Returns a handle with `.stop()`. Every periodic reader in the desktop uses
 * one, and DesktopShell.destroy() stops all of them, because a GLib source that
 * outlives the actor it updates is the classic way an extension keeps a
 * disabled session alive.
 */
export function interval(seconds, callback) {
    let id = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, seconds, () => {
        try {
            callback();
        } catch (error) {
            logError_('periodic update failed', error);
        }
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
    actor.accessible_role = Clutter.AccessibleRole.PUSH_BUTTON;
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
