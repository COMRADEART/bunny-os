// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The card every dashboard widget is.
//
// Cards share a shape, a hover response, a title row and — the part worth
// factoring out — a refresh contract. Each subclass implements `refresh()` and
// says how often it wants to be called; the base owns the timer and, more
// importantly, stops calling when the card is not on screen. A card dropped by
// the layout solver at 1280x720 must not keep reading /proc every two seconds
// for a widget nobody can see.

import St from 'gi://St';

import {box, glass, cardHeader} from '../widgets.js';
import {ease, enter} from '../animation.js';
import {interval, makeActivatable, setAccessibleRole} from '../util.js';
import {MOTION} from '../design/tokens.js';

export class Card {
    /**
     * @param {{title, refreshSeconds?, blur?, onActivate?, accessibleName?}} options
     */
    constructor({title, refreshSeconds = 0, blur = false, onActivate = null,
        accessibleName = null, headerTrailing = null} = {}) {
        this.title = title;
        this._refreshSeconds = refreshSeconds;
        this._timer = null;
        this._live = false;

        this.actor = glass('bunny-card', {blur, radius: 18});
        this.content = box({vertical: true, style_class: 'bunny-card-content'});
        this.actor.add_child(this.content);
        this.content.add_child(cardHeader(title, headerTrailing));

        this.actor.accessible_name = accessibleName ?? title;
        setAccessibleRole(this.actor, 'PANEL');

        if (onActivate) {
            makeActivatable(this.actor, onActivate, {accessibleName: accessibleName ?? title});
        } else {
            this.actor.reactive = true;
            this.actor.track_hover = true;
        }

        this.actor.connect('notify::hover', () => {
            ease(this.actor, {translation_y: this.actor.hover ? -3 : 0}, {ms: MOTION.fast});
        });
    }

    /** Subclasses override. Called on the timer and once when shown. */
    refresh() {}

    /**
     * Subclasses override to adapt to the width they were given.
     *
     * St has no container queries and the stylesheet cannot know a card's
     * allocation, so a card that has to change shape when it narrows has to be
     * told. `show` is where the width arrives, which makes this the only place
     * the information exists.
     *
     * The System card is the one that needs it: its 96-pixel dial is 39% of a
     * 248-pixel card at the compact breakpoint, and what was left could not fit
     * "Storage" and "3.9/8.3 GB" on one line.
     */
    resize(_width) {}

    /**
     * Show the card and start its timer.
     *
     * @param {{x, y, width, height}} rect
     * @param {number} index position in the entrance stagger
     */
    show(rect, index) {
        const wasLive = this._live;
        this._live = true;
        this.actor.visible = true;
        this.actor.set_position(rect.x, rect.y);
        this.actor.set_size(rect.width, rect.height);
        this.resize(rect.width);
        this.refresh();
        if (this._refreshSeconds > 0 && this._timer === null)
            this._timer = interval(this._refreshSeconds, () => this.refresh());
        if (!wasLive)
            enter(this.actor, {index});
    }

    /** Hide the card and stop its timer. The layout solver dropped it. */
    hide() {
        this._live = false;
        this.actor.visible = false;
        this._timer?.stop();
        this._timer = null;
    }

    get live() {
        return this._live;
    }

    destroy() {
        this._timer?.stop();
        this._timer = null;
        this.actor.destroy();
    }

    /** A right-aligned trailing button for the header row. */
    static headerButton(label, onActivate) {
        const button = new St.Button({
            label,
            style_class: 'bunny-card-action',
            can_focus: true,
        });
        button.connect('clicked', () => onActivate());
        return button;
    }
}
