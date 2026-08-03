import Gio from 'gi://Gio';

const ACTIONS = new Map([
    ['control-center', ['/usr/bin/bunny-command-center']],
    ['approvals', ['/usr/bin/bunny-approval-center']],
    ['assistant', ['/usr/bin/bunny-assistant']],
    ['diagnostics', ['/usr/bin/bunny-diagnostics']],
    ['wifi', ['/usr/bin/gnome-control-center', 'wifi']],
    ['bluetooth', ['/usr/bin/gnome-control-center', 'bluetooth']],
    ['sound', ['/usr/bin/gnome-control-center', 'sound']],
    ['display', ['/usr/bin/gnome-control-center', 'display']],
    ['power', ['/usr/bin/gnome-control-center', 'power']],
    ['accessibility', ['/usr/bin/gnome-control-center', 'universal-access']],
    ['privacy', ['/usr/bin/gnome-control-center', 'privacy']],
    ['vpn', ['/usr/bin/gnome-control-center', 'network']],
]);

export function launchFixedAction(name) {
    const argv = ACTIONS.get(name);
    if (!argv)
        throw new Error(`Unrecognized fixed action: ${name}`);
    try {
        Gio.Subprocess.new(argv, Gio.SubprocessFlags.NONE);
    } catch (error) {
        console.error(`Bunny Desktop could not open ${name}: ${error.message}`);
    }
}
