import Clutter from 'gi://Clutter';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {TOKENS} from '../generatedTokens.js';
import {ActivityPanel} from './activityPanel.js';
import {ApprovalPanel} from './approvalPanel.js';
import {AssistantPanel} from './assistantPanel.js';
import {applyPresentationClasses} from './presentation.js';
import {QuickSettings} from './quickSettings.js';


export class SystemPanel {
    constructor(state, settings, extensionPath, performance) {
        this._state = state;
        this._settings = settings;
        this._extensionPath = extensionPath;
        this._performance = performance;
        this._visible = false;
        this._activeTab = 'quick';
    }

    enable() {
        this.actor = new St.BoxLayout({vertical: true, style_class: 'bunny-v2-panel bunny-v2-system-panel', reactive: true, can_focus: false});
        const header = new St.BoxLayout({spacing: TOKENS.spacing.sm});
        this._title = new St.Label({text: 'Bunny OS', style_class: 'bunny-v2-title', x_expand: true});
        const close = new St.Button({
            child: new St.Icon({icon_name: 'window-close-symbolic', icon_size: TOKENS.layout.iconSmall}),
            can_focus: true,
            accessible_name: 'Close Bunny system panel',
            style_class: 'bunny-v2-focus',
        });
        close.connect('clicked', () => this.close());
        header.add_child(this._title);
        header.add_child(close);
        this.actor.add_child(header);

        this._tabRow = new St.BoxLayout({spacing: TOKENS.spacing.sm});
        for (const [id, label] of [['quick', 'Quick'], ['assistant', 'Assistant'], ['approvals', 'Approvals'], ['activity', 'Activity']]) {
            const button = new St.Button({label, can_focus: true, style_class: 'bunny-v2-control bunny-v2-focus'});
            button.connect('clicked', () => this.open(id));
            this._tabRow.add_child(button);
        }
        this.actor.add_child(this._tabRow);
        this._mockBanner = new St.Label({text: 'VISUAL MOCK DATA · actions are simulated', style_class: 'bunny-v2-mock-banner'});
        this._mockBanner.visible = this._state.snapshot.mockMode;
        this.actor.add_child(this._mockBanner);

        this._content = new St.Bin({x_expand: true, y_expand: true});
        this.actor.add_child(this._content);
        const openTab = tab => this.open(tab);
        this._tabs = new Map([
            ['quick', new QuickSettings(this._state, this._settings, openTab)],
            ['assistant', new AssistantPanel(this._state, this._extensionPath, openTab)],
            ['approvals', new ApprovalPanel(this._state)],
            ['activity', new ActivityPanel(this._state)],
        ]);
        for (const tab of this._tabs.values())
            tab.enable();
        this._showTab('quick');
        Main.layoutManager.addChrome(this.actor, {affectsStruts: false, trackFullscreen: true});
        this._monitorSignal = Main.layoutManager.connect('monitors-changed', () => this._place());
        this.actor.visible = false;
        this._place();
    }

    _showTab(id) {
        const tab = this._tabs.get(id);
        if (!tab)
            return;
        this._activeTab = id;
        this._title.text = {quick: 'Bunny OS', assistant: 'Assistant', approvals: 'Approval Center', activity: 'Activity and privacy'}[id];
        this._content.set_child(tab.actor);
    }

    open(id = 'quick') {
        const measurement = id === 'assistant' ? 'assistant-panel-open' : 'quick-settings-open';
        const started = this._performance?.begin(measurement);
        this._showTab(id);
        this._visible = true;
        this.actor.visible = true;
        if (started !== undefined)
            this._performance.end(measurement, started);
        this.actor.ease({translation_x: 0, opacity: 255, duration: this._presentation?.reducedMotion ? 0 : TOKENS.motion.panel});
    }

    close() {
        this._visible = false;
        const offset = this.actor.width + TOKENS.spacing.xl;
        this.actor.ease({
            translation_x: offset,
            opacity: 0,
            duration: this._presentation?.reducedMotion ? 0 : TOKENS.motion.panel,
            onComplete: () => { if (!this._visible) this.actor.visible = false; },
        });
    }

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor || !this.actor)
            return;
        const preferred = this._presentation?.compact
            ? Math.min(TOKENS.layout.panelMinimumWidth + TOKENS.spacing['2xl'], this._settings.get_int('assistant-panel-width'))
            : this._settings.get_int('assistant-panel-width');
        const width = Math.min(preferred, Math.max(TOKENS.layout.panelMinimumWidth, monitor.width - TOKENS.spacing['4xl'] - TOKENS.spacing['2xl']));
        const height = Math.max(TOKENS.layout.panelMinimumHeight, monitor.height - TOKENS.layout.topOffset - TOKENS.spacing['2xl']);
        this.actor.set_position(monitor.x + monitor.width - width - TOKENS.layout.edgeMargin, monitor.y + TOKENS.layout.topOffset);
        this.actor.set_size(width, height);
        for (const tab of this._tabs.values())
            tab.setAvailableHeight?.(height);
        if (!this._visible)
            this.actor.translation_x = width + TOKENS.spacing.xl;
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        applyPresentationClasses(this.actor, presentation);
        for (const tab of this._tabs.values())
            tab.applyPresentation?.(presentation);
        this._place();
        if (presentation.focus && this._visible)
            this.close();
    }

    disable() {
        if (this._monitorSignal)
            Main.layoutManager.disconnect(this._monitorSignal);
        for (const tab of this._tabs.values())
            tab.disable();
        this._tabs.clear();
        this.actor?.destroy();
        this.actor = null;
    }
}
