// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// SystemOverview: the CPU dial, and three figures beside it.
//
// Every value comes from SystemTelemetry, which returns null rather than a
// guess. The dial has a distinct null rendering — a dim empty ring with the
// word Unavailable in the middle — instead of a ring at 0%, because a ring at
// 0% is what an idle machine looks like and the two must not be confusable.
//
// The dial is drawn rather than assembled from styled widgets because an arc is
// an arc: doing it with a rotated St.Widget and a mask is three actors, a
// clipping path and a redraw on every value change, against one Cairo pass.

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {Card} from './base.js';
import {Rgb} from '../tokens.js';
import {box, MetricRow, UNAVAILABLE} from '../widgets.js';
import {clamp, formatBytes, formatPair, logError_} from '../util.js';

export class SystemOverview extends Card {
    constructor({telemetry, launcher, blur}) {
        super({
            title: 'System',
            refreshSeconds: 2,
            blur,
            accessibleName: 'System overview',
            headerTrailing: Card.headerButton('Details', () =>
                launcher.spawn(['gnome-control-center', 'info-overview'])),
        });
        this._telemetry = telemetry;
        this._fraction = null;

        const body = box({style_class: 'bunny-overview-body'});
        this.content.add_child(body);

        this._dial = new St.DrawingArea({
            style_class: 'bunny-dial',
            width: 96,
            height: 96,
            reactive: false,
        });
        this._dial.connect('repaint', area => this._paintDial(area));

        // The ring and the number it labels are one stacked unit, so the
        // number stays centred when the theme changes the font size and when
        // the card is laid out at a different width.
        const dialStack = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            width: 96,
            height: 96,
        });
        dialStack.add_child(this._dial);
        this._dialLabel = new St.Label({
            text: UNAVAILABLE,
            style_class: 'bunny-dial-value',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        dialStack.add_child(this._dialLabel);

        const dialColumn = box({vertical: true, style_class: 'bunny-dial-column'});
        dialColumn.add_child(dialStack);
        this._dialCaption = new St.Label({text: 'CPU Usage', style_class: 'bunny-dial-caption'});
        dialColumn.add_child(this._dialCaption);
        body.add_child(dialColumn);

        const rows = box({vertical: true, style_class: 'bunny-overview-rows', x_expand: true});
        this._memory = new MetricRow('RAM');
        this._storage = new MetricRow('Storage');
        this._temperature = new MetricRow('Temp');
        rows.add_child(this._memory.actor);
        rows.add_child(this._storage.actor);
        rows.add_child(this._temperature.actor);
        body.add_child(rows);
    }

    refresh() {
        const cpu = this._telemetry.cpu();
        this._fraction = cpu;
        this._dial.queue_repaint();
        this._dial.accessible_name = cpu === null
            ? 'CPU usage Unavailable'
            : `CPU usage ${Math.round(cpu * 100)} percent`;

        // `formatPair`, not two `formatBytes` around a slash: the long form is
        // fifteen characters and ellipsises to "3.9 GB…" in a 248-pixel card,
        // which is what the 1366x768 boot of the Alpha image showed.
        const memory = this._telemetry.memory();
        this._memory.set(memory === null
            ? null
            : formatPair(memory.usedBytes, memory.totalBytes));

        const storage = this._telemetry.storage();
        this._storage.set(storage === null
            ? null
            : formatPair(storage.usedBytes, storage.totalBytes));
        // Which filesystem the figure is about, for a screen reader and for
        // anyone who wonders why a 14 GB machine reports 8 GB. "Storage" is the
        // only metric on this card whose subject is a choice rather than the
        // machine, so it is the only one that has to name its subject.
        this._storage.actor.accessible_description = storage === null
            ? 'no persistent filesystem could be measured'
            : `${formatBytes(storage.freeBytes)} free on ${storage.path}` +
              (storage.filesystemType ? ` (${storage.filesystemType})` : '');

        const temperature = this._telemetry.temperature();
        this._temperature.set(temperature === null ? null : `${Math.round(temperature)}°C`);
    }

    _paintDial(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            const radius = Math.min(width, height) / 2 - 7;
            const centreX = width / 2;
            const centreY = height / 2;
            // Start at the top and sweep clockwise. A dial that starts at three
            // o'clock is a pie chart; one that starts at twelve is a gauge.
            const start = -Math.PI / 2;

            cr.setLineCap(Cairo.LineCap.ROUND);
            cr.setLineWidth(7);

            cr.newPath();
            cr.arc(centreX, centreY, radius, 0, Math.PI * 2);
            cr.setSourceRGBA(1, 1, 1, 0.08);
            cr.stroke();

            if (this._fraction !== null) {
                const value = clamp(this._fraction, 0, 1);
                // Colour steps at the thresholds a user would act on, not a
                // continuous ramp: a dial that is slightly orange at 55% trains
                // people to ignore orange.
                const [r, g, b] = value >= 0.9 ? Rgb.ERROR
                    : value >= 0.7 ? Rgb.WARNING : Rgb.ACCENT_BRIGHT;
                cr.newPath();
                cr.arc(centreX, centreY, radius, start, start + Math.PI * 2 * value);
                cr.setSourceRGBA(r, g, b, 1);
                cr.stroke();
            }
        } catch (error) {
            logError_('the CPU dial could not be drawn', error);
        } finally {
            cr?.$dispose();
        }

        this._syncDialLabel();
    }

    /**
     * The number in the middle of the ring.
     *
     * A Clutter label rather than Cairo text: Cairo would need the font, the
     * scale factor and the text direction, all of which St already has, and the
     * result would not follow a font-size change in the theme.
     */
    _syncDialLabel() {
        const text = this._fraction === null ? UNAVAILABLE : `${Math.round(this._fraction * 100)}%`;
        if (this._dialLabel.text !== text)
            this._dialLabel.text = text;
        this._dialLabel.remove_style_class_name('bunny-dial-value-unavailable');
        if (this._fraction === null)
            this._dialLabel.add_style_class_name('bunny-dial-value-unavailable');
    }
}
