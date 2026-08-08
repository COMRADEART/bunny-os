// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The pieces every surface is built from.
//
// Three things live here because they were about to be written five times each:
// a box whose orientation is set the way GNOME 50 wants it, the glass panel
// that gives the desktop its material, and the "Unavailable" convention.
//
// On that last one. Every metric in this desktop can fail to be readable, and
// each failure has to look the same or users will read the difference as
// meaning something. `valueText` is the single place that turns a possibly-null
// measurement into text, so a widget cannot accidentally print "0%" for a
// sensor that is not there — which is the specific mistake the brief calls out
// and the one that is hardest to notice, because 0% looks like a measurement.

import Clutter from 'gi://Clutter';
import St from 'gi://St';
import Shell from 'gi://Shell';

import {Colour} from './tokens.js';
import {logOnce, makeActivatable} from './util.js';

export const UNAVAILABLE = 'Unavailable';

/**
 * A St.BoxLayout with its orientation set through the property GNOME 50 has.
 *
 * St.BoxLayout's `vertical` construct property was deprecated and then removed
 * in favour of `orientation`. The fallback is not superstition: this extension
 * is also loaded by developers running an older Shell to check a layout change,
 * and a hard failure there costs an hour to diagnose from a stack trace that
 * blames the constructor.
 */
export function box({vertical = false, ...properties} = {}) {
    const widget = new St.BoxLayout(properties);
    try {
        widget.orientation = vertical
            ? Clutter.Orientation.VERTICAL
            : Clutter.Orientation.HORIZONTAL;
    } catch (_error) {
        widget.vertical = vertical;
    }
    return widget;
}

/**
 * A translucent panel, blurred behind if this session can afford it.
 *
 * Shell.BlurEffect samples what is behind the actor every frame. On a GPU that
 * is a few hundred microseconds; under llvmpipe it is milliseconds, per blurred
 * surface, per frame — which is why `blur` is a decision the caller makes and
 * DesktopShell makes it once, from the renderer probe, rather than each panel
 * assuming it can have one.
 */
export function glass(styleClass, {blur = false, radius = 18} = {}) {
    const widget = new St.Widget({
        style_class: styleClass,
        layout_manager: new Clutter.BinLayout(),
    });
    if (blur)
        applyBlur(widget, radius);
    return widget;
}

export function applyBlur(actor, radius = 18) {
    try {
        const effect = new Shell.BlurEffect({
            radius,
            brightness: 0.92,
            mode: Shell.BlurMode.BACKGROUND,
        });
        actor.add_effect_with_name('bunny-glass', effect);
        return true;
    } catch (error) {
        logOnce('blur', `Shell.BlurEffect is unavailable (${error.message}); panels stay flat-translucent`);
        return false;
    }
}

/**
 * Turn a measurement into text.
 *
 * @param {number|string|null} value null means the reader could not answer.
 * @param {(value: any) => string} format applied only to a real value.
 */
export function valueText(value, format = String) {
    return value === null || value === undefined ? UNAVAILABLE : format(value);
}

/** A card title row: a label, and optionally something pushed to the right. */
export function cardHeader(title, trailing = null) {
    const header = box({style_class: 'bunny-card-header'});
    const label = new St.Label({text: title, style_class: 'bunny-card-title'});
    header.add_child(label);
    if (trailing !== null) {
        const spacer = new St.Widget({x_expand: true});
        header.add_child(spacer);
        header.add_child(trailing);
    }
    return header;
}

/** A label pair used by every card that lists figures: name on the left, value right. */
export class MetricRow {
    constructor(name, {accessibleName = null} = {}) {
        this.actor = box({style_class: 'bunny-metric-row'});
        this._name = new St.Label({text: name, style_class: 'bunny-metric-name'});
        this._value = new St.Label({text: UNAVAILABLE, style_class: 'bunny-metric-value'});
        this.actor.add_child(this._name);
        this.actor.add_child(new St.Widget({x_expand: true}));
        this.actor.add_child(this._value);
        this.actor.accessible_name = accessibleName ?? name;
    }

    set(text) {
        const shown = text ?? UNAVAILABLE;
        if (this._value.text !== shown) {
            this._value.text = shown;
            // Screen readers announce the row, not the label, so the accessible
            // name has to carry the value or the figure is invisible to Orca.
            this.actor.accessible_name = `${this._name.text}: ${shown}`;
        }
        this._value.remove_style_class_name('bunny-metric-unavailable');
        if (shown === UNAVAILABLE)
            this._value.add_style_class_name('bunny-metric-unavailable');
    }
}

/** A thin horizontal bar, 0..1, or dimmed and empty when the value is null. */
export class Meter {
    constructor({height = 6, colour = Colour.ACCENT} = {}) {
        this.actor = new St.Widget({
            style_class: 'bunny-meter',
            height,
            x_expand: true,
            layout_manager: new Clutter.BinLayout(),
        });
        this._fill = new St.Widget({
            style_class: 'bunny-meter-fill',
            style: `background-color: ${colour};`,
            x_align: Clutter.ActorAlign.START,
        });
        this.actor.add_child(this._fill);
        this._fraction = null;
        this.actor.connect('notify::width', () => this._apply());
    }

    set(fraction) {
        this._fraction = fraction;
        this._apply();
    }

    _apply() {
        const width = this.actor.get_width();
        if (this._fraction === null) {
            this._fill.set_width(0);
            this.actor.add_style_class_name('bunny-meter-unavailable');
            return;
        }
        this.actor.remove_style_class_name('bunny-meter-unavailable');
        this._fill.set_width(Math.round(width * Math.min(1, Math.max(0, this._fraction))));
    }
}

/**
 * A pressable tile with an icon and an optional label.
 *
 * St.Button would give hover and focus for free but not the running indicator
 * or the disabled-with-a-reason state, both of which the dock and quick access
 * need; building on St.Widget keeps one implementation instead of a button
 * subclass and a non-button twin.
 */
export function iconTile({gicon = null, iconName = null, iconSize = 28, label = null,
    styleClass = 'bunny-tile', accessibleName = null, onActivate = null,
    tooltip = null} = {}) {
    const tile = box({vertical: true, style_class: styleClass});
    const icon = new St.Icon({icon_size: iconSize, style_class: 'bunny-tile-icon'});
    if (gicon)
        icon.gicon = gicon;
    else if (iconName)
        icon.icon_name = iconName;
    tile.add_child(icon);
    if (label !== null)
        tile.add_child(new St.Label({text: label, style_class: 'bunny-tile-label'}));
    if (onActivate)
        makeActivatable(tile, onActivate, {accessibleName: accessibleName ?? label ?? ''});
    if (tooltip)
        tile.accessible_description = tooltip;
    tile.iconActor = icon;
    return tile;
}

/**
 * Mark a control as present but not usable, with the reason attached.
 *
 * Used for applications the image does not install. The brief allows hiding,
 * disabling or marking them; disabling with a reason is chosen for the quick
 * access card because a tile that silently disappears leaves the user unable to
 * tell an uninstalled application from a broken desktop.
 */
export function setUnavailable(actor, reason) {
    actor.add_style_class_name('bunny-unavailable');
    actor.reactive = false;
    actor.can_focus = false;
    actor.accessible_description = reason;
}
