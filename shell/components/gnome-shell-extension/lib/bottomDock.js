// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// BottomDock: the seven things a user reaches for without thinking.
//
// The running indicator is read from Shell.App rather than remembered here. A
// dock that tracked its own launches would show a dot beside an application the
// user closed from its own window, and would show nothing beside one started
// from the overview — both of which are worse than no indicator at all.
//
// The hover animation is a translation and a small scale, capped at 1.08. The
// brief says subtle and says not to copy the macOS dock; the specific thing not
// copied is neighbour magnification, which requires the dock to recompute every
// tile's size on every pointer motion and is the expensive part of that effect
// as well as the recognisable one.
//
// A tile for an application the image does not install is not drawn at all.
// This differs from the quick access card, which draws it disabled — the
// difference is deliberate and recorded in both places: the dock is a fixed
// bar of things that work, and a permanent dead slot in it is a defect users
// report; the card is a list of *what you have*, where the absence is the
// information.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {box, glass, iconTile} from './widgets.js';
import {ease} from './animation.js';
import {interval} from './util.js';
import {Motion} from './tokens.js';

/**
 * `app` is a logical name understood by ApplicationLauncher; `command` is a
 * shell surface run directly. Exactly one of the two is set.
 */
export const DOCK_ITEMS = [
    {id: 'assistant', label: 'Bunny Assistant', icon: 'bunny-shell-symbolic', command: ['bunny-command']},
    {id: 'files', label: 'Files', app: 'files'},
    {id: 'browser', label: 'Browser', app: 'browser'},
    {id: 'vscode', label: 'VS Code', app: 'vscode'},
    {id: 'terminal', label: 'Terminal', app: 'terminal'},
    {id: 'spotify', label: 'Spotify', app: 'spotify'},
    {id: 'applications', label: 'Applications', icon: 'view-app-grid-symbolic', overview: true},
];

export class BottomDock {
    /**
     * @param {{launcher, onOverview: () => void, blur: boolean}} context
     */
    constructor(context) {
        this._context = context;
        this._tiles = new Map();

        this.actor = glass('bunny-dock', {blur: context.blur, radius: 22});
        this._row = box({style_class: 'bunny-dock-row'});
        this.actor.add_child(this._row);

        this.rebuild();
        this._timer = interval(3, () => this._refreshRunning());
    }

    /**
     * Rebuild the tile row from what is installed now.
     *
     * Called on `installed-changed`, so a Flatpak installed while the session is
     * up appears without a logout. Cheap: seven tiles.
     */
    rebuild() {
        this._row.destroy_all_children();
        this._tiles.clear();

        for (const item of DOCK_ITEMS) {
            if (item.app && !this._context.launcher.available(item.app))
                continue;

            const gicon = item.app
                ? this._context.launcher.resolve(item.app)?.get_icon() ?? null
                : null;
            const tile = iconTile({
                gicon,
                iconName: item.icon ?? null,
                iconSize: 30,
                styleClass: 'bunny-dock-tile',
                accessibleName: item.label,
                tooltip: item.label,
                onActivate: () => this._activate(item),
            });

            // The running dot is a child of the tile, not a style class, so it
            // can be shown and hidden without a restyle on a 3-second timer.
            const indicator = new St.Widget({
                style_class: 'bunny-dock-running',
                visible: false,
                x_align: Clutter.ActorAlign.CENTER,
            });
            tile.add_child(indicator);

            tile.connect('notify::hover', () => {
                const hovered = tile.hover;
                ease(tile, {
                    translation_y: hovered ? -6 : 0,
                    scale_x: hovered ? 1.08 : 1,
                    scale_y: hovered ? 1.08 : 1,
                }, {ms: Motion.HOVER_MS, mode: Clutter.AnimationMode.EASE_OUT_BACK});
            });
            tile.set_pivot_point(0.5, 1.0);

            this._row.add_child(tile);
            this._tiles.set(item.id, {tile, indicator, item});
        }
        this._refreshRunning();
    }

    destroy() {
        this._timer.stop();
        this.actor.destroy();
        this._tiles.clear();
    }

    _activate(item) {
        if (item.overview) {
            this._context.onOverview?.();
            return;
        }
        if (item.command) {
            this._context.launcher.spawn(item.command);
            return;
        }
        this._context.launcher.launch(item.app);
    }

    _refreshRunning() {
        for (const {indicator, item} of this._tiles.values()) {
            if (!item.app) {
                indicator.visible = false;
                continue;
            }
            indicator.visible = this._context.launcher.running(item.app);
        }
    }
}
