// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Every icon the desktop draws, named once.
//
// ## Why this file exists
//
// The desktop used to carry two kinds of pictogram and both were unsafe.
//
// Emoji were the visible half. `👋`, `💡`, `📝`, `🧹`, `📁`, `🛍` were written
// straight into labels, and the first booted image drew every one of them as a
// tofu box because it shipped sans and CJK fonts and no emoji font. Installing
// the font fixed that image; it did not fix the *shape* of the mistake, which
// is that an interface control's meaning was carried by a glyph the image is
// not required to have. A font that fails to install, a locale fallback, a
// user who changes the interface font — any of those puts a box back on a
// control whose label is the only thing left saying what it does.
//
// The invisible half was worse. `shop-symbolic` was the Store row's icon from
// the day the sidebar was written, and adwaita-icon-theme does not have it and
// never has: see tests/shell/data/adwaita-icon-inventory.txt, read out of the
// package this image installs. St draws `image-missing` for a name it cannot
// resolve, so that row has shown a broken-image placeholder on every boot
// since. Nothing caught it, because an icon name is a string and every string
// parses.
//
// So: every icon name in the desktop is declared here, tests/shell checks each
// one against the inventory measured from the real icon theme, and no other
// module is allowed to contain a `-symbolic` literal at all. That last rule is
// what makes the first one complete rather than a list somebody maintains.
//
// ## The runtime half
//
// The inventory is a build-time check against one package version and cannot
// promise anything about the machine the desktop is running on. `themedIcon`
// therefore asks the live icon theme too and substitutes a bundled Bunny icon
// when a name does not resolve — so the worst case is the wrong picture beside
// the right label, never a broken-image box. The substitution is logged;
// silently drawing something else is how the Store row survived this long.

// ## Why this module imports nothing
//
// Same reason as layout.js, storage.js and character/figure.js. "every icon
// name this desktop can draw exists in the icon theme the image installs" is a
// claim about a list of strings, and a claim about a list of strings should be
// checkable without starting a compositor. tests/shell/test_desktop_shell.py
// reads ALL_ICON_NAMES under node and compares it against the icon theme's own
// file list. Importing St here would have put a display server between that
// check and being able to run at all.
//
// icons.js re-exports everything below, so no caller has to know about the
// split.



/**
 * Bunny's own icons, installed by the shell's hicolor tree.
 *
 * The only names here that are not adwaita's, and the fallback for everything
 * else, which is why they are declared first.
 */
export const BUNNY_ICONS = Object.freeze(['bunny-shell-symbolic']);

/**
 * The name for each fixed thing the desktop draws.
 *
 * Grouped by surface rather than alphabetically, because the question asked of
 * this table is almost always "what does the dock use", never "what uses
 * folder-symbolic".
 */
export const Icons = Object.freeze({
    // Bunny itself
    BUNNY: 'bunny-shell-symbolic',

    // Navigation
    HOME: 'go-home-symbolic',
    FILES: 'folder-symbolic',
    APPS: 'view-app-grid-symbolic',
    SETTINGS: 'preferences-system-symbolic',
    TERMINAL: 'utilities-terminal-symbolic',
    // Not `shop-symbolic`, which does not exist in any icon theme this image
    // ships. This is the name GNOME uses for the software installer.
    STORE: 'system-software-install-symbolic',
    SEARCH: 'system-search-symbolic',

    // Power menu
    POWER: 'system-shutdown-symbolic',
    SUSPEND: 'weather-clear-night-symbolic',
    RESTART: 'system-reboot-symbolic',
    SHUT_DOWN: 'system-shutdown-symbolic',
    LOG_OUT: 'system-log-out-symbolic',

    // Generic representations, for a thing whose own icon is unknown
    FILE_GENERIC: 'text-x-generic-symbolic',
    APP_GENERIC: 'application-x-executable-symbolic',
    MEDIA_GENERIC: 'audio-x-generic-symbolic',

    // Assistant panel
    MICROPHONE: 'audio-input-microphone-symbolic',
    SEND: 'go-next-symbolic',

    // Indicators whose icon never changes
    BRIGHTNESS: 'display-brightness-symbolic',
    AC_ADAPTER: 'ac-adapter-symbolic',
    BATTERY_UNKNOWN: 'battery-missing-symbolic',

    // Throughput direction. These replace the `↑` and `↓` characters that were
    // previously part of the label text; the arrow is the meaning of the row,
    // so it is drawn from the icon theme rather than depending on the font
    // having U+2191.
    UPLOAD: 'go-up-symbolic',
    DOWNLOAD: 'go-down-symbolic',

    // Suggested actions. These replace the emoji chips one for one; each is
    // annotated with the glyph it replaced so the loss is reviewable.
    EXPLAIN: 'dialog-information-symbolic',     // was 💡
    PLAN: 'document-edit-symbolic',             // was 📝
    DISK_SPACE: 'drive-harddisk-symbolic',      // was 🧹
    WARNING: 'dialog-warning-symbolic',         // was ⚠
});

/** Volume, by band. `_refreshVolume` picks the band; this names the icon. */
export const VOLUME_ICONS = Object.freeze({
    muted: 'audio-volume-muted-symbolic',
    low: 'audio-volume-low-symbolic',
    medium: 'audio-volume-medium-symbolic',
    high: 'audio-volume-high-symbolic',
});

/** Connectivity, by transport and state. */
export const NETWORK_ICONS = Object.freeze({
    wiredConnected: 'network-wired-symbolic',
    wiredDisconnected: 'network-wired-disconnected-symbolic',
    wirelessConnected: 'network-wireless-signal-excellent-symbolic',
    wirelessLimited: 'network-wireless-acquiring-symbolic',
    wirelessOffline: 'network-wireless-offline-symbolic',
    unknown: 'network-wireless-signal-none-symbolic',
});

export const MEDIA_ICONS = Object.freeze({
    previous: 'media-skip-backward-symbolic',
    play: 'media-playback-start-symbolic',
    pause: 'media-playback-pause-symbolic',
    next: 'media-skip-forward-symbolic',
});

export const NOTIFICATION_ICONS = Object.freeze({
    info: 'dialog-information-symbolic',
    warning: 'dialog-warning-symbolic',
    error: 'dialog-error-symbolic',
});

/**
 * The battery levels adwaita actually ships, as literals.
 *
 * Written out rather than built with `battery-level-${step}-symbolic` for one
 * reason: a name assembled at runtime cannot be checked against the icon theme
 * by anything that reads the source, and the whole point of this file is that
 * every name the desktop can draw is a name something has verified.
 */
export const BATTERY_ICONS = Object.freeze({
    0: 'battery-level-0-symbolic',
    10: 'battery-level-10-symbolic',
    20: 'battery-level-20-symbolic',
    30: 'battery-level-30-symbolic',
    40: 'battery-level-40-symbolic',
    50: 'battery-level-50-symbolic',
    60: 'battery-level-60-symbolic',
    70: 'battery-level-70-symbolic',
    80: 'battery-level-80-symbolic',
    90: 'battery-level-90-symbolic',
    100: 'battery-level-100-symbolic',
});

export const BATTERY_CHARGING_ICONS = Object.freeze({
    0: 'battery-level-0-charging-symbolic',
    10: 'battery-level-10-charging-symbolic',
    20: 'battery-level-20-charging-symbolic',
    30: 'battery-level-30-charging-symbolic',
    40: 'battery-level-40-charging-symbolic',
    50: 'battery-level-50-charging-symbolic',
    60: 'battery-level-60-charging-symbolic',
    70: 'battery-level-70-charging-symbolic',
    80: 'battery-level-80-charging-symbolic',
    90: 'battery-level-90-charging-symbolic',
    // `-charged-`, not `-charging-`. adwaita breaks the pattern at the top of
    // the range and only at the top of it, so the template literal this table
    // replaced — `battery-level-${step}-charging-symbolic` — produced a name
    // that does not exist on exactly one machine state: a laptop plugged in at
    // 100%. Writing the names out is what made that visible.
    100: 'battery-level-100-charged-symbolic',
});

/**
 * The icon for a battery percentage.
 *
 * @param {number} percentage 0..100
 * @param {boolean} charging
 */
export function batteryIcon(percentage, charging) {
    const step = Math.max(0, Math.min(100, Math.round(percentage / 10) * 10));
    const table = charging ? BATTERY_CHARGING_ICONS : BATTERY_ICONS;
    return table[step] ?? Icons.BATTERY_UNKNOWN;
}

/** Every name this desktop can draw, for the inventory test. */
export const ALL_ICON_NAMES = Object.freeze([...new Set([
    ...Object.values(Icons),
    ...Object.values(VOLUME_ICONS),
    ...Object.values(NETWORK_ICONS),
    ...Object.values(MEDIA_ICONS),
    ...Object.values(NOTIFICATION_ICONS),
    ...Object.values(BATTERY_ICONS),
    ...Object.values(BATTERY_CHARGING_ICONS),
])]);
