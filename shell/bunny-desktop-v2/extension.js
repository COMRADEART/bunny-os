import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {AdaptiveDock} from './components/dock.js';
import {CommandPalette} from './components/commandPalette.js';
import {LayoutController} from './components/layoutController.js';
import {SystemPanel} from './components/systemPanel.js';
import {TopBar} from './components/topBar.js';
import {ModeController} from './controllers/modeController.js';
import {VisualState} from './services/state.js';
import {PerformanceRecorder} from './services/performance.js';


export default class BunnyDesktopV2Extension extends Extension {
    enable() {
        if (GLib.getenv('BUNNY_VISUAL_V2_PREVIEW') !== '1') {
            console.warn('Bunny Desktop V2 refused to start outside Bunny Desktop Preview');
            return;
        }

        this._settings = this.getSettings();
        this._performance = new PerformanceRecorder();
        this._modeController = new ModeController(this._settings, this._performance);
        this._modeController.enable();
        this._state = new VisualState(this.path);
        this._systemPanel = new SystemPanel(this._state, this._settings, this.path, this._performance);
        this._components = [
            this._systemPanel,
            new TopBar(this._state, this.path, this._settings, this._systemPanel),
            new AdaptiveDock(this._settings),
            new CommandPalette(this._settings, this._systemPanel, this._performance),
            new LayoutController(),
        ];
        for (const component of this._components) {
            component.enable();
            this._modeController.register(component);
        }
    }

    disable() {
        for (const component of [...(this._components ?? [])].reverse()) {
            this._modeController?.unregister(component);
            component.disable();
        }
        this._components = null;
        this._systemPanel = null;
        this._state?.destroy();
        this._state = null;
        this._modeController?.disable();
        this._modeController = null;
        this._performance?.clear();
        this._performance = null;
        this._settings = null;
    }
}
