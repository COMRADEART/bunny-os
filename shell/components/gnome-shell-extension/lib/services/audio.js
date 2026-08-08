// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// AudioManager: the output volume, through the mixer GNOME Shell already owns.
//
// Gvc is libgnome-volume-control, the same object the system volume slider
// drives. Using it rather than shelling out to pactl matters for three reasons
// that are not style: it tracks the default sink when the user plugs in
// headphones, it reports the change back so the slider and this widget cannot
// disagree, and it works identically on the PipeWire PulseAudio server this
// image ships and on a bare PulseAudio one.
//
// The image has pulseaudio-utils installed for the companion's voice output,
// so `pactl` exists and would have worked. It is still the wrong call: a
// subprocess per volume change, no change notification, and a second idea of
// what "the current sink" means.

import Gvc from 'gi://Gvc';

import {clamp, logOnce, logError_} from '../util.js';

export class AudioManager {
    constructor() {
        this._control = null;
        this._sinkChangedId = 0;
        this._streamChangedId = 0;
        this._listeners = new Set();
        try {
            // GNOME Shell keeps one mixer control for the session. Reusing it
            // avoids a second connection to the sound server and, more
            // importantly, a second cache of stream state that can go stale.
            this._control = new Gvc.MixerControl({name: 'Bunny Desktop'});
            this._control.open();
            this._sinkChangedId = this._control.connect('default-sink-changed',
                () => this._rebind());
            this._rebind();
        } catch (error) {
            this._control = null;
            logOnce('gvc', `the mixer is unavailable (${error.message}); volume reports Unavailable`);
        }
    }

    /** 0..1, or null when there is no default sink. */
    volume() {
        const sink = this._sink();
        if (sink === null)
            return null;
        const max = this._control.get_vol_max_norm();
        if (!max)
            return null;
        return clamp(sink.volume / max, 0, 1);
    }

    muted() {
        const sink = this._sink();
        return sink === null ? null : sink.is_muted;
    }

    setVolume(fraction) {
        const sink = this._sink();
        if (sink === null)
            return;
        try {
            const max = this._control.get_vol_max_norm();
            sink.volume = Math.round(clamp(fraction, 0, 1) * max);
            // push_volume is what commits it. Setting the property alone
            // updates the local object and leaves the sound server untouched,
            // which looks like a slider that moves and does nothing.
            sink.push_volume();
            if (sink.is_muted && fraction > 0)
                sink.change_is_muted(false);
        } catch (error) {
            logError_('volume change refused', error);
        }
    }

    toggleMute() {
        const sink = this._sink();
        if (sink === null)
            return;
        sink.change_is_muted(!sink.is_muted);
    }

    /** Register for changes. Returns a function that unregisters. */
    onChange(callback) {
        this._listeners.add(callback);
        return () => this._listeners.delete(callback);
    }

    destroy() {
        this._unbindStream();
        if (this._control && this._sinkChangedId)
            this._control.disconnect(this._sinkChangedId);
        this._sinkChangedId = 0;
        this._listeners.clear();
        this._control?.close();
        this._control = null;
    }

    _sink() {
        try {
            return this._control?.get_default_sink() ?? null;
        } catch (_error) {
            return null;
        }
    }

    _rebind() {
        this._unbindStream();
        const sink = this._sink();
        if (sink !== null) {
            this._boundStream = sink;
            this._streamChangedId = sink.connect('notify::volume', () => this._emit());
            this._mutedChangedId = sink.connect('notify::is-muted', () => this._emit());
        }
        this._emit();
    }

    _unbindStream() {
        if (this._boundStream) {
            if (this._streamChangedId)
                this._boundStream.disconnect(this._streamChangedId);
            if (this._mutedChangedId)
                this._boundStream.disconnect(this._mutedChangedId);
        }
        this._streamChangedId = 0;
        this._mutedChangedId = 0;
        this._boundStream = null;
    }

    _emit() {
        for (const listener of this._listeners) {
            try {
                listener();
            } catch (error) {
                logError_('volume listener failed', error);
            }
        }
    }
}
