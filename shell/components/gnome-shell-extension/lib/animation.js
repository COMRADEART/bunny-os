// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Motion, and the one place that decides whether there is any.
//
// GNOME Shell already answers "should this session animate?" through
// St.Settings.enable_animations, which follows
// org.gnome.desktop.interface.enable-animations and the accessibility
// preference behind it. Nothing in the desktop reads that setting directly:
// every animation goes through `ease` or `pulse` here, so honouring reduced
// motion is a property of the module rather than a discipline each of thirty
// call sites has to remember.
//
// Reduced motion does not mean "the same animation, faster". It means the
// actor is placed at its final value and no transition is created at all —
// which is also why `pulse` returns a handle that is already stopped rather
// than a slow throb.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {Motion} from './tokens.js';
import {interval} from './util.js';

export function animationsEnabled() {
    return St.Settings.get().enable_animations;
}

export function duration(milliseconds) {
    return animationsEnabled() ? milliseconds : Motion.REDUCED_MS;
}

/**
 * Ease an actor's properties, or set them outright under reduced motion.
 *
 * `properties` is the same object Clutter.Actor.ease takes, minus duration and
 * mode, which come from here so the durations in tokens.js are the only ones in
 * the desktop.
 */
export function ease(actor, properties, {ms = Motion.PANEL_MS, mode = Clutter.AnimationMode.EASE_OUT_QUAD, onComplete = null} = {}) {
    const time = duration(ms);
    if (time === 0) {
        for (const [key, value] of Object.entries(properties))
            actor[key] = value;
        onComplete?.();
        return;
    }
    actor.ease({...properties, duration: time, mode, onComplete: onComplete ?? undefined});
}

/**
 * The entrance the brief describes: fade plus a short rise.
 *
 * `index` staggers a row of cards. The stagger is capped so that a screen with
 * eight widgets does not take eight times as long to appear as one with one —
 * the last card must still be up inside the entrance budget.
 */
export function enter(actor, {index = 0, rise = 12, ms = Motion.ENTRANCE_MS} = {}) {
    if (duration(ms) === 0) {
        actor.opacity = 255;
        actor.translation_y = 0;
        return;
    }
    actor.opacity = 0;
    actor.translation_y = rise;
    const delay = Math.min(index, 8) * 45;
    actor.ease({
        opacity: 255,
        translation_y: 0,
        duration: duration(ms),
        delay,
        mode: Clutter.AnimationMode.EASE_OUT_CUBIC,
    });
}

/**
 * The "assistant is thinking" throb.
 *
 * A repeating opacity ease rather than a Clutter repeat count, because the
 * caller stops it on a state change and a repeating transition cancelled
 * mid-cycle leaves the actor at whatever opacity it had reached.
 */
export function pulse(actor, {low = 140, high = 255, ms = 900} = {}) {
    if (!animationsEnabled()) {
        actor.opacity = high;
        return {stop() {}};
    }
    let bright = false;
    const step = () => {
        bright = !bright;
        actor.ease({
            opacity: bright ? high : low,
            duration: ms,
            mode: Clutter.AnimationMode.EASE_IN_OUT_SINE,
        });
    };
    step();
    const handle = interval(Math.max(1, Math.round(ms / 1000)), step);
    return {
        stop() {
            handle.stop();
            actor.remove_all_transitions();
            actor.opacity = high;
        },
    };
}

/** Crossfade one actor out and another in, in the same slot. */
export function crossfade(outgoing, incoming, {ms = Motion.CHARACTER_MS} = {}) {
    const time = duration(ms);
    if (time === 0) {
        outgoing.opacity = 0;
        outgoing.visible = false;
        incoming.opacity = 255;
        incoming.visible = true;
        return;
    }
    incoming.opacity = 0;
    incoming.visible = true;
    incoming.ease({opacity: 255, duration: time, mode: Clutter.AnimationMode.EASE_OUT_QUAD});
    outgoing.ease({
        opacity: 0,
        duration: time,
        mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        onComplete: () => {
            outgoing.visible = false;
        },
    });
}
