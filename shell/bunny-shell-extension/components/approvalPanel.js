import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {launchFixedAction} from '../services/fixedActions.js';

const FIELDS = [
    ['Requesting component', 'component'], ['Requested operation', 'operation'],
    ['Affected resources', 'resources'], ['Privilege level', 'privilege'],
    ['Network impact', 'networkImpact'], ['Data impact', 'dataImpact'],
    ['Reversibility', 'reversibility'], ['Reason', 'reason'], ['Expiration', 'expiration'],
];

export class ApprovalPanel {
    constructor(state, settings) {
        this._state = state;
        this._settings = settings;
    }

    enable() {
        this.actor = new St.BoxLayout({vertical: true, style_class: 'bunny-v1-panel', spacing: 12, visible: false, reactive: true});
        const heading = new St.BoxLayout({spacing: 8});
        heading.add_child(new St.Label({text: 'Approval Center', style_class: 'title-1', x_expand: true}));
        const details = new St.Button({label: 'Open full details', can_focus: true});
        details.connect('clicked', () => launchFixedAction('approvals'));
        heading.add_child(details);
        const close = new St.Button({icon_name: 'window-close-symbolic', can_focus: true, accessible_name: 'Close Approval Center'});
        close.connect('clicked', () => this.actor.hide());
        heading.add_child(close);
        this.actor.add_child(heading);
        this._content = new St.BoxLayout({vertical: true, spacing: 8});
        this.actor.add_child(this._content);
        Main.layoutManager.addChrome(this.actor, {affectsStruts: false, trackFullscreen: true});
        Main.wm.addKeybinding('open-approvals', this._settings, Meta.KeyBindingFlags.NONE, Shell.ActionMode.NORMAL, () => {
            this._place();
            this.actor.visible ? this.actor.hide() : this.actor.show();
        });
        this._stateSignal = this._state.connect('changed', () => this._refresh());
        this._monitorSignal = Main.layoutManager.connect('monitors-changed', () => this._place());
        this._refresh();
        this._place();
    }

    _refresh() {
        this._content.destroy_all_children();
        const state = this._state.snapshot;
        if (state.mockMode)
            this._content.add_child(new St.Label({text: 'VISUAL MOCK DATA · decisions disabled', style_class: 'bunny-v1-mock'}));
        const approvals = state.approvals;
        if (!approvals.length) {
            this._content.add_child(new St.Label({text: 'No approval requests observed'}));
            return;
        }
        const approval = approvals[0];
        const severity = String(approval.severity ?? approval.risk ?? 'standard');
        this._content.add_child(new St.Label({text: `⚠ ${severity.toUpperCase()} APPROVAL`, style_class: severity === 'critical' ? 'bunny-v1-danger' : 'bunny-v1-warning'}));
        const card = new St.BoxLayout({vertical: true, style_class: 'bunny-v1-card', spacing: 6});
        for (const [label, key] of FIELDS) {
            const value = approval[key] ?? approval[key === 'operation' ? 'action' : key] ?? 'Not reported';
            card.add_child(new St.Label({text: `${label}: ${Array.isArray(value) ? value.join(', ') : value}`, x_align: 1}));
        }
        this._content.add_child(card);
        this._content.add_child(new St.Label({text: 'Approve and Deny are available in the full broker-connected view. No decision is preselected.', style_class: 'bunny-v1-muted'}));
    }

    _place() {
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;
        const width = Math.min(500, Math.floor(monitor.width * 0.42));
        this.actor.set_position(monitor.x + monitor.width - width - 18, monitor.y + 64);
        this.actor.set_size(width, Math.min(680, monitor.height - 100));
    }

    disable() {
        Main.wm.removeKeybinding('open-approvals');
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        if (this._monitorSignal)
            Main.layoutManager.disconnect(this._monitorSignal);
        this.actor?.destroy();
        this.actor = this._content = null;
    }
}
