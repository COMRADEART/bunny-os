// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Bunny Files: companion-aware file flows. Trust for opens. Bubbles, not a
// chatbot wall. This is the host-testable twin of bunny_files.py.
//
// Nautilus remains the file browser. This module is the Bunny overlay:
// Ask / Summarise / Workspace / Provenance / Checkpoint / Open. Open is a
// Trust question (Allow once / Don't allow, Don't allow focused). Nothing
// here uploads a file.

import {
    buildBubble, buildList, buildSearchField, buildSheet, limitBubbleText,
} from './design/primitives.js';
import {SCREEN_QUESTIONS} from './design/tokens.js';
import {
    ALLOW_ONCE_LABEL, DONT_ALLOW_LABEL, FILE_NOT_UPLOADED, FILE_OPEN_BUBBLE,
    FILE_OPEN_DENIED, FILE_OPEN_FAILED, FILE_OPEN_GRANTED, FILE_OPEN_HEADLINE,
    NETWORK_ALLOWLIST_NOTE, buildPrompt,
} from './trustPrompt.js';
import {routeCommandAnswer} from './commandSurface.js';

export {
    FILE_NOT_UPLOADED, FILE_OPEN_BUBBLE, FILE_OPEN_DENIED, FILE_OPEN_FAILED,
    FILE_OPEN_GRANTED, FILE_OPEN_HEADLINE,
};

export const FILE_ACTIONS = Object.freeze([
    'ask', 'summarise', 'workspace', 'provenance', 'checkpoint', 'open',
]);

export const FILE_ACTION_LABELS = Object.freeze({
    ask: 'Ask Bunny about this file',
    summarise: 'Summarise with Bunny',
    workspace: 'Open in Bunny workspace',
    provenance: 'Show provenance',
    checkpoint: 'Create checkpoint before changes',
    open: 'Open',
});

const BUBBLE_ACTIONS = new Set(['ask', 'provenance']);
const TASK_ACTIONS = new Set(['summarise', 'workspace', 'checkpoint']);

function fileName(path) {
    const raw = String(path || '').replace(/^file:\/\//, '').trim();
    if (!raw)
        return '';
    const parts = raw.split('/').filter(Boolean);
    return parts[parts.length - 1] || raw;
}

function decodeSelection(value) {
    const raw = String(value ?? '');
    if (!raw)
        return [];
    try {
        return decodeURIComponent(raw)
            .split('\n')
            .map(item => item.trim())
            .filter(Boolean);
    } catch {
        return raw.split('\n').map(item => item.trim()).filter(Boolean);
    }
}

/**
 * Parse a Nautilus handoff `bunny://files/{action}?selection=...`.
 */
export function parseFilesUri(uri) {
    const text = String(uri || '').trim();
    const match = /^bunny:\/\/files\/([a-z]+)(?:\?selection=([^#]*))?$/i.exec(text);
    if (!match)
        return {valid: false, action: '', paths: [], companionRequired: false};
    const action = match[1].toLowerCase();
    return {
        valid: FILE_ACTIONS.includes(action),
        action: FILE_ACTIONS.includes(action) ? action : '',
        paths: decodeSelection(match[2] || ''),
        companionRequired: false,
        chatbot: false,
    };
}

/**
 * Opening a file in an application is always a Trust question.
 *
 * Browse of an already-approved location is not. Ask/summarise stay local
 * unless the caller is offering a remote hop — then the existing
 * remote_dispatch disclosure applies.
 */
export function fileOpenNeedsTrust({action = 'open', approvedLocation = false} = {}) {
    if (String(action) === 'open')
        return true;
    if (String(action) === 'checkpoint')
        return true;
    return !approvedLocation && String(action) === 'workspace';
}

/**
 * The exact file Trust granted. Not a folder walk, not Pictures.
 */
export function grantedFilePath(path) {
    let raw = String(path || '').trim();
    if (!raw || raw.includes('\n') || raw.includes('\0'))
        return '';
    if (/[;|`]|\$\(/.test(raw))
        return '';
    if (raw.toLowerCase().startsWith('file://')) {
        let rest = raw.slice(7);
        try {
            rest = decodeURIComponent(rest);
        } catch {
            return '';
        }
        if (!rest)
            return '';
        raw = rest.startsWith('/') ? rest : `/${rest}`;
    }
    if (!raw.startsWith('/'))
        return '';
    return raw;
}

function isOnceGrant(decision) {
    const token = String(decision || '').trim().toLowerCase();
    return token === 'allow' || token === 'allow-once' || token === 'allow once'
        || token === 'once' || token === 'granted';
}

/**
 * Plan the open. Deny-by-default. One path. Nothing uploaded.
 */
export function resolveFileOpenAfterTrust({
    decision = 'deny', path = '', action = 'open', extraPaths = [],
} = {}) {
    void extraPaths; // never widened — Pictures and siblings stay closed
    const granted = grantedFilePath(path);
    const once = isOnceGrant(decision);
    if (String(action || 'open') !== 'open') {
        return {
            shouldOpen: false,
            uploaded: false,
            path: '',
            command: null,
            companionRequired: false,
            chatbot: false,
            note: FILE_NOT_UPLOADED,
            message: once ? 'Allow once is recorded for this request.' : FILE_OPEN_DENIED,
        };
    }
    if (!once || !granted) {
        return {
            shouldOpen: false,
            uploaded: false,
            path: '',
            command: null,
            companionRequired: false,
            chatbot: false,
            note: FILE_NOT_UPLOADED,
            message: !once ? FILE_OPEN_DENIED : FILE_OPEN_FAILED,
        };
    }
    return {
        shouldOpen: true,
        uploaded: false,
        path: granted,
        command: ['gio', 'open', granted],
        companionRequired: false,
        chatbot: false,
        note: FILE_NOT_UPLOADED,
        message: FILE_OPEN_GRANTED,
    };
}

/**
 * Grant opens that file. Deny opens nothing. Host-testable via `opener`.
 */
export function applyFileOpenAfterTrust(record = {}, opener = null) {
    const plan = resolveFileOpenAfterTrust(record);
    if (!plan.shouldOpen)
        return {...plan, launched: false, paths: []};
    let launched = false;
    if (typeof opener === 'function') {
        try {
            launched = opener(plan.command, plan.path) === true;
        } catch {
            launched = false;
        }
    }
    return {
        ...plan,
        launched,
        paths: launched ? [plan.path] : [],
        message: launched ? FILE_OPEN_GRANTED : FILE_OPEN_FAILED,
    };
}

export function buildFileOpenTrust({
    path = '', application = 'an application', requestId = 'file-open',
    cloudContext = 'none', offeringRemoteDispatch = false, network = 'Off',
} = {}) {
    const name = fileName(path) || 'this file';
    const heading = application
        ? `Bunny wants to open ${name} in ${application}`
        : FILE_OPEN_HEADLINE;
    const record = {
        requestId,
        headline: heading,
        category: 'files',
        categoryTitle: 'Files',
        resource: String(path || name),
        capabilityNote: 'Open this file in that application for this request only.',
        reason: FILE_NOT_UPLOADED,
        options: [{scope: 'once', label: ALLOW_ONCE_LABEL}],
        denyOption: {label: DONT_ALLOW_LABEL},
        risk: 'medium',
        cloudContext,
        offeringRemoteDispatch,
        fileAccess: String(path || name),
        network,
    };
    const prompt = buildPrompt(record);
    prompt.bubble = buildBubble({
        text: FILE_OPEN_BUBBLE,
        actions: [
            {id: 'review', label: 'Review the request'},
        ],
    });
    prompt.chatbot = false;
    prompt.transcript = false;
    prompt.companionRequired = false;
    prompt.focusSafeAnswer = true;
    return prompt;
}

function captionFor(action, paths) {
    const count = paths.length;
    const first = fileName(paths[0]) || 'this file';
    if (action === 'ask')
        return count > 1
            ? `Ask Bunny about ${count} files. Nothing is uploaded.`
            : `Ask Bunny about ${first}. Nothing is uploaded.`;
    if (action === 'summarise')
        return `Summarise ${first} here. Longer notes open a task card.`;
    if (action === 'workspace')
        return `Attach ${first} to a Bunny workspace. Files stay on this computer.`;
    if (action === 'provenance')
        return `Provenance for ${first}.`;
    if (action === 'checkpoint')
        return `Checkpoint before changing ${first}.`;
    return `Open ${first}. Review the request.`;
}

/**
 * Route one Files action. Short copy stays in the bubble. Opens go through
 * Trust. This is not a chat transcript.
 */
export function routeFilesAction({
    action = 'ask', paths = [], application = '', approvedLocation = true,
    cloudContext = 'none', offeringRemoteDispatch = false,
} = {}) {
    const resolved = FILE_ACTIONS.includes(action) ? action : 'ask';
    const list = Array.isArray(paths) ? paths.map(item => String(item)).filter(Boolean) : [];
    const needsTrust = fileOpenNeedsTrust({action: resolved, approvedLocation});
    const caption = limitBubbleText(captionFor(resolved, list));
    const routed = routeCommandAnswer(caption, {
        working: TASK_ACTIONS.has(resolved),
        title: FILE_ACTION_LABELS[resolved],
    });
    const surface = needsTrust ? 'trust' : (BUBBLE_ACTIONS.has(resolved) ? 'bubble' : routed.surface);
    return {
        action: resolved,
        paths: list,
        surface,
        needsTrust,
        bubble: buildBubble({text: needsTrust ? FILE_OPEN_BUBBLE : caption}),
        trust: needsTrust
            ? buildFileOpenTrust({
                path: list[0] || '',
                application,
                cloudContext,
                offeringRemoteDispatch,
            })
            : null,
        taskCard: surface === 'task-card' ? routed.taskCard : null,
        transcript: false,
        chatbot: false,
        companionRequired: false,
        uploaded: false,
        note: FILE_NOT_UPLOADED,
    };
}

/**
 * The Bunny Files overlay: a sheet of approved locations, a search field,
 * and companion actions. Not a chatbot. Companion is optional.
 */
export function buildBunnyFiles({
    locations = [], entries = [], query = '', reducedMotion = false,
} = {}) {
    const rows = (Array.isArray(entries) ? entries : []).slice(0, 40).map((entry, index) => {
        const item = entry && typeof entry === 'object' ? entry : {path: entry};
        const path = String(item.path || item.uri || '');
        return {
            id: `file-${index}`,
            title: item.name || fileName(path) || path,
            subtitle: path,
            kind: item.kind || 'file',
            path,
            accessibleName: `${item.name || fileName(path) || 'File'}. ${item.kind || 'file'}`,
            canFocus: true,
        };
    });
    const places = (Array.isArray(locations) ? locations : []).map(item => {
        const rec = item && typeof item === 'object' ? item : {path: item};
        return {
            path: String(rec.path || ''),
            enabled: rec.enabled !== false,
        };
    });
    return {
        kind: 'BunnyFiles',
        title: 'Bunny Files',
        summary: 'Approved folders and companion actions. Nautilus still browses. Opens need Trust.',
        field: buildSearchField({
            value: query,
            placeholder: 'Find a file in approved folders',
        }),
        sheet: buildSheet({
            title: 'Files',
            actions: FILE_ACTIONS.map(id => ({
                id,
                label: FILE_ACTION_LABELS[id],
                variant: id === 'open' ? 'primary' : 'secondary',
                accessibleName: FILE_ACTION_LABELS[id],
            })),
        }),
        list: buildList({rows}),
        locations: places,
        actions: FILE_ACTIONS.slice(),
        questions: SCREEN_QUESTIONS,
        doing: 'Browsing approved files',
        bunny: 'Ready to ask or open with Trust',
        next: 'Select a file. Open asks Allow once or Don\'t allow.',
        companionRequired: false,
        chatbot: false,
        transcript: false,
        nautilusIsBrowser: true,
        uploaded: false,
        note: FILE_NOT_UPLOADED,
        networkHonesty: NETWORK_ALLOWLIST_NOTE,
        reducedMotion: Boolean(reducedMotion),
        motionMs: reducedMotion ? 0 : 220,
        accessibleName: 'Bunny Files',
        canFocus: true,
        styleClass: 'bunny-files bunny-sheet',
    };
}
