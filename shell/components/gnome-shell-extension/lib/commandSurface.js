// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Universal command surface: Super+Space, character click, or the search
// field. Short answers stay in the companion bubble. Longer work opens a
// task card. This is not a chatbot transcript.

import {buildBubble, buildSearchField, buildTaskCard, limitBubbleText} from './design/primitives.js';
import {SCREEN_QUESTIONS} from './design/tokens.js';

/** How the surface is opened. Keyboard remains sufficient without the figure. */
export const COMMAND_TRIGGERS = Object.freeze([
    'super-space', 'character-click', 'search-entry',
]);

/** Super+Space in the GSettings schema (`open-launcher`). */
export const COMMAND_ACCELERATOR = '<Super>space';

const BUBBLE_CHAR_LIMIT = 220;

function sentenceCount(value) {
    const raw = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (!raw)
        return 0;
    return raw.split(/(?<=[.!?])\s+/).filter(Boolean).length;
}

/**
 * Where an answer should land. Captions stay in the bubble; work does not
 * accumulate as a chat log.
 */
export function routeCommandAnswer(text, {
    working = false, stages = [], title = '',
} = {}) {
    const original = String(text ?? '').replace(/\s+/g, ' ').trim();
    const bubbleText = limitBubbleText(original);
    const namedStages = Array.isArray(stages)
        ? stages.filter(item => typeof item === 'string' && item.trim())
        : [];
    const long = Boolean(working)
        || namedStages.length > 0
        || sentenceCount(original) > 3
        || original.length > BUBBLE_CHAR_LIMIT;
    const surface = long ? 'task-card' : 'bubble';
    return {
        surface,
        bubble: buildBubble({text: bubbleText || original}),
        taskCard: surface === 'task-card'
            ? buildTaskCard({
                title: title || 'Working',
                caption: bubbleText || original,
                stages: namedStages.length ? namedStages : ['Plan', 'Run', 'Done'],
                stageIndex: working ? 1 : 2,
            })
            : null,
        transcript: false,
        companionRequired: false,
    };
}

/**
 * The empty command surface: a search field, not a thread.
 *
 * `companionRequired` is always false: Super+Space and the search field still
 * work when the figure is hidden.
 */
export function buildCommandSurface({
    trigger = 'search-entry', query = '', open = true,
} = {}) {
    const resolved = COMMAND_TRIGGERS.includes(trigger) ? trigger : 'search-entry';
    return {
        kind: 'CommandSurface',
        trigger: resolved,
        accelerator: COMMAND_ACCELERATOR,
        query: String(query ?? ''),
        open: Boolean(open),
        field: buildSearchField({
            value: query,
            placeholder: 'Search or ask Bunny',
        }),
        accessibleName: 'Search or ask Bunny',
        companionRequired: false,
        transcript: false,
        chatbot: false,
        opens: 'search-field',
        questions: SCREEN_QUESTIONS,
        next: 'Type a search or a request. Escape dismisses.',
    };
}
