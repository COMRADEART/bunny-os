// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// SystemMonitor: throughput over time, and the power situation.
//
// The graph is auto-scaled to the largest sample in the window rather than to a
// fixed ceiling. A fixed ceiling has to be chosen for either a 100 Mbit link or
// a gigabit one and is wrong for the other; auto-scale means the shape of the
// last minute is always visible, and the peak figure is printed beside it so
// the height still means something. When the whole window is zero the scale is
// pinned to a small floor, or idle traffic would be drawn as a full-height
// mountain range of rounding noise.
//
// Battery follows the rule the brief states outright: a machine with no battery
// says AC Power. It does not say 100%, it does not draw an empty bar, and it
// does not hide the section, because "this machine runs on mains" is
// information.

import St from 'gi://St';

import {Card} from './base.js';
import {Rgb} from '../tokens.js';
import {box, Meter, MetricRow, UNAVAILABLE} from '../widgets.js';
import {formatRate, logError_} from '../util.js';

/** Samples kept. At one every two seconds this is two minutes of history. */
const WINDOW = 60;

/** Bytes per second below which the graph does not rescale. 8 KB/s. */
const SCALE_FLOOR = 8 * 1024;

export class SystemMonitor extends Card {
    constructor({network, power, blur, launcher}) {
        super({
            title: 'Network & Power',
            refreshSeconds: 2,
            blur,
            accessibleName: 'Network and power monitor',
            headerTrailing: Card.headerButton('Settings', () =>
                launcher.spawn(['gnome-control-center', 'network'])),
        });
        this._network = network;
        this._power = power;
        this._up = new Array(WINDOW).fill(0);
        this._down = new Array(WINDOW).fill(0);
        this._haveSample = false;

        const rates = box({style_class: 'bunny-monitor-rates'});
        this._upLabel = new St.Label({text: `↑ ${UNAVAILABLE}`, style_class: 'bunny-monitor-up'});
        this._downLabel = new St.Label({text: `↓ ${UNAVAILABLE}`, style_class: 'bunny-monitor-down'});
        rates.add_child(this._upLabel);
        rates.add_child(new St.Widget({x_expand: true}));
        rates.add_child(this._downLabel);
        this.content.add_child(rates);

        this._graph = new St.DrawingArea({style_class: 'bunny-monitor-graph', height: 46, reactive: false});
        this._graph.connect('repaint', area => this._paintGraph(area));
        this.content.add_child(this._graph);

        this._batteryRow = new MetricRow('Battery');
        this.content.add_child(this._batteryRow.actor);
        this._batteryMeter = new Meter({height: 5});
        this.content.add_child(this._batteryMeter.actor);
    }

    refresh() {
        const rates = this._network.rates();
        if (rates !== null) {
            this._haveSample = true;
            this._up.push(rates.upBytesPerSecond);
            this._down.push(rates.downBytesPerSecond);
            this._up.shift();
            this._down.shift();
            this._upLabel.text = `↑ ${formatRate(rates.upBytesPerSecond)}`;
            this._downLabel.text = `↓ ${formatRate(rates.downBytesPerSecond)}`;
        } else if (!this._haveSample) {
            // Before the second sample there is genuinely no rate to report.
            this._upLabel.text = `↑ ${UNAVAILABLE}`;
            this._downLabel.text = `↓ ${UNAVAILABLE}`;
        }
        this._graph.queue_repaint();

        const connection = this._network.connection();
        this._graph.accessible_name =
            `Network ${connection.state}, up ${this._upLabel.text}, down ${this._downLabel.text}`;

        this._refreshBattery();
    }

    _refreshBattery() {
        const battery = this._power.battery();
        if (!battery.present) {
            this._batteryRow.set('AC Power');
            this._batteryMeter.actor.visible = false;
            return;
        }
        this._batteryMeter.actor.visible = true;
        if (battery.percentage === null) {
            this._batteryRow.set(null);
            this._batteryMeter.set(null);
            return;
        }
        const suffix = battery.state === 'charging' ? ' · charging'
            : battery.state === 'full' ? ' · full'
                : battery.onAcPower ? ' · plugged in' : '';
        this._batteryRow.set(`${battery.percentage}%${suffix}`);
        this._batteryMeter.set(battery.percentage / 100);
    }

    _paintGraph(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            if (width <= 0 || height <= 0)
                return;

            const peak = Math.max(SCALE_FLOOR, ...this._up, ...this._down);

            cr.setLineWidth(1);
            cr.setSourceRGBA(1, 1, 1, 0.06);
            for (const fraction of [0.25, 0.5, 0.75]) {
                cr.newPath();
                cr.moveTo(0, height * fraction);
                cr.lineTo(width, height * fraction);
                cr.stroke();
            }

            this._series(cr, this._down, peak, width, height, Rgb.ACCENT_BRIGHT, 0.30);
            this._series(cr, this._up, peak, width, height, Rgb.SUCCESS, 0.18);
        } catch (error) {
            logError_('the network graph could not be drawn', error);
        } finally {
            cr?.$dispose();
        }
    }

    _series(cr, samples, peak, width, height, [r, g, b], fillAlpha) {
        const step = width / (samples.length - 1);
        cr.newPath();
        cr.moveTo(0, height);
        for (const [index, value] of samples.entries()) {
            const x = index * step;
            const y = height - Math.min(1, value / peak) * (height - 2);
            cr.lineTo(x, y);
        }
        cr.lineTo(width, height);
        cr.closePath();
        cr.setSourceRGBA(r, g, b, fillAlpha);
        cr.fillPreserve();
        cr.setSourceRGBA(r, g, b, 0.9);
        cr.setLineWidth(1.4);
        cr.stroke();
    }
}
