//! Diagnostics.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.
//!
//! Every diagnostic value carries how it was known. A prototype that presents a
//! guess with the same confidence as a measurement is worse than one that
//! reports nothing, because it launders hypotheses into the report that decides
//! the next phase.

use serde::Serialize;

/// How a diagnostic value was established.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Evidence {
    /// Measured directly in this run.
    Observed,
    /// Derived from something observed, but not itself measured.
    Inferred,
    /// Could not be determined in this environment.
    Unavailable,
    /// Deliberately not implemented.
    Unsupported,
}

impl Evidence {
    pub fn as_str(self) -> &'static str {
        match self {
            Evidence::Observed => "observed",
            Evidence::Inferred => "inferred",
            Evidence::Unavailable => "unavailable",
            Evidence::Unsupported => "unsupported",
        }
    }

    /// Whether a value with this evidence level may be stated as fact.
    pub fn is_fact(self) -> bool {
        matches!(self, Evidence::Observed)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Fact {
    pub name: String,
    pub value: String,
    pub evidence: Evidence,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub note: Option<String>,
}

impl Fact {
    pub fn new(name: impl Into<String>, value: impl Into<String>, evidence: Evidence) -> Self {
        Self {
            name: name.into(),
            value: value.into(),
            evidence,
            note: None,
        }
    }

    pub fn with_note(mut self, note: impl Into<String>) -> Self {
        self.note = Some(note.into());
        self
    }
}

/// Which renderer the compositor actually used.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum RendererKind {
    Gles,
    Vulkan,
    Pixman,
}

impl RendererKind {
    pub fn as_str(self) -> &'static str {
        match self {
            RendererKind::Gles => "opengl-es",
            RendererKind::Vulkan => "vulkan",
            RendererKind::Pixman => "pixman-software",
        }
    }

    pub fn hardware_accelerated(self) -> bool {
        !matches!(self, RendererKind::Pixman)
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct FrameTiming {
    pub frames: u64,
    pub dropped: u64,
    pub mean_frame_milliseconds: f64,
    pub worst_frame_milliseconds: f64,
}

impl FrameTiming {
    pub fn new() -> Self {
        Self {
            frames: 0,
            dropped: 0,
            mean_frame_milliseconds: 0.0,
            worst_frame_milliseconds: 0.0,
        }
    }

    pub fn record(&mut self, milliseconds: f64, target_milliseconds: f64) {
        self.frames += 1;
        if milliseconds > target_milliseconds {
            self.dropped += 1;
        }
        if milliseconds > self.worst_frame_milliseconds {
            self.worst_frame_milliseconds = milliseconds;
        }
        // Running mean; avoids keeping every sample for a long session.
        let n = self.frames as f64;
        self.mean_frame_milliseconds += (milliseconds - self.mean_frame_milliseconds) / n;
    }
}

impl Default for FrameTiming {
    fn default() -> Self {
        Self::new()
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct DiagnosticsSnapshot {
    pub notice: Vec<String>,
    pub compositor_version: String,
    pub framework: String,
    pub renderer: Fact,
    pub gpu: Fact,
    pub displays: Vec<Fact>,
    pub protocols: Vec<Fact>,
    pub xwayland: Fact,
    pub portals: Fact,
    pub pipewire: Fact,
    pub input_devices: Vec<Fact>,
    pub frame_timing: FrameTiming,
    pub memory: Fact,
    pub components: Vec<Fact>,
    pub recent_crashes: Vec<Fact>,
    pub known_limitations: Vec<String>,
}

impl DiagnosticsSnapshot {
    pub fn new() -> Self {
        Self {
            notice: crate::config::NOTICE.iter().map(|s| s.to_string()).collect(),
            compositor_version: env!("CARGO_PKG_VERSION").to_string(),
            framework: "smithay 0.7".to_string(),
            renderer: Fact::new("renderer", "unknown", Evidence::Unavailable),
            gpu: Fact::new("gpu", "unknown", Evidence::Unavailable),
            displays: Vec::new(),
            protocols: Vec::new(),
            xwayland: Fact::new("xwayland", "disabled", Evidence::Observed),
            portals: Fact::new("portals", "not queried", Evidence::Unavailable),
            pipewire: Fact::new("pipewire", "not queried", Evidence::Unavailable),
            input_devices: Vec::new(),
            frame_timing: FrameTiming::new(),
            memory: Fact::new("resident-memory", "unknown", Evidence::Unavailable),
            components: Vec::new(),
            recent_crashes: Vec::new(),
            known_limitations: Vec::new(),
        }
    }

    /// Read resident set size from /proc/self/statm.
    ///
    /// Observed when the file is readable; unavailable otherwise. Never
    /// estimated.
    pub fn measure_memory(&mut self) {
        match std::fs::read_to_string("/proc/self/statm") {
            Ok(contents) => {
                let resident_pages: u64 = contents
                    .split_whitespace()
                    .nth(1)
                    .and_then(|value| value.parse().ok())
                    .unwrap_or(0);
                let page_size = 4096u64;
                let bytes = resident_pages * page_size;
                self.memory = Fact::new(
                    "resident-memory",
                    format!("{:.1} MB", bytes as f64 / (1024.0 * 1024.0)),
                    Evidence::Observed,
                );
            }
            Err(error) => {
                self.memory = Fact::new("resident-memory", "unreadable", Evidence::Unavailable)
                    .with_note(error.to_string());
            }
        }
    }

    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).unwrap_or_else(|_| "{}".to_string())
    }
}

impl Default for DiagnosticsSnapshot {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_observed_values_are_facts() {
        assert!(Evidence::Observed.is_fact());
        assert!(!Evidence::Inferred.is_fact());
        assert!(!Evidence::Unavailable.is_fact());
        assert!(!Evidence::Unsupported.is_fact());
    }

    #[test]
    fn software_rendering_is_not_reported_as_accelerated() {
        assert!(!RendererKind::Pixman.hardware_accelerated());
        assert!(RendererKind::Gles.hardware_accelerated());
    }

    #[test]
    fn frame_timing_counts_frames_over_target_as_dropped() {
        let mut timing = FrameTiming::new();
        timing.record(10.0, 16.67);
        timing.record(30.0, 16.67);
        assert_eq!(timing.frames, 2);
        assert_eq!(timing.dropped, 1);
        assert!((timing.worst_frame_milliseconds - 30.0).abs() < f64::EPSILON);
        assert!((timing.mean_frame_milliseconds - 20.0).abs() < 1e-9);
    }

    #[test]
    fn a_new_snapshot_claims_nothing_it_has_not_measured() {
        let snapshot = DiagnosticsSnapshot::new();
        assert_eq!(snapshot.renderer.evidence, Evidence::Unavailable);
        assert_eq!(snapshot.gpu.evidence, Evidence::Unavailable);
        assert_eq!(snapshot.portals.evidence, Evidence::Unavailable);
        assert!(snapshot.notice.contains(&"NOT RELEASE QUALIFIED".to_string()));
    }

    #[test]
    fn the_snapshot_serialises_with_its_evidence_levels() {
        let mut snapshot = DiagnosticsSnapshot::new();
        snapshot.renderer = Fact::new("renderer", "opengl-es", Evidence::Observed);
        let json = snapshot.to_json();
        assert!(json.contains("\"observed\""));
        assert!(json.contains("BUNNY WAYLAND SHELL EXPERIMENT"));
    }
}
