// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Notification center: quiet defaults, optional Bunny summary, no spam.
// GNOME still owns freedesktop delivery. This is Bunny's own tray plus a
// bounded history the GTK surface can also render.

import {buildNotification} from './design/primitives.js';
import {SCREEN_QUESTIONS} from './design/tokens.js';

export const NOTIFICATION_QUIET_DEFAULTS = Object.freeze({
    quiet: true,
    maxVisibleToasts: 3,
    maxHistory: 50,
    collapseWindowMs: 8000,
    bunnySummary: true,
    sensitiveDefault: true,
});

function keyFor(item) {
    return `${String(item.source || 'Bunny')}\n${String(item.title || item.body || '')}`;
}

/**
 * Collapse repeats and info-level chatter. Errors still get their own row.
 */
export function foldNotifications(items, {
    quiet = true, bunnySummary = true, now = 0,
} = {}) {
    const rows = Array.isArray(items) ? items : [];
    const kept = [];
    const seen = new Map();
    for (const raw of rows) {
        if (!raw || typeof raw !== 'object')
            continue;
        const severity = String(raw.severity || 'info');
        const source = String(raw.source || 'Bunny');
        const title = String(raw.title || raw.body || 'Notification');
        const body = String(raw.body || '');
        const stamp = Number(raw.at || now) || 0;
        const key = keyFor({source, title});
        if (quiet && severity === 'info') {
            const previous = seen.get(key);
            if (previous !== undefined && stamp - previous <= NOTIFICATION_QUIET_DEFAULTS.collapseWindowMs) {
                const last = kept[kept.length - 1];
                if (last && keyFor(last) === key) {
                    last.count = (last.count || 1) + 1;
                    last.body = bunnySummary && source === 'Bunny'
                        ? `${title} (${last.count})`
                        : last.body;
                    continue;
                }
            }
            seen.set(key, stamp);
        }
        kept.push({
            source,
            title,
            body,
            severity,
            at: stamp,
            count: 1,
            sensitive: raw.sensitive !== false,
        });
    }
    return kept;
}

export function summarizeBunny(items) {
    const bunny = (Array.isArray(items) ? items : []).filter(
        item => String(item?.source || 'Bunny') === 'Bunny');
    if (bunny.length <= 1)
        return bunny[0] ? buildNotification({
            title: bunny[0].title, body: bunny[0].body, severity: bunny[0].severity || 'info',
        }) : null;
    const errors = bunny.filter(item => item.severity === 'error').length;
    const title = errors
        ? `Bunny: ${bunny.length} updates, ${errors} need attention`
        : `Bunny: ${bunny.length} updates`;
    return buildNotification({
        title,
        body: 'Open the notification center for the rest. Bunny will not ping for each step.',
        severity: errors ? 'warning' : 'info',
    });
}

export function buildNotificationCenter({
    items = [], quiet = true, bunnySummary = true, doNotDisturb = false,
} = {}) {
    const folded = doNotDisturb ? [] : foldNotifications(items, {quiet, bunnySummary});
    const summary = bunnySummary ? summarizeBunny(folded) : null;
    const visible = folded.slice(-NOTIFICATION_QUIET_DEFAULTS.maxHistory);
    return {
        kind: 'NotificationCenter',
        quiet,
        bunnySummary,
        doNotDisturb: Boolean(doNotDisturb),
        maxVisibleToasts: NOTIFICATION_QUIET_DEFAULTS.maxVisibleToasts,
        summary,
        items: visible.map(item => buildNotification({
            title: item.count > 1 ? `${item.title} (${item.count})` : item.title,
            body: item.body,
            severity: item.severity,
        })),
        emptyCopy: doNotDisturb
            ? 'Do Not Disturb is on. Bunny is not showing notices.'
            : 'No notices. Bunny stays quiet unless something needs you.',
        spam: false,
        companionRequired: false,
        questions: SCREEN_QUESTIONS,
        accessibleName: 'Notification center',
        styleClass: 'bunny-notification-center',
        canFocus: true,
    };
}

/**
 * Whether a live toast should appear. Quiet defaults drop duplicate info.
 */
export function shouldToast(level, message, recent = [], {quiet = true, now = Date.now()} = {}) {
    if (!quiet)
        return true;
    if (level === 'error' || level === 'warning')
        return true;
    const text = String(message ?? '');
    return !recent.some(entry =>
        entry.level === 'info'
        && entry.message === text
        && now - Number(entry.at || 0) < NOTIFICATION_QUIET_DEFAULTS.collapseWindowMs);
}
