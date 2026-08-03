import Gio from 'gi://Gio';


const FIXED_ACTIONS = Object.freeze({
    'control-center': ['bunny-control-center-v2'],
    assistant: ['bunny-assistant-v2'],
    approvals: ['bunny-approval-center-v2'],
    diagnostics: ['bunny-diagnostics-v2'],
    welcome: ['bunny-welcome-v2'],
    files: ['nautilus', '--new-window'],
    wifi: ['gnome-control-center', 'wifi'],
    bluetooth: ['gnome-control-center', 'bluetooth'],
    privacy: ['gnome-control-center', 'privacy'],
    sound: ['gnome-control-center', 'sound'],
    display: ['gnome-control-center', 'display'],
    power: ['gnome-control-center', 'power'],
    accessibility: ['gnome-control-center', 'universal-access'],
    network: ['gnome-control-center', 'network'],
});


export function launchFixedAction(id) {
    const argv = FIXED_ACTIONS[id];
    if (!argv)
        throw new Error(`Unknown fixed Bunny action: ${id}`);
    try {
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
        return true;
    } catch (error) {
        console.warn(`Unable to launch fixed Bunny action ${id}: ${error.message}`);
        return false;
    }
}
