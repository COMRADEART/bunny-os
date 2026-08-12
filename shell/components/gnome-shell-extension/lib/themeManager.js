// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// The half of the design system that talks to the session.
//
// Everything decided here is decided from a *system* setting. §8 is explicit
// that a Bunny-specific accessibility toggle which ignores the platform
// preference is not a fix, and the desktop had one of those already — a `theme`
// key in Bunny's own settings store, validated, displayed back to the user as a
// sentence, and applied by nothing.
//
// Four settings, three schemas:
//
//   org.gnome.desktop.interface      text-scaling-factor, color-scheme
//   org.gnome.desktop.a11y.interface high-contrast
//   St.Settings                      enable-animations
//
// `text-scaling-factor` is the one that matters most and is the one the desktop
// was not reading. `desktopShell._textScale()` parsed the point size out of
// `St.Settings.font_name` — but GNOME implements text scaling through Xft DPI
// for GTK clients and never rewrites `font-name`, so that function returned 1.0
// at every scale the accessibility run set. The measured "0.09 % of the screen
// changed at 150 %" was the desktop faithfully redrawing itself at the same size.
//
// ## Failure is always backwards to something that works
//
// GNOME auto-loads the extension's `stylesheet.css`. This class replaces it with
// a generated sheet, and every path that can fail puts it back. If the runtime
// directory is unwritable, if St refuses the generated CSS, if a setting reads
// as nonsense — the shipped sheet stays loaded and the desktop looks like the
// default theme. That is a degraded desktop rather than an unstyled one, and
// `degraded` records which so the shell can say so out loud.

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {renderStylesheet} from './design/stylesheet.js';
import {clampTextScale, resolveTheme, themeKey} from './design/theme.js';

const INTERFACE_SCHEMA = 'org.gnome.desktop.interface';
const A11Y_SCHEMA = 'org.gnome.desktop.a11y.interface';

/** The stylesheet names GNOME may have auto-loaded for this extension. */
const SHIPPED_SHEETS = ['stylesheet.css', 'stylesheet-light.css', 'stylesheet-dark.css'];

function log_(message) {
    console.log(`bunny-theme: ${message}`);
}

/**
 * Read a GSettings key without letting a missing schema take the desktop down.
 *
 * `org.gnome.desktop.a11y.interface` is present on every GNOME session this
 * image builds, but the desktop also has to survive being run on one that is
 * not quite what we shipped — that is what the top-level try/catch in
 * extension.js is for, and this is the same reasoning one level down.
 */
function settingsFor(schema) {
    try {
        const source = Gio.SettingsSchemaSource.get_default();
        if (source === null || source.lookup(schema, true) === null) {
            log_(`the ${schema} schema is not installed; its preferences will read as defaults`);
            return null;
        }
        return new Gio.Settings({schema_id: schema});
    } catch (error) {
        log_(`could not open ${schema}: ${error.message}`);
        return null;
    }
}

export class ThemeManager {
    /**
     * @param {object} options
     * @param {Gio.File} options.dir the extension directory, for the shipped sheet
     * @param {Function} [options.onChanged] called after a successful re-render
     */
    constructor({dir, onChanged = null}) {
        this._dir = dir;
        this._onChanged = onChanged;
        this._generation = 0;
        this._loaded = null;
        this._shippedUnloaded = [];
        this._key = '';
        this._theme = null;
        this.degraded = [];

        this._interface = settingsFor(INTERFACE_SCHEMA);
        this._a11y = settingsFor(A11Y_SCHEMA);
        this._stSettings = St.Settings.get();

        this._handlers = [];
        this._watch(this._interface, ['changed::text-scaling-factor', 'changed::color-scheme']);
        this._watch(this._a11y, ['changed::high-contrast']);
        this._watch(this._stSettings, ['notify::enable-animations', 'notify::high-contrast']);

        this.refresh({force: true});
    }

    _watch(object, signals) {
        if (!object)
            return;
        for (const signal of signals) {
            try {
                this._handlers.push([object, object.connect(signal, () => this.refresh())]);
            } catch (error) {
                // notify::high-contrast does not exist on every St.Settings
                // version. Losing one signal degrades responsiveness, not
                // correctness: the next change to any watched key re-reads all
                // of them.
                log_(`could not watch ${signal}: ${error.message}`);
            }
        }
    }

    // ------------------------------------------------------------- reading

    /**
     * The current accessibility and appearance preferences, from the system.
     *
     * Public because the layout solver and the character renderer need the same
     * numbers, and a second reader would be a second chance to read the wrong
     * key — which is the defect this class was written to fix.
     */
    preferences() {
        const scaling = this._interface?.get_double('text-scaling-factor') ?? 1;

        // Two sources say "high contrast", and they can disagree during a
        // settings change. Either being true is enough: a person who has asked
        // for high contrast anywhere has asked for it.
        let highContrast = this._a11y?.get_boolean('high-contrast') ?? false;
        try {
            highContrast = highContrast || this._stSettings.high_contrast;
        } catch (_error) {
            // Older St. The gsettings answer above stands.
        }

        const scheme = this._interface?.get_string('color-scheme') ?? 'prefer-dark';

        return {
            textScale: clampTextScale(scaling),
            highContrast,
            // `default` means the session has expressed no preference. Bunny's
            // desktop is dark by design, so `default` resolves to dark rather
            // than to light — the alternative is a desktop that changes
            // appearance when GNOME changes its mind about a default.
            scheme: scheme === 'prefer-light' ? 'light' : 'dark',
            reducedMotion: !this._stSettings.enable_animations,
            reducedTransparency: false,
        };
    }

    /** The resolved theme every surface should draw from. */
    get theme() {
        return this._theme;
    }

    /** The text scale, for the layout solver. */
    get textScale() {
        return this._theme?.textScale ?? 1;
    }

    // ------------------------------------------------------------ rendering

    refresh({force = false} = {}) {
        let preferences;
        try {
            preferences = this.preferences();
        } catch (error) {
            this._note(`could not read the display preferences (${error.message})`);
            return false;
        }

        const key = themeKey(preferences);
        if (!force && key === this._key)
            return false;

        const theme = resolveTheme(preferences);
        let css;
        try {
            css = renderStylesheet(theme);
        } catch (error) {
            this._note(`the stylesheet could not be rendered (${error.message})`);
            return false;
        }

        const file = this._write(css);
        if (file === null)
            return false;

        if (!this._apply(file))
            return false;

        this._key = key;
        this._theme = theme;
        log_(`theme ${theme.name} at ${theme.textScale}x` +
            (theme.reducedMotion ? ', reduced motion' : '') +
            (theme.reducedTransparency ? ', opaque surfaces' : ''));
        this._onChanged?.(theme);
        return true;
    }

    /**
     * Write the sheet to a fresh path.
     *
     * A new filename every time, rather than overwriting one. St keys loaded
     * stylesheets by GFile, and asking it to re-read a path it already holds is
     * relying on behaviour that is not part of the API; a new path is
     * unambiguous. The previous file is removed after the new one is loaded, so
     * a failure between the two leaves the old sheet on disk and in use.
     */
    _write(css) {
        const runtime = GLib.get_user_runtime_dir();
        if (!runtime) {
            this._note('there is no runtime directory to write the theme into');
            return null;
        }
        const directory = GLib.build_filenamev([runtime, 'bunny-shell', 'theme']);
        try {
            GLib.mkdir_with_parents(directory, 0o700);
            this._generation += 1;
            const path = GLib.build_filenamev([directory, `bunny-${this._generation}.css`]);
            const file = Gio.File.new_for_path(path);
            // replace_contents with an explicit encode, rather than
            // GLib.file_set_contents: the latter's contents parameter is a byte
            // array in introspection and whether GJS accepts a bare string for
            // it has changed between versions. Encoding here is unambiguous in
            // every version, and this runs during enable().
            file.replace_contents(
                new TextEncoder().encode(css), null, false,
                Gio.FileCreateFlags.REPLACE_DESTINATION, null);
            return file;
        } catch (error) {
            this._note(`the theme could not be written (${error.message})`);
            return null;
        }
    }

    _apply(file) {
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        if (!theme) {
            this._note('there is no St theme to load into');
            return false;
        }

        try {
            theme.load_stylesheet(file);
        } catch (error) {
            this._note(`St refused the generated stylesheet (${error.message})`);
            return false;
        }

        // Only once the generated sheet is in does the shipped one come out.
        // The other order leaves a window in which the desktop has no rules at
        // all, and that window is during `enable()`, on screen.
        this._unloadShipped(theme);

        const previous = this._loaded;
        this._loaded = file;
        if (previous) {
            try {
                theme.unload_stylesheet(previous);
                previous.delete(null);
            } catch (_error) {
                // A leftover file in the runtime directory is not worth a
                // failure path; the session's runtime directory is removed at
                // logout.
            }
        }
        return true;
    }

    _unloadShipped(theme) {
        if (this._shippedUnloaded.length > 0)
            return;
        for (const name of SHIPPED_SHEETS) {
            const file = this._dir?.get_child(name);
            if (!file || !file.query_exists(null))
                continue;
            try {
                theme.unload_stylesheet(file);
                this._shippedUnloaded.push(file);
            } catch (_error) {
                // It was never loaded. Nothing to undo.
            }
        }
    }

    _note(message) {
        log_(message);
        if (!this.degraded.includes(message))
            this.degraded.push(message);
    }

    // ------------------------------------------------------------- teardown

    destroy() {
        for (const [object, id] of this._handlers) {
            try {
                object.disconnect(id);
            } catch (_error) {
                // Already gone.
            }
        }
        this._handlers = [];

        const theme = St.ThemeContext.get_for_stage(global.stage)?.get_theme();
        if (theme) {
            // Put the session back the way GNOME left it: shipped sheet in,
            // generated sheet out. A disabled extension that leaves a generated
            // stylesheet loaded is styling a desktop it no longer owns.
            for (const file of this._shippedUnloaded) {
                try {
                    theme.load_stylesheet(file);
                } catch (error) {
                    log_(`could not restore ${file.get_basename()}: ${error.message}`);
                }
            }
            if (this._loaded) {
                try {
                    theme.unload_stylesheet(this._loaded);
                } catch (_error) {
                    // Nothing more to do.
                }
            }
        }
        this._shippedUnloaded = [];
        try {
            this._loaded?.delete(null);
        } catch (_error) {
            // The runtime directory goes at logout.
        }
        this._loaded = null;
        this._theme = null;
        this._interface = null;
        this._a11y = null;
    }
}
