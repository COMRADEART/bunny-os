// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Snap and workspaces. Companion stays bottom-right and does not cover work.
// Geometry is lib/layout.js. Live Mutter tiling is not claimed.

import {SCREEN_QUESTIONS} from './design/tokens.js';
import {
    NAMED_VIEWPORTS, SNAP_TARGETS, snapLayout,
} from './layout.js';

export {NAMED_VIEWPORTS, SNAP_TARGETS, snapLayout};

export const COMPANION_CORNER = 'bottom-right';

export function buildMultitasking({
    workspaces = [], activeId = '', reducedMotion = false,
    screen = NAMED_VIEWPORTS.fhd, scale = 1, profile = 'skeleton',
} = {}) {
    const layout = snapLayout(screen, {scale, profile});
    const items = (Array.isArray(workspaces) ? workspaces : []).map(item => {
        const rec = item && typeof item === 'object' ? item : {name: item};
        return {
            id: String(rec.id || ''),
            name: String(rec.name || 'Workspace'),
            archived: Boolean(rec.archivedAt),
            active: String(rec.id || '') === String(activeId || ''),
        };
    });
    return {
        kind: 'Multitasking',
        title: 'Workspaces',
        summary: 'Snap windows around Bunny. The figure stays bottom-right and does not cover work.',
        companionCorner: COMPANION_CORNER,
        companionCoversWork: layout.companionCoversWork,
        snapTargets: SNAP_TARGETS.slice(),
        snaps: layout.snaps,
        work: layout.work,
        reserved: layout.reserved,
        workspaces: items,
        questions: SCREEN_QUESTIONS,
        doing: 'Arranging windows',
        bunny: 'In the corner',
        next: 'Snap left or right. Maximize leaves the companion visible.',
        companionRequired: false,
        chatbot: false,
        reducedMotion: Boolean(reducedMotion),
        motionMs: reducedMotion ? 0 : 220,
        liveMutterTiling: false,
        accessibleName: 'Workspaces and snap',
        canFocus: true,
        styleClass: 'bunny-multitasking bunny-sheet',
        viewport: `${screen.width}×${screen.height}`,
        scale,
        profile: layout.profile,
    };
}

export function viewportForName(name) {
    const key = String(name || '').toLowerCase();
    if (key === '1366' || key === 'hd1366' || key === 'laptop')
        return NAMED_VIEWPORTS.hd1366;
    if (key === '4k' || key === 'uhd' || key === '2160')
        return NAMED_VIEWPORTS.uhd;
    return NAMED_VIEWPORTS.fhd;
}
