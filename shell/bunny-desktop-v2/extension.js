import GLib from 'gi://GLib';

import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {ModeController} from './controllers/modeController.js';


export default class BunnyDesktopV2Extension extends Extension {
    enable() {
        if (GLib.getenv('BUNNY_VISUAL_V2_PREVIEW') !== '1') {
            console.warn('Bunny Desktop V2 refused to start outside Bunny Desktop Preview');
            return;
        }

        this._settings = this.getSettings();
        this._modeController = new ModeController(this._settings);
        this._modeController.enable();
    }

    disable() {
        this._modeController?.disable();
        this._modeController = null;
        this._settings = null;
    }
}

