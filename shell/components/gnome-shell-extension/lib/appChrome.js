// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Remaining in-tree app chrome: Terminal, Software store, Updates.
// Same tokens/primitives as P1–P3. Companion is optional. Not IMAGE/BOOT.

import {buildSearchField, buildSheet} from './design/primitives.js';
import {SCREEN_QUESTIONS} from './design/tokens.js';
import {NETWORK_ALLOWLIST_NOTE} from './trustPrompt.js';

export const IN_TREE_APPS = Object.freeze(['terminal', 'software', 'updates']);

function chrome({id, title, summary, next, rows = [], warnings = [], reducedMotion = false}) {
    return {
        kind: 'AppChrome',
        id,
        title,
        summary,
        next,
        rows,
        warnings,
        questions: SCREEN_QUESTIONS,
        companionRequired: false,
        chatbot: false,
        transcript: false,
        reducedMotion: Boolean(reducedMotion),
        motionMs: reducedMotion ? 0 : 220,
        accessibleName: title,
        canFocus: true,
        styleClass: `bunny-app-chrome bunny-app-chrome-${id} bunny-sheet`,
        sheet: buildSheet({title}),
    };
}

/**
 * Terminal chrome around the existing command classifier.
 *
 * Live spawn remains gnome-terminal. This is the Bunny overlay: classification,
 * Trust for anything that is not read-only, no chatbot wall.
 */
export function buildTerminalChrome({
    command = '', classification = 'read_only', reducedMotion = false,
} = {}) {
    const risk = String(classification || 'read_only');
    const needsTrust = risk !== 'read_only';
    return chrome({
        id: 'terminal',
        title: 'Terminal',
        summary: 'A command field with Bunny classification. The companion is not required.',
        next: needsTrust
            ? 'This command needs Trust. Allow once or Don\'t allow. Don\'t allow is focused.'
            : 'Read-only. Run, or type another command.',
        rows: [
            {id: 'command', label: 'Command', value: String(command || ''), control: 'field'},
            {id: 'classification', label: 'Classification', value: risk.replace(/_/g, ' ')},
            {id: 'trust', label: 'Trust', value: needsTrust ? 'Required' : 'Not required'},
        ],
        warnings: needsTrust
            ? ['Non-read-only commands go through Trust. Bunny does not run them itself.']
            : [],
        reducedMotion,
    });
}

export function terminalField() {
    return buildSearchField({placeholder: 'Command'});
}

/**
 * Software store chrome. Bunny does not vendor a store; GNOME Software is
 * launched when installed. Honesty if it is missing.
 */
export function buildSoftwareChrome({
    installed = false, reducedMotion = false,
} = {}) {
    return chrome({
        id: 'software',
        title: 'Software',
        summary: installed
            ? 'Opens GNOME Software. Bunny does not vendor a second store.'
            : 'The software store is not installed on this system.',
        next: installed
            ? 'Install or remove applications in GNOME Software. Bunny permissions stay in Trust.'
            : 'Install GNOME Software, or use the package tools this image already has.',
        rows: [
            {id: 'backend', label: 'Store', value: installed ? 'GNOME Software' : 'Not installed'},
            {id: 'bunnyOwned', label: 'Bunny-owned store', value: 'No'},
        ],
        warnings: [
            'Application network still needs Trust. Site allowlists are not available.',
            NETWORK_ALLOWLIST_NOTE,
        ],
        reducedMotion,
    });
}

/**
 * Updates chrome for the in-tree Settings → System → Updates row.
 *
 * OS image updates stay separate from Bunny application updates and need
 * broker authorization. This page does not claim IMAGE, BOOT, or PASS.
 */
export function buildUpdatesChrome({
    osStatus = 'Not measured', bunnyStatus = 'Not measured', reducedMotion = false,
} = {}) {
    return chrome({
        id: 'updates',
        title: 'Updates',
        summary: 'OS image updates stay separate from Bunny application updates.',
        next: 'Inspect status. Applying an OS image needs broker authorization. Not a boot claim.',
        rows: [
            {id: 'os', label: 'OS image', value: String(osStatus || 'Not measured')},
            {id: 'bunny', label: 'Bunny applications', value: String(bunnyStatus || 'Not measured')},
            {id: 'broker', label: 'Broker', value: 'Required for OS image apply'},
        ],
        warnings: [
            'This chrome does not claim IMAGE, BOOT, or PASS.',
            'Status strings are host-visible copy, not a booted measurement.',
        ],
        reducedMotion,
    });
}

export function buildAppChrome(id, options = {}) {
    if (id === 'terminal')
        return buildTerminalChrome(options);
    if (id === 'software')
        return buildSoftwareChrome(options);
    if (id === 'updates')
        return buildUpdatesChrome(options);
    return buildSoftwareChrome({...options, installed: false});
}
