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

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {DEFAULT_CHARACTER} from './definition.js';
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

        const period = (this._target.period ?? 4000) / 1000;
        this._phase = (this._phase + deltaSeconds / period) % 1;
        this._talkPhase = (this._talkPhase + deltaSeconds * 7.5) % 1;

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

// --------------------------------------------------------------------------
// The drawing itself. Pure functions of (context, definition, pose, size), so
// nothing here holds state and the same code draws any definition.
// --------------------------------------------------------------------------

const BOX_WIDTH = 100;
const BOX_HEIGHT = 150;

function setColour(cr, palette, name, alpha = 1) {
    const [r, g, b] = palette[name] ?? [1, 0, 1];
    cr.setSourceRGBA(r, g, b, alpha);
}

/** A vertical capsule: the shape every limb and the torso are built from. */
function capsule(cr, x, yTop, yBottom, topHalf, bottomHalf) {
    cr.newPath();
    cr.arc(x, yTop, topHalf, Math.PI, 0);
    cr.lineTo(x + bottomHalf, yBottom);
    cr.arc(x, yBottom, bottomHalf, 0, Math.PI);
    cr.closePath();
}

function drawFigure(cr, definition, pose, width, height) {
    const palette = definition.palette;
    const g = definition.geometry;

    // Fit the 100x150 box into the allocation, centred, with the feet a little
    // above the bottom edge so the floor glow has room.
    const scale = Math.min(width / BOX_WIDTH, height / BOX_HEIGHT);
    cr.save();
    cr.translate((width - BOX_WIDTH * scale) / 2, (height - BOX_HEIGHT * scale) / 2);
    cr.scale(scale, scale);

    const bob = pose.bob;
    const lean = pose.lean;

    // Ground shadow first, and it does not bob with the figure — it tightens
    // instead. A shadow that moved with the body would look like the floor was
    // moving.
    const shadowTightness = 1 - bob * 0.04;
    cr.save();
    cr.translate(BOX_WIDTH / 2, g.groundShadow.y);
    cr.scale(g.groundShadow.radiusX * shadowTightness, g.groundShadow.radiusY * shadowTightness);
    cr.arc(0, 0, 1, 0, Math.PI * 2);
    cr.restore();
    cr.setSourceRGBA(0, 0, 0, 0.42);
    cr.fill();

    cr.save();
    // The lean pivots at the feet, not the centre, or the figure slides.
    cr.translate(BOX_WIDTH / 2, g.groundShadow.y);
    cr.rotate((lean * Math.PI) / 180);
    cr.translate(-BOX_WIDTH / 2, -g.groundShadow.y + bob);

    drawHood(cr, palette, g);
    drawLegs(cr, palette, g);
    drawTorso(cr, palette, g, pose);
    drawArms(cr, palette, g, pose);
    drawNeck(cr, palette, g);
    drawHead(cr, palette, g, pose);
    drawLogo(cr, palette, g, pose);
    drawRimLight(cr, palette, g, pose);

    cr.restore();
    cr.restore();
}

function drawHood(cr, palette, g) {
    // The hood sits behind the head and shoulders: a wide arc that reads as
    // fabric bunched at the neck.
    cr.newPath();
    cr.moveTo(50 - g.hood.halfWidth, g.shoulder.y + 2);
    cr.curveTo(
        50 - g.hood.halfWidth - 2, g.hood.y - g.hood.depth,
        50 + g.hood.halfWidth + 2, g.hood.y - g.hood.depth,
        50 + g.hood.halfWidth, g.shoulder.y + 2);
    cr.closePath();
    setColour(cr, palette, 'hood');
    cr.fill();
}

function drawLegs(cr, palette, g) {
    const half = g.leg.separation / 2;
    for (const side of [-1, 1]) {
        const x = 50 + side * half;
        capsule(cr, x, g.hip.y + 2, g.hip.y + g.leg.length,
            g.leg.thighWidth / 2, g.leg.ankleWidth / 2);
        const gradient = new Cairo.LinearGradient(x - 6, 0, x + 6, 0);
        const [r, gg, b] = palette.trousers;
        const [hr, hg, hb] = palette.trousersHighlight;
        gradient.addColorStopRGBA(0, hr, hg, hb, 1);
        gradient.addColorStopRGBA(0.55, r, gg, b, 1);
        gradient.addColorStopRGBA(1, r * 0.8, gg * 0.8, b * 0.8, 1);
        cr.setSource(gradient);
        cr.fill();
    }

    // Sneakers. Both point outwards from the centre line, so the toe direction
    // is the side sign and the whole shape is drawn once in a mirrored frame
    // rather than twice with a sign scattered through every coordinate.
    for (const side of [-1, 1]) {
        const x = 50 + side * half;
        const top = g.hip.y + g.leg.length - 1;
        const upper = g.shoe.height - g.shoe.soleHeight;
        const heel = g.leg.ankleWidth / 2 + 1.5;
        const toe = g.shoe.length - heel;

        cr.save();
        cr.translate(x, top);
        cr.scale(side, 1);

        cr.newPath();
        cr.moveTo(-heel, 0);
        cr.lineTo(g.leg.ankleWidth / 2, -1.2);
        cr.curveTo(toe * 0.55, 0.4, toe * 0.92, upper * 0.45, toe, upper);
        cr.lineTo(-heel, upper);
        cr.closePath();
        setColour(cr, palette, 'shoe');
        cr.fill();

        cr.newPath();
        cr.rectangle(-heel, upper, heel + toe, g.shoe.soleHeight);
        setColour(cr, palette, 'shoeSole');
        cr.fill();

        cr.newPath();
        cr.rectangle(-1.0, 1.0, 1.7, upper - 2.0);
        setColour(cr, palette, 'shoeAccent');
        cr.fill();
        cr.restore();
    }
}

function drawTorso(cr, palette, g, pose) {
    const breathe = pose.breathe * 0.5;
    capsule(cr, 50, g.torso.top + 4, g.torso.bottom,
        g.torso.topHalfWidth + breathe, g.torso.bottomHalfWidth);
    const gradient = new Cairo.LinearGradient(50 - g.torso.topHalfWidth, 0, 50 + g.torso.topHalfWidth, 0);
    const [r, gg, b] = palette.hoodie;
    const [hr, hg, hb] = palette.hoodieHighlight;
    const [sr, sg, sb] = palette.hoodieShadow;
    gradient.addColorStopRGBA(0, hr, hg, hb, 1);
    gradient.addColorStopRGBA(0.42, r, gg, b, 1);
    gradient.addColorStopRGBA(1, sr, sg, sb, 1);
    cr.setSource(gradient);
    cr.fill();

    // Pocket seam and the two drawstrings: the details that make it read as a
    // hoodie rather than a jumper, at three paths.
    cr.newPath();
    cr.moveTo(50 - 11, g.torso.bottom - 12);
    cr.curveTo(50 - 5, g.torso.bottom - 8, 50 + 5, g.torso.bottom - 8, 50 + 11, g.torso.bottom - 12);
    setColour(cr, palette, 'hoodieShadow');
    cr.setLineWidth(0.9);
    cr.stroke();

    setColour(cr, palette, 'drawstring');
    cr.setLineWidth(0.8);
    for (const side of [-1, 1]) {
        cr.newPath();
        cr.moveTo(50 + side * 3.2, g.torso.top + 5);
        cr.curveTo(
            50 + side * 3.6, g.torso.top + 10,
            50 + side * 2.4, g.torso.top + 13,
            50 + side * 3.0, g.torso.top + 16);
        cr.stroke();
    }
}

function drawArms(cr, palette, g, pose) {
    const lift = pose.armLift;
    for (const side of [-1, 1]) {
        const shoulderX = 50 + side * (g.shoulder.halfWidth - g.arm.shoulderInset);
        const shoulderY = g.shoulder.y + 1;
        // Lift swings the hand outwards and upwards around the shoulder.
        const angle = side * (0.10 + lift * 0.75);
        const handX = shoulderX + Math.sin(angle) * g.arm.length;
        const handY = shoulderY + Math.cos(angle) * g.arm.length;

        cr.save();
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.newPath();
        cr.moveTo(shoulderX, shoulderY);
        // One control point at the elbow, offset against the swing so the arm
        // bends rather than pivoting like a stick.
        cr.curveTo(
            shoulderX + Math.sin(angle) * g.arm.length * 0.35 - side * 1.5,
            shoulderY + g.arm.length * 0.42,
            handX - side * 1.0, handY - g.arm.length * 0.22,
            handX, handY);
        setColour(cr, palette, 'hoodie');
        cr.setLineWidth(g.sleeve.width);
        cr.strokePreserve();
        setColour(cr, palette, side < 0 ? 'hoodieHighlight' : 'hoodieShadow', 0.55);
        cr.setLineWidth(g.sleeve.width - 3.2);
        cr.stroke();
        cr.restore();

        cr.newPath();
        cr.arc(handX, handY + 1.4, g.arm.handRadius, 0, Math.PI * 2);
        setColour(cr, palette, side < 0 ? 'skin' : 'skinShadow');
        cr.fill();
    }
}

function drawNeck(cr, palette, g) {
    capsule(cr, g.neck.x, g.neck.top, g.neck.bottom, g.neck.width / 2, g.neck.width / 2);
    setColour(cr, palette, 'skinShadow');
    cr.fill();
}

function drawHead(cr, palette, g, pose) {
    const [cx, cy] = g.headCentre;
    const radius = g.headRadius;

    cr.save();
    cr.translate(cx, cy);
    cr.rotate((pose.headTilt * Math.PI) / 180);
    cr.translate(-cx, -cy);

    // Hair, behind: a slightly larger dome so it shows as an outline.
    cr.newPath();
    cr.arc(cx, cy - 1.2, radius + 1.4, Math.PI, Math.PI * 2);
    cr.lineTo(cx + radius + 1.4, cy + 3);
    cr.lineTo(cx - radius - 1.4, cy + 3);
    cr.closePath();
    setColour(cr, palette, 'hair');
    cr.fill();

    // Face: a circle narrowed towards the jaw.
    cr.save();
    cr.translate(cx, cy);
    cr.scale(1, 1.06);
    cr.newPath();
    cr.arc(0, 0, radius, 0, Math.PI * 2);
    cr.restore();
    const faceGradient = new Cairo.LinearGradient(cx - radius, 0, cx + radius, 0);
    const [kr, kg, kb] = palette.skin;
    const [dr, dg, db] = palette.skinShadow;
    faceGradient.addColorStopRGBA(0, Math.min(1, kr * 1.06), Math.min(1, kg * 1.06), Math.min(1, kb * 1.06), 1);
    faceGradient.addColorStopRGBA(0.6, kr, kg, kb, 1);
    faceGradient.addColorStopRGBA(1, dr, dg, db, 1);
    cr.setSource(faceGradient);
    cr.fill();

    // Fringe, in front of the face.
    cr.newPath();
    cr.moveTo(cx - radius - 0.6, cy - 2.4);
    cr.curveTo(cx - radius * 0.6, cy - radius - 2.2, cx + radius * 0.5, cy - radius - 2.6,
        cx + radius + 0.4, cy - 3.6);
    cr.curveTo(cx + radius * 0.5, cy - radius * 0.42, cx - radius * 0.2, cy - radius * 0.30,
        cx - radius - 0.6, cy - 2.4);
    cr.closePath();
    setColour(cr, palette, 'hair');
    cr.fill();
    cr.newPath();
    cr.moveTo(cx - radius * 0.42, cy - radius * 0.86);
    cr.curveTo(cx - radius * 0.10, cy - radius * 1.06, cx + radius * 0.24, cy - radius * 1.00,
        cx + radius * 0.46, cy - radius * 0.78);
    setColour(cr, palette, 'hairHighlight', 0.75);
    cr.setLineWidth(1.1);
    cr.stroke();

    drawFace(cr, palette, g, pose, cx, cy);
    cr.restore();
}

function drawFace(cr, palette, g, pose, cx, cy) {
    const open = pose.eyeOpen;
    for (const side of [-1, 1]) {
        const ex = cx + side * g.eyes.offsetX;
        const ey = cy + g.eyes.offsetY;
        if (open < 0.12) {
            // A closed eye is a line, not a squashed circle: a 0.1-tall ellipse
            // renders as a grey smudge at this scale.
            cr.newPath();
            cr.moveTo(ex - g.eyes.radius, ey);
            cr.lineTo(ex + g.eyes.radius, ey);
            setColour(cr, palette, 'eye');
            cr.setLineWidth(0.85);
            cr.stroke();
            continue;
        }
        cr.save();
        cr.translate(ex, ey);
        cr.scale(1, Math.max(0.12, open));
        cr.newPath();
        cr.arc(0, 0, g.eyes.radius, 0, Math.PI * 2);
        cr.restore();
        setColour(cr, palette, 'eye');
        cr.fill();

        // Catchlight. One pixel of white is the difference between an eye and a
        // dot, and it is the cheapest thing in this file.
        cr.newPath();
        cr.arc(ex + 0.6, ey - 0.6 * open, g.eyes.radius * 0.32, 0, Math.PI * 2);
        cr.setSourceRGBA(1, 1, 1, 0.85 * open);
        cr.fill();

        cr.newPath();
        cr.moveTo(ex - g.brow.length / 2, ey + g.brow.offsetY);
        cr.lineTo(ex + g.brow.length / 2, ey + g.brow.offsetY - side * 0.35);
        setColour(cr, palette, 'hair');
        cr.setLineWidth(0.95);
        cr.stroke();
    }

    const mouthY = cy + g.mouth.offsetY;
    const opening = pose.mouthOpen;
    cr.newPath();
    if (opening < 0.10) {
        cr.moveTo(cx - g.mouth.width / 2, mouthY);
        cr.curveTo(cx - g.mouth.width / 6, mouthY + 0.9,
            cx + g.mouth.width / 6, mouthY + 0.9,
            cx + g.mouth.width / 2, mouthY);
        setColour(cr, palette, 'mouth');
        cr.setLineWidth(0.9);
        cr.stroke();
    } else {
        cr.save();
        cr.translate(cx, mouthY);
        cr.scale(g.mouth.width / 2, Math.max(0.6, opening * 3.0));
        cr.arc(0, 0, 1, 0, Math.PI * 2);
        cr.restore();
        setColour(cr, palette, 'mouth');
        cr.fill();
    }
}

/** The Bunny mark on the chest: two ears and a head, in the accent colour. */
function drawLogo(cr, palette, g, pose) {
    const [lx, ly] = g.logo.centre;
    const size = g.logo.size;
    const breathe = pose.breathe * 0.25;
    cr.save();
    cr.translate(lx, ly + breathe);
    cr.scale(size / 12, size / 12);
    setColour(cr, palette, 'logo', 0.95);
    for (const side of [-1, 1]) {
        cr.save();
        cr.translate(side * 2.4, -3.4);
        cr.rotate((side * 12 * Math.PI) / 180);
        cr.scale(1, 2.6);
        cr.newPath();
        cr.arc(0, 0, 1.45, 0, Math.PI * 2);
        cr.restore();
        cr.fill();
    }
    cr.newPath();
    cr.arc(0, 2.6, 3.5, 0, Math.PI * 2);
    cr.fill();
    cr.restore();
}

/**
 * The violet edge light.
 *
 * Drawn last, as a stroke down the figure's left silhouette. It is what makes
 * a flat vector figure sit in the scene rather than on it, and it is the one
 * place the character picks up the state colour — success turns the rim green,
 * error turns it red — so the state is legible from across the room without
 * reading the bubble.
 */
function drawRimLight(cr, palette, g, pose) {
    const colour = palette[pose.accent] ?? palette.rimLight;
    const [r, gg, b] = colour;
    const strength = clamp(0.34 * pose.glow, 0, 0.8);
    cr.save();
    cr.setLineCap(Cairo.LineCap.ROUND);
    cr.setSourceRGBA(r, gg, b, strength);
    cr.setLineWidth(1.5);

    cr.newPath();
    cr.arc(g.headCentre[0], g.headCentre[1], g.headRadius + 0.4,
        Math.PI * 0.62, Math.PI * 1.30);
    cr.stroke();

    cr.newPath();
    cr.moveTo(50 - g.torso.topHalfWidth + 0.6, g.torso.top + 6);
    cr.lineTo(50 - g.torso.bottomHalfWidth + 0.4, g.torso.bottom - 2);
    cr.stroke();

    cr.newPath();
    cr.moveTo(50 - g.leg.separation / 2 - g.leg.thighWidth / 2 + 0.4, g.hip.y + 4);
    cr.lineTo(50 - g.leg.separation / 2 - g.leg.ankleWidth / 2 + 0.4, g.hip.y + g.leg.length - 2);
    cr.stroke();
    cr.restore();
}
