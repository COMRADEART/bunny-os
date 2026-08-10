#!/usr/bin/gjs -m
// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Draw the desktop character to PNG files, outside a compositor.
//
// The character has been wrong twice, and both times the mistake was obvious in
// the first picture anybody took of it. The reason nobody took one earlier is
// that looking at it meant building an image, booting it under QEMU and
// photographing the emulated framebuffer — a forty-minute round trip, so it
// happened once, at the end, after the geometry was committed.
//
// lib/character/figure.js imports `cairo` and no GI namespace, which is what
// makes this possible: the same drawing code the desktop runs, rendered to a
// file in about a second. It is a development tool and is not installed.
//
//   gjs -m build/scripts/render-character.js --output build/out/character
//
// One PNG per state, plus a contact sheet of all ten. The pose used is the
// state's resting pose with the breathing cycle at its midpoint — the frame the
// figure spends most of its time near, rather than the extreme of a cycle.

import Cairo from 'cairo';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

const here = GLib.path_get_dirname(
    GLib.filename_from_uri(import.meta.url)[0]);
const extension = GLib.build_filenamev(
    [here, '..', '..', 'shell', 'components', 'gnome-shell-extension']);

const {drawFigure} = await import(
    `file://${GLib.build_filenamev([extension, 'lib', 'character', 'figure.js'])}`);
const {DEFAULT_CHARACTER} = await import(
    `file://${GLib.build_filenamev([extension, 'lib', 'character', 'definition.js'])}`);

/** The order the contact sheet uses; also the order state.js declares. */
const STATES = [
    'idle', 'listening', 'thinking', 'working', 'success',
    'warning', 'error', 'talking', 'sleeping', 'celebrating',
];

const WIDTH = 300;
const HEIGHT = 450;

/**
 * The pose a state rests at.
 *
 * Taken straight from the definition rather than run through PoseAnimator: the
 * animator lives in renderer.js with the GI imports, and what is being looked
 * at here is the figure, not the easing. `breathe` and `bob` are multiplied by
 * the sine wave the animator would apply, sampled at the phase given.
 */
function poseFor(state, phase = 0.25) {
    const base = DEFAULT_CHARACTER.poses[state] ?? DEFAULT_CHARACTER.poses.idle;
    const wave = Math.sin(phase * Math.PI * 2);
    return {
        breathe: base.breathe * wave,
        bob: base.bob * wave,
        armLift: base.armLift,
        headTilt: base.headTilt,
        lean: base.lean,
        eyeOpen: base.eyeOpen,
        mouthOpen: base.mouthOpen,
        glow: base.glow,
        accent: base.accent,
        indicator: base.indicator ?? 'none',
        indicatorPhase: 0.3,
    };
}

function renderState(state, {width = WIDTH, height = HEIGHT, background = true} = {}) {
    const surface = new Cairo.ImageSurface(Cairo.Format.ARGB32, width, height);
    const cr = new Cairo.Context(surface);
    if (background) {
        // The desktop's own backdrop, so the silhouette is judged against the
        // colour it will actually sit on. On white the figure looks fine and on
        // #0b0b12 the trousers and the hoodie are nearly the same value, which
        // is exactly the condition the hem band has to survive.
        cr.setSourceRGBA(0.043, 0.043, 0.071, 1);
        cr.paint();
    }
    drawFigure(cr, DEFAULT_CHARACTER, poseFor(state), width, height);
    cr.$dispose();
    return surface;
}

function main() {
    let output = 'build/out/character';
    const argv = ARGV ?? [];
    for (let index = 0; index < argv.length; index += 1) {
        if (argv[index] === '--output' && argv[index + 1])
            output = argv[index + 1];
    }
    const directory = Gio.File.new_for_path(output);
    try {
        directory.make_directory_with_parents(null);
    } catch (error) {
        if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
            throw error;
    }

    for (const state of STATES) {
        const surface = renderState(state);
        const path = GLib.build_filenamev([output, `${state}.png`]);
        surface.writeToPNG(path);
        surface.finish();
        print(`${path}`);
    }

    // The contact sheet. Ten states in one picture is the only way to see that
    // a state reads differently from its neighbours, which is the whole point
    // of having ten.
    const columns = 5;
    const rows = Math.ceil(STATES.length / columns);
    const cell = {width: 210, height: 315};
    const sheet = new Cairo.ImageSurface(
        Cairo.Format.ARGB32, cell.width * columns, cell.height * rows);
    const cr = new Cairo.Context(sheet);
    cr.setSourceRGBA(0.043, 0.043, 0.071, 1);
    cr.paint();
    for (const [index, state] of STATES.entries()) {
        const column = index % columns;
        const row = Math.floor(index / columns);
        cr.save();
        cr.translate(column * cell.width, row * cell.height);
        drawFigure(cr, DEFAULT_CHARACTER, poseFor(state), cell.width, cell.height);
        cr.restore();
    }
    cr.$dispose();
    const sheetPath = GLib.build_filenamev([output, 'contact-sheet.png']);
    sheet.writeToPNG(sheetPath);
    sheet.finish();
    print(`${sheetPath}`);
    return 0;
}

main();
