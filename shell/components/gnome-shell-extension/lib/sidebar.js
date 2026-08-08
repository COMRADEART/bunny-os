// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Sidebar: the five places, the two tools, and the way out.
//
// Built as its own component with a `collapsed` mode from the start, because
// the brief asks for collapsibility later and retrofitting it means every
// caller that assumed a fixed width has to be found. Collapsed is not a
// separate widget: the same items lose their labels and gain tooltips, so the
// selection state, the keyboard order and the accessible names cannot diverge
// between the two forms.
//
// Selection and navigation are separate ideas here. Home, AI Assistant, Files,
// Apps and Settings are *destinations* — pressing one selects it and the
// desktop changes. Terminal and Store are *launches* — they open a program and
// the selection does not move, because the desktop you were on is still the
// desktop you are on. Power is neither and is placed apart from both.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {box, glass} from './widgets.js';
import {ease} from './animation.js';
import {makeActivatable} from './util.js';
import {Motion} from './tokens.js';

/**
 * The item table. `kind` decides what pressing it means; see the module note.
 * `id` is the value DesktopShell receives and is part of this component's
 * contract, so renaming one is a change to the shell, not to a label.
 */
export const SIDEBAR_ITEMS = [
    {id: 'home', label: 'Home', icon: 'go-home-symbolic', kind: 'destination'},
    {id: 'assistant', label: 'AI Assistant', icon: 'bunny-shell-symbolic', kind: 'destination'},
    {id: 'files', label: 'Files', icon: 'folder-symbolic', kind: 'destination'},
    {id: 'apps', label: 'Apps', icon: 'view-app-grid-symbolic', kind: 'destination'},
    {id: 'settings', label: 'Settings', icon: 'preferences-system-symbolic', kind: 'destination'},
    {id: 'divider', kind: 'divider'},
    {id: 'terminal', label: 'Terminal', icon: 'utilities-terminal-symbolic', kind: 'launch'},
    {id: 'store', label: 'Store', icon: 'shop-symbolic', kind: 'launch'},
];

export class Sidebar {
    /**
     * @param {{onSelect: (id: string) => void, onLaunch: (id: string) => void,
     *          onPower: () => void, blur: boolean}} context
     */
    constructor(context) {
        this._context = context;
        this._rows = new Map();
        this._selected = 'home';
        this._collapsed = false;

        this.actor = glass('bunny-sidebar', {blur: context.blur, radius: 22});
        this._column = box({vertical: true, style_class: 'bunny-sidebar-column'});
        this.actor.add_child(this._column);

        for (const item of SIDEBAR_ITEMS) {
            if (item.kind === 'divider') {
                this._column.add_child(new St.Widget({style_class: 'bunny-sidebar-divider'}));
                continue;
            }
            const row = this._buildRow(item);
            this._rows.set(item.id, row);
            this._column.add_child(row.actor);
        }

        this._column.add_child(new St.Widget({y_expand: true}));

        this._power = this._buildRow({
            id: 'power', label: 'Power', icon: 'system-shutdown-symbolic', kind: 'power',
        });
        this._power.actor.add_style_class_name('bunny-sidebar-power');
        this._column.add_child(this._power.actor);

        this.select('home');
    }

    /** @param {string} id one of SIDEBAR_ITEMS' destination ids */
    select(id) {
        this._selected = id;
        for (const [rowId, row] of this._rows) {
            const selected = rowId === id;
            row.actor.remove_style_class_name('bunny-sidebar-row-selected');
            if (selected)
                row.actor.add_style_class_name('bunny-sidebar-row-selected');
            // aria-current has no St equivalent; the accessible name carries it,
            // which is what Orca reads out when focus lands on the row.
            row.actor.accessible_name = selected ? `${row.label}, selected` : row.label;
        }
    }

    get selected() {
        return this._selected;
    }

    /** Collapse to icons, or expand back. Animated because it is a size change. */
    setCollapsed(collapsed) {
        if (this._collapsed === collapsed)
            return;
        this._collapsed = collapsed;
        for (const row of [...this._rows.values(), this._power]) {
            if (collapsed) {
                row.label_actor.hide();
                row.actor.accessible_description = row.label;
            } else {
                row.label_actor.show();
                row.actor.accessible_description = '';
            }
        }
        this.actor.remove_style_class_name('bunny-sidebar-collapsed');
        if (collapsed)
            this.actor.add_style_class_name('bunny-sidebar-collapsed');
    }

    get collapsed() {
        return this._collapsed;
    }

    /** Put key focus on the selected row, for the "focus the sidebar" shortcut. */
    focus() {
        (this._rows.get(this._selected) ?? this._rows.get('home'))?.actor.grab_key_focus();
    }

    destroy() {
        this.actor.destroy();
        this._rows.clear();
    }

    _buildRow(item) {
        const row = box({style_class: 'bunny-sidebar-row'});
        const icon = new St.Icon({
            icon_name: item.icon,
            icon_size: 18,
            style_class: 'bunny-sidebar-icon',
        });
        const label = new St.Label({text: item.label, style_class: 'bunny-sidebar-label'});
        row.add_child(icon);
        row.add_child(label);

        makeActivatable(row, () => this._activate(item), {accessibleName: item.label});

        // The hover lift is a translation rather than a scale: scaling a row
        // that contains text resamples the glyphs and they shimmer.
        row.connect('notify::hover', () => {
            ease(row, {translation_x: row.hover ? 3 : 0}, {ms: Motion.HOVER_MS});
        });

        return {actor: row, label: item.label, label_actor: label, icon_actor: icon};
    }

    _activate(item) {
        if (item.kind === 'destination') {
            this.select(item.id);
            this._context.onSelect?.(item.id);
        } else if (item.kind === 'launch') {
            this._context.onLaunch?.(item.id);
        } else if (item.kind === 'power') {
            this._context.onPower?.();
        }
    }
}

/**
 * The power menu.
 *
 * A modal St popup rather than a GNOME PopupMenu, because a PopupMenu belongs
 * to a PanelMenu.Button and the sidebar is not one. `Main.pushModal` is what
 * makes Escape and click-outside work; without it the menu is a widget that
 * looks like a menu and traps nothing.
 */
export class PowerMenu {
    constructor(power, {onClose = null} = {}) {
        this._power = power;
        this._onClose = onClose;
        this.actor = glass('bunny-power-menu', {blur: false, radius: 18});
        const column = box({vertical: true, style_class: 'bunny-power-column'});
        this.actor.add_child(column);

        const actions = [
            {label: 'Suspend', icon: 'weather-clear-night-symbolic', run: () => power.suspend()},
            {label: 'Restart', icon: 'system-reboot-symbolic', run: () => power.restart()},
            {label: 'Shut Down', icon: 'system-shutdown-symbolic', run: () => power.shutdown()},
            {label: 'Log Out', icon: 'system-log-out-symbolic', run: () => power.logOut()},
        ];
        for (const action of actions) {
            const row = box({style_class: 'bunny-power-row'});
            row.add_child(new St.Icon({
                icon_name: action.icon, icon_size: 16, style_class: 'bunny-sidebar-icon',
            }));
            row.add_child(new St.Label({text: action.label, style_class: 'bunny-sidebar-label'}));
            makeActivatable(row, () => {
                this._onClose?.();
                action.run();
            }, {accessibleName: action.label});
            column.add_child(row);
        }

        this.actor.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() === Clutter.KEY_Escape) {
                this._onClose?.();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
    }

    destroy() {
        this.actor.destroy();
    }
}
