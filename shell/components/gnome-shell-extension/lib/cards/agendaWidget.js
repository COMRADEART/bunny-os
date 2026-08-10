// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AgendaWidget: today, from whichever provider answered.
//
// The empty state is the interesting part of this file. It says "Nothing
// scheduled today" and names how to change that, rather than showing three
// invented meetings. AgendaService's module note has the reasoning; the short
// version is that a fake appointment is indistinguishable from a real one and
// there is no way to mark it that a user reliably reads.
//
// Events are grouped by whether they have already started. A past event stays
// on the list, dimmed, until midnight — removing it as it ends would make the
// card empty by six in the evening on a day that was full.

import St from 'gi://St';

import {Card} from './base.js';
import {box} from '../widgets.js';
import {makeActivatable} from '../util.js';

const MAX_ROWS = 4;

export class AgendaWidget extends Card {
    constructor({agenda, blur}) {
        super({
            title: "Today's Agenda",
            refreshSeconds: 60,
            blur,
            accessibleName: "Today's agenda",
            headerTrailing: Card.headerButton('View Calendar', () => agenda.openCalendar()),
        });
        this._agenda = agenda;
        this._list = box({vertical: true, style_class: 'bunny-agenda-list', x_expand: true});
        this.content.add_child(this._list);
        this._unsubscribe = agenda.onChange(() => this.refresh());
    }

    refresh() {
        this._agenda.refresh();
        this._list.destroy_all_children();
        const events = this._agenda.events();

        if (events.length === 0) {
            const empty = box({vertical: true, style_class: 'bunny-agenda-empty'});
            empty.add_child(new St.Label({
                text: 'Nothing scheduled today',
                style_class: 'bunny-agenda-empty-primary',
            }));
            empty.add_child(new St.Label({
                text: 'Add a calendar account in Settings to see your day here.',
                style_class: 'bunny-agenda-empty-secondary',
            }));
            this._list.add_child(empty);
            this.actor.accessible_name = 'Today\'s agenda: nothing scheduled';
            return;
        }

        const now = new Date();
        for (const event of events.slice(0, MAX_ROWS)) {
            const row = box({style_class: 'bunny-agenda-row'});
            const time = new St.Label({
                text: event.allDay ? 'All day' : formatTime(event.start),
                style_class: 'bunny-agenda-time',
            });
            const summary = new St.Label({
                text: event.summary,
                style_class: 'bunny-agenda-summary',
                x_expand: true,
            });
            summary.clutter_text.ellipsize = 3;
            row.add_child(time);
            row.add_child(summary);
            if (!event.allDay && event.start < now)
                row.add_style_class_name('bunny-agenda-row-past');
            makeActivatable(row, () => this._agenda.openCalendar(), {
                accessibleName: `${time.text}, ${event.summary}`,
            });
            this._list.add_child(row);
        }

        if (events.length > MAX_ROWS) {
            const more = new St.Label({
                text: `+${events.length - MAX_ROWS} more`,
                style_class: 'bunny-agenda-more',
            });
            this._list.add_child(more);
        }
        this.actor.accessible_name =
            `Today's agenda: ${events.length} event${events.length === 1 ? '' : 's'}`;
    }

    destroy() {
        this._unsubscribe?.();
        super.destroy();
    }
}

function formatTime(date) {
    const hours = date.getHours();
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${String(hours).padStart(2, '0')}:${minutes}`;
}
