// SPDX-FileCopyrightText: 2026 ComradeArt
// SPDX-License-Identifier: GPL-3.0-or-later
//
// DesktopShell: the thing that owns everything else.
//
// ## Where the actors go
//
// Two layers, and the difference is not cosmetic.
//
// **Chrome** — top bar, sidebar, dock, toasts, the search results, the power
// menu — goes through Main.layoutManager.addChrome. That puts it above windows,
// in the shell's input region, and — with trackFullscreen — makes it disappear
// under a fullscreen video without any code here knowing that fullscreen
// exists.
//
// **Desktop content** — the character, the cards, the bubbles, the scrim —
// goes into Main.layoutManager._backgroundGroup, which sits inside
// global.window_group beneath every window actor. So an open window covers the
// dashboard the way it covers a wallpaper, which is the behaviour a desktop
// has; if the cards were chrome they would float over Firefox.
//
// _backgroundGroup is private API. The fallback below inserts into uiGroup
// beneath window_group instead, which puts the content in the same place by a
// different route. Both are checked at enable() and the choice is logged, so a
// future Shell that renames the field degrades to a working desktop with a
// journal line rather than to an exception in enable().
//
// ## What this file does not do
//
// It does not read /proc, call DBus, or launch anything. Every one of those is
// behind a service in lib/services, and the rule that keeps them there is that
// this file imports no gi module except the three it needs to place actors.
// When a card needs a new number, the number arrives through a service.

import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {solve, LEFT_COLUMN, RIGHT_COLUMN} from './layout.js';
import {box, glass} from './widgets.js';
import {Icons, resolveIconName} from './icons.js';
import {enter, ease} from './animation.js';
import {interval, isLikelySoftwareRendering, log_, logError_, makeActivatable, timeout} from './util.js';

import {TopBar} from './topBar.js';
import {Sidebar, PowerMenu} from './sidebar.js';
import {BottomDock} from './bottomDock.js';
import {WallpaperLayer} from './wallpaperLayer.js';
import {NotificationLayer, NotificationService} from './notificationLayer.js';

import {CharacterViewport} from './character/viewport.js';
import {CharacterStateManager} from './character/state.js';
import {AssistantBubble} from './assistant/bubble.js';
import {SuggestedActions} from './assistant/suggestions.js';
import {AssistantPanel} from './assistant/panel.js';

import {SystemOverview} from './cards/systemOverview.js';
import {QuickAccess} from './cards/quickAccess.js';
import {MediaWidget} from './cards/mediaWidget.js';
import {AgendaWidget} from './cards/agendaWidget.js';
import {SystemMonitor} from './cards/systemMonitor.js';

import {SystemTelemetry} from './services/telemetry.js';
import {PowerManager} from './services/power.js';
import {NetworkManagerService} from './services/network.js';
import {AudioManager} from './services/audio.js';
import {BrightnessManager} from './services/brightness.js';
import {ApplicationLauncher} from './services/launcher.js';
import {MediaService} from './services/mpris.js';
import {AgendaService} from './services/agenda.js';
import {AssistantService, PHASE_TO_STATE} from './services/assistant.js';
import {VoiceService} from './services/voice.js';
import {UniversalSearch} from './services/search.js';

/** How long a reply stays on the character's face before it returns to idle. */
const TALKING_DWELL_MS = 6000;

/**
 * The states a request leaves behind, which a timer may clear.
 *
 * Deliberately not "everything except idle": WORKING and LISTENING belong to a
 * request that is still going, and a dwell timer from the *previous* request
 * firing into one of those would stop the character mid-task.
 */
const TRANSIENT_STATES = new Set(['talking', 'success', 'error', 'warning']);

export class DesktopShell {
    constructor({settings}) {
        this._settings = settings;
        this._signals = [];
        this._destroyed = false;
        //: The request the desktop is currently showing. See `_owns`.
        this._requestId = 0;
        this._voiceInteractionId = 0;
        this._voicePhase = 'idle';
        this._lastRequest = '';

        /** Names of components that failed to build. See `_optional`. */
        this.degraded = [];

        this._blur = this._decideBlur();
        this.notifications = new NotificationService();

        // Two different guarantees, and the difference is the whole of this
        // desktop's failure policy.
        //
        // *Inside* these steps, every component is built through `_optional`,
        // so one widget meeting an API that moved costs that widget and
        // nothing else. That is where the failures actually seen have been:
        // an accessibility constant, an addChrome parameter, a private field.
        //
        // *Around* them, the try still exists, because a throw that escapes
        // `_optional` is one of the structural steps failing — placing the
        // layers, connecting the session — and a desktop that got half way
        // through those is not a degraded desktop, it is debris in the
        // compositor's scene graph. destroy() is written to tolerate a
        // half-built object, so the cleanest guarantee is to tear down what
        // exists and let extension.js see the original error and fall back.
        try {
            this._buildServices();
            this._buildComponents();
            this._placeActors();
            this._connectSession();
            this._installKeybindings();
            this._relayout();
        } catch (error) {
            try {
                this.destroy();
            } catch (teardownError) {
                logError_('teardown after a failed construction also failed', teardownError);
            }
            throw error;
        }

        this._greet();
        this._reportDegradation();

        // Cheap, and it catches the two things no signal reports: an
        // application that stopped running, and midnight.
        this._housekeeping = interval(30, () => this._onHousekeeping());
    }

    // ---------------------------------------------------------------- setup

    /**
     * Blur costs a full-surface sample per blurred panel per frame. On a GPU
     * that is free; on llvmpipe in a VM — a configuration this image must stay
     * usable in — it is not. The setting wins when the user has expressed a
     * preference; otherwise the renderer decides and the decision is logged.
     *
     * The renderer is asked, not inferred. The first version of this counted
     * DRM render nodes and got the answer wrong on the very first VM it ran
     * on: QEMU's virtio-gpu creates /dev/dri/renderD128 and reports
     * `features: -virgl`, so there is a render node and Mesa is still on
     * llvmpipe. Mutter already knows — it is the thing doing the rendering —
     * and `is_rendering_hardware_accelerated` is the answer it gives GNOME
     * Shell for the same question. The node count survives only as the
     * fallback for a backend that does not expose it.
     */
    _decideBlur() {
        const preference = this._settings.get_string('desktop-blur');
        if (preference === 'on')
            return true;
        if (preference === 'off')
            return false;

        let accelerated = null;
        try {
            accelerated = global.backend?.is_rendering_hardware_accelerated?.() ?? null;
        } catch (error) {
            logError_('the backend would not report its rendering path', error);
        }
        if (accelerated === null) {
            const software = isLikelySoftwareRendering();
            log_(`the backend does not report acceleration; falling back to the render-node ` +
                `count, which says ${software ? 'software' : 'hardware'}`);
            accelerated = !software;
        } else {
            log_(`mutter reports rendering is ${accelerated ? 'hardware accelerated' : 'software'}`);
        }
        log_(`panel blur ${accelerated ? 'enabled' : 'disabled'}`);
        return accelerated;
    }

    /**
     * Construct something the desktop can do without, and survive it failing.
     *
     * The rule this enforces is the one the first three graphical boots taught,
     * each at the cost of a whole desktop: an accessibility constant that does
     * not exist, a parameter `addChrome` no longer accepts, a Shell field that
     * moved. None of those was a failure of the desktop. Each was one widget
     * asking one library for one thing, and each took every other widget down
     * with it, because construction was a single unbroken sequence and an
     * exception anywhere in it aborted the whole thing.
     *
     * So the sequence is broken up. What comes back is the component or null,
     * the failure is named in the journal and in `degraded`, and the caller
     * carries on. Nothing here swallows an error quietly — a desktop missing
     * its dock with nothing in the log would be worse than one that did not
     * start, because at least the second is reported.
     *
     * @param {string} what the user-facing name, for the journal and the toast
     * @param {() => any} factory
     */
    _optional(what, factory) {
        try {
            return factory();
        } catch (error) {
            logError_(`${what} could not be created; the rest of the desktop continues`, error);
            this.degraded.push(what);
            return null;
        }
    }

    _buildServices() {
        // The four the desktop cannot be assembled without. Each reads a file
        // or takes a reference; none of them talks to a bus or builds an actor,
        // which is why they are the four that are not guarded — there is
        // nothing here that can fail that would not also mean the session is
        // gone.
        this.telemetry = new SystemTelemetry();
        this.launcher = new ApplicationLauncher();
        this.characterState = new CharacterStateManager();
        this.search = new UniversalSearch(this.launcher);

        // Everything below reaches a system service — logind, NetworkManager,
        // PulseAudio through Gvc, the session bus, the companion's socket. Any
        // of them can be absent on a machine this desktop is expected to run
        // on, and none of them is worth a desktop.
        this.power = this._optional('power management', () => new PowerManager());
        this.network = this._optional('network status', () => new NetworkManagerService());
        this.audio = this._optional('audio control', () => new AudioManager());
        this.brightness = this._optional('brightness control', () => new BrightnessManager());
        this.media = this._optional('media control', () => new MediaService());
        this.agenda = this._optional('calendar', () => new AgendaService());
        this.assistant = this._optional('assistant bridge', () => new AssistantService());
        this.voice = this._optional('voice bridge', () => new VoiceService());

        this.assistant?.checkHealth((available, reason) => {
            this._suggestions?.rebuild();
            if (!available) {
                this.characterState.setState('sleeping', {reason});
                this._bubble?.say(
                    'I am not connected to my runtime yet. Everything else on this desktop still works.',
                    {tone: 'warning'});
            }
        });
        this.voice?.checkHealth((available, reason) => {
            this._assistantPanel?.setVoiceAvailable(available, reason);
            if (!available)
                log_(`push-to-talk unavailable: ${reason}`);
        });
    }

    _buildComponents() {
        const blur = this._blur;

        this.wallpaper = this._optional('wallpaper', () => new WallpaperLayer());
        this.notificationLayer = this._optional('notifications', () => new NotificationLayer({blur}));
        if (this.notificationLayer)
            this.notifications.attach(this.notificationLayer);

        this.topBar = this._optional('top bar', () => new TopBar({
            blur,
            launcher: this.launcher,
            audio: this.audio,
            brightness: this.brightness,
            network: this.network,
            power: this.power,
            onSearch: text => this._onSearch(text),
            onSearchActivate: text => this._onSearchActivate(text),
            onSearchDismiss: () => this._closeSearch(),
            onHome: () => this._select('home'),
            onAgenda: () => this._select('home'),
            onAvatar: () => this.launcher.spawn(['gnome-control-center', 'user-accounts']),
        }));

        this.sidebar = this._optional('sidebar', () => new Sidebar({
            blur,
            onSelect: id => this._select(id),
            onLaunch: id => this._launchFromSidebar(id),
            onPower: () => this._togglePowerMenu(),
        }));

        this.dock = this._optional('dock', () => new BottomDock({
            blur,
            launcher: this.launcher,
            onOverview: () => Main.overview.toggle(),
        }));

        this._characterViewport = this._optional('character', () => new CharacterViewport({
            stateManager: this.characterState,
            onActivate: () => this._activateAssistant(),
        }));

        this._bubble = this._optional('speech bubble', () => new AssistantBubble({blur}));
        this._suggestions = this._optional('suggested actions', () => new SuggestedActions({
            blur,
            launcher: this.launcher,
            assistant: this.assistant,
            onPrompt: text => this._ask(text),
            onAction: id => this._runSuggestedAction(id),
        }));

        this._assistantPanel = this._optional('assistant panel', () => new AssistantPanel({
            blur,
            assistant: this.assistant,
            onSubmit: text => this._ask(text),
            onVoice: () => this._startVoice(),
            onFileResult: (index, command) => this._openFileResult(index, command),
            onOpenFull: () => this.launcher.spawn(['bunny-command']),
            onDismiss: () => this._dismissAssistant(),
        }));

        // Cards, each on its own. A card is a widget over a service, so it is
        // the piece most likely to meet a machine its service has no answer
        // for, and the piece whose absence costs the least. A card whose
        // service failed to construct is not built at all rather than built
        // over a null: `media` with no MediaService is not a degraded media
        // card, it is a card with nothing to say.
        const built = {
            systemOverview: this._optional('system overview', () =>
                new SystemOverview({telemetry: this.telemetry, launcher: this.launcher, blur})),
            quickAccess: this._optional('quick access', () =>
                new QuickAccess({launcher: this.launcher, blur, onSeeAll: () => Main.overview.toggle()})),
            media: this.media === null ? null : this._optional('media card', () =>
                new MediaWidget({media: this.media, blur})),
            agenda: this.agenda === null ? null : this._optional('agenda card', () =>
                new AgendaWidget({agenda: this.agenda, blur})),
            systemMonitor: this.network === null || this.power === null
                ? null
                : this._optional('system monitor', () => new SystemMonitor({
                    network: this.network, power: this.power, launcher: this.launcher, blur,
                })),
            assistant: this._assistantPanel,
        };
        this.cards = {};
        for (const [key, card] of Object.entries(built)) {
            if (card !== null)
                this.cards[key] = card;
        }

        this._searchResults = this._buildSearchResults();
        this._powerMenu = null;

        if (this.degraded.length > 0) {
            log_(`the desktop started without: ${this.degraded.join(', ')}`);
        }
    }

    _buildSearchResults() {
        const panel = glass('bunny-search-results', {blur: this._blur, radius: 16});
        panel.visible = false;
        this._searchList = box({vertical: true, style_class: 'bunny-search-list'});
        panel.add_child(this._searchList);
        return panel;
    }

    /**
     * Parent every actor, in the two layers described at the top of the file.
     */
    _placeActors() {
        this._desktopLayer = new St.Widget({
            style_class: 'bunny-desktop-layer',
            layout_manager: new Clutter.FixedLayout(),
        });

        // Desktop content goes into uiGroup, below window_group, and is
        // *tracked as chrome*. Both halves are load-bearing and the second one
        // was missing for two releases.
        //
        // The background group was the obvious home and it is the wrong one:
        // actors under `global.window_group` are not in the shell's input
        // region, so a click on them is not delivered to the shell at all — it
        // passes through to whatever is behind, which on an empty desktop is
        // nothing. Every control in that layer was therefore inert. The dock
        // and the sidebar worked because they are chrome; the character, the
        // cards, the suggestions and the assistant's text field were not, and
        // nothing had ever pressed one of those to find out. The first run of
        // the assistant harness typed a request into a field that could not
        // take focus.
        //
        // `addChrome` puts it in the input region, and then it is lowered below
        // `window_group` so an open window still covers the dashboard the way
        // it covers a wallpaper. `trackFullscreen` keeps the old behaviour of
        // getting out of the way of a fullscreen video.
        Main.layoutManager.addChrome(this._desktopLayer, {
            affectsStruts: false,
            trackFullscreen: true,
        });
        Main.layoutManager.uiGroup.set_child_below_sibling(
            this._desktopLayer, global.window_group);
        this._desktopParent = Main.layoutManager.uiGroup;
        log_('desktop content is in uiGroup below window_group, tracked as chrome');

        for (const component of [
            this.wallpaper, this._characterViewport, this._bubble, this._suggestions,
            ...Object.values(this.cards),
        ]) {
            if (component)
                this._desktopLayer.add_child(component.actor);
        }

        // affectsStruts and trackFullscreen only. `affectsInputRegion` was a
        // parameter of this call until the X11 input-region bookkeeping went
        // away, and Params.parse refuses an unrecognised key rather than
        // ignoring it — measured on the first graphical boot:
        //
        //   bunny-desktop: failed to start
        //     (Unrecognized parameter "affectsInputRegion")
        //   _trackActor@resource:///org/gnome/shell/ui/layout.js:957
        //
        // addChrome adds the actor to uiGroup *before* it parses the
        // parameters, so the top bar was parented and then the constructor
        // aborted: one unsized bar, no sidebar, no dock, no cards, and GNOME's
        // panel back. That is why the constructor now tears down what it built
        // before rethrowing.
        const chrome = actor => Main.layoutManager.addChrome(actor, {
            affectsStruts: false,
            trackFullscreen: true,
        });
        this._chromeActors = [this._desktopLayer];
        for (const actor of [
            this.topBar?.actor, this.sidebar?.actor, this.dock?.actor,
            this.notificationLayer?.actor, this._searchResults,
        ]) {
            if (!actor)
                continue;
            chrome(actor);
            this._chromeActors.push(actor);
        }

        this._hidePanel();
    }

    /**
     * Hide GNOME's top bar, and keep it hidden.
     *
     * One `hide()` at enable() is not enough and the first graphical boot
     * showed why: LayoutManager's startup animation shows panelBox when the
     * session finishes coming up, which on an autologin session is *after* an
     * extension has enabled. The result was the Bunny bar and GNOME's bar on
     * screen together.
     *
     * So the visibility is watched. The handler is guarded against its own
     * signal — hide() inside a notify::visible handler re-enters — and the
     * connection is dropped in destroy() before the final show(), so disabling
     * the extension gives the panel back rather than fighting for it.
     */
    _hidePanel() {
        // panelBox rather than Main.panel: hiding the box removes its strut, so
        // the work area grows by its height instead of leaving a 32px band that
        // maximised windows refuse to use.
        const panelBox = Main.layoutManager.panelBox;
        panelBox.hide();
        this._panelVisibilityId = panelBox.connect('notify::visible', () => {
            if (this._destroyed || !panelBox.visible)
                return;
            panelBox.hide();
        });
        this._signals.push([panelBox, this._panelVisibilityId]);
    }

    _connectSession() {
        const track = (object, signal, handler) =>
            this._signals.push([object, object.connect(signal, handler)]);

        track(Main.layoutManager, 'monitors-changed', () => this._relayout());
        track(Main.layoutManager, 'startup-complete', () => this._relayout());

        // The overview is a full-screen surface of its own. Chrome under it
        // would draw over the workspace thumbnails, and desktop content behind
        // it would show through the blur.
        track(Main.overview, 'showing', () => this._setDesktopVisible(false));
        track(Main.overview, 'hiding', () => this._setDesktopVisible(true));

        // GNOME opens the overview at login when the session has no windows,
        // and it was already open by the time this extension enabled — so
        // 'showing' never fired, the desktop was never told to stand down, and
        // the first working boot photographed the Bunny bar, sidebar and dock
        // with GNOME's overview search, workspace strip and dash drawn over the
        // middle of them.
        //
        // Two halves to the fix. The state is adopted rather than assumed,
        // because whatever the overview is doing when this runs is not
        // knowable from a signal that has already fired; and the overview is
        // dismissed once at startup, because a desktop that shows the user a
        // character and a dashboard has already answered the question the
        // overview exists to ask.
        this._setDesktopVisible(!Main.overview.visible);
        track(Main.layoutManager, 'startup-complete', () => this._dismissOverviewOnce());
        this._dismissOverviewOnce();

        track(St.Settings.get(), 'notify::enable-animations', () => this._relayout());
        track(St.Settings.get(), 'notify::font-name', () => this._relayout());

        this._installedChangedId = this.launcher.connectInstalledChanged(() => {
            this.dock?.rebuild();
            this.cards.quickAccess?.rebuild();
            this._suggestions?.rebuild();
        });

        this._characterUnsubscribe = this.characterState.subscribe(state =>
            this._onCharacterState(state));
    }

    _installKeybindings() {
        this._keybindings = [];
        const bind = (key, handler) => {
            Main.wm.addKeybinding(
                key, this._settings, Meta.KeyBindingFlags.NONE,
                Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW, handler);
            this._keybindings.push(key);
        };
        try {
            bind('focus-desktop-search', () => {
                this.topBar?.focusSearch();
                this.characterState.noteActivity();
            });
            bind('focus-desktop-sidebar', () => this.sidebar?.focus());
            bind('focus-desktop-assistant', () => this._activateAssistant());
            bind('push-to-talk', () => this._startVoice('keyboard-shortcut'));
        } catch (error) {
            // A key missing from the compiled schema must not take the desktop
            // down with it: everything else here works without a shortcut.
            logError_('a desktop keybinding could not be registered', error);
        }
    }

    // --------------------------------------------------------------- layout

    _relayout() {
        if (this._destroyed)
            return;
        const monitor = Main.layoutManager.primaryMonitor;
        if (!monitor)
            return;

        // The full monitor, not the work area: the panel is hidden, so there
        // are no struts, and using the work area would leave the dock floating
        // above a band of wallpaper on a session that once had a panel.
        const screen = {width: monitor.width, height: monitor.height};
        const solution = solve(screen, {scale: this._textScale()});
        this._solution = solution;

        this._desktopLayer.set_position(monitor.x, monitor.y);
        this._desktopLayer.set_size(monitor.width, monitor.height);
        this.wallpaper?.setGeometry({x: 0, y: 0, width: monitor.width, height: monitor.height});

        const rects = solution.rects;
        const place = (actor, rect) => {
            actor.set_position(monitor.x + rect.x, monitor.y + rect.y);
            actor.set_size(rect.width, rect.height);
        };

        if (this.topBar)
            place(this.topBar.actor, rects.topBar);
        if (this.sidebar) {
            place(this.sidebar.actor, rects.sidebar);
            this.sidebar.setCollapsed(solution.sidebarMode === 'collapsed');
        }
        if (this.dock)
            place(this.dock.actor, rects.dock);

        this.notificationLayer?.setGeometry({
            x: monitor.x + monitor.width - 360 - rects.topBar.height,
            y: monitor.y + rects.topBar.height + 12,
            width: 360,
        });

        this._searchResults.set_position(
            monitor.x + Math.round((monitor.width - 560) / 2),
            monitor.y + rects.topBar.height + 6);
        this._searchResults.set_width(560);

        // Cards. A card the solver dropped is hidden and its timer stopped, so
        // a widget nobody can see stops reading the kernel.
        let index = 0;
        for (const key of [...LEFT_COLUMN, ...RIGHT_COLUMN]) {
            const card = this.cards[key];
            if (!card)
                continue;
            const rect = rects[key];
            if (!rect) {
                card.hide();
                continue;
            }
            if (key === 'media' && !this.cards.media?.hasMedia) {
                // Nothing is playing. Collapse rather than show an empty card.
                card.hide();
                continue;
            }
            card.show(rect, index);
            index += 1;
        }

        this._characterViewport?.setGeometry(rects.character);
        this._placeBubbles(rects.character);

        log_(`layout ${screen.width}x${screen.height} -> ${solution.breakpoint}, ` +
            `${solution.columns} card column(s)` +
            (solution.dropped.length > 0 ? `, dropped: ${solution.dropped.join(', ')}` : ''));
    }

    /**
     * How much larger than the default the user has made the interface text.
     *
     * Cards grow with their text, and a card that grows past the band has to be
     * dropped — so the scale is an input to the layout solver, not a detail of
     * the stylesheet. GNOME states it as a point size in the font name; 11 is
     * the Adwaita default and the ratio to it is the factor.
     */
    _textScale() {
        const match = /(\d+(?:\.\d+)?)\s*$/.exec(St.Settings.get().font_name ?? '');
        if (match === null)
            return 1;
        const points = Number(match[1]);
        return Number.isFinite(points) && points > 0 ? Math.max(1, points / 11) : 1;
    }

    _placeBubbles(band) {
        // Both bubbles are positioned against the figure, so with no figure
        // there is nothing to position them against and they stay where they
        // are — which is off-screen, because they start hidden.
        if (!this._characterViewport)
            return;
        const rect = this._characterViewport.figureRect();
        const figure = {
            x: rect.x - band.x,
            y: rect.y - band.y,
            width: rect.width,
            height: rect.height,
        };
        if (this._bubble) {
            this._bubble.place(figure, band, 'left');
            this._bubble.actor.set_position(
                band.x + this._bubble.actor.get_x(), band.y + this._bubble.actor.get_y());
        }

        if (this._suggestions) {
            const suggestionWidth = Math.min(268, Math.round(band.width * 0.30));
            this._suggestions.setWidth(suggestionWidth);
            const right = band.x + figure.x + figure.width + 20;
            const fits = right + suggestionWidth <= band.x + band.width;
            this._suggestions.actor.visible = fits;
            if (fits) {
                this._suggestions.actor.set_position(
                    right, band.y + Math.round(figure.y + figure.height * 0.16));
            }
        }
    }

    /**
     * Close the login overview, once.
     *
     * Once, and only at startup: the overview is a surface the user can open
     * deliberately, and a desktop that closed it whenever it appeared would be
     * a desktop that had taken the Super key away. The flag is what makes the
     * difference between dismissing GNOME's opening move and overriding the
     * user.
     */
    _dismissOverviewOnce() {
        if (this._overviewDismissed)
            return;
        this._overviewDismissed = true;
        if (!Main.overview.visible)
            return;
        log_('the session opened the overview at login; dismissing it for the desktop');
        Main.overview.hide();
    }

    _setDesktopVisible(visible) {
        this._desktopLayer.visible = visible;
        for (const actor of this._chromeActors) {
            if (actor === this._searchResults)
                continue;
            actor.visible = visible;
        }
        if (!visible)
            this._closeSearch();
    }

    // ------------------------------------------------------------ behaviour

    _greet() {
        if (!this._bubble)
            return;
        const hour = new Date().getHours();
        const salutation = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
        const events = this.agenda?.events().length ?? 0;
        const agendaLine = events === 0
            ? 'Nothing is scheduled today.'
            : `You have ${events} thing${events === 1 ? '' : 's'} on today.`;
        // Deferred one beat so the entrance animations are the first thing that
        // happens; a bubble that appears in the same frame as the cards reads
        // as a page load rather than as somebody saying hello.
        this._greetTimer = timeout(700, () => {
            this._bubble.say(`${salutation}!\n\n${agendaLine}\n\nShall we get started?`);
            this.characterState.setState('talking', {reason: 'greeting'});
            this._returnToIdleAfterTalking();
        });
    }

    /**
     * Say what did not start, once, to the person looking at the screen.
     *
     * Not silently. A desktop that comes up without its dock and says nothing
     * is a desktop the user reports as "the dock disappeared", with no way for
     * anyone to tell whether it was never built, built and hidden, or built and
     * placed off-screen. The journal line is for whoever debugs it; this toast
     * is so the user knows the machine knows.
     */
    _reportDegradation() {
        if (this.degraded.length === 0)
            return;
        this.notifications.warning(
            `Some parts of the desktop did not start: ${this.degraded.join(', ')}. ` +
            'Everything else is working.');
    }

    _select(id) {
        this.sidebar?.select(id);
        this.characterState.noteActivity();
        switch (id) {
        case 'home':
            this._closeSearch();
            break;
        case 'assistant':
            this._activateAssistant();
            break;
        case 'files':
            if (!this.launcher.launch('files'))
                this.notifications.warning('Files is not installed on this system.');
            break;
        case 'apps':
            Main.overview.toggle();
            break;
        case 'settings':
            if (!this.launcher.launch('settings'))
                this.notifications.warning('Settings is not installed on this system.');
            break;
        default:
            break;
        }
    }

    _launchFromSidebar(id) {
        this.characterState.noteActivity();
        if (id === 'terminal') {
            if (!this.launcher.launch('terminal'))
                this.notifications.warning('No terminal is installed on this system.');
            return;
        }
        if (id === 'store') {
            if (!this.launcher.launch('software'))
                this.notifications.warning('The software store is not installed on this system.');
        }
    }

    _runSuggestedAction(id) {
        this.characterState.noteActivity();
        if (id === 'terminal' || id === 'store')
            this._launchFromSidebar(id);
        else
            this._select(id);
    }

    /**
     * Click the character, press Super+Shift+B, or choose AI Assistant.
     *
     * This is the typed-input shortcut. LISTENING is reserved for an explicit
     * microphone activation, so keyboard focus can never be mistaken for a
     * live microphone.
     */
    _activateAssistant() {
        log_('assistant activated; the text input has focus');
        this.characterState.noteActivity();
        this._bubble?.say('Ready when you are. Type a request or press the microphone.', {wave: true});
        this._assistantPanel?.focusInput();
    }

    /**
     * Escape out of the assistant without submitting.
     *
     * Escape is also the explicit speech-interruption control. It releases an
     * open microphone and stops output speech; it does not cancel a task that
     * the runtime already owns.
     */
    _dismissAssistant() {
        if (this._voicePhase === 'speaking')
            this.voice?.interruptSpeech() || this.assistant?.interruptSpeech();
        this._releaseVoiceInteraction({notify: true});
        this._voicePhase = 'idle';
        if (this.characterState.state === 'listening' || this.characterState.state === 'talking')
            this.characterState.setState('idle', {reason: 'the request was dismissed'});
        this._bubble?.hide();
        global.stage.set_key_focus(null);
    }

    /**
     * Submit a request and drive the desktop from its lifecycle.
     *
     * Every callback here is guarded by `owns`, and that guard is the whole
     * reason `AssistantService.ask` returns an id. Cancelling a bridge is not
     * instantaneous — a line already written to the pipe still arrives, and the
     * read callback for it is already scheduled — so the previous request's
     * `finished` can land after the next one's `thinking`. Without the guard it
     * sets the character to SUCCESS and then IDLE while the newer request is
     * still running, and the figure goes calm in the middle of the work.
     *
     * The rule is one line: a late callback for a request that is no longer the
     * active one updates nothing. It is not an error and is not reported; it is
     * simply news about something the user has moved on from.
     */
    _ask(text) {
        const trimmed = text.trim();
        if (trimmed === '')
            return;
        if (!this.assistant) {
            this._failRequest('The assistant is not running on this session.', {
                retry: null,
            });
            return;
        }

        // A new request immediately releases speech resources. A task already
        // accepted by the runtime remains there and stays visible in Tasks.
        this._releaseVoiceInteraction({notify: false});
        this._voicePhase = 'idle';

        log_(`assistant request submitted: ${trimmed.length} characters`);
        this.characterState.noteActivity();
        this._assistantPanel?.addTurn('user', trimmed);
        this._assistantPanel?.showFileResults([]);
        this._assistantPanel?.setBusy(true);
        this._assistantPanel?.setStatus('Thinking…');
        this.characterState.setState('thinking', {reason: trimmed});
        this._bubble?.say('Let me look at that.', {wave: false});
        this._lastRequest = trimmed;

        const requestId = this.assistant.ask(trimmed, {
            onPhase: (phase, statusText, meta) => {
                if (!this._owns(meta))
                    return;
                if (phase === 'speaking')
                    this._voicePhase = 'speaking';
                this.characterState.adoptPhase(phase, PHASE_TO_STATE, {statusText});
                if (statusText)
                    this._assistantPanel?.setStatus(statusText);
            },
            onReply: (reply, isError, meta) => {
                if (!this._owns(meta))
                    return;
                this._assistantPanel?.addTurn('bunny', reply, {tone: isError ? 'error' : 'normal'});
                // The bubble is the primary surface: it shows a preview and
                // hands the rest to the card, which is a scrolling transcript
                // and already has the whole thing from `addTurn` above.
                this._bubble?.say(reply, {
                    tone: isError ? 'error' : 'normal',
                    wave: !isError,
                    onOpenFull: () => this._assistantPanel?.focusInput(),
                });
                if (!isError) {
                    this.characterState.setState('talking', {reason: 'delivering the answer'});
                    this._returnToIdleAfterTalking();
                }
            },
            onFileResults: (results, meta) => {
                if (this._owns(meta))
                    this._assistantPanel?.showFileResults(results);
            },
            onSpeechStarted: (_speech, meta) => {
                if (!this._owns(meta))
                    return;
                this._voicePhase = 'speaking';
                this._assistantPanel?.setVoiceState(false, 'speaking');
                this.characterState.setState('talking', {reason: 'speaking the typed response'});
            },
            onSpeechFinished: (_speech, meta) => {
                if (this._owns(meta))
                    this._voicePhase = 'idle';
            },
            onSpeechError: (reason, meta) => {
                if (!this._owns(meta))
                    return;
                this._voicePhase = 'idle';
                this.notifications.warning(`Bunny could not speak: ${reason}`);
            },
            onFinished: (phase, meta) => {
                if (!this._owns(meta))
                    return;
                this._voicePhase = 'idle';
                this._assistantPanel?.setBusy(false);
                this._assistantPanel?.setStatus('');
                if (phase === 'success') {
                    this.characterState.setState('success', {reason: 'the task finished'});
                    // SUCCESS is a moment, not a resting state. Without this the
                    // character holds a celebration until the next request.
                    this._returnToIdleAfterTalking();
                } else if (phase !== 'error') {
                    // Cancelled, blocked, paused — terminal for this watcher and
                    // not a failure to report. The character must still land
                    // somewhere, and idle is where it lands.
                    this._returnToIdleAfterTalking();
                }
            },
            onError: (reason, meta) => {
                if (!this._owns(meta))
                    return;
                this._failRequest(reason, {retry: trimmed});
            },
        });
        this._requestId = requestId;
    }

    /**
     * Is this callback about the request the desktop is currently showing?
     *
     * A callback with no metadata is from a caller that predates request ids;
     * it is treated as current, because refusing it would silently drop the
     * only answer that caller can give.
     */
    _owns(meta) {
        if (this._destroyed)
            return false;
        if (!meta || meta.requestId === undefined)
            return true;
        return meta.requestId === this._requestId;
    }

    /**
     * One place where a failed request lands.
     *
     * Every failure the brief lists — backend down, timeout, malformed reply,
     * action refused, application missing — arrives here as a sentence that was
     * written for a person. The diagnostic detail is already in the journal by
     * the time this runs; what goes on screen is what someone can act on, and a
     * Retry that reruns the exact request they typed.
     */
    _failRequest(reason, {retry = null} = {}) {
        this._assistantPanel?.setBusy(false);
        this._assistantPanel?.setStatus(reason, {tone: 'error'});
        this._assistantPanel?.addTurn('bunny', reason, {tone: 'error'});
        this.characterState.setState('error', {reason});
        this._bubble?.say(reason, {tone: 'error'});
        logError_('the assistant request failed', new Error(reason));
        if (retry) {
            this.notifications.error(`Bunny could not answer: ${reason}`, {
                onActivate: () => this._ask(retry),
            });
        } else {
            this.notifications.error(`Bunny could not answer: ${reason}`);
        }
        // Even a failure ends. ERROR is a state the brief says the character may
        // hold, but not for ever — the next thing a user does should not meet a
        // figure still upset about the last thing.
        this._returnToIdleAfterTalking();
    }

    /**
     * Run one explicit, bounded voice interaction in the companion service.
     * GNOME Shell renders events only; it never opens an audio device or loads
     * a recognition/synthesis model.
     */
    _startVoice(activationSource = 'push-to-talk-button') {
        // Output speech remains interruptible even when Voice Input is Off.
        // In that configuration this control is a Stop button, not an attempt
        // to open a disabled microphone.
        if (this._voicePhase === 'speaking') {
            this.voice?.interruptSpeech() || this.assistant?.interruptSpeech();
            this._voicePhase = 'idle';
            this._assistantPanel?.setVoiceState(false);
            this._assistantPanel?.setBusy(false);
            this._assistantPanel?.setStatus('Speech stopped.');
            this.characterState.setState('idle', {reason: 'speech was interrupted'});
            return;
        }

        if (!this.voice || this.voice.available === false) {
            const reason = this.voice?.availabilityReason ?? 'the voice service is unavailable';
            this.characterState.setState('warning', {reason});
            this._bubble?.say(`Voice input is unavailable: ${reason}`, {tone: 'warning'});
            this.notifications.warning(`Speech input is unavailable: ${reason}`);
            this._returnToIdleAfterTalking();
            return;
        }

        if (this.voice.cancellationPending) {
            this._assistantPanel?.setStatus(
                'Waiting for the microphone to confirm it is closed…');
            return;
        }

        // A second activation while the initial request is crossing the IPC
        // boundary means cancel, not another capture. At this point the shell
        // may not have a request id yet, so VoiceService keeps reading until it
        // can cancel and confirm closure.
        if (this._voicePhase === 'starting') {
            this._voicePhase = 'stopping';
            this._assistantPanel?.setStatus('Stopping the microphone…');
            this._releaseVoiceInteraction({
                notify: false,
                onClosed: () => {
                    if (this._voicePhase !== 'stopping')
                        return;
                    this._voicePhase = 'idle';
                    this._assistantPanel?.setBusy(false);
                    this._assistantPanel?.setStatus('');
                    this.characterState.setState('idle', {
                        reason: 'voice activation was cancelled',
                    });
                },
            });
            return;
        }

        // Clicking the same button while listening is an explicit manual stop,
        // not a second capture. Recognition continues over what was recorded.
        if (this._voicePhase === 'listening' && this.voice.stopCapture()) {
            this._voicePhase = 'stopping';
            // The MIC indicator and LISTENING pose remain until the companion
            // reports that the device actually closed. A requested stop is not
            // yet a closed microphone.
            this._assistantPanel?.setStatus('Stopping the microphone…');
            return;
        }
        if (this._voicePhase === 'stopping')
            return;
        this.assistant?.interruptSpeech();
        this.assistant?.cancelWatch();
        this._releaseVoiceInteraction({notify: false});
        this._voicePhase = 'starting';
        this._assistantPanel?.showFileResults([]);
        this._assistantPanel?.setBusy(true);
        // Conservative privacy ordering: make the persistent chrome indicator
        // visible before asking the service to open a device. The companion
        // enforces the same order internally with its ListeningIndicator.
        this._setMicrophoneVisible(true);
        this._assistantPanel?.setVoiceState(true, 'starting');
        this._assistantPanel?.setStatus('Starting microphone…');
        this.characterState.setState('listening', {reason: 'explicit push-to-talk activation'});
        this._bubble?.say('Starting the microphone…', {wave: true});

        const interactionId = this.voice.start(activationSource, {
            onMicrophone: (active, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._setMicrophoneVisible(active);
                this._assistantPanel?.setVoiceState(active, active ? 'listening' : this._voicePhase);
                if (active) {
                    this._voicePhase = 'listening';
                    this._assistantPanel?.setStatus('Listening… Click the microphone to stop.');
                    this.characterState.setState('listening', {reason: 'microphone is active'});
                    this._bubble?.say('Listening…', {wave: true});
                }
            },
            onPhase: (phase, statusText, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._voicePhase = phase === 'speaking' ? 'speaking' : phase;
                this.characterState.adoptPhase(phase, PHASE_TO_STATE, {statusText});
                if (statusText)
                    this._assistantPanel?.setStatus(statusText);
                if (phase === 'speaking')
                    this._assistantPanel?.setVoiceState(false, 'speaking');
            },
            onPartial: (partial, meta) => {
                if (this._ownsVoice(meta) && partial)
                    this._assistantPanel?.setStatus(`Hearing: ${partial}`);
            },
            onTranscript: (transcript, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                const text = String(transcript.text ?? '').trim();
                this._setMicrophoneVisible(false);
                this._assistantPanel?.setVoiceState(false);
                if (text) {
                    this._assistantPanel?.addTurn('user', text);
                    this._assistantPanel?.setStatus(`Heard: ${text}`);
                    this._bubble?.say(text, {wave: false});
                }
                this._voicePhase = 'thinking';
                this.characterState.setState('thinking', {reason: 'the transcript is being understood'});
            },
            onAccepted: (_taskId, meta) => {
                if (this._ownsVoice(meta))
                    this._assistantPanel?.setStatus('Thinking…');
            },
            onReply: (reply, isError, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._assistantPanel?.addTurn('bunny', reply, {tone: isError ? 'error' : 'normal'});
                this._bubble?.say(reply, {
                    tone: isError ? 'error' : 'normal',
                    wave: !isError,
                    onOpenFull: () => this._assistantPanel?.focusInput(),
                });
            },
            onFileResults: (results, meta) => {
                if (this._ownsVoice(meta))
                    this._assistantPanel?.showFileResults(results);
            },
            onSpeechStarted: (_speech, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._voicePhase = 'speaking';
                this._assistantPanel?.setVoiceState(false, 'speaking');
                this.characterState.setState('talking', {reason: 'speaking the response'});
            },
            onSpeechError: (reason, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._assistantPanel?.setStatus(`Response displayed; speech unavailable: ${reason}`);
                this.notifications.warning(`Bunny could not speak: ${reason}`);
            },
            onWarning: (reason, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._assistantPanel?.addTurn('bunny', reason, {tone: 'error'});
                this._assistantPanel?.setStatus(reason);
                this.characterState.setState('warning', {reason});
                this._bubble?.say(reason, {tone: 'warning'});
            },
            onFinished: (phase, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._setMicrophoneVisible(false);
                this._assistantPanel?.setVoiceState(false);
                this._assistantPanel?.setBusy(false);
                if (phase === 'success') {
                    this._assistantPanel?.setStatus('');
                    this.characterState.setState('success', {reason: 'the voice request finished'});
                } else if (phase === 'cancelled') {
                    this._assistantPanel?.setStatus('');
                    this.characterState.setState('idle', {reason: 'voice interaction cancelled'});
                }
                this._voicePhase = 'idle';
                this._returnToIdleAfterTalking();
            },
            onError: (reason, meta) => {
                if (!this._ownsVoice(meta))
                    return;
                this._voicePhase = 'idle';
                this._failRequest(reason, {retry: null});
            },
        });
        this._voiceInteractionId = interactionId;
    }

    _ownsVoice(meta) {
        if (this._destroyed)
            return false;
        return !meta || meta.interactionId === this._voiceInteractionId;
    }

    _setMicrophoneVisible(active) {
        this.topBar?.setMicrophoneActive(active);
    }

    _releaseVoiceInteraction({notify = false, onClosed = null} = {}) {
        const closed = () => {
            this._setMicrophoneVisible(false);
            this._assistantPanel?.setVoiceState(false);
            onClosed?.();
        };
        if (!this.voice) {
            closed();
            return false;
        }
        return this.voice.cancel({
            notify,
            onMicrophoneClosed: closed,
        });
    }

    _openFileResult(index, command) {
        const ordinals = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'];
        if (!Number.isInteger(index) || index < 1 || index > 24)
            return;
        const selector = ordinals[index - 1] ?? String(index);
        const request = command === 'show_containing_folder'
            ? `Show result ${selector} in its containing folder`
            : `Open result ${selector}`;
        this._ask(request);
    }

    /**
     * Land the character back on idle after a state that is a moment.
     *
     * TALKING, SUCCESS and ERROR are all things that happen *to* a request and
     * none of them is where a character should live. The set is named here
     * rather than checked as "not idle", because WORKING and LISTENING are also
     * not idle and must not be cut short by a timer that fired from an earlier
     * request — the newer request owns the character then, and this must leave
     * it alone.
     */
    _returnToIdleAfterTalking() {
        this._talkTimer?.stop();
        this._talkTimer = timeout(TALKING_DWELL_MS, () => {
            this._talkTimer = null;
            if (TRANSIENT_STATES.has(this.characterState.state))
                this.characterState.setState('idle', {reason: 'the request is over'});
        });
    }

    _onCharacterState(state) {
        // The bubble is dismissed when the character goes quiet, so a stale
        // answer does not hang beside an idle figure for the rest of the day.
        if (state === 'idle' || state === 'sleeping')
            this._bubble?.hide();
        if (this._suggestions)
            this._suggestions.actor.opacity = state === 'idle' ? 255 : 190;
    }

    _onHousekeeping() {
        // Media presence decides whether the card has a slot at all, so a
        // player starting or stopping is a layout change, not a refresh.
        const media = this.cards.media;
        if (media && media.hasMedia !== media.live)
            this._relayout();
    }

    // ---------------------------------------------------------------- search

    _onSearch(text) {
        if (text.trim() === '') {
            this._closeSearch();
            return;
        }
        this.characterState.noteActivity();
        this._renderSearch(this.search.immediate(text), []);
        this.search.files(text, 5, files => {
            if ((this.topBar?.searchText.trim() ?? '') === text.trim())
                this._renderSearch(this.search.immediate(text), files);
        });
    }

    _renderSearch(immediate, files) {
        this._searchList.destroy_all_children();
        const rows = [...immediate];
        for (const file of files) {
            rows.push({
                kind: 'file',
                title: file.name,
                subtitle: file.path,
                iconName: Icons.FILE_GENERIC,
                activate: () => this.launcher.spawn(['gio', 'open', file.path]),
            });
        }
        const query = this.topBar?.searchText.trim() ?? '';
        if (query !== '') {
            rows.push({
                kind: 'assistant',
                title: `Ask Bunny: ${query}`,
                subtitle: 'Send this to your assistant',
                iconName: Icons.BUNNY,
                activate: () => {
                    this._closeSearch();
                    this.topBar?.clearSearch();
                    this._ask(query);
                },
            });
        }

        for (const row of rows)
            this._searchList.add_child(this._searchRow(row));

        this._searchResults.visible = rows.length > 0;
        if (rows.length > 0)
            enter(this._searchResults, {rise: -6});
    }

    _searchRow(row) {
        const actor = box({style_class: 'bunny-search-row'});
        const icon = new St.Icon({icon_size: 18, style_class: 'bunny-search-row-icon'});
        if (row.gicon)
            icon.gicon = row.gicon;
        else
            icon.icon_name = resolveIconName(row.iconName ?? Icons.APP_GENERIC);
        actor.add_child(icon);
        const column = box({vertical: true, x_expand: true});
        const title = new St.Label({text: row.title, style_class: 'bunny-search-row-title'});
        const subtitle = new St.Label({text: row.subtitle, style_class: 'bunny-search-row-subtitle'});
        title.clutter_text.ellipsize = 3;
        subtitle.clutter_text.ellipsize = 3;
        column.add_child(title);
        column.add_child(subtitle);
        actor.add_child(column);
        // Kept as a plain property as well as a handler: pressing Enter in the
        // search field runs the first row, and synthesising a button event to
        // do that would need an event object there is no honest way to build.
        actor.activateRow = () => {
            this._closeSearch();
            row.activate();
        };
        makeActivatable(actor, actor.activateRow,
            {accessibleName: `${row.title}. ${row.subtitle}`});
        return actor;
    }

    _onSearchActivate() {
        this._searchList.get_first_child()?.activateRow?.();
    }

    _closeSearch() {
        if (!this._searchResults.visible)
            return;
        ease(this._searchResults, {opacity: 0}, {
            ms: 160,
            onComplete: () => {
                this._searchResults.visible = false;
                this._searchResults.opacity = 255;
            },
        });
    }

    // ----------------------------------------------------------- power menu

    _togglePowerMenu() {
        if (this._powerMenu !== null) {
            this._closePowerMenu();
            return;
        }
        if (this.power === null) {
            this.notifications.warning('Power actions are not available on this session.');
            return;
        }
        this._powerMenu = new PowerMenu(this.power, {onClose: () => this._closePowerMenu()});
        // `affectsStruts` and `trackFullscreen` only.
        //
        // This call still passed `affectsInputRegion` long after the same
        // parameter had been removed from the one in _placeActors, where it
        // aborted the desktop's construction on the first graphical boot.
        // Params.parse refuses an unrecognised key rather than ignoring it, and
        // addChrome parents the actor before it parses — so opening the power
        // menu would have parented an unsized popup and thrown, on every
        // machine, from the day the sidebar's Power row was written. It was
        // never pressed. That is the whole reason criterion 9 mattered.
        Main.layoutManager.addChrome(this._powerMenu.actor, {
            affectsStruts: false, trackFullscreen: true,
        });
        const sidebarRect = this._solution.rects.sidebar;
        const monitor = Main.layoutManager.primaryMonitor;
        this._powerMenu.actor.set_position(
            monitor.x + sidebarRect.x + sidebarRect.width + 10,
            monitor.y + sidebarRect.y + sidebarRect.height - 190);
        enter(this._powerMenu.actor, {rise: 8});

        // Modal so Escape closes it and a click elsewhere does too, which is
        // what makes it a menu rather than a panel that happens to look like one.
        this._powerGrab = Main.pushModal(this._powerMenu.actor, {
            actionMode: Shell.ActionMode.NORMAL,
        });
        this._powerMenu.actor.grab_key_focus();
        this._powerClickId = global.stage.connect('button-press-event', (_stage, event) => {
            const [x, y] = event.get_coords();
            const [ax, ay] = this._powerMenu.actor.get_transformed_position();
            const [aw, ah] = this._powerMenu.actor.get_transformed_size();
            if (x < ax || x > ax + aw || y < ay || y > ay + ah) {
                this._closePowerMenu();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
    }

    _closePowerMenu() {
        if (this._powerMenu === null)
            return;
        if (this._powerClickId) {
            global.stage.disconnect(this._powerClickId);
            this._powerClickId = 0;
        }
        if (this._powerGrab) {
            Main.popModal(this._powerGrab);
            this._powerGrab = null;
        }
        Main.layoutManager.removeChrome(this._powerMenu.actor);
        this._powerMenu.destroy();
        this._powerMenu = null;
    }

    // --------------------------------------------------------------- teardown

    /**
     * Tear everything down, from any state the constructor may have reached.
     *
     * Every step is individually guarded and every reference is optional,
     * because this is called both on a clean disable and on a construction that
     * threw partway. A teardown that assumed a fully built object would throw
     * on the first missing field and leave the rest of the desktop — including
     * GNOME's hidden panel — exactly as the failure left it.
     */
    destroy() {
        this._destroyed = true;

        const attempt = (what, action) => {
            try {
                action();
            } catch (error) {
                logError_(`teardown step "${what}" failed`, error);
            }
        };

        attempt('timers', () => {
            this._housekeeping?.stop();
            this._greetTimer?.stop();
            this._talkTimer?.stop();
        });

        attempt('keybindings', () => {
            for (const key of this._keybindings ?? [])
                Main.wm.removeKeybinding(key);
            this._keybindings = [];
        });

        attempt('power menu', () => this._closePowerMenu());

        attempt('signals', () => {
            for (const [object, id] of this._signals ?? []) {
                try {
                    object.disconnect(id);
                } catch (error) {
                    logError_('a session signal could not be disconnected', error);
                }
            }
            this._signals = [];
            if (this._installedChangedId)
                this.launcher?.disconnect(this._installedChangedId);
            this._characterUnsubscribe?.();
        });

        attempt('chrome', () => {
            for (const actor of this._chromeActors ?? []) {
                try {
                    Main.layoutManager.removeChrome(actor);
                } catch (_error) {
                    // Never tracked, because addChrome threw after parenting it.
                    // Reparenting is undone by the destroy below either way.
                }
            }
        });

        for (const [what, component] of [
            ['top bar', this.topBar], ['sidebar', this.sidebar], ['dock', this.dock],
            ['notification layer', this.notificationLayer], ['bubble', this._bubble],
            ['suggestions', this._suggestions], ['character', this._characterViewport],
            ['wallpaper', this.wallpaper],
        ]) {
            attempt(what, () => component?.destroy());
        }
        attempt('notifications', () => this.notifications?.detach());
        attempt('search results', () => this._searchResults?.destroy());
        attempt('cards', () => {
            for (const card of Object.values(this.cards ?? {}))
                card?.destroy();
        });
        attempt('desktop layer', () => this._desktopLayer?.destroy());

        for (const [what, service] of [
            ['character state', this.characterState], ['assistant', this.assistant],
            ['voice', this.voice],
            ['search', this.search], ['agenda', this.agenda], ['media', this.media],
            ['audio', this.audio], ['brightness', this.brightness], ['network', this.network],
        ]) {
            attempt(what, () => service?.destroy());
        }

        // Give GNOME its panel back, last and unconditionally. An extension
        // that left the session without a top bar after being disabled would be
        // unrecoverable without a terminal, which is the exact failure this
        // desktop exists to avoid.
        attempt('restore the GNOME panel', () => {
            this._panelVisibilityId = 0;
            Main.layoutManager.panelBox.show();
        });
    }
}
