import Clutter from 'gi://Clutter';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {TOKENS} from '../generatedTokens.js';
import {applyPresentationClasses} from './presentation.js';


export class AdaptiveDock {
    constructor(settings) {
        this._settings = settings;
        this._signals = [];
        this._docks = [];
        this._presentation = null;
    }

    enable() {
        this._favorites = AppFavorites.getAppFavorites();
        this._appSystem = Shell.AppSystem.get_default();
        this._signals.push([this._favorites, this._favorites.connect('changed', () => this._rebuild())]);
        this._signals.push([this._appSystem, this._appSystem.connect('app-state-changed', () => this._rebuild())]);
        this._signals.push([global.display, global.display.connect('notify::focus-window', () => this._syncVisibility())]);
        this._signals.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => this._createDocks())]);
        this._signals.push([this._settings, this._settings.connect('changed::dock-autohide', () => this._syncVisibility())]);
        this._createDocks();
    }

    _apps() {
        const favorites = this._favorites.getFavorites();
        const seen = new Set(favorites.map(app => app.get_id()));
        return [...favorites, ...this._appSystem.get_running().filter(app => !seen.has(app.get_id()))];
    }

    _createDocks() {
        for (const dock of this._docks) {
            dock.actor.destroy();
            dock.edge.destroy();
        }
        this._docks = [];
        for (const monitor of Main.layoutManager.monitors) {
            const actor = new St.Bin({reactive: true, track_hover: true, can_focus: false});
            const box = new St.BoxLayout({style_class: 'bunny-v2-surface bunny-v2-dock', x_align: Clutter.ActorAlign.CENTER});
            actor.set_child(box);
            const edge = new St.Widget({reactive: true, track_hover: true});
            actor.connect('notify::hover', () => actor.hover ? this._reveal(actor) : this._syncVisibility());
            edge.connect('enter-event', () => this._reveal(actor));
            Main.layoutManager.addChrome(actor, {affectsStruts: false, trackFullscreen: true});
            Main.layoutManager.addChrome(edge, {affectsStruts: false, trackFullscreen: true});
            this._docks.push({actor, box, edge, monitor});
        }
        this._rebuild();
        this._place();
        this._syncVisibility();
    }

    _rebuild() {
        const apps = this._apps();
        for (const dock of this._docks) {
            dock.box.destroy_all_children();
            const maximum = Math.max(4, Math.min(10, Math.floor((dock.monitor.width - 180) / 62)));
            for (const app of apps.slice(0, maximum)) {
                const windows = app.get_windows();
                const focused = windows.some(window => window === global.display.focus_window);
                const minimized = windows.length > 0 && windows.every(window => window.minimized);
                const button = new St.Button({
                    style_class: `bunny-v2-dock-icon bunny-v2-focus${app.get_state() === Shell.AppState.RUNNING ? ' bunny-v2-running' : ''}${focused ? ' bunny-v2-active' : ''}${minimized ? ' bunny-v2-minimized' : ''}`,
                    can_focus: true,
                    reactive: true,
                    accessible_name: app.get_name(),
                    child: app.create_icon_texture(this._presentation?.compact ? TOKENS.layout.dockTextureCompact : TOKENS.layout.dockTexture),
                });
                button._bunnyAppId = app.get_id();
                button.connect('clicked', () => app.activate());
                DND.makeDraggable(button, {restoreOnSuccess: true});
                dock.box.add_child(button);
            }
            if (apps.length > maximum) {
                const overflow = new St.Button({
                    label: `+${apps.length - maximum}`,
                    style_class: 'bunny-v2-dock-icon bunny-v2-focus',
                    can_focus: true,
                    accessible_name: 'Show remaining applications',
                });
                overflow.connect('clicked', () => Main.overview.show());
                dock.box.add_child(overflow);
            }
            dock.box._delegate = this;
        }
    }

    handleDragOver(source) {
        return source?._bunnyAppId ? DND.DragMotionResult.MOVE_DROP : DND.DragMotionResult.NO_DROP;
    }

    acceptDrop(source) {
        if (!source?._bunnyAppId)
            return false;
        const favorites = this._favorites.getFavorites();
        if (favorites.some(app => app.get_id() === source._bunnyAppId))
            this._favorites.moveFavoriteToPos(source._bunnyAppId, favorites.length - 1);
        else
            this._favorites.addFavoriteAtPos(source._bunnyAppId, favorites.length);
        return true;
    }

    _place() {
        for (const dock of this._docks) {
            const height = this._presentation?.compact ? TOKENS.layout.dockHeightCompact : TOKENS.layout.dockHeight;
            const width = Math.min(TOKENS.layout.dockMaximumWidth, dock.monitor.width - TOKENS.spacing['3xl']);
            dock.actor.set_position(dock.monitor.x + Math.floor((dock.monitor.width - width) / 2), dock.monitor.y + dock.monitor.height - height - TOKENS.spacing.lg);
            dock.actor.set_size(width, height);
            dock.edge.set_position(dock.monitor.x, dock.monitor.y + dock.monitor.height - 4);
            dock.edge.set_size(dock.monitor.width, 4);
        }
    }

    _shouldHide() {
        if (this._presentation?.focus)
            return true;
        if (!this._settings.get_boolean('dock-autohide'))
            return false;
        const window = global.display.focus_window;
        return Boolean(window?.maximized_horizontally || window?.maximized_vertically);
    }

    _syncVisibility() {
        for (const dock of this._docks)
            this._shouldHide() && !dock.actor.hover ? this._conceal(dock.actor) : this._reveal(dock.actor);
    }

    _reveal(actor) {
        actor.ease({translation_y: 0, duration: this._presentation?.reducedMotion ? 0 : TOKENS.motion.micro});
    }

    _conceal(actor) {
        actor.ease({translation_y: actor.height - 8, duration: this._presentation?.reducedMotion ? 0 : TOKENS.motion.micro});
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        for (const dock of this._docks)
            applyPresentationClasses(dock.actor, presentation);
        this._rebuild();
        this._place();
        this._syncVisibility();
    }

    disable() {
        for (const [object, signal] of this._signals)
            object.disconnect(signal);
        this._signals = [];
        for (const dock of this._docks) {
            dock.actor.destroy();
            dock.edge.destroy();
        }
        this._docks = [];
    }
}
