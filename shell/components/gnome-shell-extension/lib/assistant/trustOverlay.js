// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Trust overlay: the permission question as chrome, not a dashboard card.
//
// Phase 1's live layout is `skeleton`, which drops every card including the
// assistant panel that used to host TrustComponent. A waiting_for_approval
// that only called `_assistantPanel.showApproval` would then be a hidden
// card. This overlay is chrome (above windows), focusable, and the same
// TrustComponent the card still uses when the `full` profile places it.

import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {box, glass} from '../widgets.js';
import {logError_} from '../util.js';
import {TrustComponent} from '../components/trust.js';
import {buildApproval} from '../trustPrompt.js';
import {currentTheme} from '../design/current.js';
import {RADIUS} from '../design/tokens.js';

export class TrustOverlay {
    constructor({blur = false} = {}) {
        this.actor = new St.Widget({
            style_class: 'bunny-trust-scrim',
            reactive: true,
            visible: false,
            layout_manager: new Clutter.FixedLayout(),
        });
        this._dialog = glass('bunny-dialog bunny-trust-overlay', {
            blur, radius: RADIUS.modal,
        });
        this._column = box({vertical: true});
        this._dialog.add_child(this._column);
        this.actor.add_child(this._dialog);

        this._approvalDecision = null;
        this._trust = new TrustComponent({
            onDecision: (verdict, requestId) => {
                this._approvalDecision?.(verdict, requestId);
            },
        });
        this._column.add_child(this._trust.actor);
        this.actor.accessible_name = 'Bunny needs permission';
    }

    showApproval(approval, onDecision) {
        const requestId = String(approval?.requestId ?? '');
        if (!requestId)
            return false;
        this._approvalDecision = typeof onDecision === 'function' ? onDecision : null;
        let model;
        try {
            model = buildApproval(approval, {
                highContrast: currentTheme().highContrast,
                largeText: currentTheme().textScale > 1,
            });
        } catch (error) {
            logError_('the permission question could not be laid out; showing its reason alone', error);
            model = buildApproval({
                requestId,
                reason: String(approval?.reason ?? 'Allow Bunny to perform this action?'),
                safeDefault: String(approval?.safeDefault ?? 'denied'),
            });
        }
        const shown = this._trust.show(model);
        this.actor.visible = Boolean(shown);
        if (shown)
            this._trust.focusSafeAnswer();
        return Boolean(shown);
    }

    clearApproval(requestId = '') {
        this._trust.hide(requestId);
        if (!this._trust.requestId) {
            this._approvalDecision = null;
            this.actor.visible = false;
        }
    }

    approvalDecisionFailed(requestId) {
        this._trust.decisionFailed(requestId);
        this._trust.focusSafeAnswer();
    }

    focusSafeAnswer() {
        if (this.actor.visible)
            this._trust.focusSafeAnswer();
    }

    get visible() {
        return this.actor.visible;
    }

    place(monitor) {
        if (!monitor)
            return;
        this.actor.set_position(monitor.x, monitor.y);
        this.actor.set_size(monitor.width, monitor.height);
        const width = Math.min(440, Math.max(280, Math.round(monitor.width * 0.42)));
        this._dialog.set_width(width);
        const height = Math.max(this._dialog.get_height() || 0, 240);
        this._dialog.set_position(
            Math.round((monitor.width - width) / 2),
            Math.round(Math.max(24, (monitor.height - height) / 2)));
    }

    destroy() {
        this.actor.destroy();
    }
}
