// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Bunny-owned Settings pages. AI chrome reuses Phase 2 Control Center.
// Personality is presentation only.

import {SCREEN_QUESTIONS} from './design/tokens.js';
import {NO_ONLINE_MODELS_IS_LOCAL_ONLY} from './trustPrompt.js';
import {
    ADVANCED_TITLE,
    AI_MODE_LABELS,
    buildAiModule,
    buildPrivacyModule,
    resolveAiMode,
} from './controlCenter.js';

export const PERSONALITY_CHOICES = Object.freeze(['bunny', 'focused', 'playful']);
export const PERSONALITY_LABELS = Object.freeze({
    bunny: 'Bunny — warm and calm',
    focused: 'Focused — shorter answers',
    playful: 'Playful — lighter tone',
});
export const PERSONALITY_FORBIDDEN = Object.freeze([
    'openai', 'anthropic', 'claude', 'gpt', 'chatgpt', 'gemini', 'llama',
    'mistral', 'grok', 'copilot', 'siri', 'alexa', 'bard', 'chatgpt4',
]);
export const PROACTIVITY_CHOICES = Object.freeze(['off', 'gentle']);
export const PROACTIVITY_LABELS = Object.freeze({
    off: 'Off — wait until asked',
    gentle: 'Gentle — may offer, never act',
});

const ANIMATION_LABELS = Object.freeze({full: 'Full', reduced: 'Reduced', none: 'None'});

export function normalisePersonality(value) {
    const token = String(value || 'bunny').trim().toLowerCase().replace(/\s+/g, '');
    if (PERSONALITY_FORBIDDEN.includes(token))
        return 'bunny';
    if (PERSONALITY_CHOICES.includes(token))
        return token;
    return 'bunny';
}

export function normaliseProactivity(value) {
    const token = String(value || 'off').trim().toLowerCase();
    return PROACTIVITY_CHOICES.includes(token) ? token : 'off';
}

export function personalityMayNotRoute(value) {
    const token = String(value || 'bunny').trim().toLowerCase().replace(/\s+/g, '');
    return !PERSONALITY_FORBIDDEN.includes(token);
}

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

export function buildBunnyCompanionModule({
    launchAtLogin = false, theme = 'system', companionHidden = false,
    personality = 'bunny', proactivity = 'off', dock = 'bottom-right',
    scale = 1, animationIntensity = 1, animation = 'full',
    contextualReactions = true, visible = true, companionMode = 'full',
    voiceEnabled = true, packageId = 'Bunny', aiMode = 'automatic',
    localOnlyMode = false,
} = {}) {
    const person = normalisePersonality(personality);
    const offer = normaliseProactivity(proactivity);
    const shown = companionHidden ? false : Boolean(visible);
    const intensity = Number(animationIntensity);
    const intensityPct = Number.isFinite(intensity)
        ? (intensity <= 1 ? Math.round(intensity * 100) : Math.round(intensity))
        : 100;
    const scaleNumber = Number(scale);
    const scaleLabel = Number.isFinite(scaleNumber) ? `${scaleNumber}×` : '1×';
    const mode = resolveAiMode({localOnlyMode, aiMode});
    return moduleModel({
        id: 'bunny',
        title: 'Bunny',
        summary: 'How Bunny looks and behaves. Hide the figure and the OS still works.',
        rows: [
            row('visible', 'Companion', shown ? 'Visible' : 'Hidden', {
                hint: 'Hiding the figure does not hide Search, Settings, or Trust.',
                control: 'toggle',
            }),
            row('character', 'Character', String(packageId || 'Bunny'), {
                hint: 'One character. A missing 3D asset falls back to the vector.',
            }),
            row('personality', 'Personality', PERSONALITY_LABELS[person], {
                hint: 'Tone only. Personality cannot pick a model, a provider, or a permission.',
                control: 'choice',
            }),
            row('voiceEnabled', 'Voice', voiceEnabled ? 'Spoken replies' : 'Off', {
                hint: 'Off until you want them. Push-to-talk is Super+Alt+Space. Typed Search always works.',
                control: 'toggle',
            }),
            row('animation', 'Animation', ANIMATION_LABELS[animation] || 'Full', {control: 'choice'}),
            row('animationIntensity', 'Animation intensity', `${Math.max(0, Math.min(100, intensityPct))}%`, {
                hint: 'How far poses travel. Expression stays readable at 0%.',
                control: 'slider',
            }),
            row('dock', 'Position', String(dock || 'bottom-right').replace(/-/g, ' '), {
                hint: 'Named corners, not pixel coordinates. Default is bottom right.',
                control: 'choice',
            }),
            row('scale', 'Size', `${companionMode} · ${scaleLabel}`, {
                hint: 'Full, compact, or minimal chrome. Scale is 0.5× to 3×.',
                control: 'choice',
            }),
            row('interaction', 'Interaction', contextualReactions ? 'Reacts to pointer and ambient events' : 'Still', {
                control: 'toggle',
            }),
            row('proactivity', 'Proactivity', PROACTIVITY_LABELS[offer], {
                hint: 'Gentle may offer. It never acts, never grants, and never goes online by itself.',
                control: 'choice',
            }),
            row('memory', 'Memory', 'Working only until you turn more on', {
                hint: 'Session, durable, and cloud memory stay in Privacy. Defaults are off.',
            }),
            row('aiMode', 'Local / online AI', AI_MODE_LABELS[mode], {
                hint: 'Open AI & Models to change this. No online models ever is Local only.',
            }),
            row('privacy', 'Privacy', 'Two consents', {
                hint: 'Cloud memory is not Online for this request. Open Privacy to change either.',
            }),
        ],
        warnings: [
            'Personality is presentation. It cannot change routing or permissions.',
            NO_ONLINE_MODELS_IS_LOCAL_ONLY,
        ],
    });
}

export function buildAiModelsModule(options = {}) {
    const module = buildAiModule(options);
    return {
        ...module,
        id: 'ai-models',
        title: 'AI & Models',
        styleClass: 'bunny-cc-module bunny-cc-module-ai-models',
    };
}

export function buildSettingsPrivacyModule(options = {}) {
    const module = buildPrivacyModule(options);
    return {
        ...module,
        rows: [
            ...module.rows,
            row('localMemory', 'Memory on this computer', 'Working only', {
                hint: 'Session and durable memory stay off until you turn them on. Cloud memory is a separate consent.',
            }),
        ],
        warnings: [...module.warnings, NO_ONLINE_MODELS_IS_LOCAL_ONLY],
    };
}

export function buildBunnySettingsPages(options = {}) {
    return {
        bunny: buildBunnyCompanionModule(options.bunny || options),
        'ai-models': buildAiModelsModule(options.ai || options),
        privacy: buildSettingsPrivacyModule(options.privacy || options),
    };
}
