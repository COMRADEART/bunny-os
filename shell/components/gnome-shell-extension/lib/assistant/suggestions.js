// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// SuggestedActions: four things worth doing next, on the other side of Bunny.
//
// The brief's examples are "Explain Quantum Computing", "Create a study plan",
// "Launch Game Mode", "Open Terminal", and says these may be test data for now
// and should eventually come from Bunny AI and context. The compromise here is
// that the *list* is contextual today from what the desktop can actually see —
// the time of day, whether the companion is reachable, whether a task is
// running, what is installed — while the *wording* of the assistant prompts is
// fixed text. So a suggestion is never offered for something that would fail:
// "Open Terminal" does not appear on an image without a terminal, and the
// prompts do not appear when there is no runtime to answer them.
//
// Two kinds of suggestion, and the difference matters for permissions.
// `prompt` puts text into the assistant and asks; nothing happens until the
// runtime plans it and, where the plan needs approval, the user gives it.
// `action` runs a named desktop operation directly, and only operations that
// are already reachable from the sidebar or dock are allowed to be one — a
// suggestion chip is not a route to something the interface does not otherwise
// offer.
//
// Each row used to be led by an emoji — 💡, 📝, 🧹, 📁 — and on the first
// booted image every one of them was a tofu box, because the image shipped no
// emoji font. The font is installed now and these are still icons rather than
// emoji, because the reason has nothing to do with that image: a control whose
// meaning is carried by a codepoint the font set is not required to have is a
// control that can lose its meaning to a packaging change. The label carries
// the meaning; the icon decorates it.

import St from 'gi://St';

import {box, glass} from '../widgets.js';
import {ease} from '../animation.js';
import {makeActivatable} from '../util.js';
import {MOTION} from '../design/tokens.js';
import {Icons, themedIcon} from '../icons.js';

const MAX_SHOWN = 4;

export class SuggestedActions {
    /**
     * @param {{onPrompt: (text: string) => void, onAction: (id: string) => void,
     *          launcher, assistant, blur}} context
     */
    constructor(context) {
        this._context = context;
        this.actor = glass('bunny-suggestions', {blur: context.blur, radius: 20});
        this.actor.visible = false;
        this._column = box({vertical: true, style_class: 'bunny-suggestions-column'});
        this.actor.add_child(this._column);
        this._more = null;
        this.rebuild();
    }

    /** Recompute from what is true now. Cheap; called on state and app changes. */
    rebuild() {
        this._column.destroy_all_children();
        const items = this._candidates().slice(0, MAX_SHOWN);
        if (items.length === 0) {
            this.actor.visible = false;
            return;
        }
        this.actor.visible = true;

        for (const item of items)
            this._column.add_child(this._buildRow(item));

        const more = new St.Label({text: 'See more...', style_class: 'bunny-suggestions-more'});
        makeActivatable(more, () => this._context.onAction?.('apps'), {
            accessibleName: 'See more suggestions',
        });
        this._column.add_child(more);
    }

    setWidth(width) {
        this.actor.set_width(width);
    }

    destroy() {
        this.actor.destroy();
    }

    _buildRow(item) {
        const row = box({style_class: 'bunny-suggestion-row'});
        row.add_child(themedIcon(item.icon, {size: 16, styleClass: 'bunny-suggestion-glyph'}));
        const label = new St.Label({text: item.label, style_class: 'bunny-suggestion-label'});
        label.clutter_text.ellipsize = 3;
        row.add_child(label);
        makeActivatable(row, () => {
            if (item.prompt !== undefined)
                this._context.onPrompt?.(item.prompt);
            else
                this._context.onAction?.(item.action);
        }, {accessibleName: item.label});
        row.connect('notify::hover', () => {
            ease(row, {translation_x: row.hover ? 4 : 0}, {ms: MOTION.fast});
        });
        return row;
    }

    /**
     * What to offer, given what is true.
     *
     * Order is deliberate: assistant prompts first when the runtime can answer
     * them, because that is what the desktop is for; direct actions after, as
     * the things that always work.
     */
    _candidates() {
        const {launcher, assistant} = this._context;
        const hour = new Date().getHours();
        const items = [];

        if (assistant?.available !== false) {
            items.push({
                icon: Icons.EXPLAIN,
                label: 'Explain something to me',
                prompt: 'Explain a topic I am curious about, and ask me which one.',
            });
            items.push(hour < 12
                ? {icon: Icons.PLAN, label: 'Plan my day', prompt: 'Help me plan my day.'}
                : {icon: Icons.PLAN, label: 'Summarise what I worked on', prompt: 'Summarise what I worked on today.'});
            items.push({
                icon: Icons.DISK_SPACE,
                label: 'Free up disk space',
                prompt: 'Find what is using disk space on this machine and suggest what to remove.',
            });
        } else {
            // No runtime. Saying so once, as a row, beats four chips that all
            // fail the moment they are pressed.
            items.push({
                icon: Icons.WARNING,
                label: 'Assistant offline — open Settings',
                action: 'settings',
            });
        }

        if (launcher?.available('terminal'))
            items.push({icon: Icons.TERMINAL, label: 'Open Terminal', action: 'terminal'});
        if (launcher?.available('files'))
            items.push({icon: Icons.FILES, label: 'Browse my files', action: 'files'});
        if (launcher?.available('software'))
            items.push({icon: Icons.STORE, label: 'Find new apps', action: 'store'});

        return items;
    }
}
