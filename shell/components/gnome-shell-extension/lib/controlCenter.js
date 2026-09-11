// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Bunny Control Center modules: Bunny, AI, Privacy.
//
// Device panels still deep-link to GNOME. These three are Bunny-owned and
// reuse Phase 1 tokens. Voice is off until wanted; AI is one local-first
// control (Automatic / Local only / Online enhanced); cloud_context is
// named honestly and is not remote_dispatch.

import {SCREEN_QUESTIONS} from './design/tokens.js';
import {
    ALLOWLISTED_CEILING_NOTE,
    CLIPBOARD_BLUETOOTH_NOTE,
    CLOUD_MEMORY_IS_OFF,
    CLOUD_MEMORY_STAYS_OFF,
    NETWORK_ALLOWLIST_NOTE,
    NETWORK_FULL_INTERNET,
    NETWORK_OFF,
} from './trustPrompt.js';

/** One AI control. Never High/Ultra. Default is Automatic (local-first). */
export const AI_MODES = Object.freeze(['automatic', 'local-only', 'online-enhanced']);
export const AI_MODE_LABELS = Object.freeze({
    automatic: 'Automatic',
    'local-only': 'Local only',
    'online-enhanced': 'Online enhanced',
});
export const AI_MODE_HINTS = Object.freeze({
    automatic:
        'Picks a local model from measured resources on this computer. '
        + 'Bunny does not go online because local is slower. An online answer still '
        + 'needs Allow once for this request.',
    'local-only':
        'Refuses hosted providers. Bunny will not show a Trust prompt to generate '
        + 'online. Typed Search still works.',
    'online-enhanced':
        'Still starts locally. Online generate is offered only when the router would '
        + 'escalate, and only after Allow once for this request — not always cloud.',
});

export function resolveAiMode({localOnlyMode = false, aiMode = 'automatic'} = {}) {
    if (localOnlyMode)
        return 'local-only';
    const mode = String(aiMode || 'automatic').trim().toLowerCase();
    if (mode === 'online-enhanced')
        return 'online-enhanced';
    if (mode === 'local-only')
        return 'local-only';
    return 'automatic';
}

export const ADVANCED_TITLE = 'Advanced';
export const THROUGHPUT_NOT_MEASURED = 'Not measured';
export const ACCELERATOR_UNKNOWN = 'Unknown';
export const ACCELERATOR_ABSENT = 'Absent';
export const ACCELERATOR_UNUSABLE = 'Unusable';
export const MODEL_UNKNOWN = 'Unknown';
export const WHY_THIS_MODEL_UNAVAILABLE = 'Not available';
export const CONVERSATION_SUMMARY_UNWIRED = 'Unwired';

const ACCELERATOR_LABELS = Object.freeze({
    unknown: ACCELERATOR_UNKNOWN,
    absent: ACCELERATOR_ABSENT,
    none: ACCELERATOR_ABSENT,
    unusable: ACCELERATOR_UNUSABLE,
    'present-unusable': ACCELERATOR_UNUSABLE,
    'not-usable': ACCELERATOR_UNUSABLE,
});

export function acceleratorFacingLabel(value) {
    const token = String(value ?? 'unknown').trim().toLowerCase().replace(/_/g, '-');
    return ACCELERATOR_LABELS[token] || ACCELERATOR_UNKNOWN;
}

export function throughputFacingLabel(value) {
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0)
        return Number.isInteger(value) ? `${value} tok/s` : `${value} tok/s`;
    return THROUGHPUT_NOT_MEASURED;
}

export function modelFacingLabel(value) {
    const text = String(value ?? '').trim();
    if (!text)
        return MODEL_UNKNOWN;
    const lower = text.toLowerCase();
    if (lower === 'automatic' || lower === 'unknown' || lower === 'none')
        return MODEL_UNKNOWN;
    return text;
}

export function whyThisModelLabel(value) {
    const text = String(value ?? '').trim();
    return text || WHY_THIS_MODEL_UNAVAILABLE;
}

function aiAdvancedRows({
    modelId = '', adapter = '', tokensPerSecond = null,
    gpu = 'unknown', vram = 'unknown', npu = 'unknown', whyThisModel = '',
} = {}) {
    return [
        row('modelId', 'Model', modelFacingLabel(modelId || adapter)),
        row('adapter', 'Adapter', modelFacingLabel(adapter)),
        row('throughput', 'Throughput', throughputFacingLabel(tokensPerSecond)),
        row('gpu', 'GPU', acceleratorFacingLabel(gpu)),
        row('vram', 'VRAM', acceleratorFacingLabel(vram)),
        row('npu', 'NPU', acceleratorFacingLabel(npu)),
        row('whyThisModel', 'Why this model', whyThisModelLabel(whyThisModel)),
    ];
}

function privacyAdvancedRows() {
    return [
        row('cloudContextSession', 'Session memory online', 'Off', {
            hint: 'cloud_context does not send session memory online.',
        }),
        row('cloudContextDurable', 'Durable memory online', 'Off', {
            hint: 'Durable memory is never dumped online.',
        }),
        row('conversationSummary', 'Conversation summary', CONVERSATION_SUMMARY_UNWIRED, {
            hint: 'Conversation summary is not wired.',
        }),
    ];
}

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

function moduleModel({id, title, summary, rows, warnings = [], advanced = []}) {
    return {
        kind: 'ControlCenterModule',
        id,
        title,
        summary,
        rows,
        warnings,
        advanced,
        advancedTitle: advanced.length ? ADVANCED_TITLE : '',
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
    localOnlyMode = false, aiMode = 'automatic', voiceEnabled = true,
    microphoneEnabled = true,
    modelId = '', adapter = '', tokensPerSecond = null,
    gpu = 'unknown', vram = 'unknown', npu = 'unknown', whyThisModel = '',
} = {}) {
    const mode = resolveAiMode({localOnlyMode, aiMode});
    const warnings = {
        automatic: [
            'Automatic never goes online just because a local model is slower.',
        ],
        'local-only': [
            'Local only refuses hosted providers. Bunny will not ask to generate online.',
        ],
        'online-enhanced': [
            'Online enhanced is still local-first. Cloud generate needs Allow once for this request — not always cloud.',
        ],
    }[mode];
    return moduleModel({
        id: 'ai',
        title: 'AI',
        summary: 'One control. Automatic is the default. Answers start on this computer.',
        rows: [
            row('aiMode', 'AI mode', AI_MODE_LABELS[mode], {
                hint: AI_MODE_HINTS[mode],
                control: 'choice',
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
        warnings,
        advanced: aiAdvancedRows({
            modelId, adapter, tokensPerSecond, gpu, vram, npu, whyThisModel,
        }),
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
                    ? CLOUD_MEMORY_IS_OFF
                    : 'Minimized still cannot send saved memory, session memory, or a conversation summary.',
            }),
            row('remoteDispatch', 'Online for this request', 'Allow once each time', {
                hint: CLOUD_MEMORY_STAYS_OFF,
            }),
            row('network', 'Application network', `${NETWORK_OFF} or ${NETWORK_FULL_INTERNET}`, {
                hint: NETWORK_ALLOWLIST_NOTE,
            }),
            row('appClipboard', 'App clipboard', 'Not mediated', {
                hint: CLIPBOARD_BLUETOOTH_NOTE,
            }),
            row('appBluetooth', 'App Bluetooth', 'Not mediated', {
                hint: CLIPBOARD_BLUETOOTH_NOTE,
            }),
            row('pluginNetworkDefault', 'Plugin network', pluginNetworkDefault === 'deny' ? 'Deny until asked' : 'Ask', {
                control: 'choice',
            }),
            row('telemetryEnabled', 'Telemetry', telemetryEnabled ? 'On' : 'Off', {
                hint: 'Off by default. Bunny does not phone home for analytics.',
            }),
            row('clipboardHistory', 'Clipboard history', clipboardHistory ? 'On' : 'Off', {
                hint: 'Off by default. There is no cloud clipboard. This is not application clipboard access.',
            }),
        ],
        warnings: [
            NETWORK_ALLOWLIST_NOTE,
            ALLOWLISTED_CEILING_NOTE,
            CLIPBOARD_BLUETOOTH_NOTE,
            cloud === 'none' ? CLOUD_MEMORY_IS_OFF : '',
            CLOUD_MEMORY_STAYS_OFF,
        ].filter(Boolean),
        advanced: privacyAdvancedRows(),
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
