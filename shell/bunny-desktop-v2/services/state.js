import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';


const EMPTY_STATE = Object.freeze({
    assistantState: 'Ready',
    providerState: 'Unavailable',
    privacyState: 'Local Only',
    privacyUses: [],
    approvals: [],
    notifications: [],
    recentActions: [],
    systemContext: [],
    suggestions: [],
    networkState: 'Unavailable',
    bluetoothState: 'Unavailable',
    audioState: 'Unavailable',
    media: null,
    updates: 'Unavailable',
    mockMode: false,
    decisionAvailable: false,
    bunnyEnabled: true,
    resultConfirmed: false,
    milestoneConfirmed: false,
});


function array(value) {
    return Array.isArray(value) ? value.filter(item => item && typeof item === 'object') : [];
}


function normalize(value, mockMode) {
    const source = value && typeof value === 'object' ? value : {};
    return Object.freeze({
        assistantState: String(source.assistantState ?? EMPTY_STATE.assistantState),
        providerState: String(source.providerState ?? EMPTY_STATE.providerState),
        privacyState: String(source.privacyState ?? EMPTY_STATE.privacyState),
        privacyUses: array(source.privacyUses),
        approvals: array(source.approvals),
        notifications: array(source.notifications),
        recentActions: array(source.recentActions),
        systemContext: array(source.systemContext),
        suggestions: array(source.suggestions),
        networkState: String(source.networkState ?? EMPTY_STATE.networkState),
        bluetoothState: String(source.bluetoothState ?? EMPTY_STATE.bluetoothState),
        audioState: String(source.audioState ?? EMPTY_STATE.audioState),
        media: source.media && typeof source.media === 'object' ? source.media : null,
        updates: String(source.updates ?? EMPTY_STATE.updates),
        mockMode,
        decisionAvailable: mockMode ? false : source.decisionAvailable === true,
        bunnyEnabled: source.bunnyEnabled !== false,
        resultConfirmed: source.resultConfirmed === true,
        milestoneConfirmed: source.milestoneConfirmed === true,
    });
}


export const VisualState = GObject.registerClass({
    Signals: {'changed': {}},
}, class VisualState extends GObject.Object {
    _init(extensionPath) {
        super._init();
        this._mockMode = GLib.getenv('BUNNY_VISUAL_MOCK_MODE') === '1';
        this._path = this._mockMode
            ? GLib.build_filenamev([extensionPath, 'mock-state.json'])
            : GLib.build_filenamev([GLib.get_user_runtime_dir(), 'bunny-shell', 'core-summary-v2.json']);
        this.snapshot = normalize(null, this._mockMode);
        const parentPath = GLib.path_get_dirname(this._path);
        if (!this._mockMode)
            GLib.mkdir_with_parents(parentPath, 0o700);
        this._reload();
        this._monitor = Gio.File.new_for_path(parentPath).monitor_directory(Gio.FileMonitorFlags.NONE, null);
        this._monitorSignal = this._monitor.connect('changed', () => this._reload());
    }

    _reload() {
        try {
            const file = Gio.File.new_for_path(this._path);
            const info = file.query_info('standard::size,standard::type', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            if (info.get_file_type() !== Gio.FileType.REGULAR || info.get_size() > 1024 * 1024)
                throw new Error('state projection is not a bounded regular file');
            const [ok, contents] = file.load_contents(null);
            if (!ok)
                throw new Error('state projection could not be read');
            this.snapshot = normalize(JSON.parse(new TextDecoder().decode(contents)), this._mockMode);
        } catch (_error) {
            this.snapshot = normalize(null, this._mockMode);
        }
        this.emit('changed');
    }

    destroy() {
        if (this._monitorSignal)
            this._monitor.disconnect(this._monitorSignal);
        this._monitor?.cancel();
        this._monitor = null;
        this._monitorSignal = 0;
    }
});
