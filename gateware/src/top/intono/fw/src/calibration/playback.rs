//! Shared corrected-pitch mapping for calibrator playback and future quantizer.
//! No hardware writes, allocation, retained curve copy or automatic arming.
//! The adapter must own the output and qualify fresh calibrated CV snapshots.
use super::{Error, Profile};

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum MappingError {
    InvalidOrigin,
    InputOverflow,
    Profile(Error),
    OutputOutsideLimits,
}

// Exact rational conversion with symmetric rounding. Normal CV/pitch values
// use native arithmetic; extreme public API inputs retain the wide fallback.
fn rounded_ratio(value: i64, numerator: i32, denominator: i32) -> i64 {
    if let Ok(value) = i32::try_from(value) {
        if let Some(magnitude) = value
            .checked_abs()
            .and_then(|v| v.checked_mul(numerator))
            .and_then(|v| v.checked_add(denominator / 2))
        {
            let result = magnitude / denominator;
            return if value < 0 {
                -(result as i64)
            } else {
                result as i64
            };
        }
    }
    let result = (value.abs() * numerator as i64 + denominator as i64 / 2) / denominator as i64;
    if value < 0 {
        -result
    } else {
        result
    }
}

/// 0 V's musical meaning is independent of the oscillator's physical 0 V pitch.
/// This initial input convention is 1 V/oct, without quantization or clamping.
pub fn pitch_from_cv(microvolts: i32, zero_note: u8) -> Result<i32, MappingError> {
    if !(12..=108).contains(&zero_note) {
        return Err(MappingError::InvalidOrigin);
    }
    // 1,200,000 / 1,000,000 reduces exactly to 6/5.
    let delta = rounded_ratio(microvolts as i64, 6, 5);
    i32::try_from(zero_note as i64 * 100_000 + delta).map_err(|_| MappingError::InputOverflow)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Target {
    pub pitch_millicents: i32,
    pub requested_microvolts: i32,
    pub applied_microvolts: i32,
    pub dac_bits: u16,
}

/// The quantizer will supply its chosen pitch here; continuous playback supplies
/// pitch_from_cv directly. Both use exactly the same variable measured curve.
pub fn map_pitch(profile: &Profile, pitch: i32) -> Result<Target, MappingError> {
    let uv = profile
        .voltage_for_pitch(pitch)
        .map_err(MappingError::Profile)?;
    let bits =
        crate::bipolar::encode_profile_voltage(uv).ok_or(MappingError::OutputOutsideLimits)?;
    Ok(Target {
        pitch_millicents: pitch,
        requested_microvolts: uv,
        applied_microvolts: crate::bipolar::decode_voltage(bits).unwrap(),
        dac_bits: bits,
    })
}

pub fn map_cv(profile: &Profile, microvolts: i32, zero_note: u8) -> Result<Target, MappingError> {
    map_pitch(profile, pitch_from_cv(microvolts, zero_note)?)
}

/// Nominal 1 V/oct output, independent of an oscillator calibration profile.
pub fn map_nominal(pitch: i32, zero_note: u8) -> Result<Target, MappingError> {
    if !(12..=108).contains(&zero_note) {
        return Err(MappingError::InvalidOrigin);
    }
    let delta = pitch as i64 - zero_note as i64 * 100_000;
    let uv = rounded_ratio(delta, 5, 6);
    let uv = i32::try_from(uv).map_err(|_| MappingError::OutputOutsideLimits)?;
    let bits = crate::bipolar::encode_voltage(uv).ok_or(MappingError::OutputOutsideLimits)?;
    Ok(Target {
        pitch_millicents: pitch,
        requested_microvolts: uv,
        applied_microvolts: crate::bipolar::decode_voltage(bits).unwrap(),
        dac_bits: bits,
    })
}

/// Nearest chromatic note, ties upward. Five cents of hysteresis beyond each
/// midpoint prevents ADC noise from retriggering adjacent notes. Euclidean
/// division preserves the same behavior below note zero.
pub fn chromatic_pitch(pitch: i32, previous: Option<i32>) -> i32 {
    if let Some(note) = previous {
        if (pitch as i64 - note as i64).abs() <= 55_000 {
            return note;
        }
    }
    (((pitch as i64 + 50_000).div_euclid(100_000)) * 100_000)
        .clamp(i32::MIN as i64, i32::MAX as i64) as i32
}

/// One output owner, serviced at 1 kHz. No UI/flash operations in tick.
pub trait ProfileStorage {
    fn measured(&self) -> Option<&Profile>;
}
impl ProfileStorage for Profile {
    fn measured(&self) -> Option<&Profile> {
        Some(self)
    }
}
impl ProfileStorage for () {
    fn measured(&self) -> Option<&Profile> {
        None
    }
}
pub type Engine = PlaybackEngine<Profile>;
pub type QuantEngine = PlaybackEngine<()>;
pub struct PlaybackEngine<P: ProfileStorage> {
    profile: Option<P>,
    pub active: bool,
    pub status: &'static str,
    pub input: u8,
    pub output: u8,
    pub zero_note: u8,
    pub input_uv: i32,
    pub output_uv: i32,
    pub pitch: i32,
    sequence: Option<u16>,
    last_sample: u32,
    pending: Option<(u8, u32)>,
    token: u8,
    counts_per_v: i32,
    pub updates: u32,
    pub max_cycles: usize,
    pub last_irq_cycle: usize,
    pub max_gap_cycles: usize,
    pub chromatic: bool,
    pub standalone: bool,
    /// Full scale stage, independent from nominal/corrected voltage mapping.
    pub scale_enabled: bool,
    pub scale_id: u8,
    pub root: u8,
    pub transpose: i8,
    pub equal: bool,
    pub pattern: crate::scale::Pattern,
    quantized_pitch: Option<i32>,
    last_command: Option<u32>,
    target_since: u32,
}
impl<P: ProfileStorage> PlaybackEngine<P> {
    pub const fn new() -> Self {
        Self {
            profile: None,
            active: false,
            status: "STOPPED - RUN TO START",
            input: 0,
            output: 0,
            zero_note: 60,
            input_uv: 0,
            output_uv: 0,
            pitch: 0,
            sequence: None,
            last_sample: 0,
            pending: None,
            token: 0,
            counts_per_v: 4000,
            updates: 0,
            max_cycles: 0,
            last_irq_cycle: 0,
            max_gap_cycles: 0,
            chromatic: false,
            standalone: false,
            scale_enabled: false,
            scale_id: 0,
            root: 0,
            transpose: 0,
            equal: false,
            pattern: crate::scale::Pattern::empty(),
            quantized_pitch: None,
            last_command: None,
            target_since: 0,
        }
    }
    pub fn arm(
        &mut self,
        profile: &Profile,
        input: u8,
        output: u8,
        zero: u8,
        counts: i32,
        now: u32,
        status: u32,
    ) -> bool
    where
        P: From<Profile>,
    {
        if self.active
            || status & 768 != 0
            || input > 3
            || output > 3
            || counts <= 0
            || profile.points().len() < 2
            || !(12..=108).contains(&zero)
        {
            self.status = "CANNOT ARM - CHECK PROFILE";
            return false;
        }
        self.profile = Some(profile.clone().into());
        self.standalone = false;
        self.scale_enabled = false;
        self.start(input, output, zero, counts, now)
    }
    pub fn arm_nominal(
        &mut self,
        input: u8,
        output: u8,
        zero: u8,
        counts: i32,
        now: u32,
        status: u32,
    ) -> bool {
        if self.active
            || status & 768 != 0
            || input > 3
            || output > 3
            || counts <= 0
            || !(12..=108).contains(&zero)
        {
            self.status = "CANNOT ARM - CHECK ROUTE";
            return false;
        }
        self.profile = None;
        self.standalone = true;
        self.chromatic = true;
        self.scale_enabled = true;
        self.scale_id = 0;
        self.root = 0;
        self.transpose = 0;
        self.equal = false;
        self.start(input, output, zero, counts, now)
    }
    fn start(&mut self, input: u8, output: u8, zero: u8, counts: i32, now: u32) -> bool {
        self.input = input;
        self.output = output;
        self.zero_note = zero;
        self.counts_per_v = counts;
        self.sequence = None;
        self.last_sample = now;
        self.pending = None;
        self.quantized_pitch = None;
        self.last_command = None;
        self.target_since = now;
        self.output_uv = 0;
        self.active = true;
        self.status = "WAITING FOR CV";
        self.updates = 0;
        self.max_cycles = 0;
        self.last_irq_cycle = 0;
        self.max_gap_cycles = 0;
        true
    }
    /// Immutable per-output curve; binding is never allowed while running.
    pub fn bind_profile(&mut self, profile: &Profile) -> bool
    where
        P: From<Profile>,
    {
        if self.active || profile.points().len() < 2 {
            return false;
        }
        self.profile = Some(profile.clone().into());
        true
    }
    pub fn profile_name(&self) -> Option<&str> {
        self.profile
            .as_ref()
            .and_then(ProfileStorage::measured)
            .map(Profile::name)
    }
    pub fn arm_route(
        &mut self,
        input: u8,
        output: u8,
        zero: u8,
        counts: i32,
        now: u32,
        status: u32,
        corrected: bool,
        quantize: bool,
    ) -> bool {
        if self.active
            || status & 768 != 0
            || input > 3
            || output > 3
            || counts <= 0
            || !(12..=108).contains(&zero)
            || (corrected
                && self
                    .profile
                    .as_ref()
                    .and_then(ProfileStorage::measured)
                    .is_none())
        {
            self.status = "CANNOT ARM - CHECK ROUTE / CURVE";
            return false;
        }
        self.standalone = !corrected;
        self.scale_enabled = quantize;
        self.chromatic = quantize;
        self.start(input, output, zero, counts, now)
    }
    pub fn stop(&mut self, reason: &'static str) -> u32 {
        self.active = false;
        self.pending = None;
        self.quantized_pitch = None;
        self.last_command = None;
        self.output_uv = 0;
        self.status = reason;
        0
    }
    /// Whole measurement window must follow the output change and settling.
    /// Include output acknowledgment and foreground publication latency margin.
    pub fn feedback_ready(&self, now: u32, window_age: u32, end_age: u32) -> bool {
        self.active
            && self.last_command.is_some()
            && end_age <= 100
            && now.wrapping_sub(self.target_since) as u64 >= 450 + window_age as u64
    }
    pub fn tick(&mut self, now: u32, packed: u32, status: u32, allowed: bool) -> Option<u32> {
        if !self.active {
            return None;
        }
        if !allowed {
            return Some(self.stop("STOPPED - CONTROLS CHANGED"));
        }
        if status & 512 != 0 {
            return Some(self.stop("STOPPED - OUTPUT FAULT"));
        }
        if let Some((token, at)) = self.pending {
            if status & 511 == (token as u32 | 256) {
                self.pending = None;
            } else if now.wrapping_sub(at) >= 3 {
                return Some(self.stop("STOPPED - OUTPUT NO ACK"));
            } else {
                return None;
            }
        }
        let sequence = ((packed >> 16) & 0x7fff) as u16;
        if packed >> 31 == 0 || self.sequence == Some(sequence) {
            if now.wrapping_sub(self.last_sample) >= 10 {
                return Some(self.stop("STOPPED - CV STALE"));
            }
            return None;
        }
        self.sequence = Some(sequence);
        self.last_sample = now;
        let counts = packed as u16 as i16 as i32;
        if counts.abs() >= 32760 {
            return Some(self.stop("STOPPED - INPUT AT RAIL"));
        }
        // The hardware's nominal CV snapshot scale is exactly 4000 counts/V.
        // Avoid a software 64-bit divide on that normal path; retain the general
        // conversion for other supported scales, with the same overflow guard.
        let uv = if self.counts_per_v == 4000 {
            Ok(counts * 250)
        } else {
            i32::try_from(counts as i64 * 1_000_000 / self.counts_per_v as i64)
        };
        let Ok(uv) = uv else {
            return Some(self.stop("STOPPED - INPUT CONVERSION"));
        };
        self.input_uv = uv;
        let Ok(mut pitch) = pitch_from_cv(self.input_uv, self.zero_note) else {
            return Some(self.stop("STOPPED - INPUT CONVERSION"));
        };
        if self.scale_enabled {
            let scale = if self.scale_id == 6 {
                self.pattern.scale()
            } else {
                crate::scale::preset(self.scale_id)
            };
            let Some(scale) = scale else {
                return Some(self.stop("STOPPED - INVALID SCALE"));
            };
            if self.root > 11 || !(-12..=12).contains(&self.transpose) {
                return Some(self.stop("STOPPED - INVALID SCALE"));
            }
            let root = (self.zero_note as i32 / 12 * 12 + self.root as i32) * 100_000;
            let shift = self.transpose as i32 * 100_000;
            let previous = self.quantized_pitch.and_then(|p| p.checked_sub(shift));
            let target = if self.equal {
                scale.distribute(pitch, root, previous)
            } else {
                scale.quantize(pitch, root, previous)
            };
            let Ok(target) = target else {
                return Some(self.stop("STOPPED - SCALE OVERFLOW"));
            };
            let Some(target) = target.checked_add(shift) else {
                return Some(self.stop("STOPPED - SCALE OVERFLOW"));
            };
            pitch = target;
        } else if self.chromatic {
            pitch = chromatic_pitch(pitch, self.quantized_pitch);
        }
        // A held quantized note already has a validated DAC mapping. Reuse it,
        // but continue all freshness, ACK, watchdog and command-token handling.
        // start/stop clear last_command; live control changes are rejected above.
        let mapping = if self.chromatic && self.last_command.is_some() && pitch == self.pitch {
            Ok(Target {
                pitch_millicents: pitch,
                requested_microvolts: self.output_uv,
                applied_microvolts: self.output_uv,
                dac_bits: self.last_command.unwrap() as u16,
            })
        } else if self.standalone {
            map_nominal(pitch, self.zero_note)
        } else {
            match self.profile.as_ref().and_then(ProfileStorage::measured) {
                Some(profile) => map_pitch(profile, pitch),
                None => return Some(self.stop("STOPPED - NO PROFILE")),
            }
        };
        let target = match mapping {
            Ok(target) => target,
            Err(MappingError::Profile(Error::PitchOutsideRange)) => {
                self.quantized_pitch = None;
                self.status = if self.last_command.is_some() {
                    "HOLDING - PITCH OUT OF RANGE"
                } else {
                    "WAITING FOR IN-RANGE PITCH"
                };
                // Renew the last acknowledged command's hardware watchdog.
                // Before any valid target there is nothing to hold: stay off.
                return Some(self.last_command.unwrap_or(0));
            }
            Err(MappingError::OutputOutsideLimits) if self.standalone => {
                self.quantized_pitch = None;
                self.status = if self.last_command.is_some() {
                    "HOLDING - OUTPUT OUT OF RANGE"
                } else {
                    "WAITING FOR IN-RANGE PITCH"
                };
                return Some(self.last_command.unwrap_or(0));
            }
            Err(_) => return Some(self.stop("STOPPED - INVALID MAPPING")),
        };
        if self.last_command.is_none()
            || target.applied_microvolts != self.output_uv
            || target.pitch_millicents != self.pitch
        {
            self.target_since = now;
        }
        if self.chromatic {
            self.quantized_pitch = Some(pitch);
        }
        self.output_uv = target.applied_microvolts;
        self.pitch = target.pitch_millicents;
        self.token = self.token.wrapping_add(1);
        self.pending = Some((self.token, now));
        self.updates = self.updates.wrapping_add(1);
        self.status = match (self.standalone, self.scale_enabled) {
            (true, true) => "QUANTIZING - NOMINAL CV",
            (true, false) => "PLAYING - NOMINAL CV",
            (false, true) => "QUANTIZING - CORRECTED CV",
            (false, false) => "PLAYING - CORRECTED CV",
        };
        let command = target.dac_bits as u32
            | ((self.output as u32) << 16)
            | (1 << 18)
            | ((self.input as u32) << 19)
            | ((self.token as u32) << 21)
            | (1 << 29);
        self.last_command = Some(command);
        Some(command)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    #[test]
    fn route_stages_are_independent_and_curve_is_a_snapshot() {
        for quantize in [false, true] {
            for corrected in [false, true] {
                let mut profile = curve();
                let mut e = Engine::new();
                assert!(e.bind_profile(&profile));
                assert!(e.arm_route(0, 3, 60, 4000, 0, 0, corrected, quantize));
                e.scale_id = 1; // C major: C# becomes D, before correction.
                assert!(!e.bind_profile(&profile));
                let command = e.tick(1, sample(1, 334), 0, true).unwrap();
                let pitch = if quantize {
                    6_200_000
                } else {
                    pitch_from_cv(83500, 60).unwrap()
                };
                assert_eq!(e.pitch, pitch);
                assert_eq!(
                    command as u16,
                    if corrected {
                        map_pitch(&profile, pitch).unwrap().dac_bits
                    } else {
                        map_nominal(pitch, 60).unwrap().dac_bits
                    }
                );
                profile.rename("changed externally").unwrap();
                assert_eq!(e.profile_name(), Some("variable"));
            }
        }
        let mut e = Engine::new();
        assert!(!e.arm_route(0, 0, 60, 4000, 0, 0, true, true));
        assert!(!e.active);
    }
    #[test]
    fn four_corrected_routes_share_cv_but_not_curves_or_state() {
        let mut lanes: [Engine; 4] = core::array::from_fn(|_| Engine::new());
        let mut commands = [0; 4];
        for (n, e) in lanes.iter_mut().enumerate() {
            let mut p = Profile::new("own curve", -5_000_000, 5_000_000).unwrap();
            for step in -24..=24 {
                p.push(Point {
                    microvolts: step * 50000 + n as i32 * 1000,
                    millicents: 6_000_000 + step * 100000,
                })
                .unwrap();
            }
            assert!(e.bind_profile(&p));
            assert!(e.arm_route(1, n as u8, 60, 4000, 0, 0, true, true));
            commands[n] = e.tick(1, sample(1, 0), 0, true).unwrap();
            assert_eq!(e.output_uv, n as i32 * 1000);
        }
        for (n, e) in lanes.iter_mut().enumerate() {
            e.tick(
                3,
                sample(2, 0),
                if n == 0 { 512 } else { ack(commands[n]) },
                true,
            );
            assert_eq!(e.active, n != 0);
        }
        // One immutable curve per output; no duplicate calibration state.
        assert!(core::mem::size_of::<[Engine; 4]>() < 5200);
    }
    #[test]
    fn four_lightweight_lanes_keep_history_and_faults_independent() {
        assert!(core::mem::size_of::<QuantEngine>() < 384);
        assert!(core::mem::size_of::<Engine>() > core::mem::size_of::<QuantEngine>() + 900);
        let mut lanes: [QuantEngine; 4] = core::array::from_fn(|_| QuantEngine::new());
        let mut commands = [0; 4];
        for (n, lane) in lanes.iter_mut().enumerate() {
            assert!(lane.arm_nominal(n as u8, n as u8, 60, 4000, 0, 0));
            lane.transpose = n as i8;
            commands[n] = lane.tick(1, sample(1, 0), 0, true).unwrap();
            assert_eq!(lane.pitch, 6_000_000 + n as i32 * 100_000);
        }
        for (n, lane) in lanes.iter_mut().enumerate() {
            lane.tick(
                3,
                sample(2, 0),
                if n == 1 { 512 } else { ack(commands[n]) },
                true,
            );
            assert_eq!(lane.active, n != 1);
        }
    }
    #[test]
    fn repeated_note_still_checks_ack_freshness_and_controls() {
        let mut e = Engine::new();
        assert!(e.arm_nominal(1, 1, 60, 4000, 0, 0));
        let first = e.tick(1, sample(1, 0), 0, true).unwrap();
        let second = e.tick(2, sample(2, 1), ack(first), true).unwrap();
        assert_eq!(first as u16, second as u16);
        assert_ne!(first, second); // watchdog commands still carry fresh tokens
        assert_eq!(e.updates, 2);
        assert_eq!(e.tick(5, sample(3, 1), ack(first), true), Some(0));
        assert_eq!(e.status, "STOPPED - OUTPUT NO ACK");
        assert!(e.arm_nominal(1, 1, 60, 4000, 6, 0));
        let command = e.tick(7, sample(4, 0), 0, true).unwrap();
        assert_eq!(e.tick(17, sample(4, 0), ack(command), true), Some(0));
        assert_eq!(e.status, "STOPPED - CV STALE");
        assert!(e.arm_nominal(1, 1, 60, 4000, 18, 0));
        let command = e.tick(19, sample(5, 0), 0, true).unwrap();
        assert_eq!(e.tick(20, sample(6, 0), ack(command), false), Some(0));
        assert_eq!(e.status, "STOPPED - CONTROLS CHANGED");
    }
    #[test]
    fn native_conversions_match_original_wide_arithmetic() {
        for zero in 12u8..=108 {
            for counts in i16::MIN..=i16::MAX {
                let uv = counts as i32 * 250;
                let scaled = uv as i64 * 1_200_000;
                let delta = if scaled >= 0 {
                    (scaled + 500_000) / 1_000_000
                } else {
                    -((-scaled + 500_000) / 1_000_000)
                };
                assert_eq!(
                    pitch_from_cv(uv, zero),
                    Ok((zero as i64 * 100_000 + delta) as i32)
                );
            }
        }
        for value in (-100_000i64..=100_000).chain([
            i32::MIN as i64 - 10_800_000,
            i32::MIN as i64,
            -357_913_941,
            357_913_941,
            i32::MAX as i64,
            i32::MAX as i64 + 10_800_000,
        ]) {
            for (n, d) in [(6, 5), (5, 6)] {
                let magnitude = (value.abs() * n + d / 2) / d;
                assert_eq!(
                    rounded_ratio(value, n as i32, d as i32),
                    if value < 0 { -magnitude } else { magnitude }
                );
            }
        }
        for uv in [i32::MIN, -357_913_942, 357_913_942, i32::MAX] {
            let scaled = uv as i64 * 1_200_000;
            let delta = if scaled >= 0 {
                (scaled + 500_000) / 1_000_000
            } else {
                -((-scaled + 500_000) / 1_000_000)
            };
            assert_eq!(
                pitch_from_cv(uv, 60),
                i32::try_from(6_000_000 + delta).map_err(|_| MappingError::InputOverflow)
            );
        }
    }
    #[test]
    fn custom_two_octaves_equal_mapping_hold_and_reentry() {
        let mut e = Engine::new();
        assert!(e.arm_nominal(1, 1, 60, 4000, 0, 0));
        e.scale_id = 6;
        e.equal = true;
        e.pattern = crate::scale::Pattern::compile([1, 1 | 16 | 128]).unwrap();
        // +0.75 V lies in second equal bin -> +1 V output.
        let command = e.tick(1, sample(1, 3000), 0, true).unwrap();
        assert_eq!(e.output_uv, 1_000_000);
        assert_eq!(
            e.tick(2, sample(2, 26000), ack(command), true),
            Some(command)
        );
        assert!(e.active);
        assert_eq!(e.output_uv, 1_000_000);
        let command = e.tick(3, sample(3, 0), ack(command), true).unwrap();
        assert_eq!(e.output_uv, 0);
        assert_eq!(e.tick(4, sample(4, 0), ack(command), false), Some(0));
        assert!(!e.active);
    }
    #[test]
    fn standalone_scales_root_transpose_and_quarter_tones() {
        let mut e = Engine::new();
        assert!(e.arm_nominal(1, 1, 60, 4000, 0, 0));
        e.scale_id = 1; // C major: C# input rounds upward to D.
        let mut command = e.tick(1, sample(1, 334), 0, true).unwrap();
        assert_eq!(e.pitch, 6_200_000);
        e.stop("test");
        assert!(e.arm_nominal(1, 1, 60, 4000, 2, 0));
        e.scale_id = 1;
        e.root = 2; // D major contains C#.
        command = e.tick(3, sample(2, 334), 0, true).unwrap();
        assert_eq!(e.pitch, 6_100_000);
        e.stop("test");
        assert!(e.arm_nominal(1, 1, 60, 4000, 4, 0));
        e.transpose = 12; // Transposition must work even for chromatic scales.
        command = e.tick(5, sample(3, 0), 0, true).unwrap();
        assert_eq!(e.output_uv, 1_000_000);
        command = e.tick(6, sample(4, 160), ack(command), true).unwrap();
        assert_eq!(e.pitch, 7_200_000); // hysteresis uses pre-transpose pitch
        e.stop("test");
        assert!(e.arm_nominal(1, 1, 60, 4000, 7, 0));
        e.scale_id = 5;
        command = e.tick(8, sample(5, 167), 0, true).unwrap();
        assert_eq!(e.pitch, 6_050_000);
        assert_eq!(e.output_uv, 41_750);
        e.scale_id = 255;
        assert_eq!(e.tick(9, sample(6, 0), ack(command), true), Some(0));
        assert_eq!(e.status, "STOPPED - INVALID SCALE");
    }
    #[test]
    fn nominal_mapping_covers_bipolar_notes_without_profile() {
        for origin in 12..=108 {
            for step in -60..=60 {
                let target = map_nominal(origin as i32 * 100_000 + step * 100_000, origin).unwrap();
                let ideal = step as f64 * 1_000_000.0 / 12.0;
                assert!((target.applied_microvolts as f64 - ideal).abs() <= 126.0);
            }
            assert!(map_nominal(origin as i32 * 100_000 + 6_100_000, origin).is_err());
            assert!(map_nominal(origin as i32 * 100_000 - 6_100_000, origin).is_err());
        }
        assert!(map_nominal(0, 0).is_err());
    }
    #[test]
    fn standalone_arms_without_profile_and_preserves_safety_and_hysteresis() {
        let mut e = Engine::new();
        assert!(e.arm_nominal(1, 2, 60, 4000, 0, 0));
        assert!(e.profile.is_none());
        let command = e.tick(1, sample(1, 200), 0, true).unwrap();
        assert_eq!(e.pitch, 6_100_000);
        assert_eq!(e.output_uv, 83_250);
        let command = e.tick(2, sample(2, 160), ack(command), true).unwrap();
        assert_eq!(e.pitch, 6_100_000);
        assert_eq!((command >> 16) & 3, 2);
        assert_eq!(
            e.tick(3, sample(3, 24000), ack(command), true),
            Some(command)
        );
        assert!(e.active);
        assert_eq!(e.output_uv, 83_250);
        let command = e.tick(4, sample(4, -4000), ack(command), true).unwrap();
        assert_eq!(e.output_uv, -1_000_000);
        assert_eq!(e.tick(14, sample(4, -4000), ack(command), true), Some(0));
        assert_eq!(e.status, "STOPPED - CV STALE");
        assert!(e.arm_nominal(0, 3, 60, 4000, 20, 0));
        assert_eq!(e.tick(21, sample(5, 0), 0, false), Some(0));
        assert!(!e.active);
        assert!(e.arm(&curve(), 1, 1, 60, 4000, 30, 0));
        assert!(!e.standalone);
        e.stop("test");
        assert!(!e.arm_nominal(4, 0, 60, 4000, 31, 0));
        assert!(!e.arm_nominal(0, 4, 60, 4000, 31, 0));
        assert!(!e.arm_nominal(0, 1, 60, 4000, 31, 512));
    }
    #[test]
    fn chromatic_rounding_and_hysteresis_are_symmetric_across_zero() {
        for note in -24..140 {
            let center = note * 100_000;
            assert_eq!(chromatic_pitch(center + 49_999, None), center);
            assert_eq!(chromatic_pitch(center + 50_000, None), center + 100_000);
            assert_eq!(chromatic_pitch(center - 50_000, None), center);
            assert_eq!(chromatic_pitch(center + 55_000, Some(center)), center);
            assert_eq!(
                chromatic_pitch(center + 55_001, Some(center)),
                center + 100_000
            );
            assert_eq!(
                chromatic_pitch(center - 55_001, Some(center)),
                center - 100_000
            );
        }
    }
    #[test]
    fn chromatic_engine_uses_measured_curve_and_clears_history_on_stop() {
        let p = curve();
        let mut e = Engine::new();
        e.chromatic = true;
        assert!(e.arm(&p, 1, 2, 60, 4000, 0, 0));
        let command = e.tick(1, sample(1, 200), 0, true).unwrap(); // 60 cents -> next note
        assert_eq!(e.pitch, 6_100_000);
        assert_eq!(command as u16, map_pitch(&p, 6_100_000).unwrap().dac_bits);
        e.tick(2, sample(2, 160), ack(command), true); // 48 cents retains upper note
        assert_eq!(e.pitch, 6_100_000);
        e.stop("test");
        assert!(e.arm(&p, 1, 2, 60, 4000, 3, 0));
        e.tick(4, sample(3, 160), 0, true);
        assert_eq!(e.pitch, 6_000_000);
    }
    #[test]
    fn chromatic_outside_profile_waits_instead_of_clamping_note() {
        let mut p = Profile::new("partial", -5_000_000, 5_000_000).unwrap();
        p.push(Point {
            microvolts: 0,
            millicents: 6_030_000,
        })
        .unwrap();
        p.push(Point {
            microvolts: 1_000_000,
            millicents: 7_230_000,
        })
        .unwrap();
        let mut e = Engine::new();
        e.chromatic = true;
        assert!(e.arm(&p, 1, 1, 60, 4000, 0, 0));
        // Input is within measured pitch range, but nearest note is not.
        assert_eq!(e.tick(1, sample(1, 120), 0, true), Some(0));
        assert!(e.active);
        assert_eq!(e.status, "WAITING FOR IN-RANGE PITCH");
    }
    fn curve() -> Profile {
        let mut p = Profile::new("variable", -5_000_000, 5_000_000).unwrap();
        for (uv, mc) in [
            (-2_000_000, 4_800_000),
            (-900_000, 6_000_000),
            (200_000, 7_200_000),
            (1_500_000, 8_400_000),
        ] {
            p.push(Point {
                microvolts: uv,
                millicents: mc,
            })
            .unwrap();
        }
        p
    }
    fn sample(sequence: u32, counts: i16) -> u32 {
        (1 << 31) | (sequence << 16) | counts as u16 as u32
    }
    fn ack(command: u32) -> u32 {
        ((command >> 21) & 255) | 256
    }
    #[test]
    fn range_hold_renews_command_and_resumes_but_stale_cv_still_stops() {
        for chromatic in [false, true] {
            let mut e = Engine::new();
            e.chromatic = chromatic;
            assert!(e.arm(&curve(), 1, 1, 60, 4000, 0, 0));
            // No valid note yet: remain disabled but keep listening.
            assert_eq!(e.tick(1, sample(1, 20000), 0, true), Some(0));
            assert!(e.active);
            let command = e.tick(2, sample(2, 0), 0, true).unwrap();
            let voltage = e.output_uv;
            let pitch = e.pitch;
            for now in 3..1003 {
                let counts = if now % 2 == 0 { 20000 } else { -20000 };
                assert_eq!(
                    e.tick(now, sample(now, counts), ack(command), true),
                    Some(command)
                );
                assert!(e.active);
                assert_eq!(e.output_uv, voltage);
                assert_eq!(e.pitch, pitch);
            }
            let resumed = e
                .tick(1003, sample(1003, 4000), ack(command), true)
                .unwrap();
            assert_ne!(resumed as u16, command as u16);
            assert_eq!(e.pitch, 7_200_000);
            assert_eq!(
                e.tick(1004, sample(1004, 20000), ack(resumed), true),
                Some(resumed)
            );
            assert_eq!(
                e.tick(1014, sample(1004, 20000), ack(resumed), true),
                Some(0)
            );
            assert_eq!(e.status, "STOPPED - CV STALE");
        }
    }
    #[test]
    fn settled_audio_requires_whole_fresh_window_after_last_target_change() {
        let mut e = Engine::new();
        e.chromatic = true;
        assert!(e.arm(&curve(), 1, 1, 60, 4000, 0, 0));
        assert!(!e.feedback_ready(1000, 20, 1));
        let mut command = e.tick(1, sample(1, 0), 0, true).unwrap();
        for now in 2..500 {
            command = e.tick(now, sample(now, 0), ack(command), true).unwrap();
        }
        assert!(e.feedback_ready(500, 20, 1));
        assert!(!e.feedback_ready(500, 60, 1));
        assert!(!e.feedback_ready(500, 20, 101));
        e.tick(500, sample(500, 4000), ack(command), true);
        assert!(!e.feedback_ready(501, 20, 1));
        e.stop("test");
        assert!(!e.feedback_ready(2000, 20, 1));
    }
    #[test]
    fn engine_requires_arm_fresh_samples_and_ack_and_keeps_route() {
        let p = curve();
        let mut e = Engine::new();
        assert_eq!(e.tick(0, sample(1, 0), 0, true), None);
        assert!(!e.arm(&p, 1, 2, 60, 4000, 0, 256));
        assert!(e.arm(&p, 1, 2, 60, 4000, 0, 0));
        let c = e.tick(1, sample(1, 0), 0, true).unwrap();
        assert_eq!((c >> 16) & 3, 2);
        assert_eq!((c >> 19) & 3, 1);
        assert_eq!(crate::bipolar::decode_voltage(c as u16), Some(-900000));
        assert_eq!(e.tick(2, sample(2, 2000), 0, true), None);
        let d = e.tick(3, sample(2, 2000), ack(c), true).unwrap();
        assert_eq!(crate::bipolar::decode_voltage(d as u16), Some(-350000));
        assert_eq!(e.tick(4, sample(2, 2000), ack(d), true), None);
        assert_eq!(e.tick(13, sample(2, 2000), ack(d), true), Some(0));
        assert_eq!(e.status, "STOPPED - CV STALE");
        assert_eq!(e.tick(14, sample(3, 0), 0, true), None);
    }
    #[test]
    fn playback_faults_latch_and_clock_wrap_is_bounded() {
        let p = curve();
        for reason in 0..4 {
            let mut e = Engine::new();
            assert!(e.arm(&p, 1, 1, 60, 4000, u32::MAX - 1, 0));
            let c = e.tick(u32::MAX, sample(32767, 0), 0, true).unwrap();
            let result = match reason {
                0 => e.tick(2, sample(0, 0), 0, true),
                1 => e.tick(0, sample(0, 0), 512, true),
                2 => e.tick(0, sample(0, 0), ack(c), false),
                _ => e.tick(0, sample(0, 32767), ack(c), true),
            };
            assert_eq!(result, Some(0));
            assert!(!e.active);
            assert_eq!(e.output_uv, 0);
            assert_eq!(e.tick(3, sample(1, 0), 0, true), None);
        }
    }
    #[test]
    fn cv_origin_and_negative_rounding_are_explicit() {
        assert_eq!(pitch_from_cv(0, 60), Ok(6_000_000));
        assert_eq!(pitch_from_cv(-1_000_000, 60), Ok(4_800_000));
        assert_eq!(pitch_from_cv(1_000_000, 60), Ok(7_200_000));
        for uv in 0..100_000 {
            assert_eq!(
                pitch_from_cv(uv, 60).unwrap() - 6_000_000,
                6_000_000 - pitch_from_cv(-uv, 60).unwrap()
            );
        }
        for note in [0, 11, 109, 255] {
            assert_eq!(pitch_from_cv(0, note), Err(MappingError::InvalidOrigin));
        }
        assert_eq!(
            pitch_from_cv(i32::MAX, 60),
            Err(MappingError::InputOverflow)
        );
        assert_eq!(
            pitch_from_cv(i32::MIN, 60),
            Err(MappingError::InputOverflow)
        );
    }
    #[test]
    fn continuous_and_quantized_pitch_share_variable_curve() {
        let p = curve();
        let before = p.points().to_vec();
        assert_eq!(map_cv(&p, 0, 60).unwrap().applied_microvolts, -900_000);
        assert_eq!(
            map_cv(&p, 500_000, 60).unwrap().applied_microvolts,
            -350_000
        );
        assert_eq!(
            map_cv(&p, 1_500_000, 60).unwrap().applied_microvolts,
            850_000
        );
        for uv in (-1_000_000..=2_000_000).step_by(125) {
            let target = map_cv(&p, uv, 60).unwrap();
            assert_eq!(
                target,
                map_pitch(&p, pitch_from_cv(uv, 60).unwrap()).unwrap()
            );
            assert!((target.applied_microvolts - target.requested_microvolts).abs() <= 125);
        }
        assert_eq!(p.points(), before);
        for uv in [-1_000_001, 2_000_001] {
            assert_eq!(
                map_cv(&p, uv, 60),
                Err(MappingError::Profile(Error::PitchOutsideRange))
            );
        }
    }
    #[test]
    fn invalid_or_unrepresentable_profiles_never_produce_commands() {
        let empty = Profile::new("empty", 0, 1).unwrap();
        assert_eq!(
            map_pitch(&empty, 0),
            Err(MappingError::Profile(Error::Incomplete))
        );
        let mut p = Profile::new("outside", 8_000_001, 9_000_000).unwrap();
        p.push(Point {
            microvolts: 8_000_001,
            millicents: 0,
        })
        .unwrap();
        p.push(Point {
            microvolts: 9_000_000,
            millicents: 100_000,
        })
        .unwrap();
        assert_eq!(map_pitch(&p, 0), Err(MappingError::OutputOutsideLimits));
    }
    #[test]
    fn measured_positive_only_profile_can_replay_above_five_volts() {
        let mut p = Profile::new("positive", 0, 8_000_000).unwrap();
        p.push(Point {
            microvolts: 0,
            millicents: 0,
        })
        .unwrap();
        p.push(Point {
            microvolts: 8_000_000,
            millicents: 9_600_000,
        })
        .unwrap();
        let target = map_pitch(&p, 7_200_000).unwrap();
        assert_eq!(target.applied_microvolts, 6_000_000);
        // Nominal/unprofiled output retains its conservative +5 V ceiling.
        assert_eq!(
            map_nominal(7_300_000, 12),
            Err(MappingError::OutputOutsideLimits)
        );
    }
}
