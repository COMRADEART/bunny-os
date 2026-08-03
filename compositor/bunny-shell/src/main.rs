//! Bunny OS experimental native Wayland shell.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT
//! NOT RELEASE QUALIFIED
//! DO NOT USE AS THE DEFAULT SESSION

// The policy modules (focus, security, workspace, xwayland, accessibility)
// deliberately expose a complete API surface that the unit tests exercise and
// the event loop uses only part of. Keeping the unused half compiled and tested
// is the point: it is the specification of the boundary, and V4 consumes it.
#![allow(dead_code)]

mod accessibility;
mod compositor;
mod config;
mod diagnostics;
mod focus;
mod input;
mod output;
mod rendering;
mod security;
mod session;
mod window;
mod workspace;
mod xwayland;

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;

use smithay::{
    backend::{
        input::{InputEvent, KeyboardKeyEvent},
        renderer::{
            damage::OutputDamageTracker,
            utils::draw_render_elements,
            Color32F, Frame, Renderer,
        },
        winit::{self, WinitEvent},
    },
    input::keyboard::FilterResult,
    output::{Mode as OutputMode, Output, PhysicalProperties, Scale, Subpixel},
    reexports::wayland_server::{Display, ListeningSocket},
    utils::{Rectangle, Transform},
};

use crate::compositor::{BunnyShell, ClientState};
use crate::config::{Config, VisualMode, NOTICE};
use crate::diagnostics::{Evidence, Fact, RendererKind};

fn print_notice() {
    for line in NOTICE {
        eprintln!("{line}");
    }
}

struct Arguments {
    self_check: bool,
    diagnostics: bool,
    frames: Option<u64>,
    diagnostics_path: Option<PathBuf>,
    socket: Option<String>,
    spawn: Vec<String>,
}

fn parse_arguments() -> Arguments {
    let mut arguments = Arguments {
        self_check: false,
        diagnostics: false,
        frames: None,
        diagnostics_path: None,
        socket: None,
        spawn: Vec::new(),
    };
    let mut raw = std::env::args().skip(1);
    while let Some(argument) = raw.next() {
        match argument.as_str() {
            "--self-check" => arguments.self_check = true,
            "--diagnostics" => arguments.diagnostics = true,
            "--frames" => {
                arguments.frames = raw.next().and_then(|value| value.parse().ok());
            }
            "--diagnostics-output" => {
                arguments.diagnostics_path = raw.next().map(PathBuf::from);
            }
            "--socket" => {
                arguments.socket = raw.next();
            }
            "--spawn" => {
                if let Some(value) = raw.next() {
                    arguments.spawn.push(value);
                }
            }
            _ => {}
        }
    }
    arguments
}

fn environment() -> HashMap<String, String> {
    std::env::vars().collect()
}

/// Start-up gate. Runs before anything is initialised.
fn authorise_or_exit(environment: &HashMap<String, String>) {
    let gnome_selectable = config::gnome_is_selectable(&config::default_session_search_paths());
    if let Err(refusal) = Config::authorise(environment, gnome_selectable) {
        eprintln!("bunny-shell: {}", refusal.message());
        std::process::exit(2);
    }
}

/// Report what the shell can verify about itself without a display.
fn self_check(environment: &HashMap<String, String>) -> i32 {
    let gnome_selectable = config::gnome_is_selectable(&config::default_session_search_paths());
    let config = Config::from_environment(environment);
    let authorised = Config::authorise(environment, gnome_selectable);

    println!("bunny-shell {} self-check", env!("CARGO_PKG_VERSION"));
    for line in NOTICE {
        println!("{line}");
    }
    println!();
    println!("experimental-mode-required : yes");
    println!(
        "start-authorised           : {}",
        match &authorised {
            Ok(()) => "yes".to_string(),
            Err(refusal) => format!("no ({})", refusal.message()),
        }
    );
    println!("gnome-selectable           : {gnome_selectable}");
    println!("visual-mode                : {}", config.mode.as_str());
    println!("reduced-motion             : {}", config.reduced_motion);
    println!("xwayland-requested         : {}", config.enable_xwayland);
    println!(
        "xwayland-state             : {}",
        xwayland::resolve(config.enable_xwayland, xwayland::binary_present()).as_str()
    );
    println!("workspaces                 : {}", config.workspace_count);
    println!("key-bindings               : {}", input::default_bindings().len());
    println!(
        "accessibility-parity-claim : {}",
        if accessibility::parity_claimable() {
            "claimable"
        } else {
            "not claimable (unmeasured capabilities remain)"
        }
    );
    println!("compositor-prohibitions    : {}", security::COMPOSITOR_PROHIBITIONS.len());
    0
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    if let Ok(filter) = tracing_subscriber::EnvFilter::try_from_default_env() {
        tracing_subscriber::fmt().with_env_filter(filter).init();
    } else {
        tracing_subscriber::fmt().init();
    }

    print_notice();
    let arguments = parse_arguments();
    let environment = environment();

    if arguments.self_check {
        std::process::exit(self_check(&environment));
    }

    authorise_or_exit(&environment);

    let mut config = Config::from_environment(&environment);
    config.run_for_frames = arguments.frames;
    config.socket_name = arguments.socket.clone();
    config.diagnostics_path = arguments.diagnostics_path.clone();

    run(config, arguments)
}

fn run(config: Config, arguments: Arguments) -> Result<(), Box<dyn std::error::Error>> {
    let startup = Instant::now();

    let mut display: Display<BunnyShell> = Display::new()?;
    let handle = display.handle();
    let mut state = BunnyShell::new(&handle, config.clone());

    state.xwayland_state = xwayland::resolve(config.enable_xwayland, xwayland::binary_present());

    // The nested backend. A developer run must never take over the developer's
    // own session, so the winit backend opens a window inside it.
    let (mut backend, winit_event_loop) = winit::init::<smithay::backend::renderer::gles::GlesRenderer>()?;
    let mut winit_event_loop = winit_event_loop;

    let size = backend.window_size();
    let output = Output::new(
        "bunny-nested-0".to_string(),
        PhysicalProperties {
            size: (0, 0).into(),
            subpixel: Subpixel::Unknown,
            make: "Bunny OS".into(),
            model: "Experimental Shell".into(),
        },
    );
    let _output_global = output.create_global::<BunnyShell>(&handle);
    let mode = OutputMode {
        size,
        refresh: 60_000,
    };
    output.change_current_state(
        Some(mode),
        Some(Transform::Normal),
        Some(Scale::Fractional(config.scale)),
        Some((0, 0).into()),
    );
    output.set_preferred(mode);

    state.outputs.add(
        crate::output::OutputConfig::new("bunny-nested-0", size.w, size.h).with_scale(config.scale),
    );
    state.lock.set_outputs(state.outputs.names());

    let socket_name = match &config.socket_name {
        Some(name) => {
            let socket = ListeningSocket::bind(name.as_str())?;
            let name = name.clone();
            (socket, name)
        }
        None => {
            let socket = ListeningSocket::bind_auto("bunny-shell", 1..32)?;
            let name = socket
                .socket_name()
                .map(|value| value.to_string_lossy().to_string())
                .unwrap_or_else(|| "unknown".to_string());
            (socket, name)
        }
    };
    let (listener, socket_display_name) = socket_name;

    eprintln!("bunny-shell: listening on WAYLAND_DISPLAY={socket_display_name}");
    std::env::set_var("WAYLAND_DISPLAY", &socket_display_name);

    state.diagnostics.renderer = rendering::renderer_fact(RendererKind::Gles);
    state.diagnostics.xwayland = Fact::new(
        "xwayland",
        state.xwayland_state.as_str(),
        Evidence::Observed,
    );
    state.diagnostics.displays.push(Fact::new(
        "bunny-nested-0",
        format!("{}x{} @ scale {}", size.w, size.h, config.scale),
        Evidence::Observed,
    ));
    for protocol in [
        "wl_compositor",
        "wl_shm",
        "wl_seat",
        "wl_output",
        "xdg_wm_base",
        "xdg_activation_v1",
        "zxdg_decoration_manager_v1",
        "zxdg_output_manager_v1",
        "wp_presentation",
        "wp_viewporter",
        "wp_fractional_scale_manager_v1",
        "zwp_relative_pointer_manager_v1",
        "zwp_text_input_manager_v3",
        "zwp_idle_inhibit_manager_v1",
        "zwlr_layer_shell_v1",
        "ext_session_lock_manager_v1",
        "wl_data_device_manager",
        "zwp_primary_selection_device_manager_v1",
    ] {
        state
            .diagnostics
            .protocols
            .push(Fact::new(protocol, "advertised", Evidence::Observed));
    }

    let keyboard = state.seat.add_keyboard(Default::default(), 200, 25)?;
    let _pointer = state.seat.add_pointer();

    let mut clients = Vec::new();
    let start_time = Instant::now();
    let mut frames: u64 = 0;
    let mut first_frame_reported = false;
    let bindings = input::default_bindings();
    let _ = &bindings;

    // Spawn any requested clients once the socket exists.
    for entry in &arguments.spawn {
        match std::process::Command::new(entry)
            .env("WAYLAND_DISPLAY", &socket_display_name)
            .spawn()
        {
            Ok(_) => eprintln!("bunny-shell: spawned {entry}"),
            Err(error) => eprintln!("bunny-shell: could not spawn {entry}: {error}"),
        }
    }

    let mut damage_tracker = OutputDamageTracker::from_output(&output);
    let _ = &mut damage_tracker;

    loop {
        let frame_started = Instant::now();

        let status = winit_event_loop.dispatch_new_events(|event| match event {
            WinitEvent::Resized { size, .. } => {
                state.outputs.add(
                    crate::output::OutputConfig::new("bunny-nested-0", size.w, size.h)
                        .with_scale(config.scale),
                );
            }
            WinitEvent::Input(event) => {
                if let InputEvent::Keyboard { event } = event {
                    keyboard.input::<(), _>(
                        &mut state,
                        event.key_code(),
                        event.state(),
                        0.into(),
                        0,
                        |_, _, _| FilterResult::Forward,
                    );
                }
            }
            WinitEvent::CloseRequested => {
                state.running = false;
            }
            _ => {}
        });

        if let smithay::reexports::winit::platform::pump_events::PumpStatus::Exit(_) = status {
            break;
        }
        if !state.running {
            break;
        }

        let size = backend.window_size();
        let damage = Rectangle::from_size(size);
        {
            let (renderer, mut framebuffer) = backend.bind()?;
            let elements = rendering::collect_elements(&state, renderer, 1.0);
            let mut frame = renderer.render(&mut framebuffer, size, Transform::Flipped180)?;
            // Bunny desktop background. Regular Mode and Character Mode share
            // it; the mode never changes window management or the backdrop.
            let background = match state.visual_mode() {
                VisualMode::Regular => Color32F::new(0.06, 0.07, 0.10, 1.0),
                VisualMode::Character => Color32F::new(0.07, 0.06, 0.11, 1.0),
            };
            frame.clear(background, &[damage])?;
            draw_render_elements(&mut frame, 1.0, &elements, &[damage])?;
            let _sync = frame.finish()?;

            for (toplevel, _) in &state.toplevels {
                send_frames(toplevel.wl_surface(), start_time.elapsed().as_millis() as u32);
            }
            for mapped in &state.layer_surfaces {
                send_frames(mapped.surface.wl_surface(), start_time.elapsed().as_millis() as u32);
            }
            for (surface, _) in &state.lock_surfaces {
                send_frames(surface.wl_surface(), start_time.elapsed().as_millis() as u32);
            }

            if let Some(stream) = listener.accept()? {
                let client = display
                    .handle()
                    .insert_client(stream, Arc::new(ClientState::default()))?;
                clients.push(client);
            }

            display.dispatch_clients(&mut state)?;
            display.flush_clients()?;
        }

        backend.submit(Some(&[damage]))?;

        frames += 1;
        let elapsed_ms = frame_started.elapsed().as_secs_f64() * 1000.0;
        state.diagnostics.frame_timing.record(elapsed_ms, 16.67);

        if !first_frame_reported {
            first_frame_reported = true;
            eprintln!(
                "bunny-shell: first frame at {:.1} ms after start",
                startup.elapsed().as_secs_f64() * 1000.0
            );
        }

        if let Some(limit) = config.run_for_frames {
            if frames >= limit {
                break;
            }
        }
    }

    state.diagnostics.measure_memory();
    state.diagnostics.components.push(Fact::new(
        "startup",
        format!("{:.1} ms", startup.elapsed().as_secs_f64() * 1000.0),
        Evidence::Observed,
    ));
    state.diagnostics.known_limitations = vec![
        "Nested winit backend: no DRM/KMS output, no libinput seat.".to_string(),
        "No screencopy protocol: smithay 0.7 does not implement it.".to_string(),
        "Shell chrome is drawn by GTK layer-shell clients, not by the compositor.".to_string(),
    ];

    let report = state.diagnostics.to_json();
    if let Some(path) = &config.diagnostics_path {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }
        std::fs::write(path, &report)?;
        eprintln!("bunny-shell: diagnostics written to {}", path.display());
    }
    if arguments.diagnostics {
        println!("{report}");
    }

    Ok(())
}

fn send_frames(surface: &smithay::reexports::wayland_server::protocol::wl_surface::WlSurface, time: u32) {
    use smithay::wayland::compositor::{with_surface_tree_downward, SurfaceAttributes, TraversalAction};
    with_surface_tree_downward(
        surface,
        (),
        |_, _, &()| TraversalAction::DoChildren(()),
        |_, states, &()| {
            for callback in states
                .cached_state
                .get::<SurfaceAttributes>()
                .current()
                .frame_callbacks
                .drain(..)
            {
                callback.done(time);
            }
        },
        |_, _, &()| true,
    );
}
