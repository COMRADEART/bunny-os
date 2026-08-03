import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

const EMPTY_STATE = Object.freeze({
    bunny: 'unavailable',
    provider: 'unavailable',
    backgroundTaskCount: 0,
    pendingApprovalCount: 0,
    privacyUses: [],
    tasks: [],
    approvals: [],
    conversation: [],
    plan: [],
    recentFiles: [],
    toolActivity: [],
    results: [],
    notifications: [],
    mockMode: false,
});

export const VisualState = GObject.registerClass({
    Signals: {'changed': {}},
}, class VisualState extends GObject.Object {
    _init(extensionPath) {
        super._init();
        this._extensionPath = extensionPath;
        this._snapshot = {...EMPTY_STATE};
        this._mockMode = GLib.getenv('BUNNY_VISUAL_MOCK_MODE') === '1';
        const runtime = GLib.getenv('XDG_RUNTIME_DIR');
        this._file = runtime ? Gio.File.new_for_path(`${runtime}/bunny-shell/status.json`) : null;
        if (this._file) {
            try {
                this._monitor = this._file.monitor_file(Gio.FileMonitorFlags.NONE, null);
                this._monitor.connect('changed', () => this._read());
            } catch (error) {
                console.warn(`Bunny status monitor unavailable: ${error.message}`);
            }
        }
        this._read();
    }

    get snapshot() {
        return this._snapshot;
    }

    _readJson(file) {
        const [ok, bytes] = file.load_contents(null);
        if (!ok)
            return null;
        return JSON.parse(new TextDecoder().decode(bytes));
    }

    _read() {
        let incoming = null;
        try {
            if (this._mockMode)
                incoming = this._readJson(Gio.File.new_for_path(`${this._extensionPath}/mock-state.json`));
            else if (this._file?.query_exists(null))
                incoming = this._readJson(this._file);
        } catch (error) {
            console.warn(`Bunny status is unavailable: ${error.message}`);
        }
        const safe = incoming && typeof incoming === 'object' ? incoming : {};
        this._snapshot = {
            bunny: String(safe.bunny ?? 'unavailable'),
            provider: String(safe.provider ?? safe.localModel ?? 'unavailable'),
            backgroundTaskCount: Number.isInteger(safe.backgroundTaskCount) ? safe.backgroundTaskCount : Number.isInteger(safe.taskCount) ? safe.taskCount : 0,
            pendingApprovalCount: Number.isInteger(safe.pendingApprovalCount) ? safe.pendingApprovalCount : 0,
            privacyUses: Array.isArray(safe.privacyUses) ? safe.privacyUses : [],
            tasks: Array.isArray(safe.tasks) ? safe.tasks : [],
            approvals: Array.isArray(safe.approvals) ? safe.approvals : [],
            conversation: Array.isArray(safe.conversation) ? safe.conversation : [],
            plan: Array.isArray(safe.plan) ? safe.plan : [],
            recentFiles: Array.isArray(safe.recentFiles) ? safe.recentFiles : [],
            toolActivity: Array.isArray(safe.toolActivity) ? safe.toolActivity : [],
            results: Array.isArray(safe.results) ? safe.results : [],
            notifications: Array.isArray(safe.notifications) ? safe.notifications : [],
            mockMode: this._mockMode,
        };
        this.emit('changed');
    }

    destroy() {
        this._monitor?.cancel();
        this._monitor = null;
        this._file = null;
    }
});
