// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Companion-aware login and lock chrome. GDM stays the stock Fedora greeter.
// The figure may sit in the corner; unlock still works if it is hidden or fails.

import {SCREEN_QUESTIONS} from './design/tokens.js';

export const LOCK_PASSWORD_NAME = 'Password';
export const LOGIN_PASSWORD_NAME = 'Password';
export const COMPANION_CORNER = 'bottom-right';

export const LOCK_SUMMARY = 'Unlock this computer. Bunny is optional.';
export const LOGIN_SUMMARY = 'Sign in. Bunny is optional. The desktop works without the figure.';

function companionVisible({companionHidden = false, companionFailed = false} = {}) {
    return !companionHidden && !companionFailed;
}

function redactNotices(notices = []) {
    return (Array.isArray(notices) ? notices : []).map(item => {
        const source = String(item?.source || 'Application').slice(0, 80);
        if (item?.sensitive !== false)
            return {source, title: 'Sensitive notification', body: '', actions: []};
        return {
            source,
            title: String(item?.title || 'Notification').slice(0, 160),
            body: '',
            actions: [],
        };
    });
}

export function buildLockScreen({
    user = 'you', clock = '', companionHidden = false, companionFailed = false,
    notices = [],
} = {}) {
    const visible = companionVisible({companionHidden, companionFailed});
    return {
        kind: 'LockScreen',
        title: 'Locked',
        summary: LOCK_SUMMARY,
        user: String(user || 'you'),
        clock: String(clock || ''),
        passwordAccessibleName: LOCK_PASSWORD_NAME,
        companionVisible: visible,
        companionAnchor: COMPANION_CORNER,
        companionRequired: false,
        companionFailed: Boolean(companionFailed),
        unlockWithoutCompanion: true,
        usableWithoutCompanion: true,
        trustOnLock: false,
        chatbot: false,
        gdmBranding: false,
        notifications: redactNotices(notices),
        initialFocus: 'password',
        canFocus: true,
        styleClass: 'bunny-lock-screen',
        accessibleName: 'Bunny lock screen',
        questions: SCREEN_QUESTIONS,
        next: 'Type your password and press Return. Super+L locks again after you unlock.',
    };
}

export function buildLoginScreen({
    user = '', companionHidden = false, companionFailed = false,
} = {}) {
    const visible = companionVisible({companionHidden, companionFailed});
    return {
        kind: 'LoginScreen',
        title: 'Sign in',
        summary: LOGIN_SUMMARY,
        user: String(user || ''),
        passwordAccessibleName: LOGIN_PASSWORD_NAME,
        companionVisible: visible,
        companionAnchor: COMPANION_CORNER,
        companionRequired: false,
        companionFailed: Boolean(companionFailed),
        unlockWithoutCompanion: true,
        usableWithoutCompanion: true,
        trustOnLock: false,
        chatbot: false,
        gdmBranding: false,
        stockGreeter: true,
        initialFocus: 'password',
        canFocus: true,
        styleClass: 'bunny-login-screen',
        accessibleName: 'Bunny sign-in',
        questions: SCREEN_QUESTIONS,
        next: 'Sign in with your account. Bunny waits in the corner after first-run, or stays hidden.',
    };
}
