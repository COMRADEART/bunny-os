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
import {rgb} from '../design/current.js';
import {box, setOrientation, MetricRow, UNAVAILABLE} from '../widgets.js';
import {clamp, formatBytes, formatPair, logError_} from '../util.js';

/** The dial's diameter, wide and narrow. */
const DIAL_WIDE = 96;
const DIAL_NARROW = 72;

/** Card widths at or above this keep the wide dial. `standard` is 276. */
const COMPACT_CARD_WIDTH = 270;

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

        this._body = box({style_class: 'bunny-overview-body'});
        const body = this._body;
        this.content.add_child(body);

        this._dial = new St.DrawingArea({
            style_class: 'bunny-dial',
            width: DIAL_WIDE,
            height: DIAL_WIDE,
            reactive: false,
        });
        this._dial.connect('repaint', area => this._paintDial(area));

        // The ring and the number it labels are one stacked unit, so the
        // number stays centred when the theme changes the font size and when
        // the card is laid out at a different width.
        this._dialStack = new St.Widget({
            layout_manager: new Clutter.BinLayout(),
            width: DIAL_WIDE,
            height: DIAL_WIDE,
        });
        const dialStack = this._dialStack;
        dialStack.add_child(this._dial);
        this._dialLabel = new St.Label({
            text: UNAVAILABLE,
            style_class: 'bunny-dial-value',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        dialStack.add_child(this._dialLabel);

        this._dialColumn = box({vertical: true, style_class: 'bunny-dial-column'});
        const dialColumn = this._dialColumn;
        dialColumn.add_child(dialStack);
        this._dialCaption = new St.Label({text: 'CPU Usage', style_class: 'bunny-dial-caption'});
        dialColumn.add_child(this._dialCaption);
        body.add_child(dialColumn);

        this._rows = box({vertical: true, style_class: 'bunny-overview-rows', x_expand: true});
        const rows = this._rows;
        this._memory = new MetricRow('RAM');
        this._storage = new MetricRow('Storage');
        this._temperature = new MetricRow('Temp');
        rows.add_child(this._memory.actor);
        rows.add_child(this._storage.actor);
        rows.add_child(this._temperature.actor);
        body.add_child(rows);
    }

    /**
     * Shrink the dial when the card is narrow.
     *
     * The dial is 96 pixels and the card is 304 at the wide breakpoint and 248
     * at the compact one, so the figures beside it go from 190 pixels of room
     * to 134 — and "Storage 3.9/8.3 GB" does not fit in 134. Measured on the
     * 1366x768 boot of the Alpha image, where the value read "3.9/8...".
     *
     * The dial loses 24 pixels and stays perfectly legible; the number it sits
     * beside would have lost its second half.
     */
    resize(width) {
        const narrow = width < COMPACT_CARD_WIDTH;
        const size = narrow ? DIAL_NARROW : DIAL_WIDE;
        if (this._dial.width !== size) {
            this._dial.set_size(size, size);
            this._dialStack.set_size(size, size);
            this._dial.queue_repaint();
        }

        // Stack, rather than sit beside.
        //
        // Shrinking the dial was not enough on its own and the booted image
        // said so: "RAM 1.0/5.8 GB" fitted beside a 72-pixel dial and
        // "Storage 3.9/8.3 GB" did not, because the label is four characters
        // longer. Below the dial each row has the card's full width, which is
        // 220 pixels rather than 136, and no arithmetic about label lengths is
        // needed at all.
        if (this._stacked === narrow)
            return;
        this._stacked = narrow;
        setOrientation(this._body, narrow);
        this._body.remove_style_class_name('bunny-overview-body-stacked');
        if (narrow)
            this._body.add_style_class_name('bunny-overview-body-stacked');
        this._dialColumn.x_expand = narrow;
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
        // Appended to the row's name. MetricRow.set already writes
        // "Storage: 3.9/8.3 GB" there; this adds the subject, because Storage is
        // the only figure on the card whose subject is a choice.
        this._storage.actor.accessible_name = storage === null
            ? 'Storage: Unavailable. No persistent filesystem could be measured'
            : `Storage: ${formatPair(storage.usedBytes, storage.totalBytes)}. ` +
              `${formatBytes(storage.freeBytes)} free on ${storage.path}` +
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
                const [r, g, b] = rgb(value >= 0.9 ? 'danger'
                    : value >= 0.7 ? 'warning' : 'accentText');
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
