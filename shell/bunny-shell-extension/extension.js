import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {Dock} from './components/dock.js';
import {NotificationCenter} from './components/notificationCenter.js';
import {OverviewRail} from './components/overview.js';
import {QuickSettings} from './components/quickSettings.js';
import {TopBar} from './components/topBar.js';
import {VisualState} from './services/state.js';

export default class BunnyDesktopExtension extends Extension {
    enable() {
        if (GLib.getenv('BUNNY_VISUAL_PREVIEW') !== '1') {
            console.warn('Bunny Desktop V1 refused to start outside Bunny Visual Preview');
            return;
        }

        this._settings = this.getSettings();
        this._state = new VisualState(this.path);
        this._components = [
            new TopBar(this._state, this.path),
            new QuickSettings(this._state, this._settings),
            new NotificationCenter(this._state),
            new Dock(this._state, this._settings),
            new OverviewRail(this._state),
        ];
        for (const component of this._components)
            component.enable();
    }

    disable() {
        for (const component of [...(this._components ?? [])].reverse())
            component.disable();
        this._components = null;
        this._state?.destroy();
        this._state = null;
        this._settings = null;
    }
}
