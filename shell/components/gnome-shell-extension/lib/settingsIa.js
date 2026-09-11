// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Calm Settings information architecture. Progressive disclosure: You is
// always visible; This computer and System start collapsed. Not a macOS
// clone and not a chatbot wall.

import {SCREEN_QUESTIONS} from './design/tokens.js';
import {buildSidebar} from './design/primitives.js';
import {CONTROL_CENTER_MODULES} from './controlCenter.js';

export const SETTINGS_IA_GROUPS = Object.freeze(['you', 'device', 'system']);

export const GROUP_TITLES = Object.freeze({
    you: 'You',
    device: 'This computer',
    system: 'System',
});

export const GROUP_BLURBS = Object.freeze({
    you: 'Bunny, AI, privacy, and how this computer talks to you.',
    device: 'Stable device panels. Bunny opens GNOME Settings for these.',
    system: 'Updates, recovery, and what this image is.',
});

export const SIDEBAR_ITEMS = Object.freeze([
    {id: 'bunny', title: 'Bunny', group: 'you', blurb: 'Character, voice, personality, motion, place on screen, and how much Bunny offers.', disclosure: 'primary', gnomePanel: null, aliases: [], bunnyOwned: true},
    {id: 'ai-models', title: 'AI & Models', group: 'you', blurb: 'Automatic, Local only, or Online enhanced. Advanced facts stay collapsed.', disclosure: 'primary', gnomePanel: null, aliases: ['Voice & AI', 'Local Models', 'AI'], bunnyOwned: true},
    {id: 'privacy', title: 'Privacy', group: 'you', blurb: 'Cloud memory and a one-time online answer are two different consents.', disclosure: 'primary', gnomePanel: null, aliases: ['Memory'], bunnyOwned: true},
    {id: 'accessibility', title: 'Accessibility', group: 'you', blurb: 'Motion, contrast, text size, captions. The companion is never required.', disclosure: 'primary', gnomePanel: 'universal-access', aliases: [], bunnyOwned: true},
    {id: 'network', title: 'Network', group: 'device', blurb: 'Wi-Fi and wired. Application network is Off or On (full internet).', disclosure: 'nested', gnomePanel: 'network', aliases: [], bunnyOwned: false},
    {id: 'bluetooth', title: 'Bluetooth', group: 'device', blurb: 'Device Bluetooth. App Bluetooth is not mediated in this build.', disclosure: 'nested', gnomePanel: 'bluetooth', aliases: [], bunnyOwned: false},
    {id: 'displays', title: 'Displays', group: 'device', blurb: 'Arrangement, scale, and night light.', disclosure: 'nested', gnomePanel: 'display', aliases: [], bunnyOwned: false},
    {id: 'sound', title: 'Sound', group: 'device', blurb: 'Input, output, and volume.', disclosure: 'nested', gnomePanel: 'sound', aliases: [], bunnyOwned: false},
    {id: 'power', title: 'Power', group: 'device', blurb: 'Sleep and battery.', disclosure: 'nested', gnomePanel: 'power', aliases: [], bunnyOwned: false},
    {id: 'keyboard', title: 'Keyboard', group: 'device', blurb: 'Layout and shortcuts.', disclosure: 'nested', gnomePanel: 'keyboard', aliases: [], bunnyOwned: false},
    {id: 'mouse', title: 'Mouse and Touchpad', group: 'device', blurb: 'Pointer speed and tap-to-click.', disclosure: 'nested', gnomePanel: 'mouse', aliases: ['Mouse', 'Touchpad'], bunnyOwned: false},
    {id: 'appearance', title: 'Appearance', group: 'device', blurb: 'Wallpaper and GNOME appearance.', disclosure: 'nested', gnomePanel: 'background', aliases: [], bunnyOwned: false},
    {id: 'applications', title: 'Applications', group: 'device', blurb: 'Installed applications.', disclosure: 'nested', gnomePanel: 'applications', aliases: ['Apps'], bunnyOwned: false},
    {id: 'notifications', title: 'Notifications', group: 'device', blurb: 'Quiet Bunny notices. GNOME still owns the session daemon.', disclosure: 'nested', gnomePanel: 'notifications', aliases: [], bunnyOwned: true},
    {id: 'users', title: 'Users', group: 'device', blurb: 'People who can sign in.', disclosure: 'nested', gnomePanel: 'user-accounts', aliases: [], bunnyOwned: false},
    {id: 'datetime', title: 'Date and Time', group: 'device', blurb: 'Clock and timezone.', disclosure: 'nested', gnomePanel: 'datetime', aliases: ['Timezone'], bunnyOwned: false},
    {id: 'storage', title: 'Storage', group: 'device', blurb: 'Disks and free space.', disclosure: 'nested', gnomePanel: 'info-overview', aliases: [], bunnyOwned: false},
    {id: 'updates', title: 'Updates', group: 'system', blurb: 'OS image updates stay separate from Bunny application updates.', disclosure: 'nested', gnomePanel: null, aliases: [], bunnyOwned: true},
    {id: 'recovery', title: 'Recovery', group: 'system', blurb: 'Previous deployments, safe graphics, and diagnostics without Bunny Core.', disclosure: 'nested', gnomePanel: null, aliases: [], bunnyOwned: true},
    {id: 'plugins', title: 'Plugins', group: 'system', blurb: 'Signed extensions. Network denied until asked.', disclosure: 'nested', gnomePanel: null, aliases: [], bunnyOwned: true},
    {id: 'permissions', title: 'Permissions', group: 'system', blurb: 'Allow once or Don\'t allow. There is no Always allow everything.', disclosure: 'nested', gnomePanel: null, aliases: [], bunnyOwned: true},
    {id: 'system-information', title: 'System Information', group: 'system', blurb: 'What this computer is. Not a claim about a booted image.', disclosure: 'nested', gnomePanel: 'info-overview', aliases: ['About'], bunnyOwned: false},
]);

function fold(value) {
    return String(value || '').trim().toLowerCase().replace(/[_-]/g, ' ');
}

export function resolveSection(name) {
    const token = fold(name || 'bunny');
    if (!token)
        return SIDEBAR_ITEMS[0];
    for (const item of SIDEBAR_ITEMS) {
        const candidates = [item.id, item.title, ...(item.aliases || [])];
        if (candidates.some(candidate => fold(candidate) === token))
            return item;
    }
    return SIDEBAR_ITEMS[0];
}

export function sidebarGroups({deviceCollapsed = true} = {}) {
    return SETTINGS_IA_GROUPS.map(groupId => {
        const items = SIDEBAR_ITEMS.filter(item => item.group === groupId);
        return {
            id: groupId,
            title: GROUP_TITLES[groupId],
            blurb: GROUP_BLURBS[groupId],
            collapsed: groupId === 'you' ? false : Boolean(deviceCollapsed),
            items: items.map(item => ({
                id: item.id,
                title: item.title,
                blurb: item.blurb,
                disclosure: item.disclosure,
                gnomePanel: item.gnomePanel,
                bunnyOwned: item.bunnyOwned,
                accessibleName: item.title,
                canFocus: true,
            })),
        };
    });
}

export function buildSettingsIA({
    selected = 'bunny', companionHidden = false, deviceCollapsed = true,
} = {}) {
    const current = resolveSection(selected);
    const groups = sidebarGroups({deviceCollapsed});
    const sidebar = buildSidebar({
        collapsed: false,
        items: groups.flatMap(group => (
            group.collapsed
                ? [{id: group.id, label: group.title, accessibleName: group.title}]
                : group.items.map(item => ({id: item.id, label: item.title, accessibleName: item.title}))
        )),
    });
    return {
        kind: 'SettingsIA',
        title: 'Settings',
        summary: 'A calm sidebar. Bunny is optional. Device panels stay in GNOME.',
        groups,
        sidebar,
        selected: current.id,
        selectedTitle: current.title,
        companionRequired: false,
        companionHidden: Boolean(companionHidden),
        controlCenterModules: [...CONTROL_CENTER_MODULES],
        styleClass: 'bunny-sidebar',
        canFocus: true,
        questions: SCREEN_QUESTIONS,
        accessibleName: 'Bunny Settings',
        chatbot: false,
    };
}
