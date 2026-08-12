// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AssistantBubble: what Bunny is saying, beside Bunny.
//
// It repositions rather than having a fixed side, because the character band is
// 1028px wide at 1080p and 412px at 1024x768, and a bubble pinned to the left
// of the figure runs off the screen at the second. `place` is given the
// figure's rectangle and the band it must stay inside, and it picks the side
// with room — preferring the left, so the suggestions can have the right, and
// falling back to above the head when neither side fits.
//
// The waveform is drawn only while listening or talking. It is four bars on a
// St.DrawingArea; a real spectrum would need the capture stream, which this
// process does not have and should not open — the companion's speech service
// owns the microphone and the desktop showing a level it did not measure would
// be decoration pretending to be an instrument. So the bars follow the state's
// own rhythm, and the accessible description says "speaking" rather than
// implying a measurement.

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {rgb} from '../design/current.js';
import {box, glass} from '../widgets.js';
import {ease, animationsEnabled} from '../animation.js';
import {clamp, logError_, setAccessibleRole} from '../util.js';
import {MOTION} from '../design/tokens.js';

const MAX_WIDTH = 360;
const MIN_WIDTH = 200;
const GAP = 20;

/**
 * How much of an answer the bubble shows before it offers the rest elsewhere.
 *
 * The bubble is beside a character in the middle of a desktop, not a chat
 * transcript. A directory listing or a long explanation pinned open next to the
 * figure covers the cards it is standing among, and the brief is explicit that
 * a long response must not fill half the screen. So the bubble shows the first
 * part and says how much more there is; the full text stays in the assistant
 * card, which is a scrolling surface built for it.
 *
 * Counted in characters rather than lines because a line is a function of the
 * width, and the width changes with the breakpoint.
 */
const PREVIEW_LIMIT = 220;

export class AssistantBubble {
    constructor({blur = false} = {}) {
        this.actor = glass('bunny-bubble', {blur, radius: 20});
        this.actor.visible = false;
        this.actor.opacity = 0;

        this._column = box({vertical: true, style_class: 'bunny-bubble-column'});
        this.actor.add_child(this._column);

        this._text = new St.Label({text: '', style_class: 'bunny-bubble-text'});
        this._text.clutter_text.line_wrap = true;
        this._text.clutter_text.set_line_wrap_mode(2); // Pango.WrapMode.WORD_CHAR
        this._column.add_child(this._text);

        // The "there is more" affordance. A button rather than a clickable
        // label because it is a control, and St.Button brings the focus ring,
        // the hover state and the accessible role with it.
        this._more = new St.Button({
            label: '',
            style_class: 'bunny-bubble-more',
            visible: false,
            can_focus: true,
            x_align: Clutter.ActorAlign.START,
        });
        this._more.connect('clicked', () => this._onOpenFull?.(this._full));
        this._column.add_child(this._more);

        this._wave = new St.DrawingArea({
            style_class: 'bunny-bubble-wave', height: 18, visible: false, reactive: false,
        });
        this._wave.connect('repaint', area => this._paintWave(area));
        this._column.add_child(this._wave);

        setAccessibleRole(this.actor, 'NOTIFICATION');
        this._wavePhase = 0;
        this._timeline = null;
        this._full = '';
        this._onOpenFull = null;
    }

    /**
     * @param {string} text
     * @param {{tone?, wave?, onOpenFull?}} options
     *   `onOpenFull` is called when the user presses the "more" affordance. It
     *   is only offered when there is more, and the caller decides what "the
     *   full response" means — the bubble does not know what other surfaces
     *   exist.
     */
    say(text, {tone = 'normal', wave = false, onOpenFull = null} = {}) {
        const full = String(text ?? '');
        const truncated = full.length > PREVIEW_LIMIT;
        // Cut at a word, not mid-token: a directory listing broken inside a
        // filename reads as a corrupted name rather than a shortened list.
        let preview = full;
        if (truncated) {
            const cut = full.slice(0, PREVIEW_LIMIT);
            const lastSpace = cut.lastIndexOf(' ');
            preview = `${(lastSpace > PREVIEW_LIMIT * 0.6 ? cut.slice(0, lastSpace) : cut).trimEnd()}…`;
        }
        this._text.text = preview;
        // The accessible name carries the *whole* answer. A screen-reader user
        // has no "read the rest in the card" affordance that is any easier than
        // hearing it here, and the truncation is a visual accommodation.
        this.actor.accessible_name = `Bunny says: ${full}`;
        this._full = full;

        this._more.visible = truncated && onOpenFull !== null;
        this._onOpenFull = onOpenFull;
        if (this._more.visible) {
            const remaining = full.length - preview.length + 1;
            this._more.label = `Read the rest (${remaining} more characters)`;
        }
        for (const name of ['bunny-bubble-warning', 'bunny-bubble-error'])
            this.actor.remove_style_class_name(name);
        if (tone === 'warning')
            this.actor.add_style_class_name('bunny-bubble-warning');
        else if (tone === 'error')
            this.actor.add_style_class_name('bunny-bubble-error');

        this._setWave(wave);
        this._reveal();
    }

    hide() {
        this._setWave(false);
        if (!this.actor.visible)
            return;
        ease(this.actor, {opacity: 0, translation_y: 8}, {
            ms: MOTION.normal,
            onComplete: () => {
                this.actor.visible = false;
            },
        });
    }

    /** Keep the decorative speaking bars tied to real playback evidence. */
    setSpeaking(active) {
        this._setWave(Boolean(active));
    }

    /**
     * Position the bubble against the figure.
     *
     * @param {{x, y, width, height}} figure in band coordinates
     * @param {{width, height}} band the character band's size
     * @param {'left'|'right'} preferred
     */
    place(figure, band, preferred = 'left') {
        const width = clamp(
            Math.min(MAX_WIDTH, Math.round(band.width * 0.32)), MIN_WIDTH, MAX_WIDTH);
        this.actor.set_width(width);

        const leftX = figure.x - width - GAP;
        const rightX = figure.x + figure.width + GAP;
        const fitsLeft = leftX >= 0;
        const fitsRight = rightX + width <= band.width;

        let x;
        let y = Math.round(figure.y + figure.height * 0.13);
        if (preferred === 'left' && fitsLeft)
            x = leftX;
        else if (preferred === 'right' && fitsRight)
            x = rightX;
        else if (fitsLeft)
            x = leftX;
        else if (fitsRight)
            x = rightX;
        else {
            // Neither side. Above the head, centred, which always fits because
            // the band is at least as wide as the figure.
            x = Math.round(figure.x + (figure.width - width) / 2);
            y = Math.max(0, figure.y - 96);
        }
        this.actor.set_position(Math.round(clamp(x, 0, Math.max(0, band.width - width))), y);
    }

    destroy() {
        this._timeline?.stop();
        this._timeline = null;
        this.actor.destroy();
    }

    _reveal() {
        if (this.actor.visible && this.actor.opacity === 255)
            return;
        this.actor.visible = true;
        this.actor.opacity = 0;
        this.actor.translation_y = 10;
        ease(this.actor, {opacity: 255, translation_y: 0}, {ms: MOTION.normal});
    }

    _setWave(enabled) {
        this._wave.visible = enabled;
        if (!enabled) {
            this._timeline?.stop();
            this._timeline = null;
            return;
        }
        if (this._timeline !== null || !animationsEnabled())
            return;
        this._timeline = new Clutter.Timeline({
            actor: this._wave, duration: 1200, repeat_count: -1,
        });
        this._timeline.connect('new-frame', () => {
            this._wavePhase = (GLib.get_monotonic_time() / 1e6) % 100;
            this._wave.queue_repaint();
        });
        this._timeline.start();
    }

    _paintWave(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            if (width <= 0 || height <= 0)
                return;
            const bars = 4;
            const barWidth = 4;
            const gap = 5;
            const total = bars * barWidth + (bars - 1) * gap;
            const [r, g, b] = rgb('accentText');
            cr.setSourceRGBA(r, g, b, 0.9);
            cr.setLineCap(Cairo.LineCap.ROUND);
            cr.setLineWidth(barWidth);
            for (let index = 0; index < bars; index += 1) {
                const phase = this._wavePhase * 4 + index * 0.7;
                const amplitude = 0.35 + 0.65 * Math.abs(Math.sin(phase));
                const barHeight = Math.max(barWidth, height * amplitude);
                const x = (width - total) / 2 + index * (barWidth + gap) + barWidth / 2;
                cr.newPath();
                cr.moveTo(x, height / 2 - barHeight / 2 + barWidth / 2);
                cr.lineTo(x, height / 2 + barHeight / 2 - barWidth / 2);
                cr.stroke();
            }
        } catch (error) {
            logError_('the bubble waveform could not be drawn', error);
        } finally {
            cr?.$dispose();
        }
    }
}
