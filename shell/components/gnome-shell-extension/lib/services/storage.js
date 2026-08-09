// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Which filesystem "Storage" means, decided from the mount table.
//
// ## The failure this file exists to prevent
//
// The first booted desktop reported `14.2 MB / 14.2 MB` on a machine with a
// 14 GB partition. Nothing was broken and no number was invented: `/` on this
// image is an ostree composefs mount, statfs on it describes the composed image
// rather than the disk, and 14.2 MB is a true measurement of it. That is the
// dangerous shape of wrong — the `Unavailable` discipline does not help, because
// a confident measurement of the wrong object is indistinguishable from a
// measurement of the right one.
//
// The fix that followed was `statfs($HOME)`, and it produced the right figure
// on the image it was tried on for the wrong reason: it happened to be a path
// that happened to sit on the real partition. It says nothing about *why* that
// filesystem is the user's storage, it cannot tell a persistent home from a
// tmpfs one on a live session, and it has no answer at all on a system where
// the home directory does not exist yet.
//
// So the question is asked properly here: read the mount table, find the mount
// that actually backs each candidate path, decide whether that mount is a place
// a user's files can still be tomorrow, and take the first one that is. What
// comes back names the mount and says which rule chose it, so a surprising
// figure can be traced to a decision rather than guessed at.
//
// ## Why this module imports nothing
//
// Same reason as layout.js. Parsing a mount table and choosing among its
// entries is pure text and arithmetic, and a claim about which mount gets
// chosen on a composefs root with a persistent home is a claim that should be
// checkable without booting a composefs root. tests/shell/test_desktop_shell.py
// runs these functions under node against fixture mount tables — including the
// exact `/proc/self/mountinfo` shape that produced the 14.2 MB reading. The
// statfs half lives in telemetry.js, where Gio is already imported.

/**
 * Filesystems that do not survive a reboot.
 *
 * A user's files can be written to a tmpfs and they will not be there in the
 * morning, so reporting its capacity as "Storage" tells the user they have room
 * for something they are about to lose. The kernel pseudo-filesystems are in
 * the same list for a duller reason: they report nonsense capacities and none
 * of them is anywhere a file goes.
 */
export const EPHEMERAL_TYPES = new Set([
    'tmpfs', 'devtmpfs', 'ramfs', 'rootfs',
    'proc', 'sysfs', 'devpts', 'cgroup', 'cgroup2', 'securityfs', 'debugfs',
    'tracefs', 'configfs', 'fusectl', 'pstore', 'bpf', 'mqueue', 'hugetlbfs',
    'autofs', 'binfmt_misc', 'efivarfs', 'selinuxfs', 'nsfs', 'rpc_pipefs',
    'sunrpc', 'fuse.gvfsd-fuse', 'fuse.portal', 'fuse.snapfuse',
]);

/**
 * Filesystems that are a *view* of something else rather than a place.
 *
 * `overlay` is the one that matters on this image: an ostree/composefs root is
 * an overlay whose reported size is the size of the composed image. squashfs
 * and erofs are the live-media equivalents, and iso9660 is the installer's own
 * root. All of them have a capacity, all of them are meaningless as an answer
 * to "how much room do I have", and all of them are read-only besides.
 */
export const IMAGE_TYPES = new Set([
    'overlay', 'overlayfs', 'composefs', 'squashfs', 'erofs', 'cramfs',
    'romfs', 'iso9660', 'udf', 'ramdisk',
]);

/**
 * Mount points that are never user storage even when they are real and writable.
 *
 * /boot and /efi are real partitions on a real disk and reporting their 600 MB
 * as the machine's storage would be its own kind of true-and-useless. /run and
 * /tmp are ephemeral by type as well, and are listed here so the last-resort
 * rule cannot reach them by a route the type check does not cover.
 */
const NEVER_USER_STORAGE = [
    '/boot', '/efi', '/run', '/tmp', '/var/tmp', '/proc', '/sys', '/dev',
    '/snap', '/nix/store',
];

/**
 * The rules, in the order they are tried. The first whose path resolves to a
 * persistent mount wins, and its `role` is reported.
 *
 * The order is the brief's: the user's own data first, then any home
 * filesystem, then the writable disk the system is installed on, and only then
 * the fallback that looks at every remaining mount. `$HOME` is passed in rather
 * than read here because this module has no GLib.
 */
export const STORAGE_ROLES = [
    {
        role: 'user-data',
        description: 'the filesystem the signed-in user\'s own files are on',
        paths: home => (home ? [home] : []),
    },
    {
        role: 'home',
        description: 'the writable home filesystem',
        // /var/home before /home: on an ostree system /home is a symlink to it,
        // and resolving the symlink is work this module cannot do.
        paths: () => ['/var/home', '/home'],
    },
    {
        role: 'disk-root',
        description: 'the primary writable disk filesystem',
        // /sysroot is the physical root partition on an ostree system and is
        // the honest answer there; / is the honest answer on an ordinary one.
        // /var comes between them because on ostree it is a bind mount of the
        // stateroot and therefore already the physical partition, while on an
        // ordinary system it is simply / by another name.
        paths: () => ['/sysroot', '/var', '/'],
    },
];

/** Undo mountinfo's octal escaping of space, tab, newline and backslash. */
function unescapeField(field) {
    return field.replace(/\\(\d{3})/g, (_match, digits) =>
        String.fromCharCode(Number.parseInt(digits, 8)));
}

/**
 * Parse /proc/self/mountinfo.
 *
 * mountinfo rather than /proc/mounts because it carries the mount point's
 * position in the tree and the propagation fields, and because /proc/mounts
 * hides the difference between a bind mount and the filesystem it came from —
 * which is the difference between /var and /sysroot on this image.
 *
 * The format is fixed up to a variable-length block of optional fields
 * terminated by a lone "-":
 *
 *   36 35 98:0 /root /mount/point rw,noatime shared:1 - ext4 /dev/sda1 rw
 *   id parent dev  root  point     options   optional  -  type  source super
 *
 * A line that does not have the separator, or is short, is skipped rather than
 * guessed at. Fields never contain whitespace: the kernel escapes it.
 */
export function parseMountinfo(text) {
    const mounts = [];
    if (typeof text !== 'string')
        return mounts;
    for (const line of text.split('\n')) {
        const fields = line.trim().split(/\s+/);
        if (fields.length < 10)
            continue;
        // From index 6, because a mount point may legitimately be "-" and it
        // sits at index 4. Searching from the first position the separator can
        // actually occupy cannot mistake one for the other.
        const separator = fields.indexOf('-', 6);
        if (separator === -1 || separator + 2 >= fields.length)
            continue;
        mounts.push({
            id: Number.parseInt(fields[0], 10),
            parentId: Number.parseInt(fields[1], 10),
            device: fields[2],
            rootWithinDevice: unescapeField(fields[3]),
            mountPoint: unescapeField(fields[4]),
            options: fields[5].split(','),
            filesystemType: fields[separator + 1],
            source: unescapeField(fields[separator + 2]),
            superOptions: (fields[separator + 3] ?? '').split(','),
        });
    }
    return mounts;
}

/** True when `path` is at or below `mountPoint`. */
export function pathIsWithin(path, mountPoint) {
    if (typeof path !== 'string' || typeof mountPoint !== 'string')
        return false;
    if (mountPoint === '/')
        return path.startsWith('/');
    return path === mountPoint || path.startsWith(`${mountPoint}/`);
}

/**
 * The mount that actually provides `path`.
 *
 * The longest mount point that is a prefix of the path, and among equal ones
 * the highest mount id — which is how the kernel resolves a mount stacked over
 * another at the same point. Getting this wrong is how `/var/home/bunny` gets
 * attributed to `/` (the composefs image) instead of `/var` (the disk).
 */
export function backingMount(mounts, path) {
    let best = null;
    for (const mount of mounts) {
        if (!pathIsWithin(path, mount.mountPoint))
            continue;
        if (best === null ||
            mount.mountPoint.length > best.mountPoint.length ||
            (mount.mountPoint.length === best.mountPoint.length && mount.id > best.id))
            best = mount;
    }
    return best;
}

/**
 * Is a file written here still going to be here after a reboot?
 *
 * Returns `{persistent, reason}` in both cases. The reason is carried rather
 * than discarded because it is what turns "Storage: Unavailable" from a shrug
 * into something a journal line can explain.
 */
export function classifyMount(mount) {
    if (!mount)
        return {persistent: false, reason: 'no mount provides this path'};
    const type = mount.filesystemType;
    if (EPHEMERAL_TYPES.has(type))
        return {persistent: false, reason: `${type} does not survive a reboot`};
    if (IMAGE_TYPES.has(type))
        return {persistent: false, reason: `${type} is a composed image, not a disk`};
    const readOnly = mount.superOptions.includes('ro') || mount.options.includes('ro');
    if (readOnly)
        return {persistent: false, reason: `${mount.mountPoint} is mounted read-only`};
    if (NEVER_USER_STORAGE.some(prefix => pathIsWithin(mount.mountPoint, prefix)))
        return {persistent: false, reason: `${mount.mountPoint} is not user storage`};
    return {persistent: true, reason: `${type} on ${mount.source}`};
}

/**
 * Choose the mount whose capacity "Storage" should report.
 *
 * @param {Array} mounts parseMountinfo output
 * @param {{homeDirectory?: string|null}} options
 * @returns {{mount: object|null, role: string|null, path: string|null,
 *            description: string, rejected: Array<{path: string, reason: string}>}}
 *
 * `rejected` is returned rather than logged from in here: this module has no
 * logger, and the caller wants to say it once rather than every two seconds.
 */
export function selectStorageMount(mounts, {homeDirectory = null} = {}) {
    const rejected = [];
    for (const rule of STORAGE_ROLES) {
        for (const path of rule.paths(homeDirectory)) {
            const mount = backingMount(mounts, path);
            const verdict = classifyMount(mount);
            if (verdict.persistent) {
                return {
                    mount,
                    role: rule.role,
                    path,
                    description: rule.description,
                    rejected,
                };
            }
            rejected.push({path, reason: verdict.reason});
        }
    }

    // Last resort: any other persistent mount, largest device first is not
    // knowable without statfs, so the choice is the shallowest mount point and
    // then alphabetical — deterministic, and explained by `role` when it fires.
    // This is what answers a machine whose data lives on an explicitly mounted
    // partition that none of the rules above names.
    const remaining = mounts
        .filter(mount => classifyMount(mount).persistent)
        .sort((a, b) => {
            const depth = mount => mount.mountPoint.split('/').length;
            return depth(a) - depth(b) || a.mountPoint.localeCompare(b.mountPoint);
        });
    if (remaining.length > 0) {
        return {
            mount: remaining[0],
            role: 'persistent-mount',
            path: remaining[0].mountPoint,
            description: 'an explicitly mounted persistent filesystem',
            rejected,
        };
    }

    return {
        mount: null,
        role: null,
        path: null,
        description: 'no persistent filesystem is mounted on this system',
        rejected,
    };
}
