import Gio from 'gi://Gio';

export class LayoutController {
    constructor(settings, components) {
        this._settings = settings;
        this._components = components;
        this._signals = [];
    }

    enable() {
        this._interface = new Gio.Settings({schema_id: 'org.gnome.desktop.interface'});
        for (const key of ['layout-mode', 'theme', 'reduced-motion', 'high-contrast'])
            this._signals.push([this._settings, this._settings.connect(`changed::${key}`, () => this._apply())]);
        this._signals.push([this._interface, this._interface.connect('changed::color-scheme', () => this._apply())]);
        this._signals.push([this._interface, this._interface.connect('changed::enable-animations', () => this._apply())]);
        this._apply();
    }

    _apply() {
        const configuredTheme = this._settings.get_string('theme');
        const systemDark = this._interface.get_string('color-scheme').includes('dark');
        const presentation = {
            mode: this._settings.get_string('layout-mode'),
            theme: configuredTheme === 'system' ? (systemDark ? 'dark' : 'light') : configuredTheme,
            reducedMotion: this._settings.get_boolean('reduced-motion') || !this._interface.get_boolean('enable-animations'),
            highContrast: this._settings.get_boolean('high-contrast'),
        };
        for (const component of this._components)
            component.applyPresentation?.(presentation);
    }

    disable() {
        for (const [object, signal] of this._signals)
            object.disconnect(signal);
        this._signals = [];
        this._interface = null;
    }
}
