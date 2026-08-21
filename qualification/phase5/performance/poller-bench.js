#!/usr/bin/gjs
// Rank the desktop's 2-second pollers by what their data sources actually cost.
//
// The shell's idle CPU rose from 0.80% to 2.07% between 7edd3fd and the Alpha
// RC and Phase 4 named UI polling as the first hypothesis without measuring it.
// This measures the half that can be measured without a compositor: the read
// and parse each poller performs per tick. It does NOT measure the Clutter
// redraw, which needs the shell; that is what the in-extension instrumentation
// is for. Stated so the number is not read as the whole answer.
//
// The storage reader's real parser is imported rather than reimplemented --
// services/storage.js has no imports at all, so it can run under bare gjs. The
// util.js helpers cannot: they pull in St and Clutter.

import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

const HERE = GLib.getenv('BUNNY_SHELL_LIB');
const {parseMountinfo, selectStorageMount} = await import(`file://${HERE}/services/storage.js`);

function readText(path) {
    try {
        const [ok, bytes] = GLib.file_get_contents(path);
        return ok ? new TextDecoder().decode(bytes) : null;
    } catch (_error) {
        return null;
    }
}

// -- the four readers, transcribed from lib/services/telemetry.js -------------

function readCpu() {
    const text = readText('/proc/stat');
    if (text === null)
        return null;
    const line = text.split('\n', 1)[0].split(/\s+/).slice(1).map(Number);
    const total = line.reduce((sum, value) => sum + value, 0);
    return {total, idle: line[3] + (line[4] || 0)};
}

function readMemory() {
    const text = readText('/proc/meminfo');
    if (text === null)
        return null;
    const values = {};
    for (const row of text.split('\n')) {
        const [key, value] = row.split(':');
        if (value)
            values[key] = parseInt(value.trim(), 10) * 1024;
    }
    return {total: values.MemTotal, available: values.MemAvailable};
}

function readStorage() {
    const mountinfo = readText('/proc/self/mountinfo');
    if (mountinfo === null)
        return null;
    const selection = selectStorageMount(parseMountinfo(mountinfo), {
        homeDirectory: GLib.get_home_dir(),
    });
    if (selection.mount === null)
        return null;
    // The statfs the card performs after selecting.
    const file = Gio.File.new_for_path(selection.mount.mountPoint);
    const info = file.query_filesystem_info('filesystem::size,filesystem::used', null);
    return {
        mountPoint: selection.mount.mountPoint,
        size: info.get_attribute_uint64('filesystem::size'),
    };
}

function readTemperature() {
    // The path is resolved once and cached in the real reader, so the per-tick
    // cost is one small read. Measured as one small read.
    const zones = ['/sys/class/thermal/thermal_zone0/temp'];
    for (const path of zones) {
        const text = readText(path);
        if (text !== null)
            return parseInt(text.trim(), 10);
    }
    return null;
}

// -- measurement --------------------------------------------------------------

function bench(name, fn, iterations) {
    // One warm pass first: the page cache and the JIT are not what is being
    // compared, and a cold first call would be attributed to whichever reader
    // happened to run first.
    fn();
    const start = GLib.get_monotonic_time();
    let last = null;
    for (let i = 0; i < iterations; i++)
        last = fn();
    const elapsed = GLib.get_monotonic_time() - start;
    return {
        name,
        microsecondsPerCall: elapsed / iterations,
        totalMicroseconds: elapsed,
        iterations,
        sample: last === null ? null : JSON.stringify(last).slice(0, 90),
    };
}

const ITERATIONS = 2000;
const results = [
    bench('cpu        (/proc/stat)', readCpu, ITERATIONS),
    bench('memory     (/proc/meminfo)', readMemory, ITERATIONS),
    bench('storage    (/proc/self/mountinfo + statfs)', readStorage, ITERATIONS),
    bench('temperature(/sys thermal, cached path)', readTemperature, ITERATIONS),
];

const total = results.reduce((sum, r) => sum + r.microsecondsPerCall, 0);
print(`mountinfo is ${readText('/proc/self/mountinfo').split('\n').length - 1} lines\n`);
print('reader                                        us/call   share   per hour at 2s');
for (const r of results.sort((a, b) => b.microsecondsPerCall - a.microsecondsPerCall)) {
    const share = (100 * r.microsecondsPerCall / total).toFixed(1);
    const perHour = (r.microsecondsPerCall * 1800 / 1e6).toFixed(3);
    print(`${r.name.padEnd(45)} ${r.microsecondsPerCall.toFixed(1).padStart(7)}  ${share.padStart(5)}%  ${perHour.padStart(7)}s`);
}
print(`\ntotal per 2s tick: ${total.toFixed(1)} us  ->  ${(total * 1800 / 1e6).toFixed(3)}s of CPU per hour`);
print(`as a fraction of one core: ${(100 * total / 2e6).toFixed(4)}%`);
