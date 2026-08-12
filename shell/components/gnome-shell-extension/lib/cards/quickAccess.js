// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// QuickAccess: the applications on this machine. Only those.
//
// ## What this used to do, and why it stopped
//
// The brief that created this card named six applications — Files, VS Code, OBS
// Studio, Blender, Discord, Spotify — and the image installs one of them. The
// card drew all six, dimming the five it did not have, on the reasoning that
// "you do not have this" is information.
//
// It is information, and it was the wrong information to put in this card. The
// booted screenshots settle it: five of the six tiles carried the same generic
// application icon, because a tile for something that is not installed has no
// icon to draw. A row of identical grey diamonds labelled with product names
// does not read as "you do not have these" — it reads as a broken icon theme,
// which is precisely the failure the icon audit in the previous phase went and
// removed everywhere else.
//
// So the card is now what its title says: quick access to applications, and an
// application you cannot launch is not one. Every tile comes from
// Shell.AppSystem, carries that application's own icon, and starts it when
// pressed. A machine with four applications shows four tiles.
//
// The named six survive as a *preference order*, not as contents: if this
// machine has Files, Files is first. Nothing is drawn for the ones it lacks.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {Card} from './base.js';
import {iconTile} from '../widgets.js';
import {tileLabel} from '../format.js';
import {tilesPerRow} from '../layout.js';
import {currentTheme} from '../design/current.js';

/**
 * Preferred first, in this order, when the machine actually has them.
 *
 * A preference, not a promise. The list is the brief's, kept because a stable
 * left-to-right order between sessions is worth having and alphabetical order
 * would put Blender before Files on a machine that has both.
 */
const PREFERRED = ['files', 'vscode', 'obs', 'blender', 'discord', 'spotify', 'terminal', 'browser'];

const MAX_TILES = 8;

/**
 * Tiles per row, computed from the theme rather than fixed at four.
 *
 * A single row of eight once ran 300px past the card's right edge and out over
 * the wallpaper, on the first machine that had eight applications installed;
 * the fix was the constant `TILES_PER_ROW = 4`, derived by hand from a 304px
 * card and a 55px tile. Both of those numbers now move with the text scale, so
 * the constant would have been wrong again at the first scaled desktop. The
 * arithmetic lives in lib/layout.js where it can be measured.
 */
function tilesAcross() {
    const theme = currentTheme();
    return tilesPerRow({
        cardWidth: theme.metric.cardWidth,
        cardPadding: theme.space.md,
        tileWidth: theme.metric.quickTileWidth,
        tilePadding: theme.space.xs,
        gap: theme.metric.quickTileGap,
    });
}

export class QuickAccess extends Card {
    constructor({launcher, blur, onSeeAll}) {
        super({
            title: 'Quick Access',
            blur,
            accessibleName: 'Quick access to applications',
            headerTrailing: Card.headerButton('All apps', onSeeAll),
        });
        this._launcher = launcher;
        // A grid rather than a row: the tile count is what the machine has
        // installed, not a constant, so the container has to be able to wrap.
        this._grid = new St.Widget({
            style_class: 'bunny-quick-grid',
            layout_manager: new Clutter.GridLayout({
                orientation: Clutter.Orientation.HORIZONTAL,
                column_spacing: currentTheme().metric.quickTileGap,
                row_spacing: currentTheme().metric.quickTileGap,
            }),
        });
        this.content.add_child(this._grid);
        this._empty = new St.Label({
            text: 'No applications are installed yet.',
            style_class: 'bunny-quick-empty',
            visible: false,
        });
        this.content.add_child(this._empty);
        this.rebuild();
    }

    rebuild() {
        this._grid.destroy_all_children();

        const chosen = [];
        const placed = new Set();

        // The preferred ones this machine has, in the preferred order.
        for (const logical of PREFERRED) {
            if (chosen.length >= MAX_TILES)
                break;
            const app = this._launcher.resolve(logical);
            if (app === null || placed.has(app.get_id()))
                continue;
            placed.add(app.get_id());
            chosen.push(app);
        }

        // Then whatever else is installed, alphabetically, until the card is
        // full. `listAll` is already filtered to entries that say they should
        // be shown, so this cannot surface a background service's entry.
        if (chosen.length < MAX_TILES) {
            const others = this._launcher.listAll()
                .filter(app => !placed.has(app.get_id()))
                .sort((a, b) => a.get_name().localeCompare(b.get_name()))
                .slice(0, MAX_TILES - chosen.length);
            for (const app of others) {
                placed.add(app.get_id());
                chosen.push(app);
            }
        }

        const layout = this._grid.layout_manager;
        const perRow = tilesAcross();
        const iconSize = currentTheme().icon.large;
        for (const [position, app] of chosen.entries()) {
            layout.attach(iconTile({
                // The application's own icon, always. There is no branch here
                // that draws a placeholder, because there is no tile here for
                // something that is not installed.
                gicon: app.get_icon(),
                iconSize,
                // Drawn short, spoken in full. See tileLabel.
                label: tileLabel(app.get_name()),
                styleClass: 'bunny-quick-tile',
                accessibleName: app.get_name(),
                onActivate: () => app.activate(),
            }), position % perRow, Math.floor(position / perRow), 1, 1);
        }

        // An empty card says so rather than being an unexplained blank. This is
        // reachable — a minimal image with no graphical applications installed
        // is a configuration this repository builds.
        this._empty.visible = chosen.length === 0;
    }
}
