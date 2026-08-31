//! Small, copyable runtime state shared by the tuner operating modes.
//!
//! Keep this separate from the retained menu/UI object. Calibration profiles,
//! scale tables, and renderer state must not become part of the foreground
//! loop's stack frame just because the menu grows.

use crate::options::{DisplayMode, Opts, ReferenceTone};

pub const TUNER_CHANNELS: usize = 4;

#[derive(Clone, Copy, PartialEq, Default)]
pub enum OperatingMode {
    #[default]
    Tuner,
    Calibrator,
    Quantizer,
}

/// The small subset of menu state consumed by the real-time foreground loop.
#[derive(Clone, Copy)]
pub struct RuntimeControls {
    pub mode: OperatingMode,
    pub tuner_input: u8,
    pub display_mode: DisplayMode,
    pub reference_mode: ReferenceTone,
    pub reference_hz: u16,
}

impl RuntimeControls {
    pub fn from_options(opts: &Opts) -> Self {
        Self {
            mode: OperatingMode::Tuner,
            tuner_input: opts.tuner.input.value,
            display_mode: opts.tuner.display.value,
            reference_mode: opts.tuner.reference_tone.value,
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
}

/// Retained measurements for every physical input.
///
/// The current gateware publishes only the selected channel. Keeping the bank
/// here makes that limitation explicit and gives the future four-lane detector
/// and renderer a stable interface without growing `main()` locals again.
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
