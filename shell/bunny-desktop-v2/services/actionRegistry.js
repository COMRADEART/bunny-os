import {launchFixedAction} from './fixedActions.js';


export function commandActions(settings, systemPanel) {
    const setVisualMode = mode => {
        settings.set_string('visual-mode', mode);
        settings.set_boolean('character-enabled', mode === 'character');
    };
    const setLayout = mode => {
        settings.set_string('layout-mode', mode);
        settings.set_boolean('focus-mode-enabled', mode === 'focus');
        settings.set_boolean('compact-layout-enabled', mode === 'compact');
    };
    return [
        {id: 'open-files', label: 'Open Files', type: 'Open', run: () => launchFixedAction('files')},
        {id: 'system-settings', label: 'System Settings', type: 'Open', run: () => launchFixedAction('control-center')},
        {id: 'terminal', label: 'Terminal', type: 'Open', applicationId: 'org.gnome.Terminal.desktop'},
        {id: 'assistant', label: 'Bunny Assistant', type: 'Open', run: () => systemPanel.open('assistant')},
        {id: 'regular-mode', label: 'Switch to Regular Mode', type: 'Change setting', run: () => setVisualMode('regular')},
        {id: 'character-mode', label: 'Switch to Character Mode', type: 'Change setting', run: () => setVisualMode('character')},
        {id: 'focus-mode', label: 'Enable FocusMode', type: 'Change setting', run: () => setLayout('focus')},
        {id: 'compact-layout', label: 'Enable Compact layout', type: 'Change setting', run: () => setLayout('compact')},
        {id: 'normal-layout', label: 'Use Normal layout', type: 'Change setting', run: () => setLayout('normal')},
        {id: 'approvals', label: 'Open Approval Center', type: 'Requires approval', run: () => systemPanel.open('approvals')},
        {id: 'diagnostics', label: 'Open Diagnostics', type: 'Open', run: () => launchFixedAction('diagnostics')},
        {id: 'power', label: 'Power actions', type: 'Power action', privileged: true, run: () => systemPanel.open('approvals')},
    ];
}
