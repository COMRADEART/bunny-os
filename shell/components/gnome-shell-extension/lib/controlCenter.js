// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Bunny Control Center modules: Bunny, AI, Privacy.
//
// Device panels still deep-link to GNOME. These three are Bunny-owned and
// reuse Phase 1 tokens. Voice is off until wanted; AI is local-first;
// cloud_context is named honestly and is not remote_dispatch.

import {SCREEN_QUESTIONS} from './design/tokens.js';
import {
    CLOUD_MEMORY_STAYS_OFF,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
} from './trustPrompt.js';

export const CONTROL_CENTER_MODULES = Object.freeze(['bunny', 'ai', 'privacy']);

const CLOUD_CONTEXT_LABELS = Object.freeze({
    none: 'Off — saved memory stays on this computer',
    minimized: 'Minimized — only current-request fields may go online after Allow once',
});

function row(id, label, value, {hint = '', control = 'label'} = {}) {
    return {
        id,
        label,
        value,
        hint,
        control,
        accessibleName: hint ? `${label}: ${value}. ${hint}` : `${label}: ${value}`,
        canFocus: control !== 'label',
    };
}

function moduleModel({id, title, summary, rows, warnings = []}) {
    return {
        kind: 'ControlCenterModule',
        id,
        title,
        summary,
        rows,
        warnings,
        questions: SCREEN_QUESTIONS,
        companionRequired: false,
        styleClass: `bunny-cc-module bunny-cc-module-${id}`,
        canFocus: true,
    };
}

export function buildBunnyModule({
    launchAtLogin = false, theme = 'system', companionHidden = false,
} = {}) {
    return moduleModel({
        id: 'bunny',
        title: 'Bunny',
        summary: 'The companion is optional. Keyboard, dock, and Search still run the OS.',
        rows: [
            row('launchBunnyAtLogin', 'Open Bunny at login', launchAtLogin ? 'On' : 'Off', {
                control: 'toggle',
            }),
            row('theme', 'Appearance', String(theme), {control: 'choice'}),
            row('companion', 'Companion', companionHidden ? 'Hidden' : 'Visible', {
                hint: 'Hiding the figure does not hide Search, Settings, or Trust.',
                control: 'toggle',
            }),
        ],
    });
}

export function buildAiModule({
    localAiEnabled = true, localOnlyMode = false, voiceEnabled = true,
    microphoneEnabled = true,
} = {}) {
    return moduleModel({
        id: 'ai',
        title: 'AI',
        summary: 'Answers start on this computer. Online generate is a separate Allow once.',
        rows: [
            row('localAiEnabled', 'Local AI', localAiEnabled ? 'On' : 'Off', {
                hint: 'Models on this machine. Nothing leaves until you allow a hop.',
                control: 'toggle',
            }),
            row('localOnlyMode', 'Local-only', localOnlyMode ? 'On' : 'Off', {
                hint: 'Refuses cloud failover. Local voice and local models stay available.',
                control: 'toggle',
            }),
            row('voiceListening', 'Voice listening', 'Off until you ask', {
                hint: 'Push-to-talk is Super+Alt+Space. Typed Search always works.',
            }),
            row('voiceEnabled', 'Spoken replies', voiceEnabled ? 'Available' : 'Off', {
                control: 'toggle',
            }),
            row('microphoneEnabled', 'Microphone permission', microphoneEnabled ? 'Allowed when you talk' : 'Blocked', {
                control: 'toggle',
            }),
        ],
        warnings: localOnlyMode
            ? ['Local-only is on. Bunny will not fail over to an online model.']
            : [],
    });
}

export function buildPrivacyModule({
    cloudContext = 'none', telemetryEnabled = false, clipboardHistory = false,
    pluginNetworkDefault = 'deny',
} = {}) {
    const cloud = CLOUD_CONTEXT_LABELS[cloudContext] ? cloudContext : 'none';
    return moduleModel({
        id: 'privacy',
        title: 'Privacy',
        summary: 'Cloud memory and a one-time online answer are two different consents.',
        rows: [
            row('cloudContext', 'Cloud memory', CLOUD_CONTEXT_LABELS[cloud], {
                hint: cloud === 'none'
                    ? CLOUD_MEMORY_STAYS_OFF
                    : 'Minimized still cannot send saved memory, session memory, or a conversation summary.',
            }),
            row('network', 'Application network', `${NETWORK_OFF} or ${NETWORK_FULL_INTERNET}`, {
                hint: NETWORK_ALLOWLIST_NOTE,
            }),
            row('pluginNetworkDefault', 'Plugin network', pluginNetworkDefault === 'deny' ? 'Deny until asked' : 'Ask', {
                control: 'choice',
            }),
            row('telemetryEnabled', 'Telemetry', telemetryEnabled ? 'On' : 'Off', {
                hint: 'Off by default. Bunny does not phone home for analytics.',
            }),
            row('clipboardHistory', 'Clipboard history', clipboardHistory ? 'On' : 'Off', {
                hint: 'Off by default. There is no cloud clipboard.',
            }),
        ],
        warnings: [
            NETWORK_ALLOWLIST_NOTE,
            cloud === 'none' ? CLOUD_MEMORY_STAYS_OFF : '',
        ].filter(Boolean),
    });
}

export function buildControlCenter(options = {}) {
    const modules = {
        bunny: buildBunnyModule(options.bunny || options),
        ai: buildAiModule(options.ai || options),
        privacy: buildPrivacyModule(options.privacy || options),
    };
    return {
        kind: 'ControlCenter',
        title: 'Control Center',
        modules: CONTROL_CENTER_MODULES.map(id => modules[id]),
        gnomeOwnsDevices: true,
        companionRequired: false,
        accessibleName: 'Bunny Control Center',
        questions: SCREEN_QUESTIONS,
    };
}
