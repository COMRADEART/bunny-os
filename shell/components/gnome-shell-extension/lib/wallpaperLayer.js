// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// WallpaperLayer: a contrast scrim, and nothing else.
//
// The wallpaper itself is not drawn here, on purpose. GNOME already has a
// background renderer that handles multiple monitors, hot-plug, per-workspace
// backgrounds, the light/dark pair and the user's own choice of image. Drawing
// a second one inside the extension would mean two images on screen during the
// crossfade, a black frame on monitor hot-plug, and a wallpaper the user
// changed in Settings that the desktop ignored. The image ships as an install
// route and the dconf default points at it — see
// shell/components/dconf/10-bunny-shell.
//
// What GNOME cannot do is guarantee contrast, because the user may set any
// image at all. This layer is the guarantee: a vignette that darkens the edges
// and the lower band, drawn once per geometry change into a Cairo surface
// Clutter then caches. The panels sit on it, so their 4.5:1 text contrast holds
// over a white photograph as well as over the shipped wallpaper.
//
// It is also the fallback the brief asks for. When the shipped SVG is missing,
// GNOME paints the dconf gradient behind this scrim and the result is still a
// composed dark desktop rather than a grey rectangle.

import Cairo from 'cairo';
import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {currentTheme, rgb} from './design/current.js';
import {logError_} from './util.js';

export class WallpaperLayer {
    constructor() {
        this.actor = new St.DrawingArea({
            style_class: 'bunny-wallpaper-scrim',
            reactive: false,
        });
        this.actor.connect('repaint', area => this._paint(area));
    }

    /** @param {{x, y, width, height}} rect the monitor this layer covers */
    setGeometry(rect) {
        this.actor.set_position(rect.x, rect.y);
        this.actor.set_size(rect.width, rect.height);
        this.actor.queue_repaint();
    }

    destroy() {
        this.actor.destroy();
    }

    _paint(area) {
        let cr = null;
        try {
            cr = area.get_context();
            const [width, height] = area.get_surface_size();
            if (width <= 0 || height <= 0)
                return;

            // The scrim's colour is the theme's own ground, not a fixed
            // near-black. Three hardcoded floats here were #080B12 — the dark
            // theme's background — which meant the light theme's scrim darkened
            // a warm-white desktop with a cool near-black.
            const [r, g, b] = rgb('surfacePrimary');

            // At high contrast there is no gradient at all.
            //
            // This layer exists to guarantee contrast over an image the user
            // may have chosen, and at high contrast the only guarantee worth
            // giving is that there is no image. The first booted high-contrast
            // screenshot showed cyan controls and opaque black panels over the
            // *purple wallpaper*, because the wallpaper is GNOME's to draw and
            // this scrim was still only dimming it.
            if (currentTheme().highContrast) {
                cr.setSourceRGBA(r, g, b, 1.0);
                cr.rectangle(0, 0, width, height);
                cr.fill();
                return;
            }

            // Corner vignette. Centred slightly above the middle because the
            // character stands below centre and the darkest part of the frame
            // should not be behind its face.
            const radial = new Cairo.RadialGradient(
                width * 0.5, height * 0.42, Math.min(width, height) * 0.25,
                width * 0.5, height * 0.42, Math.max(width, height) * 0.78);
            radial.addColorStopRGBA(0, r, g, b, 0.0);
            radial.addColorStopRGBA(0.62, r, g, b, 0.22);
            radial.addColorStopRGBA(1, r, g, b, 0.62);
            cr.setSource(radial);
            cr.rectangle(0, 0, width, height);
            cr.fill();

            // Bottom band, under the dock and the lower cards.
            const linear = new Cairo.LinearGradient(0, height * 0.55, 0, height);
            linear.addColorStopRGBA(0, r, g, b, 0.0);
            linear.addColorStopRGBA(1, r, g, b, 0.55);
            cr.setSource(linear);
            cr.rectangle(0, height * 0.55, width, height * 0.45);
            cr.fill();

            // Top band, under the bar.
            const top = new Cairo.LinearGradient(0, 0, 0, 140);
            top.addColorStopRGBA(0, r, g, b, 0.48);
            top.addColorStopRGBA(1, r, g, b, 0.0);
            cr.setSource(top);
            cr.rectangle(0, 0, width, 140);
            cr.fill();
        } catch (error) {
            logError_('the wallpaper scrim could not be drawn', error);
        } finally {
            // GJS will not free the Cairo context for us and the warning it
            // prints when it collects one is the only sign anything is wrong.
            cr?.$dispose();
        }
    }
}

/**
 * A plain gradient actor, for the one case the scrim cannot cover.
 *
 * If Clutter cannot give the drawing area a surface — which happens on a stage
 * that has not been allocated yet — the desktop still needs something opaque
 * behind it, because a transparent desktop over GNOME's default background is
 * the blue screen this work exists to replace. Constructed only when
 * DesktopShell asks for it.
 */
export function fallbackGradient() {
    return new St.Widget({
        style_class: 'bunny-wallpaper-fallback',
        reactive: false,
        layout_manager: new Clutter.BinLayout(),
    });
}
