// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// SystemTelemetry: CPU, memory, storage and temperature, from the kernel.
//
// Every number here comes from /proc or /sys. There is no fallback value and no
// plausible default: a reader that cannot answer returns null, and the widget
// above it prints "Unavailable". That rule is the reason this file has no
// constants in it that look like measurements.
//
// CPU load is a rate, so the first sample cannot produce one. `cpu` returns
// null until it has two samples to subtract, rather than reporting the
// since-boot average as if it were the current load — those differ by a lot on
// a machine that has been up for a week, and the since-boot figure would look
// entirely reasonable on the dial.

import Gio from 'gi://Gio';

import {logOnce, readText, listDirectory, readInt} from '../util.js';

export class SystemTelemetry {
    constructor() {
        this._previousCpu = null;
        this._thermalPath = undefined; // undefined = not yet looked for
    }

    /** Fraction of the last interval spent not idle, 0..1, or null. */
    cpu() {
        const text = readText('/proc/stat');
        if (text === null) {
            logOnce('proc-stat', '/proc/stat is unreadable; CPU load reports Unavailable');
            return null;
        }
        const line = text.split('\n').find(row => row.startsWith('cpu '));
        if (!line)
            return null;
        const fields = line.trim().split(/\s+/).slice(1).map(Number);
        if (fields.length < 5 || fields.some(value => !Number.isFinite(value)))
            return null;
        // user nice system idle iowait irq softirq steal ...
        const idle = fields[3] + fields[4];
        const total = fields.reduce((sum, value) => sum + value, 0);
        const sample = {idle, total};
        const previous = this._previousCpu;
        this._previousCpu = sample;
        if (previous === null)
            return null;
        const deltaTotal = sample.total - previous.total;
        const deltaIdle = sample.idle - previous.idle;
        if (deltaTotal <= 0)
            return null;
        return Math.min(1, Math.max(0, 1 - deltaIdle / deltaTotal));
    }

    /** {usedBytes, totalBytes} or null. */
    memory() {
        const text = readText('/proc/meminfo');
        if (text === null) {
            logOnce('proc-meminfo', '/proc/meminfo is unreadable; memory reports Unavailable');
            return null;
        }
        const values = new Map();
        for (const line of text.split('\n')) {
            const match = /^(\w+):\s+(\d+) kB$/.exec(line.trim());
            if (match)
                values.set(match[1], Number(match[2]) * 1024);
        }
        const total = values.get('MemTotal');
        // MemAvailable is the kernel's own estimate of what a new allocation
        // could get. Deriving "used" from MemFree instead counts the page cache
        // as used and reports a nearly-full machine that is nothing of the kind.
        const available = values.get('MemAvailable');
        if (!Number.isFinite(total) || !Number.isFinite(available))
            return null;
        return {usedBytes: Math.max(0, total - available), totalBytes: total};
    }

    /** {usedBytes, totalBytes} for the root filesystem, or null. */
    storage(path = '/') {
        try {
            const info = Gio.File.new_for_path(path).query_filesystem_info(
                'filesystem::size,filesystem::used', null);
            const total = info.get_attribute_uint64('filesystem::size');
            const used = info.get_attribute_uint64('filesystem::used');
            if (!total)
                return null;
            return {usedBytes: used, totalBytes: total};
        } catch (_error) {
            logOnce('statfs', `${path} could not be queried; storage reports Unavailable`);
            return null;
        }
    }

    /**
     * Degrees Celsius, or null.
     *
     * Preference order matters. hwmon exposes a named sensor and the CPU
     * package temperature is the one a user means by "temperature"; thermal
     * zones are a fallback because zone 0 on a laptop is as likely to be the
     * battery or the wireless card as the processor. The chosen path is
     * resolved once and logged, so an odd reading can be traced to its sensor.
     */
    temperature() {
        if (this._thermalPath === undefined)
            this._thermalPath = this._findThermalSensor();
        if (this._thermalPath === null)
            return null;
        const milli = readInt(this._thermalPath);
        if (milli === null)
            return null;
        const celsius = milli / 1000;
        // A sensor reporting outside this range is reporting something that is
        // not an ambient temperature; saying nothing beats printing -273°C.
        if (celsius < -40 || celsius > 150)
            return null;
        return celsius;
    }

    _findThermalSensor() {
        const preferred = ['coretemp', 'k10temp', 'zenpower', 'cpu_thermal', 'acpitz'];
        const candidates = [];
        for (const entry of listDirectory('/sys/class/hwmon')) {
            const base = `/sys/class/hwmon/${entry}`;
            const name = (readText(`${base}/name`) ?? '').trim();
            for (const file of listDirectory(base)) {
                if (/^temp\d+_input$/.test(file))
                    candidates.push({name, path: `${base}/${file}`});
            }
        }
        for (const wanted of preferred) {
            const match = candidates.find(candidate => candidate.name === wanted);
            if (match) {
                logOnce('thermal', `temperature read from hwmon ${match.name} (${match.path})`);
                return match.path;
            }
        }
        for (const entry of listDirectory('/sys/class/thermal')) {
            if (!entry.startsWith('thermal_zone'))
                continue;
            const path = `/sys/class/thermal/${entry}/temp`;
            if (readInt(path) !== null) {
                const type = (readText(`/sys/class/thermal/${entry}/type`) ?? entry).trim();
                logOnce('thermal', `temperature read from thermal zone ${type} (${path})`);
                return path;
            }
        }
        if (candidates.length > 0) {
            logOnce('thermal', `temperature read from hwmon ${candidates[0].name} (${candidates[0].path})`);
            return candidates[0].path;
        }
        logOnce('thermal', 'no thermal sensor found; temperature reports Unavailable');
        return null;
    }
}
