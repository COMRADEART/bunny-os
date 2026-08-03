import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import {APPROVED_POSES} from './characterState.js';


const MAX_CACHE_ENTRIES = 3;


export class CharacterAssetLoader {
    constructor(extensionPath) {
        const development = GLib.build_filenamev([
            extensionPath, '..', '..', 'visual-v2', 'assets', 'character', 'bunny-guide', 'v1',
        ]);
        const installed = '/usr/share/bunny-visual-v2/character/bunny-guide/v1';
        this._root = Gio.File.new_for_path(development).query_exists(null) ? development : installed;
        this._cache = new Map();
        this.loadCount = 0;
    }

    load(pose) {
        if (!APPROVED_POSES.includes(pose))
            throw new Error(`Unapproved Bunny guide pose: ${pose}`);
        if (this._cache.has(pose)) {
            const value = this._cache.get(pose);
            this._cache.delete(pose);
            this._cache.set(pose, value);
            return value;
        }
        const file = Gio.File.new_for_path(GLib.build_filenamev([this._root, `${pose}.png`]));
        if (!file.query_exists(null))
            throw new Error(`Bunny guide asset unavailable: ${pose}`);
        const icon = new Gio.FileIcon({file});
        this._cache.set(pose, icon);
        this.loadCount += 1;
        while (this._cache.size > MAX_CACHE_ENTRIES)
            this._cache.delete(this._cache.keys().next().value);
        return icon;
    }

    clear() {
        this._cache.clear();
    }

    get cacheSize() {
        return this._cache.size;
    }
}
