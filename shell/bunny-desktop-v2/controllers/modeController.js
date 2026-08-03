import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';


const PRESENTATION_KEYS = new Set([
    'visual-mode',
    'color-scheme',
    'accent-color',
    'layout-mode',
    'character-enabled',
    'character-scale',
    'character-position',
    'reduced-motion',
    'panel-transparency',
    'dock-autohide',
    'assistant-panel-width',
    'focus-mode-enabled',
    'compact-layout-enabled',
]);


export class ModeController {
    constructor(settings) {
        this._settings = settings;
        this._components = new Set();
        this._settingsSignal = 0;
    }

    enable() {
        this._settingsSignal = this._settings.connect('changed', (_settings, key) => {
            if (PRESENTATION_KEYS.has(key))
                this._apply();
        });
        Main.wm.addKeybinding(
            'toggle-visual-mode',
            this._settings,
            Meta.KeyBindingFlags.NONE,
            Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW,
            () => this.toggleVisualMode(),
        );
        this._apply();
    }

    register(component) {
        this._components.add(component);
        component.applyPresentation?.(this.snapshot());
        return component;
    }

    unregister(component) {
        this._components.delete(component);
    }

    setVisualMode(mode) {
        if (!['regular', 'character'].includes(mode))
            throw new Error(`Unsupported Bunny visual mode: ${mode}`);
        this._settings.set_string('visual-mode', mode);
        this._settings.set_boolean('character-enabled', mode === 'character');
    }

    toggleVisualMode() {
        this.setVisualMode(this._settings.get_string('visual-mode') === 'regular' ? 'character' : 'regular');
    }

    snapshot() {
        const visualMode = this._settings.get_string('visual-mode');
        const layout = this._settings.get_string('layout-mode');
        return Object.freeze({
            visualMode,
            characterVisible: visualMode === 'character' && this._settings.get_boolean('character-enabled'),
            colorScheme: this._settings.get_string('color-scheme'),
            accent: this._settings.get_string('accent-color'),
            layout,
            compact: layout === 'compact' || this._settings.get_boolean('compact-layout-enabled'),
            focus: layout === 'focus' || this._settings.get_boolean('focus-mode-enabled'),
            characterScale: this._settings.get_double('character-scale'),
            characterPosition: this._settings.get_string('character-position'),
            reducedMotion: this._settings.get_boolean('reduced-motion'),
            panelTransparency: this._settings.get_double('panel-transparency'),
            dockAutohide: this._settings.get_boolean('dock-autohide'),
            assistantPanelWidth: this._settings.get_int('assistant-panel-width'),
        });
    }

    _apply() {
        const presentation = this.snapshot();
        for (const component of this._components)
            component.applyPresentation?.(presentation);
    }

    disable() {
        Main.wm.removeKeybinding('toggle-visual-mode');
        if (this._settingsSignal)
            this._settings.disconnect(this._settingsSignal);
        this._settingsSignal = 0;
        this._components.clear();
    }
}

