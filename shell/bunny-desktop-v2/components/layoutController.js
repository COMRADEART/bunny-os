import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {applyPresentationClasses} from './presentation.js';


export class LayoutController {
    enable() {
        Main.uiGroup.add_style_class_name('bunny-v2-root');
    }

    applyPresentation(presentation) {
        applyPresentationClasses(Main.uiGroup, presentation);
    }

    disable() {
        for (const name of [
            'bunny-v2-root', 'bunny-v2-light', 'bunny-v2-high-contrast',
            'bunny-v2-compact', 'bunny-v2-focus', 'bunny-v2-reduced-motion',
            'bunny-v2-regular-mode', 'bunny-v2-character-mode',
        ])
            Main.uiGroup.remove_style_class_name(name);
    }
}
