// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Drawable models for every Phase 1 primitive. No GJS, no IO.
//
// St widgets live in lib/widgets.js and consume these models. Keeping the
// models here means tests/shell can measure "a Button has a focus treatment
// and a TaskTimeline never says AI is typing" under node, which is the only
// way those claims survive a compositor that this host cannot start.

import {
    OS_COMPANION_STATES,
    OS_PRESENTATION_MODES,
    RADIUS,
    SCREEN_QUESTIONS,
} from './tokens.js';
import {NETWORK_ALLOWLIST_NOTE} from '../trustPrompt.js';

/** Every primitive this phase ships, named once so a test can enumerate them. */
export const PRIMITIVE_KINDS = [
    'Button', 'IconButton', 'Card', 'Panel', 'Sheet', 'Dialog', 'Popover',
    'Tooltip', 'TextField', 'SearchField', 'Toggle', 'Slider', 'Menu', 'List',
    'Sidebar', 'TaskCard', 'TaskTimeline', 'PermissionCard', 'Bubble',
    'CompanionAnchor', 'Notification', 'DockItem',
];

export const BUTTON_VARIANTS = ['primary', 'secondary', 'ghost', 'destructive'];
export const FIELD_KINDS = ['text', 'search'];

function text(value, fallback = '') {
    return String(value ?? fallback);
}

function actionsOf(actions) {
    if (!Array.isArray(actions))
        return [];
    return actions
        .filter(item => item && typeof item === 'object')
        .map(item => ({
            id: text(item.id),
            label: text(item.label),
            variant: BUTTON_VARIANTS.includes(item.variant) ? item.variant : 'secondary',
            accessibleName: text(item.accessibleName || item.label),
        }))
        .filter(item => item.id && item.label);
}

/** One control. Focus is always on — a button without a ring is not a primitive. */
export function buildButton({
    label = '', variant = 'secondary', disabled = false, icon = '', destructive = false,
} = {}) {
    const resolved = destructive ? 'destructive' : (BUTTON_VARIANTS.includes(variant) ? variant : 'secondary');
    return {
        kind: 'Button',
        label: text(label),
        variant: resolved,
        disabled: Boolean(disabled),
        icon: text(icon),
        styleClass: `bunny-button bunny-button-${resolved}`,
        canFocus: !disabled,
        accessibleName: text(label),
    };
}

export function buildIconButton({
    icon = '', accessibleName = '', disabled = false,
} = {}) {
    const name = text(accessibleName);
    return {
        kind: 'IconButton',
        icon: text(icon),
        disabled: Boolean(disabled),
        styleClass: 'bunny-icon-button',
        canFocus: !disabled,
        accessibleName: name,
        // An icon-only control with no name is invisible to Orca. Refuse it.
        valid: Boolean(name),
    };
}

export function buildCard({title = '', body = '', elevated = false} = {}) {
    return {
        kind: 'Card',
        title: text(title),
        body: text(body),
        styleClass: elevated ? 'bunny-card bunny-card-raised' : 'bunny-card',
        radius: RADIUS.card,
        elevation: elevated ? 'raised' : 'base',
    };
}

export function buildPanel({title = ''} = {}) {
    return {
        kind: 'Panel',
        title: text(title),
        styleClass: 'bunny-panel',
        radius: RADIUS.panel,
        elevation: 'raised',
    };
}

export function buildSheet({title = '', actions = []} = {}) {
    return {
        kind: 'Sheet',
        title: text(title),
        actions: actionsOf(actions),
        styleClass: 'bunny-sheet',
        radius: RADIUS.sheet,
        elevation: 'overlay',
        canFocus: true,
    };
}

export function buildDialog({
    title = '', body = '', actions = [], modal = true,
} = {}) {
    return {
        kind: 'Dialog',
        title: text(title),
        body: text(body),
        actions: actionsOf(actions),
        modal: Boolean(modal),
        styleClass: 'bunny-dialog',
        radius: RADIUS.modal,
        elevation: 'dialog',
        canFocus: true,
        scrim: true,
    };
}

export function buildPopover({anchor = 'bottom', items = []} = {}) {
    return {
        kind: 'Popover',
        anchor: text(anchor, 'bottom'),
        items: actionsOf(items),
        styleClass: 'bunny-popover',
        radius: RADIUS.card,
        elevation: 'overlay',
        canFocus: true,
    };
}

export function buildTooltip({label = ''} = {}) {
    return {
        kind: 'Tooltip',
        label: text(label),
        styleClass: 'bunny-tooltip',
        radius: RADIUS.control,
        // Tooltips are not in the tab order. The labelled control is.
        canFocus: false,
        role: 'tooltip',
    };
}

export function buildTextField({
    label = '', value = '', placeholder = '', password = false,
} = {}) {
    return {
        kind: 'TextField',
        fieldKind: 'text',
        label: text(label),
        value: text(value),
        placeholder: text(placeholder),
        password: Boolean(password),
        styleClass: 'bunny-text-field',
        radius: RADIUS.control,
        canFocus: true,
        accessibleName: text(label || placeholder),
    };
}

export function buildSearchField({value = '', placeholder = 'Search'} = {}) {
    const field = buildTextField({label: 'Search', value, placeholder});
    return {
        ...field,
        kind: 'SearchField',
        fieldKind: 'search',
        styleClass: 'bunny-search-field',
    };
}

export function buildToggle({label = '', on = false, disabled = false} = {}) {
    return {
        kind: 'Toggle',
        label: text(label),
        on: Boolean(on),
        disabled: Boolean(disabled),
        styleClass: 'bunny-toggle',
        canFocus: !disabled,
        accessibleName: text(label),
        role: 'switch',
    };
}

export function buildSlider({
    label = '', value = 0, min = 0, max = 100, step = 1,
} = {}) {
    const lo = Number(min);
    const hi = Number(max);
    const raw = Number(value);
    const clamped = Number.isFinite(raw) ? Math.min(hi, Math.max(lo, raw)) : lo;
    return {
        kind: 'Slider',
        label: text(label),
        value: clamped,
        min: lo,
        max: hi,
        step: Number(step) || 1,
        styleClass: 'bunny-slider',
        canFocus: true,
        accessibleName: text(label),
        role: 'slider',
    };
}

export function buildMenu({items = []} = {}) {
    return {
        kind: 'Menu',
        items: actionsOf(items),
        styleClass: 'bunny-menu',
        radius: RADIUS.card,
        canFocus: true,
        role: 'menu',
    };
}

export function buildList({rows = []} = {}) {
    const items = (Array.isArray(rows) ? rows : []).map((row, index) => ({
        id: text(row?.id || `row-${index}`),
        title: text(row?.title),
        subtitle: text(row?.subtitle),
        styleClass: 'bunny-list-row',
        canFocus: true,
    }));
    return {kind: 'List', rows: items, styleClass: 'bunny-list', role: 'list'};
}

export function buildSidebar({collapsed = false, items = []} = {}) {
    return {
        kind: 'Sidebar',
        collapsed: Boolean(collapsed),
        items: actionsOf(items),
        styleClass: collapsed ? 'bunny-sidebar bunny-sidebar-collapsed' : 'bunny-sidebar',
        canFocus: true,
    };
}

export function buildDockItem({
    id = '', label = '', running = false, accessibleName = '',
} = {}) {
    const name = text(accessibleName || label);
    return {
        kind: 'DockItem',
        id: text(id),
        label: text(label),
        running: Boolean(running),
        styleClass: running ? 'bunny-dock-item bunny-dock-item-running' : 'bunny-dock-item',
        canFocus: true,
        accessibleName: name,
        valid: Boolean(name),
    };
}

export function buildNotification({
    title = '', body = '', severity = 'info', actions = [],
} = {}) {
    return {
        kind: 'Notification',
        title: text(title),
        body: text(body),
        severity: text(severity, 'info'),
        actions: actionsOf(actions),
        styleClass: `bunny-notification bunny-notification-${text(severity, 'info')}`,
        radius: RADIUS.card,
        canFocus: true,
        role: 'status',
    };
}

export function buildPermissionCard({
    application = '', action = '', effect = '', duration = '',
    files = '', network = '', enforced = true,
} = {}) {
    const isEnforced = Boolean(enforced);
    return {
        kind: 'PermissionCard',
        application: text(application),
        action: text(action),
        effect: text(effect),
        duration: text(duration),
        files: text(files),
        network: text(network),
        enforced: isEnforced,
        standing: isEnforced ? 'granted' : 'unenforced',
        enforcementNote: isEnforced ? 'Enforced' : 'Declared, not enforced',
        networkHonesty: NETWORK_ALLOWLIST_NOTE,
        styleClass: 'bunny-permission-card',
        radius: RADIUS.card,
        canFocus: true,
        questions: SCREEN_QUESTIONS,
    };
}

/**
 * Speech-bubble copy: one to three sentences, never a transcript.
 *
 * Counted in sentences rather than characters because a 220-character cut can
 * land mid-thought; a sentence cut cannot.
 */
export function limitBubbleText(value, {maxSentences = 3} = {}) {
    const raw = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (!raw)
        return '';
    const parts = raw.split(/(?<=[.!?])\s+/).filter(Boolean);
    if (parts.length <= maxSentences)
        return raw;
    return parts.slice(0, maxSentences).join(' ');
}

export function buildBubble({
    text: copy = '', actions = [], kind = 'caption',
} = {}) {
    const limited = limitBubbleText(copy);
    return {
        kind: 'Bubble',
        text: limited,
        originalLength: String(copy ?? '').length,
        truncated: limited !== String(copy ?? '').replace(/\s+/g, ' ').trim(),
        actions: actionsOf(actions),
        tone: text(kind, 'caption'),
        styleClass: 'bunny-bubble',
        radius: RADIUS.bubble,
        // Captions, not a chat log. Actions sit *under* the text when present.
        transcript: false,
        canFocus: actionsOf(actions).length > 0,
        role: 'status',
    };
}

/**
 * Compact task timeline. Marks are ✓ / ● / ○ — never a fake percentage and
 * never "AI is typing…".
 */
export function buildTaskTimeline({
    stages = [], stageIndex = -1, details = null, expanded = false,
    canPause = true, canCancel = true, caption = '',
} = {}) {
    const named = Array.isArray(stages) ? stages.filter(s => typeof s === 'string' && s.trim()) : [];
    const index = Number.isInteger(stageIndex) ? stageIndex : -1;
    const marks = named.map((name, position) => {
        const done = index >= 0 && position < index;
        const current = position === index;
        return {
            name,
            done,
            current,
            pending: !done && !current,
            // Named marks, not dingbats: the image is not required to have
            // U+2713 / U+25CF / U+25CB. CSS draws the check / disc / ring.
            glyph: done ? 'done' : current ? 'current' : 'pending',
        };
    });
    const actions = [];
    if (canPause)
        actions.push({id: 'pause', label: 'Pause', variant: 'secondary', accessibleName: 'Pause this task'});
    if (canCancel)
        actions.push({id: 'cancel', label: 'Cancel', variant: 'ghost', accessibleName: 'Cancel this task'});

    const detail = details && typeof details === 'object' ? {
        plan: text(details.plan),
        tools: Array.isArray(details.tools) ? details.tools.map(text) : [],
        files: Array.isArray(details.files) ? details.files.map(text) : [],
        permissions: Array.isArray(details.permissions) ? details.permissions.map(text) : [],
    } : {plan: '', tools: [], files: [], permissions: []};

    return {
        kind: 'TaskTimeline',
        caption: text(caption),
        stages: marks,
        details: detail,
        expanded: Boolean(expanded),
        actions: actionsOf(actions),
        styleClass: 'bunny-task-timeline',
        typingIndicator: false,
        questions: SCREEN_QUESTIONS,
    };
}

export function buildTaskCard({
    title = '', caption = '', stages = [], stageIndex = -1, details = null,
} = {}) {
    const timeline = buildTaskTimeline({stages, stageIndex, details, caption});
    return {
        kind: 'TaskCard',
        title: text(title),
        timeline,
        styleClass: 'bunny-task-card',
        radius: RADIUS.card,
        questions: SCREEN_QUESTIONS,
        typingIndicator: false,
    };
}

/**
 * Where the companion sits. Default bottom-right. Drag / scale / hide are
 * hooks — the compositor still owns real placement on Wayland.
 */
export function buildCompanionAnchor({
    corner = 'bottom-right',
    mode = 'compact',
    hidden = false,
    scale = 1,
    state = 'idle',
} = {}) {
    const corners = ['bottom-right', 'bottom-left', 'top-right', 'top-left'];
    const resolvedCorner = corners.includes(corner) ? corner : 'bottom-right';
    const resolvedMode = OS_PRESENTATION_MODES[mode] ? mode : 'compact';
    const osState = OS_COMPANION_STATES[state] ? state : 'idle';
    const numericScale = Number(scale);
    const clamped = Number.isFinite(numericScale)
        ? Math.min(2, Math.max(0.75, numericScale)) : 1;
    return {
        kind: 'CompanionAnchor',
        corner: resolvedCorner,
        mode: resolvedMode,
        hidden: Boolean(hidden),
        scale: clamped,
        state: osState,
        label: OS_COMPANION_STATES[osState].label,
        draggable: true,
        scalable: true,
        hideable: true,
        absolutePlacementAvailable: false,
        styleClass: 'bunny-companion-anchor',
        requiredToUseOs: false,
        parts: OS_PRESENTATION_MODES[resolvedMode],
    };
}

export const BUILDERS = {
    Button: buildButton,
    IconButton: buildIconButton,
    Card: buildCard,
    Panel: buildPanel,
    Sheet: buildSheet,
    Dialog: buildDialog,
    Popover: buildPopover,
    Tooltip: buildTooltip,
    TextField: buildTextField,
    SearchField: buildSearchField,
    Toggle: buildToggle,
    Slider: buildSlider,
    Menu: buildMenu,
    List: buildList,
    Sidebar: buildSidebar,
    TaskCard: buildTaskCard,
    TaskTimeline: buildTaskTimeline,
    PermissionCard: buildPermissionCard,
    Bubble: buildBubble,
    CompanionAnchor: buildCompanionAnchor,
    Notification: buildNotification,
    DockItem: buildDockItem,
};
