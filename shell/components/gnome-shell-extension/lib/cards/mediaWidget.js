// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// MediaWidget: what is playing, when something is.
//
// The card collapses when no MPRIS player exists on the bus — not "shows
// nothing", collapses, so the cards below it move up and the column does not
// carry a hole. The brief allows either that or a neutral state; collapsing is
// chosen because on a freshly installed machine nothing is playing and a
// permanent empty music card is the first thing a user sees that does nothing.
//
// Album art is loaded from the artUrl the player publishes, which is usually a
// file:// URI into its own cache. Remote URLs are refused: this desktop makes
// no outbound connection, and a media player that published an https artUrl
// would otherwise turn the shell into an HTTP client on a privacy-reviewed
// image. That refusal is the reason for the scheme check in _setArt.

import Gio from 'gi://Gio';
import St from 'gi://St';

import {Card} from './base.js';
import {box, Meter} from '../widgets.js';
import {makeActivatable, logOnce} from '../util.js';
import {Icons, MEDIA_ICONS, setIconName, themedIcon} from '../icons.js';

export class MediaWidget extends Card {
    constructor({media, blur}) {
        super({title: 'Now Playing', refreshSeconds: 2, blur, accessibleName: 'Media player'});
        this._media = media;

        const row = box({style_class: 'bunny-media-row'});
        this._art = new St.Icon({
            icon_name: Icons.MEDIA_GENERIC,
            icon_size: 44,
            style_class: 'bunny-media-art',
        });
        row.add_child(this._art);

        const text = box({vertical: true, style_class: 'bunny-media-text', x_expand: true});
        this._title = new St.Label({text: '', style_class: 'bunny-media-title'});
        this._artist = new St.Label({text: '', style_class: 'bunny-media-artist'});
        this._title.clutter_text.ellipsize = 3;
        this._artist.clutter_text.ellipsize = 3;
        text.add_child(this._title);
        text.add_child(this._artist);
        row.add_child(text);
        this.content.add_child(row);

        const controls = box({style_class: 'bunny-media-controls'});
        this._previous = this._control(MEDIA_ICONS.previous, 'Previous track',
            () => this._media.previous());
        this._playPause = this._control(MEDIA_ICONS.play, 'Play or pause',
            () => this._media.playPause());
        this._next = this._control(MEDIA_ICONS.next, 'Next track',
            () => this._media.next());
        controls.add_child(this._previous);
        controls.add_child(this._playPause);
        controls.add_child(this._next);

        this._elapsed = new St.Label({text: '', style_class: 'bunny-media-time'});
        this._remaining = new St.Label({text: '', style_class: 'bunny-media-time'});
        controls.add_child(new St.Widget({x_expand: true}));
        controls.add_child(this._elapsed);
        controls.add_child(new St.Label({text: '/', style_class: 'bunny-media-time'}));
        controls.add_child(this._remaining);
        this.content.add_child(controls);

        this._progress = new Meter({height: 4});
        this.content.add_child(this._progress.actor);

        this._unsubscribe = media.onChange(() => this.refresh());
    }

    /** True when there is something to show. DesktopShell asks before placing it. */
    get hasMedia() {
        return this._media.current() !== null;
    }

    refresh() {
        const track = this._media.current();
        if (track === null) {
            this.actor.visible = false;
            return;
        }
        this.actor.visible = this.live;

        this._title.text = track.title ?? 'Unknown track';
        this._artist.text = track.artist ?? 'Unknown artist';
        this._setArt(track.artUrl);

        const playing = track.status === 'Playing';
        setIconName(this._playPause.iconActor,
            playing ? MEDIA_ICONS.pause : MEDIA_ICONS.play);
        this._playPause.accessible_name = playing ? 'Pause' : 'Play';
        this._previous.visible = track.canGoPrevious;
        this._next.visible = track.canGoNext;

        const {positionSeconds: position, lengthSeconds: length} = track;
        if (position !== null && length !== null && length > 0) {
            this._progress.set(position / length);
            this._elapsed.text = formatClock(position);
            this._remaining.text = formatClock(length);
        } else {
            // A live stream has no length. An empty bar is right; a full one
            // would say the track is over.
            this._progress.set(null);
            this._elapsed.text = position === null ? '' : formatClock(position);
            this._remaining.text = '';
        }

        this.actor.accessible_name =
            `${playing ? 'Playing' : 'Paused'}: ${this._title.text} by ${this._artist.text}`;
    }

    destroy() {
        this._unsubscribe?.();
        super.destroy();
    }

    _control(iconName, accessibleName, onActivate) {
        const button = box({style_class: 'bunny-media-button'});
        const icon = themedIcon(iconName, {size: 16});
        button.add_child(icon);
        button.iconActor = icon;
        makeActivatable(button, onActivate, {accessibleName});
        return button;
    }

    _setArt(artUrl) {
        if (!artUrl) {
            this._art.gicon = null;
            setIconName(this._art, Icons.MEDIA_GENERIC);
            return;
        }
        // file: only. See the module note: this process does not fetch.
        if (!artUrl.startsWith('file://')) {
            logOnce('media-art-remote',
                'a media player published remote album art; it is not fetched and the placeholder is shown');
            this._art.gicon = null;
            setIconName(this._art, Icons.MEDIA_GENERIC);
            return;
        }
        try {
            this._art.gicon = Gio.FileIcon.new(Gio.File.new_for_uri(artUrl));
        } catch (_error) {
            this._art.gicon = null;
            setIconName(this._art, Icons.MEDIA_GENERIC);
        }
    }
}

function formatClock(seconds) {
    const total = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${minutes}:${String(rest).padStart(2, '0')}`;
}
