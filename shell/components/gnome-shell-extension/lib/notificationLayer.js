// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// NotificationLayer and NotificationService: the desktop's own toasts.
//
// Scope, stated plainly, because the name invites a wrong assumption: this does
// **not** take over freedesktop notifications. GNOME's message tray still
// receives every org.freedesktop.Notifications message and still shows it, and
// applications are unaffected. What this layer carries is the desktop's own
// feedback — "Files is not installed", "the assistant could not be reached",
// "this display has no adjustable backlight" — the things the shell itself
// needs to say and which have nowhere else to go.
//
// Replacing the message tray was considered and rejected for this phase: it
// means reimplementing action buttons, replaceable notifications, urgency,
// per-application settings, do-not-disturb and the notification history, and
// getting any of them wrong loses a user's messages. That is a phase of its
// own, and until then two half-working notification systems would be worse than
// one that works and one that is honest about being small.
//
// Toasts are announced to Orca through the actor's accessible role, and they
// are never the only report of anything: every message here is also a journal
// line, because a toast that has faded is evidence nobody can retrieve.

import St from 'gi://St';

import {box, glass} from './widgets.js';
import {ease, enter} from './animation.js';
import {log_, makeActivatable, setAccessibleRole, timeout} from './util.js';
import {Motion} from './tokens.js';

const DISMISS_AFTER_MS = {info: 4500, warning: 7000, error: 9000};
const MAX_VISIBLE = 3;

const ICONS = {
    info: 'dialog-information-symbolic',
    warning: 'dialog-warning-symbolic',
    error: 'dialog-error-symbolic',
};

export class NotificationLayer {
    constructor({blur = false} = {}) {
        this._blur = blur;
        this._toasts = [];
        this.actor = box({vertical: true, style_class: 'bunny-notification-layer'});
        this.actor.reactive = false;
    }

    /** @param {{x, y, width}} rect the top-right corner the stack hangs from */
    setGeometry(rect) {
        this.actor.set_position(rect.x, rect.y);
        this.actor.set_width(rect.width);
    }

    /** @param {'info'|'warning'|'error'} level */
    push(level, message, {onActivate = null} = {}) {
        log_(`notification (${level}): ${message}`);

        const toast = glass('bunny-toast', {blur: this._blur, radius: 14});
        toast.add_style_class_name(`bunny-toast-${level}`);
        const row = box({style_class: 'bunny-toast-row'});
        row.add_child(new St.Icon({
            icon_name: ICONS[level] ?? ICONS.info,
            icon_size: 16,
            style_class: 'bunny-toast-icon',
        }));
        const label = new St.Label({text: message, style_class: 'bunny-toast-text'});
        label.clutter_text.line_wrap = true;
        label.clutter_text.set_line_wrap_mode(2);
        row.add_child(label);
        toast.add_child(row);
        setAccessibleRole(toast, 'NOTIFICATION');
        toast.accessible_name = message;

        const dismiss = () => this._dismiss(toast);
        makeActivatable(toast, () => {
            onActivate?.();
            dismiss();
        }, {accessibleName: message});

        this.actor.add_child(toast);
        enter(toast, {rise: -8});
        this._toasts.push({toast, timer: timeout(DISMISS_AFTER_MS[level] ?? 5000, dismiss)});

        while (this._toasts.length > MAX_VISIBLE)
            this._dismiss(this._toasts[0].toast);
    }

    destroy() {
        for (const entry of this._toasts)
            entry.timer.stop();
        this._toasts = [];
        this.actor.destroy();
    }

    _dismiss(toast) {
        const index = this._toasts.findIndex(entry => entry.toast === toast);
        if (index === -1)
            return;
        this._toasts[index].timer.stop();
        this._toasts.splice(index, 1);
        ease(toast, {opacity: 0, translation_y: -10}, {
            ms: Motion.PANEL_MS,
            onComplete: () => toast.destroy(),
        });
    }
}

/**
 * The service half.
 *
 * Separate from the layer so components take a dependency on "somewhere to say
 * this" rather than on an actor. It also means the desktop can be constructed,
 * report a problem, and place the layer afterwards — which is the order things
 * actually happen during enable().
 */
export class NotificationService {
    constructor() {
        this._layer = null;
        this._pending = [];
    }

    attach(layer) {
        this._layer = layer;
        for (const [level, message, options] of this._pending)
            layer.push(level, message, options);
        this._pending = [];
    }

    info(message, options = {}) {
        this._push('info', message, options);
    }

    warning(message, options = {}) {
        this._push('warning', message, options);
    }

    error(message, options = {}) {
        this._push('error', message, options);
    }

    detach() {
        this._layer = null;
    }

    _push(level, message, options) {
        if (this._layer === null) {
            // Queued rather than dropped: a failure during startup is exactly
            // the one worth seeing, and it happens before the layer exists.
            this._pending.push([level, message, options]);
            log_(`notification queued (${level}): ${message}`);
            return;
        }
        this._layer.push(level, message, options);
    }
}
