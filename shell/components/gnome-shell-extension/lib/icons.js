// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Turning an icon name into something St can draw.
//
// The names themselves are in iconNames.js, which imports nothing so the test
// suite can check them against the real icon theme. This half needs St, and it
// exists because a build-time check against one package version cannot promise
// anything about the machine the desktop is running on: `themedIcon` asks the
// live icon theme too, and substitutes a bundled Bunny icon when a name does
// not resolve. The worst case is the wrong picture beside the right label,
// never a broken-image box — which is what `shop-symbolic` produced on every
// boot for a whole release.
//
// Everything from iconNames.js is re-exported, so callers import one module.

import St from 'gi://St';

import {logOnce} from './util.js';
import {Icons} from './iconNames.js';

export * from './iconNames.js';

let _theme = null;
let _themeUnavailable = false;

/**
 * Ask the live icon theme whether it has this name.
 *
 * Returns true when the theme cannot be consulted at all. That is deliberate:
 * an unavailable St.IconTheme is a fact about this Shell build, not about the
 * icon, and substituting the Bunny mark for every icon on the desktop because
 * a lookup API moved would be a far worse failure than the one being guarded.
 */
export function iconExists(name) {
    if (_themeUnavailable)
        return true;
    try {
        if (_theme === null)
            _theme = new St.IconTheme();
        return _theme.has_icon(name);
    } catch (error) {
        _themeUnavailable = true;
        logOnce('icon-theme', `the icon theme cannot be queried (${error.message}); ` +
            'icon names are used as given');
        return true;
    }
}

/**
 * An icon name that will draw something, and a journal line when it is not the
 * name that was asked for.
 */
export function resolveIconName(name, {fallback = Icons.BUNNY} = {}) {
    if (!name)
        return fallback;
    if (iconExists(name))
        return name;
    logOnce(`icon-missing-${name}`,
        `the icon theme has no "${name}"; drawing "${fallback}" instead`);
    return fallback;
}

/**
 * The one constructor for a themed icon in this desktop.
 *
 * Every St.Icon built from a *name* goes through here. Icons built from a
 * GIcon — an application's own, out of its .desktop entry — do not and cannot:
 * that name belongs to the application, not to this desktop, and there is
 * nothing to check it against.
 */
export function themedIcon(name, {size = 16, styleClass = null, fallback = Icons.BUNNY} = {}) {
    const properties = {icon_name: resolveIconName(name, {fallback}), icon_size: size};
    if (styleClass)
        properties.style_class = styleClass;
    return new St.Icon(properties);
}

/** Change an existing icon's name, through the same resolution. */
export function setIconName(icon, name, {fallback = Icons.BUNNY} = {}) {
    icon.icon_name = resolveIconName(name, {fallback});
}
