// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Task overlay: longer command-surface work as a card/timeline, not a
// chatbot transcript. Chrome (above windows), optional; Search still works
// if this fails to construct.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {box, glass} from '../widgets.js';
import {RADIUS} from '../design/tokens.js';

export class TaskOverlay {
    constructor({blur = false} = {}) {
        this.actor = new St.Widget({
            style_class: 'bunny-task-overlay-layer',
            reactive: false,
            visible: false,
            layout_manager: new Clutter.FixedLayout(),
        });
        this._card = glass('bunny-dialog bunny-task-overlay', {
            blur, radius: RADIUS.card,
        });
        this._column = box({vertical: true, style_class: 'bunny-task-overlay-column'});
        this._title = new St.Label({style_class: 'bunny-trust-heading'});
        this._caption = new St.Label({style_class: 'bunny-bubble-text'});
        this._caption.clutter_text.line_wrap = true;
        this._caption.clutter_text.set_line_wrap_mode(2);
        this._caption.clutter_text.ellipsize = 0;
        this._stages = box({style_class: 'bunny-task-timeline'});
        this._column.add_child(this._title);
        this._column.add_child(this._caption);
        this._column.add_child(this._stages);
        this._card.add_child(this._column);
        this.actor.add_child(this._card);
        this.actor.accessible_name = 'Bunny task';
        this._model = null;
    }

    show(model) {
        if (!model || model.kind !== 'TaskCard')
            return false;
        this._model = model;
        this._title.text = String(model.title || 'Working');
        this._caption.text = String(model.timeline?.caption || '');
        this._stages.destroy_all_children();
        for (const stage of model.timeline?.stages || []) {
            const label = new St.Label({
                text: `${stage.glyph === 'done' ? 'Done' : stage.glyph === 'current' ? 'Now' : 'Next'}: ${stage.name}`,
                style_class: `bunny-task-stage bunny-task-stage-${stage.glyph}`,
            });
            this._stages.add_child(label);
        }
        this.actor.visible = true;
        this.actor.accessible_name = `${this._title.text}. ${this._caption.text}`.trim();
        return true;
    }

    hide() {
        this.actor.visible = false;
        this._model = null;
    }

    get visible() {
        return this.actor.visible;
    }

    place(monitor) {
        if (!monitor)
            return;
        this.actor.set_position(monitor.x, monitor.y);
        this.actor.set_size(monitor.width, monitor.height);
        const width = Math.min(420, Math.max(260, Math.round(monitor.width * 0.36)));
        this._card.set_width(width);
        this._card.set_position(
            Math.round((monitor.width - width) / 2),
            Math.round(monitor.height * 0.18));
    }

    destroy() {
        this.actor.destroy();
    }
}
