// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Turning a measurement into text, and nothing else.
//
// The fourth module in this extension to import nothing, for the fourth time
// for the same reason: layout.js decides where things go, storage.js decides
// which filesystem is meant, iconNames.js decides what may be drawn, and this
// decides what a number reads as. Every one of those is a claim that can be
// wrong, and every one of them should be checkable without starting a
// compositor — util.js imports Gio, GLib, St, Clutter and Atk, and a pure
// function living beside them cannot be evaluated under node at all.
//
// That is not hypothetical here. `formatPair` exists because
// `3.9 GB / 8.3 GB` ellipsised to `3.9 GB…` in the 248-pixel card at
// 1366x768, and the test that keeps it short is a table of byte counts run
// through the real function.
//
// util.js re-exports everything below, so no caller changed.

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

/**
 * A used-of-total pair, short enough to survive a narrow card.
 *
 * `3.9 GB / 8.3 GB` is fifteen characters and does not fit beside its label in
 * a 248-pixel card, so at the compact breakpoint the value ellipsised to
 * `3.9 GB…` — which drops the half of the figure that gives the other half a
 * meaning. Measured on the 1366x768 boot of the Alpha image.
 *
 * Both numbers are expressed in the *total's* unit and the unit is written
 * once. That is what makes it short, and it is also more honest than the
 * original: `975.5 MB / 5.8 GB` invites a comparison between two numbers in
 * different units, and `1.0/5.8 GB` does not.
 */
export function formatPair(used, total) {
    if (!Number.isFinite(used) || !Number.isFinite(total) || total <= 0)
        return null;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let index = 0;
    let scale = 1;
    while (total / scale >= 1024 && index < units.length - 1) {
        scale *= 1024;
        index += 1;
    }
    const places = index <= 1 ? 0 : 1;
    return `${(used / scale).toFixed(places)}/${(total / scale).toFixed(places)} ${units[index]}`;
}

export function formatRate(bytesPerSecond) {
    if (bytesPerSecond === null || !Number.isFinite(bytesPerSecond))
        return null;
    const formatted = formatBytes(bytesPerSecond, {decimals: 1});
    return formatted === null ? null : `${formatted}/s`;
}
