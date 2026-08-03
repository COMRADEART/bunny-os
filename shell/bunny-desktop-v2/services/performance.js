import GLib from 'gi://GLib';


const TARGETS = Object.freeze({
    'command-palette-open': 150,
    'quick-settings-open': 150,
    'assistant-panel-open': 250,
    'visual-mode-switch': 300,
});
const MAX_RECORDS = 32;


export class PerformanceRecorder {
    constructor() {
        this._records = [];
    }

    begin(name) {
        if (!(name in TARGETS))
            throw new Error(`Unknown Bunny performance measurement: ${name}`);
        return GLib.get_monotonic_time();
    }

    end(name, started) {
        const milliseconds = (GLib.get_monotonic_time() - started) / 1000;
        this._records.push(Object.freeze({name, milliseconds, targetMilliseconds: TARGETS[name]}));
        while (this._records.length > MAX_RECORDS)
            this._records.shift();
        if (milliseconds > TARGETS[name])
            console.warn(`Bunny ${name} exceeded its prototype target: ${milliseconds.toFixed(1)} ms`);
        return milliseconds;
    }

    snapshot() {
        return Object.freeze([...this._records]);
    }

    clear() {
        this._records = [];
    }
}
