import Clutter from 'gi://Clutter';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as AppFavorites from 'resource:///org/gnome/shell/ui/appFavorites.js';
import * as DND from 'resource:///org/gnome/shell/ui/dnd.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';

const MAX_VISIBLE_APPS = 10;

export class Dock {
    constructor(state, settings) {
        this._state = state;
        this._settings = settings;
        this._signals = [];
    }

    enable() {
        this.actor = new St.Bin({name: 'bunny-v1-dock-container', reactive: true, can_focus: false});
        this._box = new St.BoxLayout({style_class: 'bunny-v1-dock', x_align: Clutter.ActorAlign.CENTER});
        this.actor.set_child(this._box);
        this._hotEdge = new St.Widget({reactive: true, track_hover: true});
        this.actor.connect('notify::hover', () => {
            if (this.actor.hover)
                this._reveal();
            else if (this._shouldHide())
                this._conceal();
        });
        this._hotEdge.connect('enter-event', () => this._reveal());
        Main.layoutManager.addChrome(this.actor, {affectsStruts: false, trackFullscreen: true});
        Main.layoutManager.addChrome(this._hotEdge, {affectsStruts: false, trackFullscreen: true});
        this._favorites = AppFavorites.getAppFavorites();
        this._appSystem = Shell.AppSystem.get_default();
        this._signals.push([this._favorites, this._favorites.connect('changed', () => this._rebuild())]);
        this._signals.push([this._appSystem, this._appSystem.connect('app-state-changed', () => this._rebuild())]);
        this._signals.push([global.display, global.display.connect('notify::focus-window', () => this._syncVisibility())]);
        this._signals.push([Main.layoutManager, Main.layoutManager.connect('monitors-changed', () => this._place())]);
        this._signals.push([this._settings, this._settings.connect('changed::dock-auto-hide', () => this._syncVisibility())]);
        this._box._delegate = this;
        this._rebuild();
        this._place();
        this._syncVisibility();
    }

    _apps() {
        const favorites = this._favorites.getFavorites();
        const seen = new Set(favorites.map(app => app.get_id()));
        const running = this._appSystem.get_running().filter(app => !seen.has(app.get_id()));
        return [...favorites, ...running];
    }

    _rebuild() {
        this._box.destroy_all_children();
        const apps = this._apps();
        for (const app of apps.slice(0, MAX_VISIBLE_APPS)) {
            const button = new St.Button({
                style_class: `bunny-v1-dock-icon${app.get_state() === Shell.AppState.RUNNING ? ' bunny-v1-running' : ''}`,
                can_focus: true,
                reactive: true,
                accessible_name: app.get_name(),
                child: app.create_icon_texture(32),
            });
            button._bunnyAppId = app.get_id();
            button.connect('clicked', () => app.activate());
            DND.makeDraggable(button, {restoreOnSuccess: true});
            this._box.add_child(button);
        }
        if (apps.length > MAX_VISIBLE_APPS) {
            const overflow = new St.Button({
                label: `+${apps.length - MAX_VISIBLE_APPS}`,
                style_class: 'bunny-v1-dock-icon',
                can_focus: true,
                accessible_name: 'Show remaining applications',
            });
            overflow.connect('clicked', () => Main.overview.show());
            this._box.add_child(overflow);
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
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = Math.min(620, monitor.width - 48);
        this.actor.set_position(monitor.x + Math.floor((monitor.width - width) / 2), monitor.y + monitor.height - 82);
        this.actor.set_size(width, 64);
        this._box.set_position(0, 0);
        this._box.set_size(width, 64);
        this._hotEdge.set_position(monitor.x, monitor.y + monitor.height - 4);
        this._hotEdge.set_size(monitor.width, 4);
    }

    _shouldHide() {
        if (!this._settings.get_boolean('dock-auto-hide'))
            return false;
        const window = global.display.focus_window;
        return Boolean(window?.maximized_horizontally || window?.maximized_vertically);
    }

    _syncVisibility() {
        if (this._shouldHide())
            this._conceal();
        else
            this._reveal();
    }

    _reveal() {
        this.actor.ease({translation_y: 0, duration: this._settings.get_boolean('reduced-motion') ? 0 : 120});
    }

    _conceal() {
        this.actor.ease({translation_y: 58, duration: this._settings.get_boolean('reduced-motion') ? 0 : 120});
    }

    disable() {
        for (const [object, signal] of this._signals)
            object.disconnect(signal);
        this._signals = [];
        this.actor?.destroy();
        this._hotEdge?.destroy();
        this.actor = this._hotEdge = this._box = null;
    }
}
