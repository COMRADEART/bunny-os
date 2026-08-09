// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The figure itself: pure Cairo, and nothing else.
//
// Split out of renderer.js for one reason, and it is the reason the character
// was wrong twice. A figure that can only be drawn inside a GNOME Shell
// process can only be looked at by building an image, booting a virtual
// machine and photographing its screen — which is a forty-minute loop, so it
// gets run once, at the end, when the geometry is already committed. Both
// times the desktop shipped a character that read as a robed figure, the
// mistake was visible in the first picture anybody took.
//
// This module imports `cairo` and no GI namespace at all. `gjs -m
// build/scripts/render-character.js` renders every state to a PNG in about a
// second, and tests/shell/test_desktop_shell.py renders them and asserts on
// the pixels — that the legs are two separated shapes rather than one, that
// the garment is narrower at the hem than at the shoulders, that the hem band
// exists. Those are the three things that were wrong, stated as measurements
// of the output rather than as intentions in a comment.
//
// Everything here is a pure function of (context, definition, pose, size).
// Nothing holds state, and the same code draws any definition.

import Cairo from 'cairo';

export const BOX_WIDTH = 100;
const BOX_HEIGHT = 150;

/**
 * Local, rather than imported from util.js.
 *
 * util.js imports Gio, GLib, St, Clutter and Atk, and importing it here would
 * put every one of those between this module and being renderable outside a
 * compositor — which is the entire property this file exists to have. Three
 * lines of arithmetic is the price.
 */
function clamp(value, low, high) {
    return Math.min(high, Math.max(low, value));
}

function setColour(cr, palette, name, alpha = 1) {
    const [r, g, b] = palette[name] ?? [1, 0, 1];
    cr.setSourceRGBA(r, g, b, alpha);
}

/** A vertical capsule: the shape the limbs and the neck are built from. */
function capsule(cr, x, yTop, yBottom, topHalf, bottomHalf) {
    cr.newPath();
    cr.arc(x, yTop, topHalf, Math.PI, 0);
    cr.lineTo(x + bottomHalf, yBottom);
    cr.arc(x, yBottom, bottomHalf, 0, Math.PI);
    cr.closePath();
}

/** A rectangle with rounded corners, for the ribbed bands. */
function roundedRect(cr, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    cr.newPath();
    cr.arc(x + r, y + r, r, Math.PI, Math.PI * 1.5);
    cr.arc(x + width - r, y + r, r, Math.PI * 1.5, 0);
    cr.arc(x + width - r, y + height - r, r, 0, Math.PI * 0.5);
    cr.arc(x + r, y + height - r, r, Math.PI * 0.5, Math.PI);
    cr.closePath();
}

export function drawFigure(cr, definition, pose, width, height) {
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

    // Back to front. The order is the figure's own depth: what is behind the
    // body, then the body, then what is in front of it.
    drawHood(cr, palette, g);
    drawLegs(cr, palette, g);
    drawShoes(cr, palette, g);
    drawNeck(cr, palette, g);
    drawTorso(cr, palette, g, pose);
    drawLogo(cr, palette, g, pose);
    drawArms(cr, palette, g, pose);
    drawHead(cr, palette, g, pose);
    drawRimLight(cr, palette, g, pose);
    drawStateIndicator(cr, palette, g, pose);

    cr.restore();
    cr.restore();
}

function drawHood(cr, palette, g) {
    // The hood sits behind the head and shoulders: a wide arc that reads as
    // fabric bunched at the neck. Drawn before everything, so only its top edge
    // shows above the shoulder line.
    cr.newPath();
    cr.moveTo(50 - g.hood.halfWidth, g.shoulder.y + 2);
    cr.curveTo(
        50 - g.hood.halfWidth - 2.5, g.hood.y - g.hood.depth,
        50 + g.hood.halfWidth + 2.5, g.hood.y - g.hood.depth,
        50 + g.hood.halfWidth, g.shoulder.y + 2);
    cr.closePath();
    setColour(cr, palette, 'hood');
    cr.fill();
}

/**
 * Two legs, with background between them.
 *
 * Each leg is drawn as an explicit outline rather than a capsule so it can
 * narrow at the knee and again at the ankle: a straight taper from thigh to
 * ankle reads as a tube, and two tubes side by side read as one shape with a
 * line down it. The knee is where a leg stops being a cylinder.
 */
function drawLegs(cr, palette, g) {
    const half = g.leg.separation / 2;
    const top = g.hip.y - 1;
    const bottom = g.hip.y + g.leg.length;
    const knee = top + (bottom - top) * 0.52;

    for (const side of [-1, 1]) {
        const x = 50 + side * half;
        const thigh = g.leg.thighWidth / 2;
        const kneeHalf = g.leg.kneeWidth / 2;
        const ankle = g.leg.ankleWidth / 2;

        cr.newPath();
        cr.moveTo(x - thigh, top);
        cr.lineTo(x + thigh, top);
        cr.curveTo(x + thigh, knee - 6, x + kneeHalf, knee, x + kneeHalf, knee + 2);
        cr.lineTo(x + ankle, bottom);
        cr.lineTo(x - ankle, bottom);
        cr.lineTo(x - kneeHalf, knee + 2);
        cr.curveTo(x - kneeHalf, knee, x - thigh, knee - 6, x - thigh, top);
        cr.closePath();

        const gradient = new Cairo.LinearGradient(x - thigh, 0, x + thigh, 0);
        const [r, gg, b] = palette.trousers;
        const [hr, hg, hb] = palette.trousersHighlight;
        gradient.addColorStopRGBA(0, hr, hg, hb, 1);
        gradient.addColorStopRGBA(0.55, r, gg, b, 1);
        gradient.addColorStopRGBA(1, r * 0.78, gg * 0.78, b * 0.78, 1);
        cr.setSource(gradient);
        cr.fill();

        // The turn-up above the shoe. One line, and it is what stops the
        // trouser and the sneaker reading as a single boot.
        cr.newPath();
        cr.moveTo(x - ankle, bottom - 4.2);
        cr.lineTo(x + ankle, bottom - 4.2);
        setColour(cr, palette, 'trousersHighlight', 0.75);
        cr.setLineWidth(0.9);
        cr.stroke();
    }
}

/**
 * Sneakers.
 *
 * Both point outwards from the centre line, so the toe direction is the side
 * sign and the whole shape is drawn once in a mirrored frame rather than twice
 * with a sign scattered through every coordinate.
 */
function drawShoes(cr, palette, g) {
    const half = g.leg.separation / 2;
    for (const side of [-1, 1]) {
        const x = 50 + side * half;
        const top = g.hip.y + g.leg.length - 1.5;
        const upper = g.shoe.height - g.shoe.soleHeight;
        const heel = g.leg.ankleWidth / 2 + 1.6;
        const toe = g.shoe.length - heel;

        cr.save();
        cr.translate(x, top);
        cr.scale(side, 1);

        cr.newPath();
        cr.moveTo(-heel, 0.6);
        cr.curveTo(-heel - 0.6, upper * 0.4, -heel - 0.4, upper, -heel, upper);
        cr.lineTo(toe, upper);
        cr.curveTo(toe * 0.92, upper * 0.45, toe * 0.55, 0.4, g.leg.ankleWidth / 2, -1.0);
        cr.lineTo(-heel, 0.6);
        cr.closePath();
        setColour(cr, palette, 'shoe');
        cr.fill();

        roundedRect(cr, -heel - 0.6, upper, heel + toe + 0.6, g.shoe.soleHeight, 0.9);
        setColour(cr, palette, 'shoeSole');
        cr.fill();

        // The stripe. Violet, because it is the one place on the figure other
        // than the chest mark where the product's accent colour appears, and
        // two accents at opposite ends of a silhouette is what makes a
        // character look designed rather than assembled.
        cr.newPath();
        cr.moveTo(-0.4, 0.8);
        cr.lineTo(1.6, 0.8);
        cr.lineTo(3.0, upper - 0.6);
        cr.lineTo(1.0, upper - 0.6);
        cr.closePath();
        setColour(cr, palette, 'shoeAccent');
        cr.fill();
        cr.restore();
    }
}

/**
 * The hoodie.
 *
 * Explicitly pathed rather than built from a capsule, and that is the fix for
 * the robe: a capsule's bottom is a semicircle wider than the hips beneath it,
 * which is a hem no garment has. This one has sloped shoulders, a taper to the
 * waist, and a flat hem with a ribbed band under it.
 */
function drawTorso(cr, palette, g, pose) {
    const breathe = pose.breathe * 0.5;
    const shoulderHalf = g.torso.topHalfWidth + breathe;
    const hemHalf = g.torso.hemHalfWidth;
    const top = g.torso.top;
    const hem = g.torso.hem;
    const waist = top + (hem - top) * 0.62;

    cr.newPath();
    // Left shoulder, sloping down and out from the collar.
    cr.moveTo(50 - g.collar.width / 2, top);
    cr.curveTo(
        50 - shoulderHalf * 0.62, top - 0.4,
        50 - shoulderHalf, top + g.shoulder.slope * 0.5,
        50 - shoulderHalf, top + g.shoulder.slope);
    // Down the left side, tucking in slightly at the waist.
    cr.curveTo(
        50 - shoulderHalf, waist - 4,
        50 - hemHalf - 0.8, waist,
        50 - hemHalf, hem);
    // The hem: flat, with the faintest curve so it is not a ruled line.
    cr.curveTo(50 - hemHalf * 0.4, hem + 0.8, 50 + hemHalf * 0.4, hem + 0.8, 50 + hemHalf, hem);
    // Back up the right side.
    cr.curveTo(
        50 + hemHalf + 0.8, waist,
        50 + shoulderHalf, waist - 4,
        50 + shoulderHalf, top + g.shoulder.slope);
    cr.curveTo(
        50 + shoulderHalf, top + g.shoulder.slope * 0.5,
        50 + shoulderHalf * 0.62, top - 0.4,
        50 + g.collar.width / 2, top);
    // The collar, dipping between the shoulders so the neck comes out of it.
    cr.curveTo(
        50 + g.collar.width / 2 - 1, top + g.collar.depth,
        50 - g.collar.width / 2 + 1, top + g.collar.depth,
        50 - g.collar.width / 2, top);
    cr.closePath();

    const gradient = new Cairo.LinearGradient(50 - shoulderHalf, 0, 50 + shoulderHalf, 0);
    const [r, gg, b] = palette.hoodie;
    const [hr, hg, hb] = palette.hoodieHighlight;
    const [sr, sg, sb] = palette.hoodieShadow;
    gradient.addColorStopRGBA(0, hr, hg, hb, 1);
    gradient.addColorStopRGBA(0.42, r, gg, b, 1);
    gradient.addColorStopRGBA(1, sr, sg, sb, 1);
    cr.setSource(gradient);
    cr.fill();

    // The ribbed hem band. The most load-bearing shape in the figure: it is
    // what declares that the garment ends and the trousers begin, and without
    // it every other change here still reads as a robe.
    roundedRect(cr, 50 - hemHalf, hem - g.rib.height, hemHalf * 2, g.rib.height + 1.0, 1.2);
    setColour(cr, palette, 'hoodieRib');
    cr.fill();

    // The kangaroo pocket, as an outline rather than a fill: a filled panel at
    // this size becomes a bib.
    cr.newPath();
    cr.moveTo(50 - g.pocket.halfWidth, g.pocket.top);
    cr.lineTo(50 - g.pocket.halfWidth + 1.2, g.pocket.bottom - 1.2);
    cr.curveTo(
        50 - g.pocket.halfWidth * 0.4, g.pocket.bottom,
        50 + g.pocket.halfWidth * 0.4, g.pocket.bottom,
        50 + g.pocket.halfWidth - 1.2, g.pocket.bottom - 1.2);
    cr.lineTo(50 + g.pocket.halfWidth, g.pocket.top);
    setColour(cr, palette, 'hoodieShadow');
    cr.setLineWidth(1.0);
    cr.stroke();

    // The two drawstrings, hanging from the collar.
    //
    // Short, near-vertical and close together. The first version curved each
    // one outwards and then back in, which mirrored into a symmetrical loop
    // hanging over the chest mark — a lanyard with a pendant on it, which is
    // not what a hoodie has. A drawstring hangs; it does not swag.
    setColour(cr, palette, 'drawstring');
    cr.setLineWidth(0.75);
    for (const side of [-1, 1]) {
        cr.newPath();
        cr.moveTo(50 + side * 2.2, top + g.collar.depth * 0.8);
        cr.curveTo(
            50 + side * 2.6, top + 3.5,
            50 + side * 2.4, top + 5.5,
            50 + side * 2.7, top + 7.5);
        cr.stroke();
        // The aglet, so the string ends rather than fading out.
        cr.newPath();
        cr.arc(50 + side * 2.7, top + 7.9, 0.55, 0, Math.PI * 2);
        cr.fill();
    }
}

/**
 * Two arms, each ending in a cuff and a hand.
 *
 * The sleeve is stroked in the garment colour and then re-stroked, narrower, in
 * a shade — so the sleeve has an edge where it crosses the body and the arm is
 * a separate limb rather than part of the torso outline. That edge is the third
 * of the three things the earlier figure was missing.
 */
function drawArms(cr, palette, g, pose) {
    const lift = pose.armLift;
    for (const side of [-1, 1]) {
        const shoulderX = 50 + side * (g.shoulder.halfWidth - g.arm.shoulderInset);
        const shoulderY = g.shoulder.y + 1;
        // Lift swings the hand outwards and upwards around the shoulder. The
        // rest angle is wide enough that the sleeve clears the hem instead of
        // ending inside it.
        const angle = side * (g.arm.restAngle + lift * 0.78);
        const handX = shoulderX + Math.sin(angle) * g.arm.length;
        const handY = shoulderY + Math.cos(angle) * g.arm.length;

        cr.save();
        cr.setLineCap(Cairo.LineCap.ROUND);
        cr.newPath();
        cr.moveTo(shoulderX, shoulderY);
        // One control point at the elbow, offset against the swing so the arm
        // bends rather than pivoting like a stick.
        cr.curveTo(
            shoulderX + Math.sin(angle) * g.arm.length * 0.35 - side * 1.6,
            shoulderY + g.arm.length * 0.42,
            handX - side * 1.0, handY - g.arm.length * 0.22,
            handX, handY);
        setColour(cr, palette, side < 0 ? 'hoodieHighlight' : 'hoodie');
        cr.setLineWidth(g.sleeve.width);
        cr.strokePreserve();
        setColour(cr, palette, side < 0 ? 'hoodie' : 'hoodieShadow');
        cr.setLineWidth(g.sleeve.width - 2.6);
        cr.stroke();
        cr.restore();

        // The cuff, square to the forearm. Drawn in the rib colour so it pairs
        // with the hem: the same band at both ends of the garment.
        cr.save();
        cr.translate(handX, handY);
        cr.rotate(-angle);
        roundedRect(cr, -g.sleeve.cuffWidth / 2, -g.sleeve.cuffHeight,
            g.sleeve.cuffWidth, g.sleeve.cuffHeight, 0.8);
        setColour(cr, palette, 'hoodieRib');
        cr.fill();
        cr.restore();

        // The hand, below the cuff.
        cr.newPath();
        cr.arc(handX + Math.sin(angle) * 2.2, handY + Math.cos(angle) * 2.2,
            g.arm.handRadius, 0, Math.PI * 2);
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

    // Ears, before the face so the face's edge overlaps them. Two small shapes
    // that cost four lines and do more for "this is a person" than any amount
    // of work on the jaw: a head with no ears reads as a mask or a helmet.
    for (const side of [-1, 1]) {
        cr.save();
        cr.translate(cx + side * (radius - 0.6), cy + g.ear.offsetY);
        cr.scale(0.8, 1.15);
        cr.newPath();
        cr.arc(0, 0, g.ear.radius, 0, Math.PI * 2);
        cr.restore();
        setColour(cr, palette, 'skinShadow');
        cr.fill();
    }

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
 * It is what makes a flat vector figure sit in the scene rather than on it, and
 * it is the one place on the *body* that picks up the state colour — success
 * turns the rim green, error turns it red — so a glance at the figure says
 * something without reading the bubble.
 *
 * ## Why it is only on the head and the shoulder
 *
 * The first version stroked a straight line down the torso from shoulder to hem
 * and a second down the outside of the left leg, on the theory that those are
 * where the silhouette is. They were, before the arms moved outboard of the
 * body. Afterwards the two strokes sat at almost the same x, ran nearly the
 * whole height of the figure, and were drawn *over* the sleeve — so in the
 * success and error frames the character appeared to be holding a coloured
 * staff. It is in the contact sheet from that render and it is unmistakable.
 *
 * Tracing the true silhouette would mean recomputing the sleeve curve here and
 * keeping it in step with drawArms forever. Lighting the head and the near
 * shoulder is what the light would do anyway — it comes from above and to the
 * left — and it cannot be crossed by a limb, because those two surfaces are the
 * topmost thing on that side whatever the arms are doing.
 */
function drawRimLight(cr, palette, g, pose) {
    const colour = palette[pose.accent] ?? palette.rimLight;
    const [r, gg, b] = colour;
    const strength = clamp(0.36 * pose.glow, 0, 0.85);
    cr.save();
    cr.setLineCap(Cairo.LineCap.ROUND);
    cr.setSourceRGBA(r, gg, b, strength);
    cr.setLineWidth(1.5);

    // The head, from the temple round to the jaw.
    cr.newPath();
    cr.arc(g.headCentre[0], g.headCentre[1], g.headRadius + 0.9,
        Math.PI * 0.62, Math.PI * 1.34);
    cr.stroke();

    // The near shoulder: the slope from the collar out to where the sleeve
    // begins, which is the widest lit edge on the figure.
    cr.newPath();
    cr.moveTo(50 - g.collar.width / 2 - 1, g.torso.top + 0.4);
    cr.curveTo(
        50 - g.torso.topHalfWidth * 0.62, g.torso.top - 0.2,
        50 - g.torso.topHalfWidth, g.torso.top + g.shoulder.slope * 0.5,
        50 - g.torso.topHalfWidth + 0.3, g.torso.top + g.shoulder.slope + 1.5);
    cr.setLineWidth(1.3);
    cr.stroke();
    cr.restore();
}

/**
 * The small mark beside the head that says what the figure is doing.
 *
 * Four states get one, and the four were chosen by asking which states a person
 * could not otherwise tell apart at a glance. A listening figure and an idle
 * figure differ by a six-degree head tilt, which is deliberate — a character
 * that changed its whole stance every time a microphone opened would be
 * exhausting to sit in front of — but that leaves "is it listening to me?"
 * answerable only by reading the bubble. This answers it.
 *
 * Everything here is small, in the accent colour, and outside the silhouette,
 * so it can be ignored. Success, error and the rest are already carried by the
 * rim light and the floor glow changing colour, and adding a second signal for
 * them would be noise.
 */
function drawStateIndicator(cr, palette, g, pose) {
    const kind = pose.indicator ?? 'none';
    if (kind === 'none')
        return;
    const colour = palette[pose.accent] ?? palette.rimLight;
    const [r, gg, b] = colour;
    const phase = pose.indicatorPhase ?? 0;
    const {x, y, radius} = g.indicator;

    cr.save();
    cr.setLineCap(Cairo.LineCap.ROUND);

    if (kind === 'listening') {
        // Two arcs opening away from the head, the outer one fading in and out.
        // The shape people already read as "this is hearing you".
        for (const [index, scale] of [[0, 1.6], [1, 2.8]]) {
            const wave = 0.5 + 0.5 * Math.sin((phase - index * 0.18) * Math.PI * 2);
            cr.newPath();
            cr.arc(x, y, radius * scale, -Math.PI * 0.42, Math.PI * 0.42);
            cr.setSourceRGBA(r, gg, b, 0.30 + 0.55 * wave);
            cr.setLineWidth(1.1);
            cr.stroke();
        }
    } else if (kind === 'thinking') {
        // Three dots, lit in turn. Slow: 1.6 seconds for the cycle.
        for (let index = 0; index < 3; index += 1) {
            const lit = 0.5 + 0.5 * Math.sin((phase - index * 0.14) * Math.PI * 2);
            cr.newPath();
            cr.arc(x + index * radius * 2.1, y, radius * 0.62, 0, Math.PI * 2);
            cr.setSourceRGBA(r, gg, b, 0.25 + 0.6 * lit);
            cr.fill();
        }
    } else if (kind === 'working') {
        // A three-quarter ring turning once every 1.6 seconds.
        const start = phase * Math.PI * 2;
        cr.newPath();
        cr.arc(x + radius, y, radius * 1.7, start, start + Math.PI * 1.5);
        cr.setSourceRGBA(r, gg, b, 0.85);
        cr.setLineWidth(1.3);
        cr.stroke();
    } else if (kind === 'alert') {
        // A bar and a dot. Not the warning triangle: at this size a triangle
        // with a stroke inside it is four pixels of mud.
        cr.newPath();
        cr.moveTo(x + radius, y - radius * 1.6);
        cr.lineTo(x + radius, y + radius * 0.35);
        cr.setSourceRGBA(r, gg, b, 0.95);
        cr.setLineWidth(1.5);
        cr.stroke();
        cr.newPath();
        cr.arc(x + radius, y + radius * 1.5, 0.85, 0, Math.PI * 2);
        cr.setSourceRGBA(r, gg, b, 0.95);
        cr.fill();
    }
    cr.restore();
}
