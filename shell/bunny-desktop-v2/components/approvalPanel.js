import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';
import {launchFixedAction} from '../services/fixedActions.js';


const FIELDS = [
    ['Requesting application', 'application'],
    ['Operation', 'operation'],
    ['Resources affected', 'resources'],
    ['Privilege level', 'privilege'],
    ['Network impact', 'networkImpact'],
    ['Data impact', 'dataImpact'],
    ['Reversibility', 'reversibility'],
    ['Reason', 'reason'],
    ['Expiration', 'expiration'],
];


export class ApprovalPanel {
    constructor(state) {
        this._state = state;
        this.actor = new St.BoxLayout({vertical: true, spacing: TOKENS.spacing.md});
    }

    enable() {
        this._stateSignal = this._state.connect('changed', () => this._rebuild());
        this._rebuild();
    }

    _rebuild() {
        this.actor.destroy_all_children();
        this.actor.add_child(new St.Label({text: 'Approval Center', style_class: 'bunny-v2-title'}));
        const approvals = this._state.snapshot.approvals;
        if (!approvals.length) {
            this.actor.add_child(new St.Label({text: 'No approval requests observed.', style_class: 'bunny-v2-muted'}));
            return;
        }
        for (const approval of approvals) {
            const severity = String(approval.severity ?? 'standard').toLocaleLowerCase();
            const card = new St.BoxLayout({vertical: true, style_class: `bunny-v2-card bunny-v2-approval bunny-v2-severity-${severity}`, spacing: TOKENS.spacing.sm});
            card.add_child(new St.Label({text: `${severity.toLocaleUpperCase()} · approval required`, style_class: 'bunny-v2-heading'}));
            for (const [label, key] of FIELDS) {
                const raw = approval[key] ?? 'Not reported';
                const value = Array.isArray(raw) ? raw.join(', ') : String(raw);
                card.add_child(new St.Label({text: `${label}: ${value}`, style_class: 'bunny-v2-body'}));
            }
            if (severity === 'critical')
                card.add_child(new St.Label({text: 'Explicit confirmation required. Review irreversible consequences before deciding.', style_class: 'bunny-v2-danger'}));
            const actions = new St.BoxLayout({spacing: TOKENS.spacing.sm, x_align: Clutter.ActorAlign.END});
            const inspect = new St.Button({label: 'Inspect details', can_focus: true, style_class: 'bunny-v2-control bunny-v2-focus'});
            inspect.connect('clicked', () => launchFixedAction('approvals'));
            const deny = new St.Button({label: this._state.snapshot.mockMode ? 'Deny · simulated' : 'Deny', can_focus: true, style_class: 'bunny-v2-control bunny-v2-focus'});
            const approve = new St.Button({label: this._state.snapshot.mockMode ? 'Approve · simulated' : 'Approve', can_focus: true, style_class: 'bunny-v2-control bunny-v2-focus'});
            deny.reactive = approve.reactive = this._state.snapshot.decisionAvailable;
            deny.can_focus = approve.can_focus = this._state.snapshot.decisionAvailable;
            actions.add_child(inspect);
            actions.add_child(deny);
            actions.add_child(approve);
            card.add_child(actions);
            this.actor.add_child(card);
        }
    }

    applyPresentation(_presentation) {}

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this.actor.destroy();
    }
}
