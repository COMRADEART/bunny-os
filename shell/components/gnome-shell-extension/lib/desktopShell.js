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
import {UniversalSearch} from './services/search.js';

/** How long a reply stays on the character's face before it returns to idle. */
const TALKING_DWELL_MS = 6000;

export class DesktopShell {
    constructor({settings}) {
        this._settings = settings;
        this._signals = [];
        this._destroyed = false;

        this._blur = this._decideBlur();

        this.notifications = new NotificationService();
        this._buildServices();
        this._buildComponents();
        this._placeActors();
        this._connectSession();
        this._installKeybindings();

        this._relayout();
        this._greet();

        // Cheap, and it catches the two things no signal reports: an
        // application that stopped running, and midnight.
        this._housekeeping = interval(30, () => this._onHousekeeping());
    }

    // ---------------------------------------------------------------- setup

    /**
     * Blur costs a full-surface sample per blurred panel per frame. On a GPU
     * that is free; on llvmpipe in a VM — a configuration this image must stay
     * usable in — it is not. The setting wins when the user has expressed a
     * preference; otherwise the renderer probe decides and says so.
     */
    _decideBlur() {
        const preference = this._settings.get_string('desktop-blur');
        if (preference === 'on')
            return true;
        if (preference === 'off')
            return false;
        const software = isLikelySoftwareRendering();
        log_(software
            ? 'no DRM render node found; assuming software rendering and disabling panel blur'
            : 'hardware rendering detected; panel blur enabled');
        return !software;
    }

    _buildServices() {
        this.telemetry = new SystemTelemetry();
        this.power = new PowerManager();
        this.network = new NetworkManagerService();
        this.audio = new AudioManager();
        this.brightness = new BrightnessManager();
        this.launcher = new ApplicationLauncher();
        this.media = new MediaService();
        this.agenda = new AgendaService();
        this.assistant = new AssistantService();
        this.search = new UniversalSearch(this.launcher);
        this.characterState = new CharacterStateManager();

        this.assistant.checkHealth((available, reason) => {
            this._assistantPanel?.setVoiceAvailable(available, reason);
            this._suggestions?.rebuild();
            if (!available) {
                this.characterState.setState('sleeping', {reason});
                this._bubble?.say(
                    'I am not connected to my runtime yet. Everything else on this desktop still works.',
                    {tone: 'warning'});
            }
        });
    }

    _buildComponents() {
        const blur = this._blur;

        this.wallpaper = new WallpaperLayer();
        this.notificationLayer = new NotificationLayer({blur});
        this.notifications.attach(this.notificationLayer);

        this.topBar = new TopBar({
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
        });

        this.sidebar = new Sidebar({
            blur,
            onSelect: id => this._select(id),
            onLaunch: id => this._launchFromSidebar(id),
            onPower: () => this._togglePowerMenu(),
        });

        this.dock = new BottomDock({
            blur,
            launcher: this.launcher,
            onOverview: () => Main.overview.toggle(),
        });

        this._characterViewport = new CharacterViewport({
            stateManager: this.characterState,
            onActivate: () => this._activateAssistant(),
        });

        this._bubble = new AssistantBubble({blur});
        this._suggestions = new SuggestedActions({
            blur,
            launcher: this.launcher,
            assistant: this.assistant,
            onPrompt: text => this._ask(text),
            onAction: id => this._runSuggestedAction(id),
        });

        this._assistantPanel = new AssistantPanel({
            blur,
            assistant: this.assistant,
            onSubmit: text => this._ask(text),
            onVoice: () => this._startVoice(),
            onOpenFull: () => this.launcher.spawn(['bunny-command']),
        });

        this.cards = {
            systemOverview: new SystemOverview({telemetry: this.telemetry, launcher: this.launcher, blur}),
            quickAccess: new QuickAccess({
                launcher: this.launcher, blur, onSeeAll: () => Main.overview.toggle(),
            }),
            media: new MediaWidget({media: this.media, blur}),
            agenda: new AgendaWidget({agenda: this.agenda, blur}),
            systemMonitor: new SystemMonitor({
                network: this.network, power: this.power, launcher: this.launcher, blur,
            }),
            assistant: this._assistantPanel,
        };

        this._searchResults = this._buildSearchResults();
        this._powerMenu = null;
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

        const backgroundGroup = Main.layoutManager._backgroundGroup;
        if (backgroundGroup) {
            backgroundGroup.add_child(this._desktopLayer);
            this._desktopParent = backgroundGroup;
        } else {
            // Same position in the scene graph, reached without the private
            // field. Logged because it means a Shell change and somebody should
            // look at it before the next release.
            log_('Main.layoutManager._backgroundGroup is absent; ' +
                'placing desktop content below window_group in uiGroup');
            Main.layoutManager.uiGroup.insert_child_below(this._desktopLayer, global.window_group);
            this._desktopParent = Main.layoutManager.uiGroup;
        }

        this._desktopLayer.add_child(this.wallpaper.actor);
        this._desktopLayer.add_child(this._characterViewport.actor);
        this._desktopLayer.add_child(this._bubble.actor);
        this._desktopLayer.add_child(this._suggestions.actor);
        for (const card of Object.values(this.cards))
            this._desktopLayer.add_child(card.actor);

        const chrome = actor => Main.layoutManager.addChrome(actor, {
            affectsStruts: false,
            affectsInputRegion: true,
            trackFullscreen: true,
        });
        chrome(this.topBar.actor);
        chrome(this.sidebar.actor);
        chrome(this.dock.actor);
        chrome(this.notificationLayer.actor);
        chrome(this._searchResults);
        this._chromeActors = [
            this.topBar.actor, this.sidebar.actor, this.dock.actor,
            this.notificationLayer.actor, this._searchResults,
        ];

        // GNOME's own top bar goes away. panelBox rather than Main.panel, so
        // the work area grows by its height instead of leaving a 32px gap that
        // maximised windows refuse to use.
        Main.layoutManager.panelBox.hide();
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

        track(St.Settings.get(), 'notify::enable-animations', () => this._relayout());
        track(St.Settings.get(), 'notify::font-name', () => this._relayout());

        this._installedChangedId = this.launcher.connectInstalledChanged(() => {
            this.dock.rebuild();
            this.cards.quickAccess.rebuild();
            this._suggestions.rebuild();
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
                this.topBar.focusSearch();
                this.characterState.noteActivity();
            });
            bind('focus-desktop-sidebar', () => this.sidebar.focus());
            bind('focus-desktop-assistant', () => this._activateAssistant());
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
        this.wallpaper.setGeometry({x: 0, y: 0, width: monitor.width, height: monitor.height});

        const rects = solution.rects;
        const place = (actor, rect) => {
            actor.set_position(monitor.x + rect.x, monitor.y + rect.y);
            actor.set_size(rect.width, rect.height);
        };

        place(this.topBar.actor, rects.topBar);
        place(this.sidebar.actor, rects.sidebar);
        place(this.dock.actor, rects.dock);
        this.sidebar.setCollapsed(solution.sidebarMode === 'collapsed');

        this.notificationLayer.setGeometry({
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
            if (key === 'media' && !this.cards.media.hasMedia) {
                // Nothing is playing. Collapse rather than show an empty card.
                card.hide();
                continue;
            }
            card.show(rect, index);
            index += 1;
        }

        this._characterViewport.setGeometry(rects.character);
        this._placeBubbles(rects.character);

        log_(`layout ${screen.width}x${screen.height} → ${solution.breakpoint}, ` +
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
        const rect = this._characterViewport.figureRect();
        const figure = {
            x: rect.x - band.x,
            y: rect.y - band.y,
            width: rect.width,
            height: rect.height,
        };
        this._bubble.place(figure, band, 'left');
        this._bubble.actor.set_position(
            band.x + this._bubble.actor.get_x(), band.y + this._bubble.actor.get_y());

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
        const hour = new Date().getHours();
        const salutation = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
        const events = this.agenda.events().length;
        const agendaLine = events === 0
            ? 'Nothing is scheduled today.'
            : `You have ${events} thing${events === 1 ? '' : 's'} on today.`;
        // Deferred one beat so the entrance animations are the first thing that
        // happens; a bubble that appears in the same frame as the cards reads
        // as a page load rather than as somebody saying hello.
        this._greetTimer = timeout(700, () => {
            this._bubble.say(`${salutation}! ☀\n\n${agendaLine}\n\nShall we get started?`);
            this.characterState.setState('talking', {reason: 'greeting'});
            this._returnToIdleAfterTalking();
        });
    }

    _select(id) {
        this.sidebar.select(id);
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

    /** Click the character, press the shortcut, or choose AI Assistant. */
    _activateAssistant() {
        this.characterState.setState('listening', {reason: 'waiting for your request'});
        this._bubble.say('I am listening. What would you like to do?', {wave: true});
        this._assistantPanel.focusInput();
    }

    _ask(text) {
        const trimmed = text.trim();
        if (trimmed === '')
            return;
        this.characterState.noteActivity();
        this._assistantPanel.addTurn('user', trimmed);
        this._assistantPanel.setBusy(true);
        this._assistantPanel.setStatus('Thinking…');
        this.characterState.setState('thinking', {reason: trimmed});
        this._bubble.say('Let me work on that.', {wave: false});

        this.assistant.ask(trimmed, {
            onPhase: (phase, statusText) => {
                this.characterState.adoptPhase(phase, PHASE_TO_STATE, {statusText});
                if (statusText)
                    this._assistantPanel.setStatus(statusText);
            },
            onReply: (reply, isError) => {
                this._assistantPanel.addTurn('bunny', reply, {tone: isError ? 'error' : 'normal'});
                this._bubble.say(reply, {tone: isError ? 'error' : 'normal', wave: !isError});
                if (!isError) {
                    this.characterState.setState('talking', {reason: 'delivering the answer'});
                    this._returnToIdleAfterTalking();
                }
            },
            onFinished: phase => {
                this._assistantPanel.setBusy(false);
                this._assistantPanel.setStatus('');
                if (phase === 'success')
                    this.characterState.setState('success', {reason: 'the task finished'});
            },
            onError: reason => {
                this._assistantPanel.setBusy(false);
                this._assistantPanel.setStatus(reason, {tone: 'error'});
                this._assistantPanel.addTurn('bunny', reason, {tone: 'error'});
                this.characterState.setState('error', {reason});
                this._bubble.say(reason, {tone: 'error'});
                this.notifications.error(`Bunny could not answer: ${reason}`);
            },
        });
    }

    /**
     * Hand the microphone to the companion's speech service.
     *
     * Not implemented as a capture stream here; see the note in
     * assistant/panel.js. `bunny-command --listen` is the surface that owns
     * consent and the confirmation step.
     */
    _startVoice() {
        this.characterState.setState('listening', {reason: 'speech input requested'});
        this._bubble.say('Listening…', {wave: true});
        if (!this.launcher.spawn(['bunny-command', '--listen'])) {
            this.characterState.setState('warning', {reason: 'speech input is unavailable'});
            this.notifications.warning('Speech input is not available on this system.');
        }
    }

    _returnToIdleAfterTalking() {
        this._talkTimer?.stop();
        this._talkTimer = timeout(TALKING_DWELL_MS, () => {
            this._talkTimer = null;
            if (this.characterState.state === 'talking')
                this.characterState.setState('idle', {reason: 'finished speaking'});
        });
    }

    _onCharacterState(state) {
        // The bubble is dismissed when the character goes quiet, so a stale
        // answer does not hang beside an idle figure for the rest of the day.
        if (state === 'idle' || state === 'sleeping')
            this._bubble.hide();
        this._suggestions.actor.opacity = state === 'idle' ? 255 : 190;
    }

    _onHousekeeping() {
        // Media presence decides whether the card has a slot at all, so a
        // player starting or stopping is a layout change, not a refresh.
        const wanted = this.cards.media.hasMedia;
        if (wanted !== this.cards.media.live)
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
            if (this.topBar.searchText.trim() === text.trim())
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
                iconName: 'text-x-generic-symbolic',
                activate: () => this.launcher.spawn(['gio', 'open', file.path]),
            });
        }
        const query = this.topBar.searchText.trim();
        if (query !== '') {
            rows.push({
                kind: 'assistant',
                title: `Ask Bunny: ${query}`,
                subtitle: 'Send this to your assistant',
                iconName: 'bunny-shell-symbolic',
                activate: () => {
                    this._closeSearch();
                    this.topBar.clearSearch();
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
            icon.icon_name = row.iconName ?? 'application-x-executable-symbolic';
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
        this._powerMenu = new PowerMenu(this.power, {onClose: () => this._closePowerMenu()});
        Main.layoutManager.addChrome(this._powerMenu.actor, {
            affectsStruts: false, affectsInputRegion: true, trackFullscreen: true,
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

    destroy() {
        this._destroyed = true;

        this._housekeeping?.stop();
        this._greetTimer?.stop();
        this._talkTimer?.stop();

        for (const key of this._keybindings ?? [])
            Main.wm.removeKeybinding(key);
        this._keybindings = [];

        this._closePowerMenu();

        for (const [object, id] of this._signals) {
            try {
                object.disconnect(id);
            } catch (error) {
                logError_('a session signal could not be disconnected', error);
            }
        }
        this._signals = [];
        this.launcher.disconnect(this._installedChangedId);
        this._characterUnsubscribe?.();

        for (const actor of this._chromeActors ?? []) {
            try {
                Main.layoutManager.removeChrome(actor);
            } catch (_error) {
                // Already removed with its component.
            }
        }

        this.topBar.destroy();
        this.sidebar.destroy();
        this.dock.destroy();
        this.notificationLayer.destroy();
        this.notifications.detach();
        this._searchResults.destroy();

        for (const card of Object.values(this.cards))
            card.destroy();
        this._bubble.destroy();
        this._suggestions.destroy();
        this._characterViewport.destroy();
        this.wallpaper.destroy();
        this._desktopLayer.destroy();

        this.characterState.destroy();
        this.assistant.destroy();
        this.search.destroy();
        this.agenda.destroy();
        this.media.destroy();
        this.audio.destroy();
        this.brightness.destroy();
        this.network.destroy();

        // Give GNOME its panel back. An extension that left the session without
        // a top bar after being disabled would be unrecoverable without a
        // terminal, which is the exact failure this desktop exists to avoid.
        Main.layoutManager.panelBox.show();
    }
}
