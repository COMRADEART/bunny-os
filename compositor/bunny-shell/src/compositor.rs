//! Compositor state and Wayland protocol handlers.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.

use std::os::unix::io::OwnedFd;

use smithay::{
    delegate_compositor, delegate_data_device, delegate_fractional_scale, delegate_idle_inhibit,
    delegate_layer_shell, delegate_output, delegate_presentation, delegate_primary_selection,
    delegate_relative_pointer, delegate_seat, delegate_session_lock, delegate_shm,
    delegate_text_input_manager, delegate_viewporter, delegate_xdg_activation,
    delegate_xdg_decoration, delegate_xdg_shell,
    input::{pointer::CursorImageStatus, Seat, SeatHandler, SeatState},
    reexports::{
        wayland_protocols::xdg::shell::server::xdg_toplevel,
        wayland_server::{
            protocol::{wl_buffer, wl_output::WlOutput, wl_seat, wl_surface::WlSurface},
            Client, DisplayHandle,
        },
    },
    utils::Serial,
    wayland::{
        buffer::BufferHandler,
        compositor::{CompositorClientState, CompositorHandler, CompositorState},
        fractional_scale::{FractionalScaleHandler, FractionalScaleManagerState},
        idle_inhibit::{IdleInhibitHandler, IdleInhibitManagerState},
        output::{OutputHandler, OutputManagerState},
        presentation::PresentationState,
        relative_pointer::RelativePointerManagerState,
        selection::{
            data_device::{
                ClientDndGrabHandler, DataDeviceHandler, DataDeviceState, ServerDndGrabHandler,
            },
            primary_selection::{PrimarySelectionHandler, PrimarySelectionState},
            SelectionHandler,
        },
        session_lock::{
            LockSurface, SessionLockHandler, SessionLockManagerState, SessionLocker,
        },
        shell::{
            wlr_layer::{
                Layer, LayerSurface, WlrLayerShellHandler, WlrLayerShellState,
            },
            xdg::{
                decoration::{XdgDecorationHandler, XdgDecorationState},
                PopupSurface, PositionerState, ToplevelSurface, XdgShellHandler, XdgShellState,
            },
        },
        shm::{ShmHandler, ShmState},
        text_input::TextInputManagerState,
        viewporter::ViewporterState,
        xdg_activation::{
            XdgActivationHandler, XdgActivationState, XdgActivationToken, XdgActivationTokenData,
        },
    },
};

use crate::{
    accessibility::AccessibilityState,
    config::{Config, VisualMode},
    diagnostics::DiagnosticsSnapshot,
    focus::{FocusCause, FocusPolicy, FocusTarget, ShellSurface},
    output::OutputLayout,
    security::ApplicationRegistry,
    session::SessionLock,
    window::{ManagedWindow, Rect, WindowOrigin},
    workspace::Workspaces,
    xwayland::XWaylandState,
};

/// Per-client state the compositor keeps.
#[derive(Default)]
pub struct ClientState {
    pub compositor_state: CompositorClientState,
}

impl smithay::reexports::wayland_server::backend::ClientData for ClientState {
    fn initialized(&self, _client_id: smithay::reexports::wayland_server::backend::ClientId) {}
    fn disconnected(
        &self,
        _client_id: smithay::reexports::wayland_server::backend::ClientId,
        _reason: smithay::reexports::wayland_server::backend::DisconnectReason,
    ) {
    }
}

/// A shell chrome surface that a layer-shell client has mapped.
pub struct MappedLayerSurface {
    pub surface: LayerSurface,
    pub layer: Layer,
    pub namespace: String,
    pub role: ShellSurface,
    pub geometry: Rect,
}

/// The compositor.
pub struct BunnyShell {
    pub config: Config,
    pub running: bool,

    // Protocol state.
    pub compositor_state: CompositorState,
    pub xdg_shell_state: XdgShellState,
    pub shm_state: ShmState,
    pub seat_state: SeatState<Self>,
    pub data_device_state: DataDeviceState,
    pub primary_selection_state: PrimarySelectionState,
    pub output_manager_state: OutputManagerState,
    pub xdg_decoration_state: XdgDecorationState,
    pub xdg_activation_state: XdgActivationState,
    pub viewporter_state: ViewporterState,
    pub fractional_scale_state: FractionalScaleManagerState,
    pub presentation_state: PresentationState,
    pub relative_pointer_state: RelativePointerManagerState,
    pub layer_shell_state: WlrLayerShellState,
    pub session_lock_state: SessionLockManagerState,
    pub text_input_state: TextInputManagerState,
    pub idle_inhibit_state: IdleInhibitManagerState,

    pub seat: Seat<Self>,

    // Bunny policy state.
    pub windows: Vec<ManagedWindow>,
    pub toplevels: Vec<(ToplevelSurface, u64)>,
    pub layer_surfaces: Vec<MappedLayerSurface>,
    pub lock_surfaces: Vec<(LockSurface, String)>,
    pub workspaces: Workspaces,
    pub focus: FocusPolicy,
    pub lock: SessionLock,
    pub outputs: OutputLayout,
    pub accessibility: AccessibilityState,
    pub registry: ApplicationRegistry,
    pub diagnostics: DiagnosticsSnapshot,
    pub xwayland_state: XWaylandState,
    pub idle_inhibited: bool,

    next_window_id: u64,
}

impl BunnyShell {
    pub fn new(display: &DisplayHandle, config: Config) -> Self {
        let compositor_state = CompositorState::new::<Self>(display);
        let xdg_shell_state = XdgShellState::new::<Self>(display);
        let shm_state = ShmState::new::<Self>(display, vec![]);
        let mut seat_state = SeatState::new();
        let seat = seat_state.new_wl_seat(display, "bunny-seat");
        let workspaces = Workspaces::new(config.workspace_count);
        let accessibility = AccessibilityState {
            reduced_motion: config.reduced_motion,
            high_contrast: config.high_contrast,
            ..Default::default()
        };

        Self {
            running: true,
            compositor_state,
            xdg_shell_state,
            shm_state,
            seat_state,
            data_device_state: DataDeviceState::new::<Self>(display),
            primary_selection_state: PrimarySelectionState::new::<Self>(display),
            output_manager_state: OutputManagerState::new_with_xdg_output::<Self>(display),
            xdg_decoration_state: XdgDecorationState::new::<Self>(display),
            xdg_activation_state: XdgActivationState::new::<Self>(display),
            viewporter_state: ViewporterState::new::<Self>(display),
            fractional_scale_state: FractionalScaleManagerState::new::<Self>(display),
            // 1 is CLOCK_MONOTONIC on Linux, which is the clock the winit and
            // DRM backends both time frames against.
            presentation_state: PresentationState::new::<Self>(display, 1),
            relative_pointer_state: RelativePointerManagerState::new::<Self>(display),
            layer_shell_state: WlrLayerShellState::new::<Self>(display),
            session_lock_state: SessionLockManagerState::new::<Self, _>(display, |_client| true),
            text_input_state: TextInputManagerState::new::<Self>(display),
            idle_inhibit_state: IdleInhibitManagerState::new::<Self>(display),
            seat,
            windows: Vec::new(),
            toplevels: Vec::new(),
            layer_surfaces: Vec::new(),
            lock_surfaces: Vec::new(),
            workspaces,
            focus: FocusPolicy::new(),
            lock: SessionLock::new(),
            outputs: OutputLayout::new(),
            accessibility,
            registry: ApplicationRegistry::new(),
            diagnostics: DiagnosticsSnapshot::new(),
            xwayland_state: XWaylandState::Disabled,
            idle_inhibited: false,
            next_window_id: 1,
            config,
        }
    }

    fn allocate_window_id(&mut self) -> u64 {
        let id = self.next_window_id;
        self.next_window_id += 1;
        id
    }

    pub fn visual_mode(&self) -> VisualMode {
        self.config.mode
    }

    /// The area windows may occupy, after the top bar and dock have taken their
    /// exclusive zones.
    pub fn work_area(&self) -> Rect {
        let full = self
            .outputs
            .primary()
            .map(|output| output.logical_geometry())
            .unwrap_or(Rect::new(0, 0, 1920, 1080));
        let mut top = 0;
        let mut bottom = 0;
        for mapped in &self.layer_surfaces {
            match mapped.role {
                ShellSurface::TopBar => top = top.max(mapped.geometry.height),
                ShellSurface::Dock => bottom = bottom.max(mapped.geometry.height),
                _ => {}
            }
        }
        Rect::new(
            full.x,
            full.y + top,
            full.width,
            (full.height - top - bottom).max(1),
        )
    }

    pub fn window_by_id(&self, id: u64) -> Option<&ManagedWindow> {
        self.windows.iter().find(|window| window.id == id)
    }

    pub fn window_by_id_mut(&mut self, id: u64) -> Option<&mut ManagedWindow> {
        self.windows.iter_mut().find(|window| window.id == id)
    }

    pub fn window_id_for_surface(&self, surface: &WlSurface) -> Option<u64> {
        self.toplevels
            .iter()
            .find(|(toplevel, _)| toplevel.wl_surface() == surface)
            .map(|(_, id)| *id)
    }

    /// Windows on the active workspace, back to front.
    pub fn visible_windows(&self) -> Vec<&ManagedWindow> {
        self.windows
            .iter()
            .filter(|window| self.workspaces.is_visible(window))
            .collect()
    }

    /// Ask to focus a window because the user did something.
    pub fn focus_window(&mut self, id: u64) -> bool {
        let visible = self
            .window_by_id(id)
            .map(|window| self.workspaces.is_visible(window))
            .unwrap_or(false);
        let modal_child = self
            .windows
            .iter()
            .find(|window| window.modal_parent == Some(id))
            .map(|window| window.id);
        self.focus
            .request(FocusTarget::Window(id), FocusCause::UserAction, modal_child, visible)
            .is_ok()
    }

    /// Focus the next window on the active workspace.
    pub fn focus_next(&mut self) -> Option<u64> {
        let ids: Vec<u64> = self.visible_windows().iter().map(|window| window.id).collect();
        if ids.is_empty() {
            return None;
        }
        let current = match self.focus.focused() {
            Some(FocusTarget::Window(id)) => ids.iter().position(|candidate| *candidate == id),
            _ => None,
        };
        let next = match current {
            Some(index) => ids[(index + 1) % ids.len()],
            None => ids[0],
        };
        if self.focus_window(next) {
            Some(next)
        } else {
            None
        }
    }

    /// Refresh a window's application identity from its xdg-toplevel state.
    ///
    /// Application identification is what the dock's running-application
    /// indicators and the command palette's window results depend on, so it is
    /// read from the protocol rather than guessed from the process.
    pub fn refresh_window_identification(&mut self, surface: &WlSurface) {
        use smithay::wayland::compositor::with_states;
        use smithay::wayland::shell::xdg::XdgToplevelSurfaceData;

        let Some(id) = self.window_id_for_surface(surface) else {
            return;
        };
        let identity = with_states(surface, |states| {
            states
                .data_map
                .get::<XdgToplevelSurfaceData>()
                .and_then(|data| data.lock().ok().map(|data| (data.app_id.clone(), data.title.clone())))
        });
        let Some((app_id, title)) = identity else {
            return;
        };
        let mut changed = false;
        if let Some(window) = self.window_by_id_mut(id) {
            if let Some(app_id) = app_id {
                if window.app_id != app_id {
                    window.app_id = app_id;
                    changed = true;
                }
            }
            if let Some(title) = title {
                if window.title != title {
                    window.title = title;
                    changed = true;
                }
            }
        }
        if changed {
            if let Some(window) = self.window_by_id(id) {
                let line = format!(
                    "window {id} identified: app_id={} title={} origin={}",
                    window.app_id,
                    window.display_name(),
                    window.origin.as_str()
                );
                eprintln!("bunny-shell: {}", crate::security::redact(&line));
                let entry = crate::diagnostics::Fact::new(
                    format!("window-{id}"),
                    format!("{} ({})", window.app_id, window.origin.as_str()),
                    crate::diagnostics::Evidence::Observed,
                );
                self.diagnostics.components.push(entry);
            }
        }
    }

    /// Classify a layer-shell namespace into a Bunny shell role.
    ///
    /// An unrecognised namespace is treated as a plain layer surface with no
    /// special privileges — a third-party panel cannot claim to be the Bunny
    /// top bar and inherit its exclusive zone.
    pub fn classify_namespace(namespace: &str) -> Option<ShellSurface> {
        match namespace {
            "bunny-top-bar" => Some(ShellSurface::TopBar),
            "bunny-dock" => Some(ShellSurface::Dock),
            "bunny-launcher" => Some(ShellSurface::Launcher),
            "bunny-command-palette" => Some(ShellSurface::CommandPalette),
            "bunny-quick-settings" => Some(ShellSurface::QuickSettings),
            "bunny-notification-center" => Some(ShellSurface::NotificationCenter),
            "bunny-notification" => Some(ShellSurface::NotificationBanner),
            "bunny-assistant" => Some(ShellSurface::AssistantPanel),
            "bunny-approval" => Some(ShellSurface::ApprovalPanel),
            "bunny-overview" => Some(ShellSurface::Overview),
            "bunny-character" => Some(ShellSurface::CharacterLayer),
            _ => None,
        }
    }
}

// --- Core protocols -------------------------------------------------------

impl CompositorHandler for BunnyShell {
    fn compositor_state(&mut self) -> &mut CompositorState {
        &mut self.compositor_state
    }

    fn client_compositor_state<'a>(&self, client: &'a Client) -> &'a CompositorClientState {
        &client.get_data::<ClientState>().unwrap().compositor_state
    }

    fn commit(&mut self, surface: &WlSurface) {
        use smithay::backend::renderer::utils::on_commit_buffer_handler;
        on_commit_buffer_handler::<Self>(surface);
        self.refresh_window_identification(surface);
    }
}

impl BufferHandler for BunnyShell {
    fn buffer_destroyed(&mut self, _buffer: &wl_buffer::WlBuffer) {}
}

impl ShmHandler for BunnyShell {
    fn shm_state(&self) -> &ShmState {
        &self.shm_state
    }
}

impl SeatHandler for BunnyShell {
    type KeyboardFocus = WlSurface;
    type PointerFocus = WlSurface;
    type TouchFocus = WlSurface;

    fn seat_state(&mut self) -> &mut SeatState<Self> {
        &mut self.seat_state
    }

    fn focus_changed(&mut self, _seat: &Seat<Self>, _focused: Option<&WlSurface>) {}

    fn cursor_image(&mut self, _seat: &Seat<Self>, _image: CursorImageStatus) {}
}

impl OutputHandler for BunnyShell {}

// --- Shell ----------------------------------------------------------------

impl XdgShellHandler for BunnyShell {
    fn xdg_shell_state(&mut self) -> &mut XdgShellState {
        &mut self.xdg_shell_state
    }

    fn new_toplevel(&mut self, surface: ToplevelSurface) {
        let id = self.allocate_window_id();
        let area = self.work_area();
        // Open at a readable default size inside the work area rather than at
        // the origin, so a new window is never hidden behind the top bar.
        let width = (area.width as f64 * 0.6) as i32;
        let height = (area.height as f64 * 0.6) as i32;
        let geometry = Rect::new(
            area.x + (area.width - width) / 2,
            area.y + (area.height - height) / 2,
            width.max(320),
            height.max(240),
        );
        let mut window = ManagedWindow::new(id, String::new(), geometry, WindowOrigin::Wayland);
        window.workspace = self.workspaces.active();

        surface.with_pending_state(|state| {
            state.states.set(xdg_toplevel::State::Activated);
            state.size = Some((geometry.width, geometry.height).into());
        });
        surface.send_configure();

        self.toplevels.push((surface, id));
        self.windows.push(window);
        // A newly opened window is the result of a user action (launching or a
        // click), so it may take focus.
        self.focus_window(id);
    }

    fn toplevel_destroyed(&mut self, surface: ToplevelSurface) {
        if let Some(position) = self.toplevels.iter().position(|(candidate, _)| candidate == &surface) {
            let (_, id) = self.toplevels.remove(position);
            self.windows.retain(|window| window.id != id);
            if self.focus.focused() == Some(FocusTarget::Window(id)) {
                self.focus_next();
            }
        }
    }

    fn new_popup(&mut self, _surface: PopupSurface, _positioner: PositionerState) {}

    fn grab(&mut self, _surface: PopupSurface, _seat: wl_seat::WlSeat, _serial: Serial) {}

    fn reposition_request(&mut self, _surface: PopupSurface, _positioner: PositionerState, _token: u32) {}
}

impl WlrLayerShellHandler for BunnyShell {
    fn shell_state(&mut self) -> &mut WlrLayerShellState {
        &mut self.layer_shell_state
    }

    fn new_layer_surface(
        &mut self,
        surface: LayerSurface,
        _output: Option<WlOutput>,
        layer: Layer,
        namespace: String,
    ) {
        let full = self
            .outputs
            .primary()
            .map(|output| output.logical_geometry())
            .unwrap_or(Rect::new(0, 0, 1920, 1080));
        let role = Self::classify_namespace(&namespace);

        // Size the surface from its role. A client that asked for a size keeps
        // it; otherwise the shell suggests one appropriate to the role.
        let (width, height, x, y) = match role {
            Some(ShellSurface::TopBar) => (full.width, 32, full.x, full.y),
            Some(ShellSurface::Dock) => (full.width, 64, full.x, full.y + full.height - 64),
            Some(ShellSurface::CommandPalette) => {
                let w = full.width.min(720);
                (w, 420, full.x + (full.width - w) / 2, full.y + 96)
            }
            Some(ShellSurface::QuickSettings) => {
                let w = 380;
                (w, 520, full.x + full.width - w - 16, full.y + 40)
            }
            Some(ShellSurface::NotificationCenter) => {
                let w = 420;
                (w, full.height - 80, full.x + full.width - w - 16, full.y + 40)
            }
            Some(ShellSurface::AssistantPanel) => {
                let w = 460;
                (w, full.height - 120, full.x + full.width - w - 16, full.y + 48)
            }
            Some(ShellSurface::ApprovalPanel) => {
                let w = full.width.min(640);
                (w, 520, full.x + (full.width - w) / 2, full.y + 120)
            }
            _ => (full.width.min(480), full.height.min(360), full.x, full.y),
        };

        surface.with_pending_state(|state| {
            state.size = Some((width, height).into());
        });
        surface.send_configure();

        eprintln!(
            "bunny-shell: layer surface mapped: namespace={namespace} layer={layer:?} \
             role={role:?} geometry={width}x{height}+{x}+{y} focusable={}",
            role.map(|surface| surface.focusable()).unwrap_or(true)
        );
        self.diagnostics.components.push(crate::diagnostics::Fact::new(
            format!("layer-surface-{namespace}"),
            format!("{layer:?} {width}x{height}+{x}+{y}"),
            crate::diagnostics::Evidence::Observed,
        ));

        self.layer_surfaces.push(MappedLayerSurface {
            surface,
            layer,
            namespace,
            role: role.unwrap_or(ShellSurface::Overview),
            geometry: Rect::new(x, y, width, height),
        });
    }

    fn layer_destroyed(&mut self, surface: LayerSurface) {
        self.layer_surfaces.retain(|mapped| mapped.surface != surface);
    }
}

impl XdgDecorationHandler for BunnyShell {
    fn new_decoration(&mut self, toplevel: ToplevelSurface) {
        use smithay::reexports::wayland_protocols::xdg::decoration::zv1::server::zxdg_toplevel_decoration_v1::Mode;
        // Bunny draws window frames itself, so client-side decorations are not
        // requested. Applications that insist are still honoured below.
        toplevel.with_pending_state(|state| {
            state.decoration_mode = Some(Mode::ServerSide);
        });
        toplevel.send_configure();
    }

    fn request_mode(&mut self, toplevel: ToplevelSurface, mode: smithay::reexports::wayland_protocols::xdg::decoration::zv1::server::zxdg_toplevel_decoration_v1::Mode) {
        toplevel.with_pending_state(|state| {
            state.decoration_mode = Some(mode);
        });
        toplevel.send_configure();
    }

    fn unset_mode(&mut self, toplevel: ToplevelSurface) {
        use smithay::reexports::wayland_protocols::xdg::decoration::zv1::server::zxdg_toplevel_decoration_v1::Mode;
        toplevel.with_pending_state(|state| {
            state.decoration_mode = Some(Mode::ServerSide);
        });
        toplevel.send_configure();
    }
}

impl XdgActivationHandler for BunnyShell {
    fn activation_state(&mut self) -> &mut XdgActivationState {
        &mut self.xdg_activation_state
    }

    fn request_activation(
        &mut self,
        _token: XdgActivationToken,
        _token_data: XdgActivationTokenData,
        surface: WlSurface,
    ) {
        // Activation is treated as a request for attention, never as a focus
        // grant. The focus policy refuses a SurfaceRequest cause, so the window
        // is marked urgent in the dock instead of stealing the keyboard.
        if let Some(id) = self.window_id_for_surface(&surface) {
            let _ = self
                .focus
                .request(FocusTarget::Window(id), FocusCause::SurfaceRequest, None, true);
        }
    }
}

// --- Selection ------------------------------------------------------------

impl SelectionHandler for BunnyShell {
    type SelectionUserData = ();
}

impl DataDeviceHandler for BunnyShell {
    fn data_device_state(&self) -> &DataDeviceState {
        &self.data_device_state
    }
}

impl ClientDndGrabHandler for BunnyShell {}

impl ServerDndGrabHandler for BunnyShell {
    fn send(&mut self, _mime_type: String, _fd: OwnedFd, _seat: Seat<Self>) {}
}

impl PrimarySelectionHandler for BunnyShell {
    fn primary_selection_state(&self) -> &PrimarySelectionState {
        &self.primary_selection_state
    }
}

// --- Session lock ---------------------------------------------------------

impl SessionLockHandler for BunnyShell {
    fn lock_state(&mut self) -> &mut SessionLockManagerState {
        &mut self.session_lock_state
    }

    fn lock(&mut self, confirmation: SessionLocker) {
        // Lock the policy state first. Desktop content stops being presented
        // from this moment, before any lock surface exists.
        self.lock.set_outputs(self.outputs.names());
        self.lock.lock();
        self.focus.set_locked(true);
        confirmation.lock();
    }

    fn unlock(&mut self) {
        // Reached only when the locking client says authentication succeeded.
        // The compositor never checks a password itself.
        self.lock.unlock(true);
        self.focus.set_locked(false);
        self.lock_surfaces.clear();
    }

    fn new_surface(&mut self, surface: LockSurface, _output: WlOutput) {
        let name = self
            .outputs
            .primary()
            .map(|output| output.name.clone())
            .unwrap_or_else(|| "unknown".to_string());
        let size = self
            .outputs
            .primary()
            .map(|output| output.logical_size())
            .unwrap_or((1920, 1080));
        surface.with_pending_state(|state| {
            // ext-session-lock sizes are unsigned; a negative logical size is
            // not representable and would mean the output metrics are wrong.
            state.size = Some((size.0.max(0) as u32, size.1.max(0) as u32).into());
        });
        surface.send_configure();
        self.lock.surface_attached(name.clone());
        self.lock_surfaces.push((surface, name));
    }
}

// --- Smaller protocols ----------------------------------------------------

impl FractionalScaleHandler for BunnyShell {
    fn new_fractional_scale(&mut self, _surface: WlSurface) {}
}

impl IdleInhibitHandler for BunnyShell {
    fn inhibit(&mut self, _surface: WlSurface) {
        self.idle_inhibited = true;
    }

    fn uninhibit(&mut self, _surface: WlSurface) {
        self.idle_inhibited = false;
    }
}

delegate_compositor!(BunnyShell);
delegate_shm!(BunnyShell);
delegate_seat!(BunnyShell);
delegate_output!(BunnyShell);
delegate_data_device!(BunnyShell);
delegate_primary_selection!(BunnyShell);
delegate_xdg_shell!(BunnyShell);
delegate_layer_shell!(BunnyShell);
delegate_xdg_decoration!(BunnyShell);
delegate_xdg_activation!(BunnyShell);
delegate_viewporter!(BunnyShell);
delegate_fractional_scale!(BunnyShell);
delegate_presentation!(BunnyShell);
delegate_relative_pointer!(BunnyShell);
delegate_session_lock!(BunnyShell);
delegate_text_input_manager!(BunnyShell);
delegate_idle_inhibit!(BunnyShell);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn an_unknown_namespace_does_not_become_bunny_chrome() {
        assert_eq!(BunnyShell::classify_namespace("bunny-top-bar"), Some(ShellSurface::TopBar));
        assert_eq!(BunnyShell::classify_namespace("evil-top-bar"), None);
        assert_eq!(BunnyShell::classify_namespace(""), None);
    }

    #[test]
    fn the_character_layer_has_its_own_namespace() {
        assert_eq!(
            BunnyShell::classify_namespace("bunny-character"),
            Some(ShellSurface::CharacterLayer)
        );
    }
}
