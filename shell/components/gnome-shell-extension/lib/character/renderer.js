// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// How the character is drawn, and the seam that lets something else draw it.
//
// ## Why vector and not the GLB
//
// The repository already has a 3D character: assets/companion/characters/
// default-bunny-3d ships a GLB and companion/character/three_d renders it
// through a GTK4 GLArea. None of that is reachable from here. A GNOME Shell
// extension runs inside the compositor process, in GJS, with no GTK and no GL
// context of its own; a Wayland client cannot have its surface reparented into
// the shell's scene graph, so the existing renderer can be a window beside the
// desktop but not the figure standing on it. That is a protocol boundary, not
// an effort estimate.
//
// The other shipped option is the per-state PNG set in the same packages. Those
// frames are 96x96. The figure the brief asks for occupies roughly 320x460, so
// they would be upscaled about fivefold. They are not used for that reason and
// no other; ImageCharacterRenderer below can play them, and will look right the
// day a package ships frames at the size the viewport allocates.
//
// So the default renderer draws the figure with Cairo, from the data in
// definition.js. It is resolution-independent, costs no GPU, runs on llvmpipe
// in a VM, and — the point of the seam — is one implementation of
// CharacterRenderer among several.
//
// ## The interface
//
// A renderer is any object with:
//
//   actor            a Clutter actor the viewport parents and sizes
//   setState(name)   adopt a state from character/state.js
//   setLevel(v)      0..1 speech amplitude, for mouth movement; may be ignored
//   setSize(w, h)    the viewport's allocation changed
//   destroy()
//
// Nothing else. createRenderer() is the only place that knows which
// implementations exist.

import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {DEFAULT_CHARACTER} from './definition.js';
import {drawFigure} from './figure.js';
import {animationsEnabled} from '../animation.js';
import {clamp, logOnce, logError_} from '../util.js';

/**
 * Redraws per second while animating.
 *
 * Not 60. The character's motion is breathing and a slow bob over a four-second
 * cycle; at 24 the difference is not visible and the Cairo cost is 40% of what
 * it would be. On the llvmpipe path that this image has to remain usable on,
 * that difference is the difference between a desktop that idles under 3% of a
 * core and one that does not.
 */
const TARGET_FPS = 24;
const FRAME_US = Math.round(1e6 / TARGET_FPS);

/** How fast a pose parameter closes on its target, per second. */
const POSE_EASE_PER_SECOND = 3.6;

export function createRenderer(kind, options) {
    switch (kind) {
    case 'image':
        return new ImageCharacterRenderer(options);
    case 'vector':
    default:
        return new VectorCharacterRenderer(options);
    }
}

/**
 * The animator: current pose values chasing the target pose.
 *
 * Kept apart from the drawing so a second renderer gets the same easing, the
 * same blink timing and the same breathing phase without copying any of it —
 * which is what makes two renderers look like the same character rather than
 * two characters.
 */
class PoseAnimator {
    constructor(definition) {
        this._definition = definition;
        this._target = definition.poses.idle;
        this._current = {...definition.poses.idle};
        this._phase = 0;
        this._blinkAt = 0;
        this._blink = 1;
        this._level = 0;
        this._talkPhase = 0;
        this._indicatorPhase = 0;
    }

    setState(state) {
        this._target = this._definition.poses[state] ?? this._definition.poses.idle;
        this._state = state;
    }

    setLevel(level) {
        this._level = clamp(level, 0, 1);
    }

    /** @param {number} deltaSeconds since the last advance */
    advance(deltaSeconds) {
        const k = Math.min(1, POSE_EASE_PER_SECOND * deltaSeconds);
        for (const key of ['breathe', 'bob', 'armLift', 'headTilt', 'lean', 'eyeOpen', 'mouthOpen', 'glow']) {
            const from = this._current[key] ?? 0;
            const to = this._target[key] ?? 0;
            this._current[key] = from + (to - from) * k;
        }
        this._current.accent = this._target.accent;
        this._current.indicator = this._target.indicator ?? 'none';

        const period = (this._target.period ?? 4000) / 1000;
        this._phase = (this._phase + deltaSeconds / period) % 1;
        this._talkPhase = (this._talkPhase + deltaSeconds * 7.5) % 1;
        // The indicator runs on its own slow clock rather than the body's, so a
        // thinking figure's dots do not pulse in lockstep with its breathing.
        this._indicatorPhase = (this._indicatorPhase + deltaSeconds / 1.6) % 1;

        this._advanceBlink(deltaSeconds);
    }

    _advanceBlink(deltaSeconds) {
        const rate = this._target.blinkRate ?? 0;
        if (rate === 0) {
            this._blink = 1;
            return;
        }
        this._blinkAt -= deltaSeconds;
        if (this._blinkAt <= 0) {
            // Poisson-ish rather than metronomic: an eye that blinks on an
            // exact 4.3-second beat reads as a machine, which is the one thing
            // a character must not read as.
            const mean = 60 / rate;
            this._blinkAt = mean * (0.55 + Math.random() * 0.9);
            this._blinkStarted = 0.16;
        }
        if (this._blinkStarted > 0) {
            this._blinkStarted -= deltaSeconds;
            const t = clamp(this._blinkStarted / 0.16, 0, 1);
            // Down and back up over 160ms.
            this._blink = Math.abs(t - 0.5) * 2;
        } else {
            this._blink = 1;
        }
    }

    /** The values the renderer draws with. */
    values() {
        const wave = Math.sin(this._phase * Math.PI * 2);
        const talking = this._state === 'talking' || this._level > 0.02;
        const mouth = talking
            ? clamp(this._current.mouthOpen + (0.34 * Math.max(this._level,
                0.5 + 0.5 * Math.sin(this._talkPhase * Math.PI * 2))), 0, 1)
            : this._current.mouthOpen;
        return {
            breathe: this._current.breathe * wave,
            bob: this._current.bob * wave,
            armLift: this._current.armLift + this._current.armLift * 0.12 * wave,
            headTilt: this._current.headTilt,
            lean: this._current.lean,
            eyeOpen: clamp(this._current.eyeOpen * this._blink, 0, 1),
            mouthOpen: mouth,
            glow: this._current.glow,
            accent: this._current.accent ?? 'rimLight',
            indicator: this._current.indicator ?? 'none',
            indicatorPhase: this._indicatorPhase,
        };
    }
}

/** Draws the figure defined in definition.js with Cairo. */
export class VectorCharacterRenderer {
    constructor({definition = DEFAULT_CHARACTER} = {}) {
        this.kind = 'vector';
        this._definition = definition;
        this._animator = new PoseAnimator(definition);
        this._lastFrameUs = 0;
        this._lastPaintUs = 0;

        this.actor = new St.DrawingArea({
            style_class: 'bunny-character-surface',
            reactive: false,
            x_expand: true,
            y_expand: true,
        });
        this.actor.connect('repaint', area => this._paint(area));

        // Frame-clock driven rather than timer driven: Clutter fires new-frame
        // in step with the compositor, so a repaint queued here lands in the
        // frame being assembled instead of provoking an extra one.
        this._timeline = new Clutter.Timeline({
            actor: this.actor,
            duration: 4000,
            repeat_count: -1,
        });
        this._timeline.connect('new-frame', () => this._tick());
        if (animationsEnabled())
            this._timeline.start();
        else
            logOnce('character-static', 'animations are disabled; the character is drawn in a resting pose');
    }

    setState(state) {
        this._animator.setState(state);
        if (!animationsEnabled()) {
            // Reduced motion still changes pose, it just does not animate to it.
            this._animator.advance(1);
            this.actor.queue_repaint();
        }
    }

    setLevel(level) {
        this._animator.setLevel(level);
    }

    setSize(width, height) {
        this.actor.set_size(width, height);
        this.actor.queue_repaint();
    }

    destroy() {
        this._timeline?.stop();
        this._timeline = null;
        this.actor.destroy();
    }

    _tick() {
        const now = GLib.get_monotonic_time();
        if (this._lastFrameUs === 0)
            this._lastFrameUs = now;
        const delta = (now - this._lastFrameUs) / 1e6;
        this._lastFrameUs = now;
        this._animator.advance(Math.min(delta, 0.2));
        if (now - this._lastPaintUs < FRAME_US)
            return;
        this._lastPaintUs = now;
        this.actor.queue_repaint();
    }

    _paint(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            if (width <= 0 || height <= 0)
                return;
            const pose = this._animator.values();
            drawFigure(cr, this._definition, pose, width, height);
        } catch (error) {
            logError_('the character could not be drawn', error);
        } finally {
            cr?.$dispose();
        }
    }
}

/**
 * Plays a character package's per-state PNG frames.
 *
 * Present so the seam is real rather than asserted: it is a complete second
 * implementation of the interface, and it is what a package with
 * viewport-sized art would use. It is not the default, for the reason in the
 * module note — the packages that exist ship 96px frames.
 */
export class ImageCharacterRenderer {
    constructor({packagePath, frames = {}} = {}) {
        this.kind = 'image';
        this._frames = frames;
        this._packagePath = packagePath;
        this.actor = new St.Widget({
            style_class: 'bunny-character-surface',
            layout_manager: new Clutter.BinLayout(),
        });
        this._image = new St.Icon({icon_size: 256, style_class: 'bunny-character-frame'});
        this.actor.add_child(this._image);
        this.setState('idle');
    }

    setState(state) {
        const relative = this._frames[state] ?? this._frames.idle;
        if (!relative) {
            logOnce(`character-frame-${state}`, `the character package has no frame for ${state}`);
            return;
        }
        this._image.gicon = Gio.FileIcon.new(
            Gio.File.new_for_path(GLib.build_filenamev([this._packagePath, relative])));
    }

    setLevel(_level) {
        // Frame packages have no continuous mouth channel; the speaking-open and
        // speaking-closed frames are what they offer, and switching between them
        // on an amplitude threshold looks worse than holding one.
    }

    setSize(width, height) {
        this._image.icon_size = Math.max(64, Math.min(width, height));
    }

    destroy() {
        this.actor.destroy();
    }
}

