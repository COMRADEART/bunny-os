// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// QuickAccess: the applications on this machine, and honestly which ones are.
//
// The brief names six: Files, VS Code, OBS Studio, Blender, Discord, Spotify.
// This image installs one of them. The card therefore does what the brief
// permits and marks the rest unavailable rather than hiding them, because a
// grid that silently shrinks to a single tile tells the user nothing, whereas
// six tiles of which five are dimmed and say "not installed" tells them exactly
// what they have and what they do not.
//
// The named six are a *starting* list, not the list. Everything else in the
// grid comes from Shell.AppSystem — the applications that are actually here —
// so a machine with Inkscape and GIMP shows Inkscape and GIMP. The named
// entries are pinned first so the card has a stable shape between sessions.

import {Card} from './base.js';
import {Icons} from '../icons.js';
import {box, iconTile, setUnavailable} from '../widgets.js';
import {KNOWN_APPLICATIONS} from '../services/launcher.js';

/** Pinned first, in this order. Names are the brief's. */
const PINNED = [
    {logical: 'files', label: 'Files'},
    {logical: 'vscode', label: 'VS Code'},
    {logical: 'obs', label: 'OBS Studio'},
    {logical: 'blender', label: 'Blender'},
    {logical: 'discord', label: 'Discord'},
    {logical: 'spotify', label: 'Spotify'},
];

const MAX_TILES = 8;

export class QuickAccess extends Card {
    constructor({launcher, blur, onSeeAll}) {
        super({
            title: 'Quick Access',
            blur,
            accessibleName: 'Quick access to applications',
            headerTrailing: Card.headerButton('All apps', onSeeAll),
        });
        this._launcher = launcher;
        this._grid = box({style_class: 'bunny-quick-grid'});
        this.content.add_child(this._grid);
        this.rebuild();
    }

    rebuild() {
        this._grid.destroy_all_children();
        const placed = new Set();

        for (const entry of PINNED) {
            const app = this._launcher.resolve(entry.logical);
            const tile = iconTile({
                gicon: app?.get_icon() ?? null,
                iconName: app ? null : Icons.APP_GENERIC,
                iconSize: 26,
                label: entry.label,
                styleClass: 'bunny-quick-tile',
                accessibleName: entry.label,
                onActivate: app ? () => this._launcher.launch(entry.logical) : null,
            });
            if (app === null) {
                const tried = (KNOWN_APPLICATIONS[entry.logical] ?? []).join(' or ');
                setUnavailable(tile, `${entry.label} is not installed (looked for ${tried})`);
                tile.accessible_name = `${entry.label}, not installed`;
            } else {
                placed.add(app.get_id());
            }
            this._grid.add_child(tile);
        }

        // Fill the remaining slots with what is installed, so the card is
        // about this machine rather than about the brief's example list.
        const remaining = MAX_TILES - PINNED.length;
        if (remaining > 0) {
            const others = this._launcher.listAll()
                .filter(app => !placed.has(app.get_id()))
                .sort((a, b) => a.get_name().localeCompare(b.get_name()))
                .slice(0, remaining);
            for (const app of others) {
                this._grid.add_child(iconTile({
                    gicon: app.get_icon(),
                    iconSize: 26,
                    label: app.get_name(),
                    styleClass: 'bunny-quick-tile',
                    accessibleName: app.get_name(),
                    onActivate: () => app.activate(),
                }));
            }
        }
    }
}
