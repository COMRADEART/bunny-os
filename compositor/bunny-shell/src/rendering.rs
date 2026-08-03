//! Frame composition.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.

use smithay::backend::renderer::{
    element::{
        surface::{render_elements_from_surface_tree, WaylandSurfaceRenderElement},
        Kind,
    },
    gles::GlesRenderer,
};
use smithay::wayland::shell::wlr_layer::Layer;

use crate::compositor::BunnyShell;
use crate::diagnostics::{Evidence, Fact, RendererKind};

/// The stacking order the shell composes in, topmost first.
///
/// Render element lists are front to back, so the first element drawn is the
/// one nearest the user.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StackingSlot {
    LockScreen,
    OverlayLayer,
    TopLayer,
    Windows,
    BottomLayer,
    BackgroundLayer,
}

pub const STACKING_ORDER: [StackingSlot; 6] = [
    StackingSlot::LockScreen,
    StackingSlot::OverlayLayer,
    StackingSlot::TopLayer,
    StackingSlot::Windows,
    StackingSlot::BottomLayer,
    StackingSlot::BackgroundLayer,
];

/// Build the render element list for one frame.
///
/// While the session is locked this returns *only* lock surfaces. That is the
/// mechanism behind "a shell crash must not expose the unlocked desktop": the
/// desktop is not merely covered, it is not composed at all.
pub fn collect_elements(
    state: &BunnyShell,
    renderer: &mut GlesRenderer,
    scale: f64,
) -> Vec<WaylandSurfaceRenderElement<GlesRenderer>> {
    let mut elements = Vec::new();

    if !state.lock.state().desktop_visible() {
        for (surface, _output) in &state.lock_surfaces {
            elements.extend(render_elements_from_surface_tree(
                renderer,
                surface.wl_surface(),
                (0, 0),
                scale,
                1.0,
                Kind::Unspecified,
            ));
        }
        return elements;
    }

    for slot in STACKING_ORDER {
        match slot {
            StackingSlot::LockScreen => {}
            StackingSlot::OverlayLayer => {
                push_layer(state, renderer, scale, Layer::Overlay, &mut elements)
            }
            StackingSlot::TopLayer => push_layer(state, renderer, scale, Layer::Top, &mut elements),
            StackingSlot::Windows => {
                // Focused window first so it composes above its siblings.
                let focused = match state.focus.focused() {
                    Some(crate::focus::FocusTarget::Window(id)) => Some(id),
                    _ => None,
                };
                let mut ordered: Vec<_> = state.visible_windows();
                ordered.sort_by_key(|window| if Some(window.id) == focused { 0 } else { 1 });
                for window in ordered {
                    if let Some((toplevel, _)) = state
                        .toplevels
                        .iter()
                        .find(|(_, id)| *id == window.id)
                    {
                        elements.extend(render_elements_from_surface_tree(
                            renderer,
                            toplevel.wl_surface(),
                            (window.geometry.x, window.geometry.y),
                            scale,
                            1.0,
                            Kind::Unspecified,
                        ));
                    }
                }
            }
            StackingSlot::BottomLayer => {
                push_layer(state, renderer, scale, Layer::Bottom, &mut elements)
            }
            StackingSlot::BackgroundLayer => {
                push_layer(state, renderer, scale, Layer::Background, &mut elements)
            }
        }
    }

    elements
}

fn push_layer(
    state: &BunnyShell,
    renderer: &mut GlesRenderer,
    scale: f64,
    layer: Layer,
    elements: &mut Vec<WaylandSurfaceRenderElement<GlesRenderer>>,
) {
    for mapped in state.layer_surfaces.iter().filter(|mapped| mapped.layer == layer) {
        elements.extend(render_elements_from_surface_tree(
            renderer,
            mapped.surface.wl_surface(),
            (mapped.geometry.x, mapped.geometry.y),
            scale,
            1.0,
            Kind::Unspecified,
        ));
    }
}

/// Record which renderer was actually used.
pub fn renderer_fact(kind: RendererKind) -> Fact {
    Fact::new("renderer", kind.as_str(), Evidence::Observed).with_note(if kind.hardware_accelerated() {
        "Hardware path selected by the backend."
    } else {
        "Software fallback: no accelerated renderer was available."
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_lock_screen_is_the_topmost_slot() {
        assert_eq!(STACKING_ORDER[0], StackingSlot::LockScreen);
    }

    #[test]
    fn the_background_layer_is_the_bottom_slot() {
        assert_eq!(STACKING_ORDER[STACKING_ORDER.len() - 1], StackingSlot::BackgroundLayer);
    }

    #[test]
    fn windows_compose_between_the_top_and_bottom_layers() {
        let windows = STACKING_ORDER
            .iter()
            .position(|slot| *slot == StackingSlot::Windows)
            .unwrap();
        let top = STACKING_ORDER
            .iter()
            .position(|slot| *slot == StackingSlot::TopLayer)
            .unwrap();
        let bottom = STACKING_ORDER
            .iter()
            .position(|slot| *slot == StackingSlot::BottomLayer)
            .unwrap();
        assert!(top < windows);
        assert!(windows < bottom);
    }

    #[test]
    fn the_software_renderer_is_reported_as_a_fallback() {
        let fact = renderer_fact(RendererKind::Pixman);
        assert_eq!(fact.value, "pixman-software");
        assert!(fact.note.unwrap().contains("Software fallback"));
    }
}
