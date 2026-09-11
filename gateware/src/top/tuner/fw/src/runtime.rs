//! Small, copyable runtime state shared by the tuner operating modes.
//!
//! Keep this separate from the retained menu/UI object. Calibration profiles,
//! scale tables, and renderer state must not become part of the foreground
//! loop's stack frame just because the menu grows.

use crate::options::{DisplayMode, Opts};

pub const TUNER_CHANNELS: usize = 4;

#[derive(Clone, Copy, PartialEq, Default)]
pub enum OperatingMode {
    #[default]
    Tuner,
    Calibrator,
    Verify,
    Profiles,
    Quantizer,
    Play,
}

/// The small subset of menu state consumed by the real-time foreground loop.
#[derive(Clone, Copy)]
pub struct RuntimeControls {
    pub mode: OperatingMode,
    pub tuner_input: u8,
    pub display_mode: DisplayMode,
    pub reference_hz: u16,
    pub calibration_input: u8,
    pub calibration_output: u8,
    pub target_millicents: i32,
    pub verify_scan: bool,
    pub verify_points: bool,
    pub zero_note: u8,
}

impl RuntimeControls {
    pub fn from_options(opts: &Opts) -> Self {
        Self {
            verify_scan: opts.verify.mode.value!=crate::options::VerifyMode::Manual,
            verify_points: opts.verify.mode.value==crate::options::VerifyMode::Points,
            zero_note: opts.calibrate.zero_note.value.clamp(12,108),
            mode: if opts.tracker.page.value == crate::options::Page::Calibrate {
                OperatingMode::Calibrator
            } else if opts.tracker.page.value == crate::options::Page::Verify {
                OperatingMode::Verify
            } else if opts.tracker.page.value == crate::options::Page::Profiles {
                OperatingMode::Profiles
            } else if opts.tracker.page.value == crate::options::Page::Play {
                OperatingMode::Play
            } else { OperatingMode::Tuner },
            target_millicents: opts.verify.note.value as i32 * 100000
                + opts.verify.cents.value as i32 * 1000,
            calibration_input: opts.calibrate.input.value,
            calibration_output: opts.calibrate.output.value,
            tuner_input: opts.tuner.input.value,
            display_mode: opts.tuner.display.value,
            reference_hz: opts.settings.reference.value,
        }
    }
}

#[derive(Clone, Copy, Default)]
pub struct ChannelMeasurement {
    pub frequency_hz: f32,
    pub vrms: f32,
    pub vpp: f32,
    pub valid: bool,
    pub sequence: u16,
    pub window_age_ms: u32,
    pub end_age_ms: u32,
    pub qualified: bool,
}

/// Retained measurements for every physical input.
///
/// Four independent gateware lanes populate this bank each UI iteration.
/// Keeping it retained avoids growing `main()` locals as instrument views grow.
#[derive(Clone, Copy, Default)]
pub struct MeasurementBank {
    channels: [ChannelMeasurement; TUNER_CHANNELS],
}

impl MeasurementBank {
    pub fn update(&mut self, channel: u8, measurement: ChannelMeasurement) {
        if let Some(slot) = self.channels.get_mut(channel as usize) {
            *slot = measurement;
        }
    }

    pub fn channel(&self, channel: u8) -> ChannelMeasurement {
        self.channels
            .get(channel as usize)
            .copied()
            .unwrap_or_default()
    }

    pub fn all(&self) -> &[ChannelMeasurement; TUNER_CHANNELS] {
        &self.channels
    }
}
