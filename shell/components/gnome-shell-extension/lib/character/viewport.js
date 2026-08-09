// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// CharacterViewport: the greeting, the floor, the figure, and the hit target.
//
// The viewport owns the band the layout solver reserved and decides how to use
// it; the renderer only draws a figure into a rectangle it is handed. That
// split is what lets the figure be replaced without touching the greeting, the
// glow or the click behaviour — and it is why the glow is here and not in the
// renderer, even though it is the same Cairo pass away.
//
// The glow responds to state, which the brief asks for, and it is the only
// element that does so with colour as well as intensity. That is on purpose: it
// is a large, soft, low-frequency shape, so a hue change in it is legible from
// across a room and is not the sort of thing that makes text hard to read. The
// panels never change colour with state for exactly the opposite reason.

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Rgb} from '../tokens.js';
import {box} from '../widgets.js';
import {createRenderer} from './renderer.js';
import {DEFAULT_CHARACTER} from './definition.js';
import {ease, animationsEnabled} from '../animation.js';
import {clamp, logError_, makeActivatable} from '../util.js';

/** Which token colour the floor glow takes in each state. */
const GLOW_COLOUR = {
    idle: Rgb.ACCENT,
    listening: Rgb.ACCENT_BRIGHT,
    thinking: Rgb.ACCENT,
    working: Rgb.ACCENT_BRIGHT,
    success: Rgb.SUCCESS,
    celebrating: Rgb.SUCCESS,
    warning: Rgb.WARNING,
    error: Rgb.ERROR,
    talking: Rgb.ACCENT_BRIGHT,
    sleeping: Rgb.ACCENT,
};

const GLOW_INTENSITY = {
    idle: 0.55, listening: 0.85, thinking: 0.65, working: 0.80,
    success: 0.95, celebrating: 1.0, warning: 0.80, error: 0.85,
    talking: 0.80, sleeping: 0.22,
};

export class CharacterViewport {
    /**
     * @param {{stateManager, onActivate: () => void, definition?, rendererKind?}} context
     */
    constructor(context) {
        this._context = context;
        this._rect = {x: 0, y: 0, width: 400, height: 600};
        this._glowColour = GLOW_COLOUR.idle;
        this._glowIntensity = GLOW_INTENSITY.idle;
        this._glowPulse = 0;

        // FixedLayout, not BinLayout. Every child here is placed by
        // setGeometry at a computed position — the greeting at the top-left,
        // the glow under the feet, the figure between them — and BinLayout
        // would centre all four on top of each other and discard those
        // positions.
        this.actor = new St.Widget({
            style_class: 'bunny-character-viewport',
            layout_manager: new Clutter.FixedLayout(),
        });

        this._greeting = this._buildGreeting();
        this.actor.add_child(this._greeting);

        this._glow = new St.DrawingArea({style_class: 'bunny-character-glow', reactive: false});
        this._glow.connect('repaint', area => this._paintGlow(area));
        this.actor.add_child(this._glow);

        this._renderer = createRenderer(context.rendererKind ?? 'vector', {
            definition: context.definition ?? DEFAULT_CHARACTER,
        });
        this.actor.add_child(this._renderer.actor);

        // The hit target is a separate transparent actor covering the figure
        // rather than the figure itself. A DrawingArea that is reactive gets a
        // pick pass on every pointer motion over the desktop, and the pick for
        // a Cairo surface is its bounding box anyway — so this costs the same
        // and keeps the renderer free of input concerns.
        this._hit = new St.Widget({style_class: 'bunny-character-hit'});
        makeActivatable(this._hit, () => {
            this._context.stateManager.noteActivity();
            this._context.onActivate?.();
        }, {accessibleName: 'Bunny, your assistant'});
        this._hit.connect('notify::hover', () => {
            ease(this._glow, {opacity: this._hit.hover ? 255 : 220}, {ms: 200});
        });
        this.actor.add_child(this._hit);

        this._unsubscribe = context.stateManager.subscribe((state, reason) =>
            this._onState(state, reason));

        // The glow breathes on its own clock, slower than the figure, so the
        // two are not visibly locked together.
        this._timeline = new Clutter.Timeline({
            actor: this._glow, duration: 5200, repeat_count: -1,
        });
        this._timeline.connect('new-frame', () => {
            this._glowPulse = Math.sin(
                (GLib.get_monotonic_time() / 1e6) * (Math.PI * 2 / 5.2));
            this._glow.queue_repaint();
        });
        if (animationsEnabled())
            this._timeline.start();
    }

    /** @param {{x, y, width, height}} rect the band the layout solver assigned */
    setGeometry(rect) {
        this._rect = rect;
        this.actor.set_position(rect.x, rect.y);
        this.actor.set_size(rect.width, rect.height);

        // The figure is sized from the band's height, capped so it does not
        // become a giant on a 1440p screen, and centred horizontally with its
        // feet a fifth of the way up from the bottom — where the dock is not.
        //
        // 0.78 of the band, not 0.68. The character is the desktop's primary
        // interaction surface and at the smaller figure it read as one more
        // widget among six — the booted screenshots show it about the same
        // visual weight as the System card beside it. The cap moved with it so
        // a 1440p screen still gets a person rather than a poster.
        const figureHeight = clamp(rect.height * 0.78, 280, 600);
        const figureWidth = figureHeight * (100 / 150);
        const figureX = Math.round((rect.width - figureWidth) / 2);
        const figureY = Math.round(rect.height - figureHeight - rect.height * 0.06);

        this._renderer.actor.set_position(figureX, figureY);
        this._renderer.setSize(Math.round(figureWidth), Math.round(figureHeight));

        this._hit.set_position(figureX, figureY);
        this._hit.set_size(Math.round(figureWidth), Math.round(figureHeight));

        // The glow is an ellipse under the feet, wider than the figure.
        const glowWidth = Math.round(figureWidth * 1.9);
        const glowHeight = Math.round(figureHeight * 0.34);
        this._glow.set_position(
            Math.round((rect.width - glowWidth) / 2),
            Math.round(figureY + figureHeight - glowHeight * 0.62));
        this._glow.set_size(glowWidth, glowHeight);
        this._glow.queue_repaint();

        this._greeting.set_position(0, 0);
        this._greeting.set_width(rect.width);
    }

    /** Speech amplitude, 0..1, forwarded to whichever renderer is loaded. */
    setLevel(level) {
        this._renderer.setLevel(level);
    }

    /** The rectangle the figure occupies, for the bubbles to position against. */
    figureRect() {
        return {
            x: this._rect.x + this._renderer.actor.get_x(),
            y: this._rect.y + this._renderer.actor.get_y(),
            width: this._renderer.actor.get_width(),
            height: this._renderer.actor.get_height(),
        };
    }

    destroy() {
        this._timeline?.stop();
        this._timeline = null;
        this._unsubscribe?.();
        this._renderer.destroy();
        this.actor.destroy();
    }

    _buildGreeting() {
        const column = box({vertical: true, style_class: 'bunny-greeting'});
        const name = GLib.get_real_name();
        const first = (name && name !== 'Unknown' ? name : GLib.get_user_name() ?? '')
            .trim().split(/\s+/)[0] || 'there';
        // No emoji. The greeting is the first line of text on the desktop and
        // it read "Good evening, Bunny □" on the first booted image, because
        // the wave was a codepoint the installed fonts did not have. The font
        // is installed now; the greeting still does not depend on it, because
        // the sentence was never improved by the wave and a first impression
        // is the worst place to find out a font is missing.
        this._hello = new St.Label({
            text: `${timeOfDayGreeting()}, ${first}`,
            style_class: 'bunny-greeting-primary',
        });
        this._prompt = new St.Label({
            text: 'How can I help you today?',
            style_class: 'bunny-greeting-secondary',
        });
        column.add_child(this._hello);
        column.add_child(this._prompt);
        return column;
    }

    _onState(state, reason) {
        this._renderer.setState(state);
        this._glowColour = GLOW_COLOUR[state] ?? GLOW_COLOUR.idle;
        this._glowIntensity = GLOW_INTENSITY[state] ?? GLOW_INTENSITY.idle;
        this._glow.queue_repaint();

        // The state goes in the accessible *name*, not the description.
        //
        // `accessible_description` does nothing. St actors expose
        // `accessible-name` and `accessible-role`; assigning
        // `accessible_description` in GJS creates an ordinary JavaScript
        // property on the object and no assistive technology ever sees it.
        // Measured: every control in the desktop's accessibility tree reported
        // an empty description, including this one — so a screen-reader user
        // was told the character exists and never told what it is doing, which
        // for a figure whose entire job is to show what is happening is most of
        // the information gone.
        //
        // The name changes on every transition, which is what an assistive
        // technology watches. It is also what makes the state observable from
        // outside the process, so the harness can watch the lifecycle without
        // the desktop growing a test hook.
        this._hit.accessible_name = reason
            ? `Bunny, your assistant — ${state}. ${reason}`
            : `Bunny, your assistant — ${state}`;
    }

    _paintGlow(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            if (width <= 0 || height <= 0)
                return;
            const [r, g, b] = this._glowColour;
            const breath = animationsEnabled() ? 1 + this._glowPulse * 0.06 : 1;
            const peak = clamp(this._glowIntensity * breath, 0, 1);

            cr.save();
            cr.translate(width / 2, height / 2);
            cr.scale(width / 2, height / 2);
            const gradient = new Cairo.RadialGradient(0, 0, 0.04, 0, 0, 1);
            gradient.addColorStopRGBA(0, r, g, b, 0.42 * peak);
            gradient.addColorStopRGBA(0.38, r, g, b, 0.20 * peak);
            gradient.addColorStopRGBA(1, r, g, b, 0);
            cr.setSource(gradient);
            cr.arc(0, 0, 1, 0, Math.PI * 2);
            cr.fill();
            cr.restore();

            // A tighter ring right under the feet, so the figure reads as
            // standing on the glow rather than floating in it.
            cr.save();
            cr.translate(width / 2, height * 0.52);
            cr.scale(width * 0.17, height * 0.075);
            const core = new Cairo.RadialGradient(0, 0, 0.1, 0, 0, 1);
            core.addColorStopRGBA(0, r, g, b, 0.55 * peak);
            core.addColorStopRGBA(1, r, g, b, 0);
            cr.setSource(core);
            cr.arc(0, 0, 1, 0, Math.PI * 2);
            cr.fill();
            cr.restore();
        } catch (error) {
            logError_('the floor glow could not be drawn', error);
        } finally {
            cr?.$dispose();
        }
    }
}

function timeOfDayGreeting() {
    const hour = GLib.DateTime.new_now_local().get_hour();
    if (hour < 5)
        return 'Still up';
    if (hour < 12)
        return 'Good morning';
    if (hour < 18)
        return 'Good afternoon';
    return 'Good evening';
}
