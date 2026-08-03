//! Outputs, scaling and hotplug.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.

use crate::window::Rect;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputTransform {
    Normal,
    Rotated90,
    Rotated180,
    Rotated270,
}

impl OutputTransform {
    /// Portrait orientations swap the logical width and height.
    pub fn swaps_dimensions(self) -> bool {
        matches!(self, OutputTransform::Rotated90 | OutputTransform::Rotated270)
    }
}

#[derive(Debug, Clone)]
pub struct OutputConfig {
    pub name: String,
    pub physical_width: i32,
    pub physical_height: i32,
    pub refresh_millihertz: i32,
    /// Fractional scale. 1.0, 1.25, 1.5, 2.0 are the common values.
    pub scale: f64,
    pub transform: OutputTransform,
    /// Position of this output's logical origin in the global space.
    pub position: (i32, i32),
}

impl OutputConfig {
    pub fn new(name: impl Into<String>, width: i32, height: i32) -> Self {
        Self {
            name: name.into(),
            physical_width: width,
            physical_height: height,
            refresh_millihertz: 60_000,
            scale: 1.0,
            transform: OutputTransform::Normal,
            position: (0, 0),
        }
    }

    pub fn with_scale(mut self, scale: f64) -> Self {
        if scale > 0.0 {
            self.scale = scale;
        }
        self
    }

    pub fn with_transform(mut self, transform: OutputTransform) -> Self {
        self.transform = transform;
        self
    }

    pub fn with_position(mut self, x: i32, y: i32) -> Self {
        self.position = (x, y);
        self
    }

    pub fn refresh_hz(&self) -> f64 {
        self.refresh_millihertz as f64 / 1000.0
    }

    /// The size in logical (scaled) coordinates, accounting for rotation.
    ///
    /// Rounded up, because a logical size that rounds down leaves a strip of
    /// the display that no surface covers — which is exactly how a lock screen
    /// ends up with an uncovered edge.
    pub fn logical_size(&self) -> (i32, i32) {
        let (width, height) = if self.transform.swaps_dimensions() {
            (self.physical_height, self.physical_width)
        } else {
            (self.physical_width, self.physical_height)
        };
        let scaled_width = (width as f64 / self.scale).ceil() as i32;
        let scaled_height = (height as f64 / self.scale).ceil() as i32;
        (scaled_width.max(1), scaled_height.max(1))
    }

    pub fn logical_geometry(&self) -> Rect {
        let (width, height) = self.logical_size();
        Rect::new(self.position.0, self.position.1, width, height)
    }
}

/// The set of outputs currently active.
#[derive(Debug, Default, Clone)]
pub struct OutputLayout {
    outputs: Vec<OutputConfig>,
}

impl OutputLayout {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add(&mut self, output: OutputConfig) {
        self.remove(&output.name);
        self.outputs.push(output);
    }

    pub fn remove(&mut self, name: &str) -> bool {
        let before = self.outputs.len();
        self.outputs.retain(|output| output.name != name);
        before != self.outputs.len()
    }

    pub fn outputs(&self) -> &[OutputConfig] {
        &self.outputs
    }

    pub fn len(&self) -> usize {
        self.outputs.len()
    }

    pub fn is_empty(&self) -> bool {
        self.outputs.is_empty()
    }

    pub fn get(&self, name: &str) -> Option<&OutputConfig> {
        self.outputs.iter().find(|output| output.name == name)
    }

    /// The output that carries the top bar and the dock.
    ///
    /// The primary output is the first one added, which for a laptop plus an
    /// external display is the built-in panel. This is a stated policy, not an
    /// accident: the shell chrome stays where the user's hands are.
    pub fn primary(&self) -> Option<&OutputConfig> {
        self.outputs.first()
    }

    /// Every output name that must be covered by a lock surface.
    pub fn names(&self) -> Vec<String> {
        self.outputs.iter().map(|output| output.name.clone()).collect()
    }

    /// Whether any two outputs use different scales, which is the case the
    /// fractional-scale protocol exists to handle.
    pub fn has_mixed_scaling(&self) -> bool {
        let mut scales = self.outputs.iter().map(|output| output.scale);
        match scales.next() {
            None => false,
            Some(first) => scales.any(|scale| (scale - first).abs() > f64::EPSILON),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_4k_display_at_200_percent_is_1920_by_1080_logically() {
        let output = OutputConfig::new("DP-1", 3840, 2160).with_scale(2.0);
        assert_eq!(output.logical_size(), (1920, 1080));
    }

    #[test]
    fn fractional_scaling_rounds_up_so_no_strip_is_left_uncovered() {
        // 1920 / 1.5 is exactly 1280, but 1921 / 1.5 is 1280.67 and must not
        // round down to 1280.
        let output = OutputConfig::new("DP-1", 1921, 1080).with_scale(1.5);
        let (width, _) = output.logical_size();
        assert_eq!(width, 1281);
    }

    #[test]
    fn a_portrait_display_swaps_its_logical_dimensions() {
        let output = OutputConfig::new("DP-2", 1920, 1080).with_transform(OutputTransform::Rotated90);
        assert_eq!(output.logical_size(), (1080, 1920));
    }

    #[test]
    fn hotplug_add_and_remove_change_the_layout() {
        let mut layout = OutputLayout::new();
        layout.add(OutputConfig::new("eDP-1", 1920, 1080));
        layout.add(OutputConfig::new("DP-1", 3840, 2160).with_scale(2.0));
        assert_eq!(layout.len(), 2);
        assert!(layout.remove("DP-1"));
        assert_eq!(layout.len(), 1);
        assert!(!layout.remove("DP-1"));
    }

    #[test]
    fn re_adding_an_output_replaces_rather_than_duplicates() {
        let mut layout = OutputLayout::new();
        layout.add(OutputConfig::new("eDP-1", 1920, 1080));
        layout.add(OutputConfig::new("eDP-1", 2560, 1440));
        assert_eq!(layout.len(), 1);
        assert_eq!(layout.get("eDP-1").unwrap().physical_width, 2560);
    }

    #[test]
    fn the_primary_output_is_the_first_one_added() {
        let mut layout = OutputLayout::new();
        layout.add(OutputConfig::new("eDP-1", 1920, 1080));
        layout.add(OutputConfig::new("DP-1", 3840, 2160));
        assert_eq!(layout.primary().unwrap().name, "eDP-1");
    }

    #[test]
    fn mixed_scaling_is_detected() {
        let mut layout = OutputLayout::new();
        layout.add(OutputConfig::new("eDP-1", 1920, 1080).with_scale(1.0));
        assert!(!layout.has_mixed_scaling());
        layout.add(OutputConfig::new("DP-1", 3840, 2160).with_scale(2.0));
        assert!(layout.has_mixed_scaling());
    }
}
