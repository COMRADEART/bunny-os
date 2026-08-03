//! Configuration and start-up gating for the experimental Bunny shell.
//!
//! BUNNY WAYLAND SHELL EXPERIMENT - NOT RELEASE QUALIFIED - DO NOT USE AS THE
//! DEFAULT SESSION.

use std::collections::HashMap;
use std::path::PathBuf;

/// The banner every report, package and running session must display.
pub const NOTICE: [&str; 3] = [
    "BUNNY WAYLAND SHELL EXPERIMENT",
    "NOT RELEASE QUALIFIED",
    "DO NOT USE AS THE DEFAULT SESSION",
];

pub const EXPERIMENTAL_MODE_VARIABLE: &str = "BUNNY_SHELL_EXPERIMENTAL";

/// The two approved visual experiences carried forward from Visual Phase V2.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VisualMode {
    /// No guide character anywhere; the full professional desktop layout.
    Regular,
    /// Exactly one guide character, only inside approved containers.
    Character,
}

impl VisualMode {
    pub fn as_str(self) -> &'static str {
        match self {
            VisualMode::Regular => "regular",
            VisualMode::Character => "character",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "regular" => Some(VisualMode::Regular),
            "character" => Some(VisualMode::Character),
            _ => None,
        }
    }
}

/// Why the shell refused to start. Every variant is a fail-closed outcome.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StartRefusal {
    NotExperimentalMode,
    ConfiguredAsDefaultSession,
    QualificationRunInProgress,
    GnomeFallbackMissing,
}

impl StartRefusal {
    pub fn message(&self) -> String {
        match self {
            StartRefusal::NotExperimentalMode => format!(
                "refusing to start: set {EXPERIMENTAL_MODE_VARIABLE}=1 to run the experimental shell"
            ),
            StartRefusal::ConfiguredAsDefaultSession => {
                "refusing to start: the experimental shell must not be configured as the default session"
                    .to_string()
            }
            StartRefusal::QualificationRunInProgress => {
                "refusing to start: a qualification run is in progress".to_string()
            }
            StartRefusal::GnomeFallbackMissing => {
                "refusing to start: GNOME is not installed as a selectable session; GNOME must remain the supported fallback"
                    .to_string()
            }
        }
    }
}

/// Runtime configuration. Values come from the environment and the command
/// line only; the shell reads no user-writable configuration file in V3, so a
/// compromised file cannot change the security posture.
#[derive(Debug, Clone)]
pub struct Config {
    pub mode: VisualMode,
    pub reduced_motion: bool,
    pub socket_name: Option<String>,
    pub enable_xwayland: bool,
    pub workspace_count: usize,
    pub diagnostics_path: Option<PathBuf>,
    pub run_for_frames: Option<u64>,
    pub high_contrast: bool,
    pub scale: f64,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            mode: VisualMode::Regular,
            reduced_motion: false,
            socket_name: None,
            // XWayland is opt-in. The shell must start without it.
            enable_xwayland: false,
            workspace_count: 4,
            diagnostics_path: None,
            run_for_frames: None,
            high_contrast: false,
            scale: 1.0,
        }
    }
}

impl Config {
    /// Apply the environment. Does not decide whether the shell may start.
    pub fn from_environment(environment: &HashMap<String, String>) -> Self {
        let mut config = Config::default();
        if let Some(mode) = environment.get("BUNNY_SHELL_MODE").and_then(|v| VisualMode::parse(v)) {
            config.mode = mode;
        }
        if environment.get("BUNNY_SHELL_REDUCED_MOTION").map(String::as_str) == Some("1") {
            config.reduced_motion = true;
        }
        if environment.get("BUNNY_SHELL_HIGH_CONTRAST").map(String::as_str) == Some("1") {
            config.high_contrast = true;
        }
        if environment.get("BUNNY_SHELL_XWAYLAND").map(String::as_str) == Some("1") {
            config.enable_xwayland = true;
        }
        if let Some(scale) = environment
            .get("BUNNY_SHELL_SCALE")
            .and_then(|value| value.parse::<f64>().ok())
        {
            if scale > 0.0 {
                config.scale = scale;
            }
        }
        config
    }

    /// Decide whether the shell may start at all.
    ///
    /// `gnome_selectable` is supplied by the caller so the check can be tested
    /// without a session directory on disk.
    pub fn authorise(
        environment: &HashMap<String, String>,
        gnome_selectable: bool,
    ) -> Result<(), StartRefusal> {
        if environment.get(EXPERIMENTAL_MODE_VARIABLE).map(String::as_str) != Some("1") {
            return Err(StartRefusal::NotExperimentalMode);
        }
        if environment.get("BUNNY_SHELL_IS_DEFAULT_SESSION").map(String::as_str) == Some("1") {
            return Err(StartRefusal::ConfiguredAsDefaultSession);
        }
        if environment
            .get("BUNNY_QUALIFICATION_RUN")
            .map(|value| !value.is_empty())
            .unwrap_or(false)
        {
            return Err(StartRefusal::QualificationRunInProgress);
        }
        if !gnome_selectable
            && environment.get("BUNNY_SHELL_ALLOW_MISSING_GNOME").map(String::as_str) != Some("1")
        {
            return Err(StartRefusal::GnomeFallbackMissing);
        }
        Ok(())
    }
}

/// True when GNOME is still offered as a selectable session.
pub fn gnome_is_selectable(search_paths: &[PathBuf]) -> bool {
    const GNOME_SESSIONS: [&str; 3] = ["gnome.desktop", "gnome-wayland.desktop", "gnome-xorg.desktop"];
    search_paths.iter().any(|directory| {
        GNOME_SESSIONS
            .iter()
            .any(|name| directory.join(name).is_file())
    })
}

pub fn default_session_search_paths() -> Vec<PathBuf> {
    vec![
        PathBuf::from("/usr/share/wayland-sessions"),
        PathBuf::from("/usr/share/xsessions"),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), (*v).to_string()))
            .collect()
    }

    #[test]
    fn refuses_without_explicit_experimental_mode() {
        let result = Config::authorise(&env(&[]), true);
        assert_eq!(result, Err(StartRefusal::NotExperimentalMode));
    }

    #[test]
    fn refuses_when_configured_as_the_default_session() {
        let environment = env(&[
            ("BUNNY_SHELL_EXPERIMENTAL", "1"),
            ("BUNNY_SHELL_IS_DEFAULT_SESSION", "1"),
        ]);
        assert_eq!(
            Config::authorise(&environment, true),
            Err(StartRefusal::ConfiguredAsDefaultSession)
        );
    }

    #[test]
    fn refuses_during_a_qualification_run() {
        let environment = env(&[
            ("BUNNY_SHELL_EXPERIMENTAL", "1"),
            ("BUNNY_QUALIFICATION_RUN", "dsq-3"),
        ]);
        assert_eq!(
            Config::authorise(&environment, true),
            Err(StartRefusal::QualificationRunInProgress)
        );
    }

    #[test]
    fn refuses_when_gnome_is_no_longer_selectable() {
        let environment = env(&[("BUNNY_SHELL_EXPERIMENTAL", "1")]);
        assert_eq!(
            Config::authorise(&environment, false),
            Err(StartRefusal::GnomeFallbackMissing)
        );
    }

    #[test]
    fn starts_only_when_every_gate_passes() {
        let environment = env(&[("BUNNY_SHELL_EXPERIMENTAL", "1")]);
        assert_eq!(Config::authorise(&environment, true), Ok(()));
    }

    #[test]
    fn xwayland_is_off_unless_requested() {
        assert!(!Config::default().enable_xwayland);
        let environment = env(&[("BUNNY_SHELL_XWAYLAND", "1")]);
        assert!(Config::from_environment(&environment).enable_xwayland);
    }

    #[test]
    fn default_visual_mode_is_regular() {
        assert_eq!(Config::default().mode, VisualMode::Regular);
    }
}
