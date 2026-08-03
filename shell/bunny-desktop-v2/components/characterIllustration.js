import Atk from 'gi://Atk';
import Clutter from 'gi://Clutter';
import St from 'gi://St';

import {TOKENS} from '../generatedTokens.js';
import {CharacterAssetLoader} from '../services/characterAssetLoader.js';
import {descriptionForPose, poseForState} from '../services/characterState.js';


export class CharacterIllustration {
    constructor(state, extensionPath) {
        this._state = state;
        this._extensionPath = extensionPath;
        this._availableHeight = 0;
        this._presentation = null;
        this._loader = null;
        this.active = false;
        this.actor = new St.Bin({
            style_class: 'bunny-v2-character-region',
            reactive: false,
            can_focus: false,
            accessible_role: Atk.Role.PANEL,
        });
    }

    enable() {
        this._stateSignal = this._state.connect('changed', () => this._rebuild());
    }

    setAvailableHeight(height) {
        if (this._availableHeight === height)
            return;
        this._availableHeight = height;
        this._rebuild();
    }

    applyPresentation(presentation) {
        this._presentation = presentation;
        this._rebuild();
    }

    _rebuild() {
        const presentation = this._presentation;
        const allowed = presentation?.characterVisible === true
            && !presentation.compact
            && !presentation.focus
            && this._availableHeight >= TOKENS.layout.characterMinimumPanelHeight;
        if (!allowed) {
            this.active = false;
            this.actor.set_child(null);
            this.actor.visible = false;
            this._loader?.clear();
            this._loader = null;
            return;
        }

        const pose = poseForState(this._state.snapshot);
        if (!pose) {
            this.active = false;
            this.actor.set_child(null);
            this.actor.visible = false;
            return;
        }
        if (['task-completed', 'celebrating'].includes(pose) && !presentation.successAppearances)
            return this._hide();
        if (['warning', 'error', 'offline'].includes(pose) && !presentation.errorAppearances)
            return this._hide();
        if (['explaining', 'requesting-approval', 'privacy-mode', 'pointing-at-interface'].includes(pose) && !presentation.educationalAppearances)
            return this._hide();
        this._loader ??= new CharacterAssetLoader(this._extensionPath);
        const maximum = Math.floor(this._availableHeight * TOKENS.layout.characterMaximumPanelRatio);
        const size = Math.min(maximum, Math.round(TOKENS.layout.characterIllustrationHeight * presentation.characterScale));
        const image = new St.Icon({
            gicon: this._loader.load(pose),
            icon_size: size,
            reactive: false,
            can_focus: false,
            accessible_role: Atk.Role.REDUNDANT_OBJECT,
        });
        this.actor.accessible_name = descriptionForPose(pose);
        this.actor.x_align = presentation.characterPosition === 'left'
            ? Clutter.ActorAlign.START
            : presentation.characterPosition === 'right'
                ? Clutter.ActorAlign.END
                : Clutter.ActorAlign.CENTER;
        this.actor.height = size;
        this.actor.set_child(image);
        this.actor.visible = true;
        this.active = true;
    }

    _hide() {
        this.active = false;
        this.actor.set_child(null);
        this.actor.visible = false;
        return undefined;
    }

    disable() {
        if (this._stateSignal)
            this._state.disconnect(this._stateSignal);
        this._loader?.clear();
        this._loader = null;
        this.actor.destroy();
    }
}
