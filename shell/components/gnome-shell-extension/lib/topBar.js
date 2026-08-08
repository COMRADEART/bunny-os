// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// TopBar: identity on the left, search in the middle, the machine on the right.
//
// The right-hand indicators are read-only here, with one exception each way:
// volume and brightness are adjustable inline because changing them is a
// hundred times a day action and a trip to Settings for it is the sort of thing
// that makes a desktop feel like a configuration screen. Network is not, and
// deliberately: choosing a Wi-Fi network involves a scan, a password field and
// a secret store, all of which GNOME already does correctly, so the indicator
// opens that rather than reimplementing it badly.
//
// The clock updates on a minute boundary rather than every second. A
// once-a-second timer that redraws a label showing minutes wakes the CPU sixty
// times for one visible change, which on a laptop is measurable.

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import St from 'gi://St';

import {Metric} from './tokens.js';
import {box, glass} from './widgets.js';
import {interval, makeActivatable, timeout, logError_} from './util.js';

export class TopBar {
    /**
     * @param {{launcher, audio, brightness, network, power, onSearch,
     *          onSearchActivate, onAvatar, blur}} context
     */
    constructor(context) {
        this._context = context;
        this._clockTimer = null;
        this._alignTimer = null;
        this._pollTimer = null;
        this._audioUnsubscribe = null;

        this.actor = glass('bunny-top-bar', {blur: context.blur, radius: 24});
        const row = box({style_class: 'bunny-top-bar-row', x_expand: true});
        this.actor.add_child(row);

        row.add_child(this._buildIdentity());
        row.add_child(new St.Widget({x_expand: true}));
        row.add_child(this._buildSearch());
        row.add_child(new St.Widget({x_expand: true}));
        row.add_child(this._buildIndicators());

        this._startClock();
        this._pollTimer = interval(5, () => this._refreshIndicators());
        this._audioUnsubscribe = context.audio?.onChange(() => this._refreshVolume()) ?? null;
        this._refreshIndicators();
    }

    /** Move key focus into the search field. Bound to a keyboard shortcut. */
    focusSearch() {
        this._search.grab_key_focus();
    }

    get searchText() {
        return this._search.get_text();
    }

    clearSearch() {
        this._search.set_text('');
    }

    destroy() {
        this._clockTimer?.stop();
        this._alignTimer?.stop();
        this._pollTimer?.stop();
        this._audioUnsubscribe?.();
        this.actor.destroy();
    }

    _buildIdentity() {
        const identity = box({style_class: 'bunny-top-identity'});
        identity.add_child(new St.Icon({
            icon_name: 'bunny-shell-symbolic',
            icon_size: 18,
            style_class: 'bunny-top-logo',
        }));
        identity.add_child(new St.Label({text: 'Bunny OS', style_class: 'bunny-top-wordmark'}));
        makeActivatable(identity, () => this._context.onHome?.(), {accessibleName: 'Bunny OS home'});
        return identity;
    }

    _buildSearch() {
        const wrapper = box({style_class: 'bunny-search-wrapper'});
        this._search = new St.Entry({
            style_class: 'bunny-search-entry',
            hint_text: 'Search anything...',
            can_focus: true,
            x_expand: true,
        });
        this._search.set_primary_icon(new St.Icon({
            icon_name: 'system-search-symbolic',
            style_class: 'bunny-search-icon',
            icon_size: 16,
        }));
        this._search.accessible_name = 'Search applications, files, settings and Bunny';

        this._search.clutter_text.connect('text-changed', () => {
            this._context.onSearch?.(this._search.get_text());
        });
        this._search.clutter_text.connect('activate', () => {
            this._context.onSearchActivate?.(this._search.get_text());
        });
        this._search.clutter_text.connect('key-press-event', (_actor, event) => {
            if (event.get_key_symbol() === Clutter.KEY_Escape) {
                this._context.onSearchDismiss?.();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        wrapper.add_child(this._search);
        return wrapper;
    }

    _buildIndicators() {
        const indicators = box({style_class: 'bunny-top-indicators'});

        this._volumeIcon = this._indicatorButton('audio-volume-high-symbolic', 'Volume', () => {
            this._context.audio?.toggleMute();
            this._refreshVolume();
        });
        this._volumeIcon.connect('scroll-event', (_actor, event) => this._onVolumeScroll(event));
        indicators.add_child(this._volumeIcon);

        this._brightnessIcon = this._indicatorButton('display-brightness-symbolic', 'Brightness', () => {
            this._context.launcher?.spawn(['gnome-control-center', 'display']);
        });
        this._brightnessIcon.connect('scroll-event', (_actor, event) => this._onBrightnessScroll(event));
        indicators.add_child(this._brightnessIcon);

        this._networkIcon = this._indicatorButton('network-wireless-signal-none-symbolic', 'Network', () => {
            this._context.network?.openSettings();
        });
        indicators.add_child(this._networkIcon);

        this._batteryBox = box({style_class: 'bunny-top-battery'});
        this._batteryIcon = new St.Icon({icon_size: 16, style_class: 'bunny-top-indicator-icon'});
        this._batteryLabel = new St.Label({text: '', style_class: 'bunny-top-battery-label'});
        this._batteryBox.add_child(this._batteryIcon);
        this._batteryBox.add_child(this._batteryLabel);
        makeActivatable(this._batteryBox,
            () => this._context.launcher?.spawn(['gnome-control-center', 'power']),
            {accessibleName: 'Power settings'});
        indicators.add_child(this._batteryBox);

        this._clock = new St.Label({text: '', style_class: 'bunny-top-clock'});
        this._date = new St.Label({text: '', style_class: 'bunny-top-date'});
        const clockBox = box({vertical: true, style_class: 'bunny-top-clock-box'});
        clockBox.add_child(this._clock);
        clockBox.add_child(this._date);
        makeActivatable(clockBox, () => this._context.onAgenda?.(), {accessibleName: 'Date and time'});
        indicators.add_child(clockBox);

        this._avatar = new St.Label({
            text: this._initials(),
            style_class: 'bunny-top-avatar',
        });
        makeActivatable(this._avatar, () => this._context.onAvatar?.(), {
            accessibleName: `Account: ${GLib.get_real_name() || GLib.get_user_name()}`,
        });
        indicators.add_child(this._avatar);

        return indicators;
    }

    _indicatorButton(iconName, accessibleName, onActivate) {
        const button = new St.Icon({
            icon_name: iconName,
            icon_size: 16,
            style_class: 'bunny-top-indicator-icon',
        });
        makeActivatable(button, onActivate, {accessibleName});
        return button;
    }

    _initials() {
        const name = GLib.get_real_name() || GLib.get_user_name() || '?';
        const parts = name.trim().split(/\s+/).filter(Boolean);
        if (parts.length === 0)
            return '?';
        if (parts.length === 1)
            return parts[0].slice(0, 1).toUpperCase();
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }

    /**
     * Tick on the minute, not on a 60-second period.
     *
     * A 60-second interval started at :37 shows the new minute 37 seconds late,
     * for ever. The first timeout aligns to the boundary and the interval takes
     * over from there.
     */
    _startClock() {
        this._renderClock();
        const now = GLib.DateTime.new_now_local();
        const msToNextMinute = (60 - now.get_second()) * 1000;
        this._alignTimer = timeout(msToNextMinute, () => {
            this._renderClock();
            this._clockTimer = interval(60, () => this._renderClock());
        });
    }

    _renderClock() {
        const now = GLib.DateTime.new_now_local();
        // %-I and %-l are glibc extensions for a space-padded hour; the shell
        // runs on glibc, and the alternative is a leading zero users read as
        // military time.
        this._clock.text = now.format('%H:%M');
        this._date.text = now.format('%a %-d %b');
        this._clock.get_parent().accessible_name = now.format('%A %-d %B, %H:%M');
    }

    _refreshIndicators() {
        this._refreshVolume();
        this._refreshBrightness();
        this._refreshNetwork();
        this._refreshBattery();
    }

    _refreshVolume() {
        const audio = this._context.audio;
        if (!audio)
            return;
        const volume = audio.volume();
        const muted = audio.muted();
        if (volume === null) {
            this._volumeIcon.icon_name = 'audio-volume-muted-symbolic';
            this._volumeIcon.accessible_name = 'Volume: Unavailable';
            return;
        }
        const level = muted ? 'muted' : volume < 0.01 ? 'muted'
            : volume < 0.34 ? 'low' : volume < 0.67 ? 'medium' : 'high';
        this._volumeIcon.icon_name = `audio-volume-${level}-symbolic`;
        this._volumeIcon.accessible_name = muted
            ? 'Volume muted'
            : `Volume ${Math.round(volume * 100)} percent`;
    }

    _refreshBrightness() {
        const brightness = this._context.brightness;
        const value = brightness?.percentage() ?? null;
        // A machine with no controllable backlight gets no control. Showing a
        // dead icon is the "Linux configuration screen" failure mode.
        this._brightnessIcon.visible = value !== null;
        if (value !== null)
            this._brightnessIcon.accessible_name = `Brightness ${value} percent`;
    }

    _refreshNetwork() {
        const connection = this._context.network?.connection();
        if (!connection) {
            this._networkIcon.accessible_name = 'Network: Unavailable';
            return;
        }
        const {state, kind} = connection;
        const iconName = kind === 'wired'
            ? (state === 'connected' ? 'network-wired-symbolic' : 'network-wired-disconnected-symbolic')
            : state === 'connected' ? 'network-wireless-signal-excellent-symbolic'
                : state === 'limited' ? 'network-wireless-acquiring-symbolic'
                    : 'network-wireless-offline-symbolic';
        this._networkIcon.icon_name = iconName;
        this._networkIcon.accessible_name = `Network ${state}`;
    }

    _refreshBattery() {
        const battery = this._context.power?.battery();
        if (!battery) {
            this._batteryBox.visible = false;
            return;
        }
        this._batteryBox.visible = true;
        if (!battery.present) {
            // The brief is explicit: a desktop says AC Power, it does not
            // invent a percentage.
            this._batteryIcon.icon_name = 'ac-adapter-symbolic';
            this._batteryLabel.text = 'AC';
            this._batteryBox.accessible_name = 'Running on AC power';
            return;
        }
        if (battery.percentage === null) {
            this._batteryIcon.icon_name = 'battery-missing-symbolic';
            this._batteryLabel.text = '';
            this._batteryBox.accessible_name = 'Battery level Unavailable';
            return;
        }
        const charging = battery.state === 'charging' || battery.state === 'full';
        const step = Math.max(0, Math.min(100, Math.round(battery.percentage / 10) * 10));
        this._batteryIcon.icon_name = charging
            ? `battery-level-${step}-charging-symbolic`
            : `battery-level-${step}-symbolic`;
        this._batteryLabel.text = `${battery.percentage}%`;
        this._batteryBox.accessible_name = charging
            ? `Battery ${battery.percentage} percent, charging`
            : `Battery ${battery.percentage} percent`;
    }

    _onVolumeScroll(event) {
        const audio = this._context.audio;
        const current = audio?.volume();
        if (current === null || current === undefined)
            return Clutter.EVENT_PROPAGATE;
        const direction = event.get_scroll_direction();
        const delta = direction === Clutter.ScrollDirection.UP ? 0.05
            : direction === Clutter.ScrollDirection.DOWN ? -0.05 : 0;
        if (delta === 0)
            return Clutter.EVENT_PROPAGATE;
        audio.setVolume(current + delta);
        this._refreshVolume();
        return Clutter.EVENT_STOP;
    }

    _onBrightnessScroll(event) {
        const brightness = this._context.brightness;
        const current = brightness?.percentage();
        if (current === null || current === undefined)
            return Clutter.EVENT_PROPAGATE;
        const direction = event.get_scroll_direction();
        const delta = direction === Clutter.ScrollDirection.UP ? 5
            : direction === Clutter.ScrollDirection.DOWN ? -5 : 0;
        if (delta === 0)
            return Clutter.EVENT_PROPAGATE;
        try {
            brightness.setPercentage(current + delta);
        } catch (error) {
            logError_('brightness scroll failed', error);
        }
        return Clutter.EVENT_STOP;
    }
}

// Referenced so the token module is a declared dependency of the bar's sizing
// even though the height itself is set in stylesheet.css. Keeps the two from
// drifting silently: a change here that is not mirrored there fails review.
export const TOP_BAR_HEIGHT = Metric.TOP_BAR_HEIGHT;
