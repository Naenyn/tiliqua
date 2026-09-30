//! Bipolar tracking sweep, with output acknowledgments and origin rechecks.
use crate::bipolar::{self, Density};
use crate::bipolar_sweep::{Failure, Outcome, Request, Sweep};
use crate::oscillator_calibration::automatic::{Automatic, Phase};
use crate::oscillator_calibration::averaging::{Average, LOW_PITCH};
use crate::oscillator_calibration::deviation::{Deviation, Summary};
use crate::oscillator_calibration::verification_scan::Scan;
use crate::oscillator_calibration::{
    sweep::{Measurement, Policy},
    CalibrationGrade, CalibrationQuality, Profile, Route,
};
use crate::pac;
use crate::pitch_math;
use crate::runtime::{ChannelMeasurement, OperatingMode, RuntimeControls};

// A V/oct oscillator normally responds much faster than one detector frame.
// Wait only for the acknowledged output and a short analog guard; freshness
// and agreement are established by the *subsequent* detector windows, not by
// leaving every voltage applied for hundreds of milliseconds before sampling.
const ACQUISITION_SETTLE_MS: u64 = 75;
// The output acknowledgement can take up to 100 ms. Window timestamps must
// therefore begin at least 100 + 75 ms after the command during a scan.
const SCAN_WINDOW_START_MS: u64 = 175;
// The status gate is slightly later than the window-start guard so the first
// candidate cannot be evaluated before the output has had a full opportunity
// to acknowledge and settle.
const SCAN_READY_MS: u64 = 225;

#[derive(Clone, Copy, Debug)]
pub struct VerificationDiagnostic {
    pub frames: u16,
    pub valid: u16,
    pub qualified: u16,
    pub fresh: u16,
    pub settled_fresh: u16,
    pub target_near: u16,
    pub min_hz: f32,
    pub max_hz: f32,
    pub settled_min_hz: f32,
    pub settled_max_hz: f32,
    pub last_window_age_ms: u32,
    pub last_end_age_ms: u32,
}

impl VerificationDiagnostic {
    fn new() -> Self {
        Self {
            frames: 0,
            valid: 0,
            qualified: 0,
            fresh: 0,
            settled_fresh: 0,
            target_near: 0,
            min_hz: f32::INFINITY,
            max_hz: f32::NEG_INFINITY,
            settled_min_hz: f32::INFINITY,
            settled_max_hz: f32::NEG_INFINITY,
            last_window_age_ms: 0,
            last_end_age_ms: 0,
        }
    }

    fn observe(&mut self, value: ChannelMeasurement, fresh: bool, settled: bool, target_near: bool) {
        self.frames = self.frames.saturating_add(1);
        self.valid = self.valid.saturating_add(value.valid as u16);
        self.qualified = self.qualified.saturating_add(value.qualified as u16);
        self.fresh = self.fresh.saturating_add(fresh as u16);
        self.settled_fresh = self.settled_fresh.saturating_add((fresh && settled) as u16);
        self.target_near = self.target_near.saturating_add((fresh && target_near) as u16);
        if value.frequency_hz.is_finite() && value.frequency_hz > 0.0 {
            self.min_hz = self.min_hz.min(value.frequency_hz);
            self.max_hz = self.max_hz.max(value.frequency_hz);
            if fresh && settled {
                self.settled_min_hz = self.settled_min_hz.min(value.frequency_hz);
                self.settled_max_hz = self.settled_max_hz.max(value.frequency_hz);
            }
        }
        self.last_window_age_ms = value.window_age_ms;
        self.last_end_age_ms = value.end_age_ms;
    }

    pub fn hz_range(&self) -> Option<(f32, f32)> {
        self.min_hz
            .is_finite()
            .then_some((self.min_hz, self.max_hz))
    }

    pub fn settled_hz_range(&self) -> Option<(f32, f32)> {
        self.settled_min_hz
            .is_finite()
            .then_some((self.settled_min_hz, self.settled_max_hz))
    }

    fn ambiguous_waveform(&self) -> bool {
        self.frames >= 32
            && self.valid >= 16
            && self
                .hz_range()
                // A detector alternating between adjacent integer-period
                // families spans approximately one octave. This is the common
                // wavefolded/ensemble failure signature; waiting longer cannot
                // turn it into a repeatable calibration observation.
                .is_some_and(|(lo, hi)| lo > 0.0 && hi / lo >= 1.8)
    }
}

fn incomplete_replay_extension(
    target_guided: bool,
    average: &crate::oscillator_calibration::averaging::Snapshot,
    diagnostic: &VerificationDiagnostic,
) -> bool {
    target_guided
        && !diagnostic.ambiguous_waveform()
        && diagnostic.settled_fresh >= 16
        && diagnostic.target_near >= 16
        && (8..crate::oscillator_calibration::averaging::WINDOWS).contains(&average.count)
        && average.raw_span <= 10_000
        && average.span_resets == 0
        && average.gap_resets == 0
}

#[cfg(test)]
mod replay_extension_tests {
    use super::*;

    #[test]
    fn extends_only_near_target_incomplete_stable_replay() {
        let mut diagnostic = VerificationDiagnostic::new();
        diagnostic.frames = 105;
        diagnostic.valid = 98;
        diagnostic.qualified = 98;
        diagnostic.settled_fresh = 22;
        diagnostic.target_near = 22;
        diagnostic.min_hz = 2015.37;
        diagnostic.max_hz = 2260.05;
        let mut average = crate::oscillator_calibration::averaging::Average::new().snapshot();
        average.count = 13;
        average.raw_span = 5_898;
        assert!(incomplete_replay_extension(true, &average, &diagnostic));

        average.count = 7;
        assert!(!incomplete_replay_extension(true, &average, &diagnostic));
        average.count = 16;
        assert!(!incomplete_replay_extension(true, &average, &diagnostic));
        average.count = 13;
        average.raw_span = 11_000;
        assert!(!incomplete_replay_extension(true, &average, &diagnostic));
        average.raw_span = 5_898;
        diagnostic.target_near = 15;
        assert!(!incomplete_replay_extension(true, &average, &diagnostic));
        diagnostic.target_near = 22;
        diagnostic.max_hz = diagnostic.min_hz * 2.0;
        assert!(!incomplete_replay_extension(true, &average, &diagnostic));
        assert!(!incomplete_replay_extension(false, &average, &diagnostic));
    }
}

/// Keep operation controls independent of the visible page. Manual VERIFY
/// may adjust its target while visible; navigation cannot retarget a run.
pub fn background_controls(
    mut captured: RuntimeControls,
    current: RuntimeControls,
    verifying: bool,
) -> RuntimeControls {
    if verifying && current.mode == OperatingMode::Verify {
        captured.target_millicents = current.target_millicents;
    }
    captured
}

pub struct Live {
    pub automatic: Option<Automatic>,
    sweep: Option<Sweep>,
    pub profile: Option<Profile>,
    pub profile_quality: CalibrationQuality,
    pub pending_profile: Option<Profile>,
    pub pending_quality: CalibrationQuality,
    pending_route: Option<Route>,
    pub profile_route: Option<Route>,
    pub verifying: bool,
    pub scan: Option<Scan>,
    pub refinement: Option<crate::oscillator_calibration::refinement::Refinement>,
    pub target_millicents: i32,
    pub error_cents: Option<f32>,
    pub deviation: Option<Summary>,
    statistics: Deviation,
    average: Average,
    pub verify_retried: bool,
    verify_extended: bool,
    pub failure_verification: Option<crate::oscillator_calibration::averaging::Snapshot>,
    pub recovered_verification: Option<crate::oscillator_calibration::averaging::Snapshot>,
    pub failure_verification_diagnostic: Option<VerificationDiagnostic>,
    pub recovered_verification_diagnostic: Option<VerificationDiagnostic>,
    verify_diagnostic: VerificationDiagnostic,
    suggested_note: Option<u8>,
    verify_command: u32,
    verify_started: u64,
    verify_token: u8,
    pub status: &'static str,
    pub zero_error_cents: Option<f32>,
    pub failure_voltage: Option<i32>,
    pub failure_output_status: Option<u32>,
    pub failure_output_cause: &'static str,
    pub failure_acquisition: Option<crate::bipolar_sweep::AcquisitionDiagnostic>,
    pub period_family_corrections: u8,
    pub scan_warnings: crate::bipolar_sweep::ScanWarnings,
    pub sweep_timing: crate::bipolar_sweep::SweepTiming,
    pub tracking_failure: Option<crate::bipolar_sweep::TrackingFailure>,
    pub input: u8,
    pub output: u8,
    pub millivolts: i32,
    pub point: u8,
    pub point_count: u8,
    sweep_command: u32,
    waiting: Option<u8>,
    previous_sequence: Option<u16>,
    sequence: u64,
}

impl Live {
    /// Keep an already acknowledged output alive before optional serial and
    /// framebuffer work. The sweep state machine still owns all transitions;
    /// this repeats only its exact current command and never starts output.
    pub fn renew_output(&self, tuner: &pac::TUNER_PERIPH) {
        let command = if self.verifying {
            self.verify_command
        } else if self.sweep.is_some() {
            self.sweep_command
        } else {
            0
        };
        if command & (1 << 18) != 0 {
            tuner.cal_command().write(|w| unsafe { w.value().bits(command) });
        }
    }
    #[inline(never)]
    pub fn new() -> Self {
        Self {
            automatic: None,
            sweep: None,
            profile: None,
            profile_quality: CalibrationQuality::default(),
            pending_profile: None,
            pending_quality: CalibrationQuality::default(),
            pending_route: None,
            profile_route: None,
            verifying: false,
            scan: None,
            refinement: None,
            target_millicents: 0,
            error_cents: None,
            verify_command: 0,
            verify_started: 0,
            verify_token: 0,
            deviation: None,
            statistics: Deviation::new(),
            average: Average::new(),
            suggested_note: None,
            failure_voltage: None,
            failure_output_status: None,
            failure_output_cause: "",
            failure_acquisition: None,
            period_family_corrections: 0,
            scan_warnings: crate::bipolar_sweep::ScanWarnings::default(),
            sweep_timing: crate::bipolar_sweep::SweepTiming::default(),
            verify_retried: false,
            verify_extended: false,
            failure_verification: None,
            recovered_verification: None,
            failure_verification_diagnostic: None,
            recovered_verification_diagnostic: None,
            verify_diagnostic: VerificationDiagnostic::new(),
            status: "READY - RUN IN MENU",
            zero_error_cents: None,
            tracking_failure: None,
            input: 0,
            output: 0,
            millivolts: 0,
            point: 0,
            point_count: 121,
            sweep_command: 0,
            waiting: None,
            previous_sequence: None,
            sequence: 0,
        }
    }
    pub fn take_suggested_note(&mut self) -> Option<u8> {
        self.suggested_note.take()
    }
    pub fn recall(&mut self, record: crate::oscillator_calibration::storage::Recalled) -> bool {
        if self.active() || self.pending_profile.is_some() {
            return false;
        }
        self.automatic = None;
        self.scan = None;
        self.failure_voltage = None;
        self.failure_output_status = None;
        self.failure_output_cause = "";
        self.failure_acquisition = None;
        self.period_family_corrections = 0;
        self.scan_warnings = crate::bipolar_sweep::ScanWarnings::default();
        self.sweep_timing = crate::bipolar_sweep::SweepTiming::default();
        self.failure_verification = None;
        self.recovered_verification = None;
        self.failure_verification_diagnostic = None;
        self.recovered_verification_diagnostic = None;
        self.verify_retried = false;
        self.verify_extended = false;
        self.refinement = None;
        self.input = record.route.input();
        self.output = record.route.output();
        self.point_count = record.profile.points().len() as u8;
        self.point = 0;
        self.suggested_note = record.profile.suggested_note();
        self.profile = Some(record.profile);
        self.profile_quality = record.quality;
        self.profile_route = Some(record.route);
        self.error_cents = None;
        self.deviation = None;
        self.statistics.clear();
        self.millivolts = 0;
        self.status = "LOADED - OUTPUT STOPPED";
        true
    }
    pub fn active(&self) -> bool {
        self.sweep.is_some()
            || self.verifying
            || self.automatic.as_ref().is_some_and(|a| a.active())
    }
    /// A poor score is advisory. Only a complete independent replay with its
    /// local repeat check may be kept by explicit user action.
    pub fn can_accept_imperfect(&self) -> bool {
        !self.active()
            && self.pending_profile.is_some()
            && self.pending_quality.grade == CalibrationGrade::Unsafe
            && self.automatic.as_ref().is_some_and(|a| a.phase == Phase::Review)
            && self.scan.as_ref().is_some_and(|s| {
                s.complete && s.missing == 0
                    && s.local.as_ref().is_some_and(|c| c.tested == 9)
            })
    }
    pub fn acquiring_points(&self) -> Option<&[crate::oscillator_calibration::Point]> {
        self.sweep.as_ref().map(Sweep::progress_points)
    }
    fn operation_profile(&self) -> Option<&Profile> {
        if self.automatic.as_ref().is_some_and(|a| a.active()) {
            self.pending_profile.as_ref()
        } else {
            self.profile.as_ref()
        }
    }
    /// Start the whole workflow without replacing the previously accepted profile.
    pub fn toggle_automatic(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        controls: RuntimeControls,
        now: u64,
    ) {
        if self.automatic.as_ref().is_some_and(|a| a.active()) {
            if self.automatic.as_ref().is_some_and(|a| a.best.is_some()) {
                self.finish_automatic(tuner, "PAUSED - REVIEW VERIFIED CURVE");
            } else {
                self.sweep = None;
                self.stop_verify(tuner, "CANCELLED - PRIOR PROFILE KEPT");
                self.pending_profile = None;
                self.pending_route = None;
                self.automatic = None;
                self.scan = None;
                self.refinement = None;
            }
            return;
        }
        if self.active() {
            self.status = "BUSY - STOP CHECK FIRST";
            return;
        }
        self.automatic = None;
        self.toggle(tuner, controls, now);
        if self.sweep.is_some() {
            self.automatic = Some(Automatic::new_with_policy(now, controls.calibration_policy));
        }
    }
    pub fn can_continue_automatic(&self) -> bool {
        // CAL is one-shot: a reviewed result can be accepted, discarded, or
        // replaced by a fresh run. No manual "continue refinement" checkpoint.
        false
    }
    pub fn accept_scan(&mut self, tuner: &pac::TUNER_PERIPH) {
        if self.active() || tuner.cal_status().read().value().bits() & 768 != 0 {
            self.status = "BUSY - STOP OUTPUT FIRST";
            return;
        }
        let user_override = self.can_accept_imperfect();
        if self.automatic.is_some() && !self.pending_quality.acceptable() && !user_override {
            self.status = "INCOMPLETE CHECK - CANNOT ACCEPT";
            return;
        }
        if let Some(profile) = self.pending_profile.take() {
            self.suggested_note = profile.suggested_note();
            self.profile = Some(profile);
            self.profile_quality = self.pending_quality;
            if user_override {
                self.profile_quality.grade = CalibrationGrade::UserAccepted;
            }
            self.pending_quality = CalibrationQuality::default();
            self.profile_route = self.pending_route.take();
            self.status = if user_override {
                "USER-KEPT IN RAM - CHECK QUALITY"
            } else {
                "ACCEPTED IN RAM - SAVE PROFILE"
            };
            self.automatic = None;
        } else {
            self.status = "NO SCAN TO ACCEPT";
        }
    }
    pub fn discard_scan(&mut self) {
        if self.active() {
            self.status = "BUSY - STOP OUTPUT FIRST";
            return;
        }
        if self.pending_profile.take().is_some() {
            self.automatic = None;
            self.pending_quality = CalibrationQuality::default();
            self.pending_route = None;
            self.status = "DISCARDED - PRIOR PROFILE KEPT";
        } else {
            self.status = "NO SCAN TO DISCARD";
        }
    }
    #[inline(never)]
    pub fn start_refinement(&mut self, tuner: &pac::TUNER_PERIPH, c: RuntimeControls, now: u64) {
        if self.pending_profile.is_some() {
            self.status = "ACCEPT OR DISCARD CAL FIRST";
            return;
        }
        if self.active() {
            self.status = "BUSY - STOP OUTPUT FIRST";
            return;
        }
        if self
            .refinement
            .as_ref()
            .is_some_and(|r| r.stage == crate::oscillator_calibration::refinement::Stage::Ready)
        {
            self.status = "ACCEPT OR DISCARD FIRST";
            return;
        }
        if c.mode != OperatingMode::Verify || !c.verify_scan || c.verify_points {
            self.status = "REFINE NEEDS VERIFY SCAN";
            return;
        }
        let Some(scan) = self.scan.as_ref().filter(|s| {
            !s.points_mode && s.complete && s.local.as_ref().is_some_and(|l| l.tested == 9)
        }) else {
            self.status = "RUN SCAN BEFORE REFINE";
            return;
        };
        let Some(profile) = self.profile.as_ref() else {
            return;
        };
        let Some(route) = self.profile_route else {
            return;
        };
        let r = match crate::oscillator_calibration::refinement::Refinement::new(
            profile,
            scan.worst_pitch,
        ) {
            Ok(r) => r,
            Err(reason) => {
                self.status = reason;
                return;
            }
        };
        let pitch = r.request(profile).unwrap().millicents;
        self.refinement = Some(r);
        self.input = route.input();
        self.output = route.output();
        self.verifying = true;
        self.apply_target(tuner, pitch, now);
    }
    #[inline(never)]
    pub fn accept_refinement(&mut self, tuner: &pac::TUNER_PERIPH) {
        if self.active() || tuner.cal_status().read().value().bits() & 768 != 0 {
            self.status = "BUSY - STOP OUTPUT FIRST";
            return;
        }
        if let Some(candidate) = self
            .refinement
            .as_mut()
            .and_then(|r| r.take_candidate(self.profile.as_ref()?))
        {
            self.point_count = candidate.points().len() as u8;
            self.profile = Some(candidate);
            self.refinement = None;
            self.scan = None;
            self.status = "REFINED IN RAM - SAVE PROFILE";
        } else {
            self.status = "NO VERIFIED CANDIDATE";
        }
    }
    pub fn discard_refinement(&mut self, tuner: &pac::TUNER_PERIPH) {
        if self.refinement.is_none() {
            self.status = "NO CANDIDATE TO DISCARD";
            return;
        }
        self.stop_verify(tuner, "DISCARDED - ORIGINAL KEPT");
        self.refinement = None;
    }
    fn stop_verify(&mut self, tuner: &pac::TUNER_PERIPH, status: &'static str) {
        if let Some(r) = self.refinement.as_mut().filter(|r| r.active()) {
            r.reject(status);
        }
        tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
        self.verifying = false;
        self.error_cents = None;
        self.millivolts = 0;
        self.status = status;
        self.statistics.clear();
        self.deviation = None;
    }
    pub fn toggle_verify(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        controls: RuntimeControls,
        now: u64,
    ) {
        if self.pending_profile.is_some() {
            self.status = "ACCEPT OR DISCARD CAL FIRST";
            return;
        }
        if self.verifying {
            self.stop_verify(tuner, "STOPPED - OUTPUT ZERO");
            return;
        }
        if self.sweep.is_some() || controls.mode != OperatingMode::Verify {
            return;
        }
        if self
            .refinement
            .as_ref()
            .is_some_and(|r| r.stage == crate::oscillator_calibration::refinement::Stage::Ready)
        {
            self.status = "ACCEPT OR DISCARD FIRST";
            return;
        }
        self.refinement = None;
        let Some(route) = self.profile_route.filter(|_| self.profile.is_some()) else {
            self.status = "NO COMPLETED CAL - VERIFY BLOCKED";
            return;
        };
        self.scan = if controls.verify_scan {
            self.profile.as_ref().and_then(|p| {
                if option_env!("TILIQUA_INTONO_REPEAT_DIAGNOSTIC") == Some("1") {
                    Scan::repeat(p, 4454000)
                } else if controls.verify_points {
                    Scan::points(p)
                } else {
                    Scan::new(p)
                }
            })
        } else {
            None
        };
        if controls.verify_scan && self.scan.is_none() {
            self.status = "NO SCAN TARGETS IN RANGE";
            return;
        }
        self.input = route.input();
        self.output = route.output();
        // Starting requires a deliberate action, including after a fault/range
        // error. Never reinterpret an audio cable as incoming pitch CV.
        tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
        self.verifying = true;
        let target = self
            .scan
            .as_ref()
            .map_or(controls.target_millicents, |s| s.target);
        self.apply_target(tuner, target, now);
    }
    fn apply_target(&mut self, tuner: &pac::TUNER_PERIPH, pitch: i32, now: u64) {
        let voltage = self.operation_profile().and_then(|p| {
            if let Some(scan) = self.scan.as_ref().filter(|s| s.repeat_check().is_some()) {
                scan.repeat_check()?
                    .request(p, scan.tested)
                    .filter(|point| point.millicents == pitch)
                    .map(|point| point.microvolts)
            } else if let Some(r) = self.refinement.as_ref().filter(|r| r.active()) {
                r.request(p)
                    .filter(|point| point.millicents == pitch)
                    .map(|point| point.microvolts)
            } else if let Some(check) = self.scan.as_ref().and_then(|s| s.local.as_ref()) {
                check
                    .next()
                    .filter(|point| point.millicents == pitch)
                    .map(|point| point.microvolts)
            } else if let Some(scan) = self.scan.as_ref().filter(|s| s.points_mode) {
                p.points()
                    .get(scan.tested as usize)
                    .filter(|point| point.millicents == pitch)
                    .map(|point| point.microvolts)
            } else {
                p.voltage_for_pitch(pitch).ok()
            }
        });
        let Some(counts) = voltage.and_then(bipolar::encode_profile_voltage) else {
            self.stop_verify(tuner, "OUT OF RANGE - ZERO");
            return;
        };
        self.target_millicents = pitch;
        self.failure_voltage = None;
        self.verify_retried = false;
        self.verify_extended = false;
        self.failure_verification = None;
        self.failure_verification_diagnostic = None;
        self.verify_diagnostic = VerificationDiagnostic::new();
        self.average.clear();
        self.error_cents = None;
        self.statistics.clear();
        self.deviation = None;
        self.verify_token = self.verify_token.wrapping_add(1);
        self.previous_sequence = None;
        self.millivolts = bipolar::decode_voltage(counts).unwrap() / 1000;
        self.verify_command = counts as u32
            | ((self.output as u32) << 16)
            | (1 << 18)
            | ((self.input as u32) << 19)
            | ((self.verify_token as u32) << 21);
        self.verify_started = now;
        self.status = "APPLYING TARGET";
        tuner
            .cal_command()
            .write(|w| unsafe { w.value().bits(self.verify_command) });
    }
    fn tick_verify(&mut self, tuner: &pac::TUNER_PERIPH, controls: RuntimeControls, now: u64) {
        if controls.mode != OperatingMode::Verify
            || controls.verify_scan != self.scan.is_some()
            || self
                .scan
                .as_ref()
                .is_some_and(|s| s.points_mode != controls.verify_points)
        {
            self.stop_verify(tuner, "STOPPED - OUTPUT ZERO");
            return;
        }
        let status = tuner.cal_status().read().value().bits();
        if status & 512 != 0 || now < self.verify_started {
            self.stop_verify(tuner, "OUTPUT FAULT - ZERO");
            return;
        }
        if status & 511 == (self.verify_token as u32 | 256) {
            if self.scan.is_none() && controls.target_millicents != self.target_millicents {
                self.apply_target(tuner, controls.target_millicents, now);
                return;
            }
            self.status = if now - self.verify_started
                < if self.scan.is_some() { SCAN_READY_MS } else { 550 }
            {
                "SETTLING"
            } else {
                "CORRECTED TARGET ACTIVE"
            };
        } else if now - self.verify_started >= 100 {
            self.stop_verify(tuner, "NO OUTPUT ACK - ZERO");
            return;
        }
        tuner
            .cal_command()
            .write(|w| unsafe { w.value().bits(self.verify_command) });
    }
    #[inline(never)]
    pub fn toggle(&mut self, tuner: &pac::TUNER_PERIPH, controls: RuntimeControls, now: u64) {
        if self
            .refinement
            .as_ref()
            .is_some_and(|r| r.stage == crate::oscillator_calibration::refinement::Stage::Ready)
        {
            self.status = "ACCEPT OR DISCARD FIRST";
            return;
        }
        if self.verifying {
            self.stop_verify(tuner, "STOPPED - OUTPUT ZERO");
        }
        if let Some(s) = self.sweep.as_mut() {
            s.cancel();
            return;
        }
        // RUN during review explicitly rescans; it never accepts the candidate.
        self.pending_profile = None;
        self.pending_quality = CalibrationQuality::default();
        self.pending_route = None;
        self.scan = None;
        self.refinement = None;
        self.input = controls.calibration_input;
        self.output = controls.calibration_output;
        self.zero_error_cents = None;
        self.failure_voltage = None;
        self.failure_output_status = None;
        self.failure_output_cause = "";
        self.failure_acquisition = None;
        self.period_family_corrections = 0;
        self.sweep_timing = crate::bipolar_sweep::SweepTiming::default();
        self.failure_verification = None;
        self.recovered_verification = None;
        self.failure_verification_diagnostic = None;
        self.recovered_verification_diagnostic = None;
        self.verify_retried = false;
        self.verify_extended = false;
        self.tracking_failure = None;
        let density = Density::Semitone;
        self.point_count = (bipolar::full_intervals(density) + 1) as u8;
        self.suggested_note = None;
        let tolerance = match controls.calibration_policy {
            crate::options::CalibrationPolicy::Precision => 3000,
            crate::options::CalibrationPolicy::Auto | crate::options::CalibrationPolicy::Fast => 5000,
            crate::options::CalibrationPolicy::Forgiving => 10000,
        };
        self.sweep = Sweep::new(
            Route::new(self.input, self.output).unwrap(),
            density,
            Policy {
                settle_ms: ACQUISITION_SETTLE_MS,
                point_timeout_ms: 5000,
                // Explicit opt-in for a known well-behaved oscillator. Keep
                // the same voltage grid, settling guard, tolerance, fallback
                // estimator and independent final verification.
                stable_samples: if controls.calibration_policy == crate::options::CalibrationPolicy::Fast {
                    3
                } else {
                    5
                },
                tolerance_millicents: tolerance,
            },
            tolerance,
            now,
        );
        self.waiting = None;
        self.sweep_command = 0;
        self.previous_sequence = None;
        self.sequence = 0;
        self.point = 0;
        self.status = "CHARACTERIZING -5V TO +8V";
        tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
    }
    // Keep acquisition temporaries off the perpetual frame used during flash
    // save/recall. These operations are mutually exclusive, not nested.
    #[inline(never)]
    pub fn tick(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        value: ChannelMeasurement,
        controls: RuntimeControls,
        now: u64,
    ) {
        if self.automatic.as_ref().is_some_and(|a| a.active()) {
            self.tick_automatic(tuner, value, controls, now);
            return;
        }
        if self.verifying {
            self.tick_verification(tuner, value, controls, now);
        } else {
            self.tick_sweep(tuner, value, controls, now);
        }
    }
    fn begin_auto_check(&mut self, tuner: &pac::TUNER_PERIPH, now: u64) {
        self.refinement = None;
        let boundary = self.automatic.as_ref().and_then(|a| {
            if a.regional_check { a.last_recovery.map(|(uv, _)| uv) } else { None }
        });
        let regional = boundary.and_then(|uv| self.pending_profile.as_ref().and_then(|p| {
            let high = uv >= p.points().last()?.microvolts;
            Scan::targeted_boundary(p, high)
        }));
        if boundary.is_some() && regional.is_none() {
            self.automatic.as_mut().unwrap().regional_check = false;
        }
        self.scan = self.pending_profile.as_ref().and_then(|p| {
            if let Some(scan) = regional {
                Some(scan)
            } else if let Some(best) = self.automatic.as_ref().and_then(|a| a.best.as_ref()) {
                best.recheck(p)
            } else {
                Scan::targeted(p)
            }
        });
        if let Some(scan) = self.scan.as_ref() {
            let pitch = scan.target;
            self.automatic.as_mut().unwrap().start_check_timing(now);
            self.verifying = true;
            self.apply_target(tuner, pitch, now);
        } else {
            self.finish_automatic(tuner, "CHECK FAILED - PRIOR PROFILE KEPT");
        }
    }
    /// Undo the single tentative insertion; no extra full-profile RAM copy.
    fn rollback_auto(&mut self) {
        if let Some(auto) = self.automatic.as_mut() {
            if let Some(point) = auto.undo.take() {
                if !self
                    .pending_profile
                    .as_mut()
                    .is_some_and(|p| p.undo_refinement(point))
                {
                    self.pending_profile = None;
                    auto.best = None;
                }
            }
            self.scan = auto.best.clone();
        }
    }
    fn finish_automatic(&mut self, tuner: &pac::TUNER_PERIPH, reason: &'static str) {
        if self.automatic.as_ref().is_some_and(|a| a.phase == Phase::Reverify) {
            if let (Some(auto), Some(scan)) = (self.automatic.as_mut(), self.scan.as_ref()) {
                auto.recheck_missing_uv = scan.first_missing_uv;
            }
        }
        let range_checkpoint = self.automatic.as_ref().is_some_and(|a| {
            a.phase == Phase::Verify && a.undo.is_none()
        }) && matches!(reason,
            "REVIEW - MORE RANGE SEARCH?" | "REVIEW - CHECKS DISAGREE"
                | "REVIEW - INCOMPLETE CHECK");
        if !range_checkpoint {
            self.rollback_auto();
        }
        self.sweep = None;
        self.stop_verify(tuner, reason);
        self.refinement = None;
        let auto = self.automatic.as_mut().unwrap();
        auto.phase = Phase::Review;
        auto.review_reason = Some(reason);
        self.pending_quality = auto.best.as_ref().map(Scan::quality).unwrap_or_default();
        // Preserve a coherent retained-point count even when the quality gate
        // rejects and removes the pending profile below. `point` otherwise
        // remains the larger acquisition count while `point_count` reflects a
        // recovered subrange, producing confusing displays such as 94/62.
        if let Some(p) = self.pending_profile.as_ref() {
            self.point_count = p.points().len() as u8;
            self.point = self.point_count;
        }
        if auto.best.is_none() && range_checkpoint {
            // A review checkpoint keeps a candidate for another user-requested
            // trim. A complete replay may also be explicitly kept as-is.
            self.pending_quality = self.scan.as_ref().map(Scan::quality).unwrap_or_default();
        } else if auto.best.is_none() {
            self.pending_profile = None;
            self.pending_route = None;
            self.pending_quality = CalibrationQuality::default();
        } else if !auto.quality_allowed(self.pending_quality) {
            // Automatic target missed: keep the checked candidate for review.
            // The user may explicitly accept it with its recorded poor score.
            self.status = "OFF TARGET - REVIEW QUALITY";
        } else if matches!(reason, "REFINE WORSE - BEST KEPT" | "REFINE NO GAIN - BEST KEPT") {
            // A rejected optional edit does not undo the independently
            // checked, policy-acceptable curve that preceded it.
            self.status = "READY - CHECKED CURVE; NO EDIT";
        } else if reason.starts_with("FAILED -") || reason.starts_with("SCAN TIMEOUT") {
            // A later refinement/recheck can fail even though rollback leaves
            // the previously verified curve within the selected policy.  The
            // failure diagnostic remains available over serial, but the user
            // is reviewing that retained, acceptable curve—not a failed run.
            self.status = "REVIEW - USABLE GRADED RESULT";
        }
    }
    #[inline(never)]
    fn tick_automatic(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        value: ChannelMeasurement,
        mut controls: RuntimeControls,
        now: u64,
    ) {
        self.automatic.as_mut().unwrap().account_time(now);
        let phase = self.automatic.as_ref().unwrap().phase;
        if phase == Phase::Sweep {
            controls.mode = OperatingMode::Calibrator;
            controls.calibration_input = self.input;
            controls.calibration_output = self.output;
            self.tick_sweep(tuner, value, controls, now);
            if self.sweep.is_none() {
                if self.pending_profile.is_some() {
                    self.automatic.as_mut().unwrap().phase = Phase::Verify;
                    self.begin_auto_check(tuner, now);
                } else {
                    self.finish_automatic(tuner, self.status);
                }
            }
            return;
        }
        controls.mode = OperatingMode::Verify;
        controls.verify_scan = true;
        controls.verify_points = false;
        self.tick_verification(tuner, value, controls, now);
        if self.verifying {
            return;
        }
        if matches!(phase, Phase::Verify | Phase::Reverify) {
            if let (Some(auto), Some(scan)) = (self.automatic.as_mut(), self.scan.as_ref()) {
                auto.finish_check_timing(now, scan.tested, scan.total);
            }
        }
        if phase == Phase::Refine {
            self.automatic.as_mut().unwrap().last_refine =
                self.refinement.as_ref().and_then(|r| r.diagnostic());
            if self.status == "REFINE COMPARE UNSTABLE"
                && self.automatic.as_ref().unwrap().can_retry_unstable()
            {
                // One fresh local acquisition and paired comparison, never a
                // relaxed threshold or an unvalidated insertion. No scan restart.
                let target = self.refinement.as_ref().unwrap().check.targets[2].millicents;
                let profile = self.pending_profile.as_ref().unwrap();
                if let Ok(r) =
                    crate::oscillator_calibration::refinement::Refinement::new(profile, target)
                {
                    let pitch = r.request(profile).unwrap().millicents;
                    let auto = self.automatic.as_mut().unwrap();
                    auto.unstable_retries += 1;
                    auto.passes += 1;
                    self.refinement = Some(r);
                    self.verifying = true;
                    self.apply_target(tuner, pitch, now);
                    return;
                }
            }
            let point = self.refinement.as_ref().and_then(|r| r.ready_point());
            if let Some(point) = point {
                let candidate = self
                    .refinement
                    .as_mut()
                    .unwrap()
                    .take_candidate(self.pending_profile.as_ref().unwrap());
                if let Some(candidate) = candidate {
                    self.pending_profile = Some(candidate);
                    let auto = self.automatic.as_mut().unwrap();
                    auto.undo = Some(point);
                    auto.phase = Phase::Reverify;
                    self.begin_auto_check(tuner, now);
                    return;
                }
            }
            // A repeatable midpoint can still be too steep for a safe local
            // insertion. If paired comparison rejects that edit, keep the
            // larger contiguous side and independently verify it afresh.
            let recovered = match (self.automatic.as_mut(), self.pending_profile.as_mut()) {
                (Some(auto), Some(profile)) => auto.recover_failed_refinement(profile),
                _ => false,
            };
            if recovered {
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.refinement = None;
                self.begin_auto_check(tuner, now);
                return;
            }
            if self.status == "SCAN TIMEOUT - OUTPUT ZERO" && self.scan.is_some() {
                // A boundary was not recoverable within the bounded trim
                // policy. Keep traversing the planned check with this target
                // marked missing; do not turn a measurement deadline into a
                // whole-scan stop or claim a verified result.
                self.verifying = true;
                self.continue_automatic_after_missing(tuner, now);
                return;
            }
            self.finish_automatic(tuner, self.status);
            return;
        }
        if matches!(
            self.status,
            "SCAN TIMEOUT - OUTPUT ZERO" | "FAILED - UNSTABLE PITCH"
        ) && phase == Phase::Verify
        {
            let recovered = match (
                self.failure_voltage,
                self.scan.as_ref(),
                self.pending_profile.as_mut(),
            ) {
                (Some(uv), Some(scan), Some(profile)) => {
                    let automatic = self.automatic.as_mut().unwrap();
                    automatic.recover_edge(scan, profile, uv)
                        || automatic.recover_partial(scan, profile, uv)
                }
                _ => false,
            };
            if recovered {
                if self.status == "FAILED - UNSTABLE PITCH" {
                    self.automatic.as_mut().unwrap().last_recovery =
                        self.failure_voltage.map(|uv| (uv, "UNSTABLE REPLAY"));
                }
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.recovered_verification = self.failure_verification;
                self.recovered_verification_diagnostic =
                    self.failure_verification_diagnostic;
                self.failure_voltage = None;
                self.failure_verification = None;
                // The failed target has been removed from the candidate range.
                // Do not retain its verbose detector snapshot while reporting
                // the restarted pass: stale diagnostics can crowd the bounded
                // serial report and hide the eventual review summary.
                self.failure_verification_diagnostic = None;
                self.begin_auto_check(tuner, now);
                return;
            }
        }
        if self.status == "SCAN DONE - MISSING TARGETS" {
            // A completed pass can contain one timed-out target while all
            // later targets were measured. Recover around the *actual* gap,
            // then check only that new boundary before a final full replay.
            // Never certify the incomplete pass itself.
            let recovered = if phase == Phase::Verify {
                match (self.scan.as_ref(), self.pending_profile.as_mut()) {
                    (Some(scan), Some(profile)) => self.automatic
                        .as_mut().unwrap().recover_missing_regions(scan, profile),
                    _ => false,
                }
            } else {
                false
            };
            if recovered {
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.begin_auto_check(tuner, now);
                return;
            }
            self.finish_automatic(tuner, if phase == Phase::Reverify {
                "REVIEW - RECHECK INCOMPLETE"
            } else {
                "REVIEW - INCOMPLETE CHECK"
            });
            return;
        }
        if self.status != "SCAN DONE - OUTPUT ZERO"
            || !self.scan.as_ref().is_some_and(|s| s.complete)
        {
            self.finish_automatic(tuner, self.status);
            return;
        }
        // A timeout is a missing observation, not a synthetic zero-error
        // pitch. Finish every planned target and offer the measured curve for
        // explicit review, but never auto-certify an incomplete replay.
        if self.scan.as_ref().is_some_and(|s| s.missing != 0) {
            self.finish_automatic(tuner, if phase == Phase::Reverify {
                "REVIEW - RECHECK INCOMPLETE"
            } else {
                "REVIEW - INCOMPLETE CHECK"
            });
            return;
        }
        // Boundary recovery probes only the affected half-volt. A successful
        // local probe does not certify the other octaves: perform exactly one
        // fresh full-range check after the boundary has stopped moving.
        if phase == Phase::Verify && self.automatic.as_ref().unwrap().regional_check {
            let recovered = match (self.scan.as_ref(), self.pending_profile.as_mut()) {
                (Some(scan), Some(profile)) => self.automatic.as_mut().unwrap()
                    .recover_completed(scan, profile),
                _ => false,
            };
            if recovered {
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.begin_auto_check(tuner, now);
                return;
            }
            self.automatic.as_mut().unwrap().regional_check = false;
            self.begin_auto_check(tuner, now);
            return;
        }
        // A complete scan with an unsafe *localized* error need not discard
        // several octaves that replayed correctly. Cut at the bad target and
        // verify the remaining contiguous range afresh. The user still has
        // to accept the resulting limited-range candidate explicitly.
        if phase == Phase::Verify {
            let recovered = match (self.scan.as_ref(), self.pending_profile.as_mut()) {
                (Some(scan), Some(profile)) => self
                    .automatic
                    .as_mut()
                    .unwrap()
                    .recover_completed(scan, profile),
                _ => false,
            };
            if recovered {
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.recovered_verification_diagnostic = None;
                self.begin_auto_check(tuner, now);
                return;
            }
            // No user-driven recovery checkpoint: either continue to a
            // measured refinement below or finish with this reviewed curve.
        }
        let scan = self.scan.as_ref().unwrap();
        let auto = self.automatic.as_mut().unwrap();
        let accepted = auto.improves(scan);
        if let Some(old) = auto.best.as_ref() {
            auto.last_recheck = Some((old.checked_worst().1, scan.checked_worst().1, accepted));
        }
        if !accepted {
            if phase == Phase::Reverify {
                // A rejected tentative edit does not invalidate the earlier
                // checked curve. If that curve was still unsafe, roll the edit
                // back and keep searching its largest usable measured side.
                self.rollback_auto();
                let recovered = match self.pending_profile.as_mut() {
                    Some(profile) => self.automatic.as_mut().unwrap()
                        .recover_rejected_recheck(profile),
                    None => false,
                };
                if recovered {
                    self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                    self.point = self.point_count;
                    self.begin_auto_check(tuner, now);
                    return;
                }
            }
            self.finish_automatic(tuner, "REVIEW - RECHECK REJECTED");
            return;
        }
        auto.undo = None;
        auto.best = Some(scan.clone());
        // A later grid/local disagreement is not evidence for another curve
        // anchor. Recover a contiguous measured side, then independently
        // replay that smaller candidate before offering it to the user.
        if phase == Phase::Reverify {
            let recovered = match (self.scan.as_ref(), self.pending_profile.as_mut()) {
                (Some(scan), Some(profile)) => auto.recover_recheck_disagreement(scan, profile),
                _ => false,
            };
            if recovered {
                self.point_count = self.pending_profile.as_ref().unwrap().points().len() as u8;
                self.point = self.point_count;
                self.recovered_verification_diagnostic = None;
                self.begin_auto_check(tuner, now);
                return;
            }
        }
        let profile = self.pending_profile.as_ref().unwrap();
        if let Some(reason) = auto.stop_reason(scan, profile.points().len()) {
            self.finish_automatic(tuner, reason);
            return;
        }
        let refinement = scan.local.as_ref()
            .ok_or("REFINE LOCAL CHECK INCOMPLETE")
            .and_then(|check| {
                crate::oscillator_calibration::refinement::Refinement::from_verified_check(
                    profile, check,
                )
            });
        match refinement {
            Ok(r) => {
                let pitch = r.request(profile).unwrap().millicents;
                auto.passes += 1;
                auto.phase = Phase::Refine;
                self.refinement = Some(r);
                self.verifying = true;
                self.apply_target(tuner, pitch, now);
            }
            Err(reason) => self.finish_automatic(tuner, reason),
        }
    }
    // Verification/refinement must not nest under the sweep's profile-copy
    // temporaries. Keep these mutually exclusive stack frames separate.
    fn continue_automatic_after_missing(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        now: u64,
    ) {
        let mut start_local = false;
        {
            let scan = self.scan.as_mut().unwrap();
            if scan.first_missing_uv.is_none() {
                scan.first_missing_uv = self.failure_voltage;
            }
            if let Some(local) = scan.local.as_mut() {
                local.record_missing();
                scan.missing += 1;
            } else {
                scan.record_missing();
                // A gap already invalidates this pass. Finish observing the
                // remaining grid before selecting a contiguous region; the
                // nine local repeats cannot certify a grid with missing data.
                start_local = scan.complete && scan.missing == 0;
            }
        }
        if start_local {
            let profile = self.pending_profile.as_ref().unwrap();
            let pitch = self.scan.as_ref().unwrap().worst_pitch;
            self.scan.as_mut().unwrap().local =
                crate::oscillator_calibration::verification_scan::LocalCheck::new(profile, pitch);
        }
        let next = self.scan.as_ref().unwrap().local.as_ref().and_then(|c| c.next())
            .map(|point| point.millicents)
            .or_else(|| {
                let scan = self.scan.as_ref().unwrap();
                (!scan.complete).then_some(scan.target)
            });
        if let Some(pitch) = next {
            self.apply_target(tuner, pitch, now);
        } else {
            let reason = if self.scan.as_ref().unwrap().missing == 0 {
                "SCAN DONE - OUTPUT ZERO"
            } else {
                "SCAN DONE - MISSING TARGETS"
            };
            self.stop_verify(tuner, reason);
        }
    }
    /// A diagnostic CHECK should cover the rest of the measured range even
    /// when one target has no stable pitch. Missing targets remain explicit
    /// gaps and can never count as a successful full-range verification.
    fn continue_readonly_scan_after_missing(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        now: u64,
    ) {
        let scan = self.scan.as_mut().unwrap();
        let next = if let Some(local) = scan.local.as_mut() {
            local.record_missing();
            scan.missing += 1;
            local.next().map(|point| point.millicents)
        } else if scan.record_missing() && !scan.complete {
            Some(scan.target)
        } else {
            None
        };
        if let Some(target) = next {
            self.apply_target(tuner, target, now);
        } else {
            self.stop_verify(tuner, "SCAN DONE - MISSING TARGETS");
        }
    }
    #[inline(never)]
    fn tick_verification(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        value: ChannelMeasurement,
        controls: RuntimeControls,
        now: u64,
    ) {
        if self.verifying {
            self.tick_verify(tuner, controls, now);
            let fresh = self.previous_sequence != Some(value.sequence);
            // Both automatic replay and the read-only CHECK scan command a
            // known target. Use the same bounded estimator for both; the
            // free-running manual pitch readout still uses its original path.
            let target_guided = self.scan.is_some();
            self.error_cents = if self.verifying && self.status=="CORRECTED TARGET ACTIVE"
                && value.valid && (value.qualified || target_guided)
                // Scan windows include the entire permitted 100 ms ACK delay
                // plus the short settling guard, and reject stale ends.
                && (self.scan.is_none() || value.end_age_ms<=100)
                && now.saturating_sub(self.verify_started)>=
                    (if self.scan.as_ref().is_some_and(|s|s.repeat_check().is_some()) {2000}
                     else if self.scan.is_some() {SCAN_WINDOW_START_MS} else {350})+value.window_age_ms as u64
            {
                {
                    let measured = pitch_math::millicents(value.frequency_hz, 440.0);
                    // During a profile scan the commanded target is
                    // independent evidence. Resolve only an octave-equivalent
                    // reading already within 150 cents of that target. Manual
                    // free tuning and the main tuner remain untouched.
                    let selected = if target_guided {
                        // Automatic replay has an independent commanded target.
                        // A summed/ensemble oscillator can briefly publish a
                        // strong unrelated partial between correct fundamental
                        // readings. Ignore that candidate instead of letting it
                        // erase target-adjacent evidence; max-age and timeout
                        // bounds still require eight recent matching readings.
                        crate::oscillator_calibration::period_family_near(
                            measured,
                            self.target_millicents,
                            150_000,
                        )
                        .map(|v| v.0)
                    } else {
                        Some(measured)
                    };
                    selected.map(|pitch| (pitch - self.target_millicents) as f32 / 1000.0)
                }
            } else {
                None
            };
            let settled = self.verifying
                && self.status == "CORRECTED TARGET ACTIVE"
                && value.end_age_ms <= 100
                && now.saturating_sub(self.verify_started)
                    >= (if self.scan.as_ref().is_some_and(|s| s.repeat_check().is_some()) {
                        2000
                    } else if self.scan.is_some() {
                        SCAN_WINDOW_START_MS
                    } else {
                        350
                    }) + value.window_age_ms as u64;
            self.verify_diagnostic
                .observe(value, fresh, settled, self.error_cents.is_some());
            let mut averaged = None;
            let mut tight = None;
            // Low notes always need independent detector windows. Automatic
            // replay may use the same bounded estimator at any pitch: some
            // digitally controlled oscillators are audibly stationary but
            // quantize adjacent instantaneous period estimates several cents
            // apart. The estimator still requires sixteen non-overlapping
            // windows whose quarter and half-block means agree, so drift,
            // beating, and period-family errors remain rejected.
            let bounded_average =
                self.scan.is_some() && (self.target_millicents <= LOW_PITCH || target_guided);
            let (guided_max_span, quarter_delta, half_delta) = self
                .automatic
                .as_ref()
                .filter(|a| a.active())
                .map_or((25_000, 5_000, 2_500), |a| match a.policy {
                    crate::options::CalibrationPolicy::Precision => (25_000, 2_000, 1_000),
                    // Auto's final grade separately reports 3/5/10-cent
                    // stability. Allow modest within-window drift here so
                    // a 5.6c raw span and 1.9c half-block shift can be
                    // graded as Character instead of erasing the whole
                    // upper range as a verification timeout.
                    crate::options::CalibrationPolicy::Auto | crate::options::CalibrationPolicy::Fast => (25_000, 5_000, 2_500),
                    crate::options::CalibrationPolicy::Forgiving => (25_000, 10_000, 5_000),
                });
            if !value.valid {
                self.statistics.clear();
                self.average.clear();
                self.previous_sequence = Some(value.sequence);
            } else if self.previous_sequence != Some(value.sequence) {
                self.previous_sequence = Some(value.sequence);
                // During automatic replay, valid but ambiguous frames are
                // distractors rather than evidence of silence. Preserve only
                // recent target-adjacent samples across them. Manual VERIFY and
                // acquisition retain their stricter reset-on-rejection behavior.
                if !target_guided || self.error_cents.is_some() {
                    self.statistics
                        .observe(self.error_cents, value.sequence, now);
                }
                if bounded_average && (!target_guided || self.error_cents.is_some()) {
                    if let Some(error) = self.error_cents {
                        averaged = self.average.observe_with_limits(
                            (error * 1000.0) as i32,
                            now.saturating_sub(value.window_age_ms as u64),
                            now.saturating_sub(value.end_age_ms as u64),
                            if target_guided {
                                if self.target_millicents <= LOW_PITCH {
                                    guided_max_span.min(
                                        crate::oscillator_calibration::averaging::MAX_SPAN,
                                    )
                                } else {
                                    guided_max_span
                                }
                            } else {
                                crate::oscillator_calibration::averaging::MAX_SPAN
                            },
                            quarter_delta,
                            half_delta,
                        );
                        tight = self.average.tight_estimate();
                    } else {
                        self.average.clear();
                    }
                } else if bounded_average && !target_guided {
                    self.average.clear();
                }
            }
            // Independent windows need more time than the manual readout's
            // 500 ms statistics window.
            self.deviation = if bounded_average && self.target_millicents <= LOW_PITCH {
                tight
                    .map(|v| Summary {
                        mean: v.mean as f32 / 1000.0,
                        spread: v.spread as f32 / 1000.0,
                        count: 8,
                        averaged: false,
                    })
                    .or_else(|| {
                        averaged.map(|v| Summary {
                            mean: v.mean as f32 / 1000.0,
                            spread: v.spread as f32 / 1000.0,
                            count: crate::oscillator_calibration::averaging::WINDOWS,
                            averaged: true,
                        })
                    })
            } else if bounded_average {
                // Preserve the established fast path for tightly clustered
                // high notes. Use the longer independent-window estimate only
                // when instantaneous digital estimates exceed that 3c bound.
                self.statistics
                    .summary_with_max_age(now, 4000)
                    .filter(|s| s.settled(self.target_millicents))
                    .or_else(|| {
                        averaged.map(|v| Summary {
                            mean: v.mean as f32 / 1000.0,
                            spread: v.spread as f32 / 1000.0,
                            count: crate::oscillator_calibration::averaging::WINDOWS,
                            averaged: true,
                        })
                    })
            } else if self.scan.is_some() {
                self.statistics.summary_with_max_age(now, 4000)
            } else {
                self.statistics.summary(now)
            };
            if self.verifying && self.scan.is_some() {
                // A missing/unstable signal must not leave a scan holding a
                // pitch forever. Manual VERIFY remains an explicitly held CV.
                if now.saturating_sub(self.verify_started)
                    >= crate::oscillator_calibration::automatic::VERIFY_TIMEOUT_MS
                        + if self.verify_extended { 3_000 } else { 0 }
                {
                    let average = self.average.snapshot();
                    // A qualified, target-adjacent tone can yield fewer than
                    // sixteen *non-overlapping* windows in five seconds. Keep
                    // the accumulated evidence at the same CV for one short
                    // extension rather than discarding an otherwise usable
                    // half of the oscillator's range. This never accepts an
                    // incomplete estimate: normal quality checks still need
                    // all sixteen windows and reject drift or ambiguity.
                    if !self.verify_extended
                        && incomplete_replay_extension(
                            target_guided,
                            &average,
                            &self.verify_diagnostic,
                        )
                    {
                        self.verify_extended = true;
                        return;
                    }
                    // A full-range check begins with a potentially large
                    // downward jump. Permit exactly one fresh acquisition at
                    // this unchanged voltage. Other targets retain their 5s
                    // timeout, with one bounded same-CV retry only if they
                    // actually produced mild, target-adjacent pitch evidence.
                    let first_auto_check = self
                        .automatic
                        .as_ref()
                        .is_some_and(|a| matches!(a.phase, Phase::Verify | Phase::Reverify))
                        && self
                            .scan
                            .as_ref()
                            .is_some_and(|s| s.tested == 0 && s.local.is_none());
                    // A real, target-adjacent tone that drifts a few cents
                    // should get one independent retry at the *same* CV.
                    // Trimming the entire upper range on a single such
                    // window discards valid points. Gross drift, silence and
                    // period-family ambiguity remain ineligible.
                    let mild_unstable_check = target_guided
                        && !self.verify_diagnostic.ambiguous_waveform()
                        && self.verify_diagnostic.settled_fresh >= 16
                        && self.verify_diagnostic.target_near >= 16
                        && average.count == crate::oscillator_calibration::averaging::WINDOWS
                        && average.raw_span <= 10_000
                        && average.quarter_delta <= 5_000;
                    if (first_auto_check || mild_unstable_check) && !self.verify_retried {
                        self.verify_retried = true;
                        self.verify_extended = false;
                        self.verify_started = now;
                        self.average.clear();
                        self.statistics.clear();
                        self.verify_diagnostic = VerificationDiagnostic::new();
                        self.deviation = None;
                        self.error_cents = None;
                        self.previous_sequence = Some(value.sequence);
                        return;
                    }
                    self.failure_voltage = bipolar::decode_voltage(self.verify_command as u16);
                    self.failure_verification = Some(average);
                    self.failure_verification_diagnostic = Some(self.verify_diagnostic);
                    let reason = if target_guided && self.verify_diagnostic.ambiguous_waveform() {
                        "FAILED - AMBIGUOUS WAVEFORM"
                    } else if target_guided
                        && average.count == crate::oscillator_calibration::averaging::WINDOWS
                        && (average.quarter_delta > quarter_delta
                            || average.half_delta > half_delta)
                    {
                        "FAILED - UNSTABLE PITCH"
                    } else {
                        "SCAN TIMEOUT - OUTPUT ZERO"
                    };
                    if self.automatic.is_none()
                        && self.scan.as_ref().is_some_and(|scan| {
                            scan.local.as_ref().is_some_and(|local| local.tested < 9)
                                || (!scan.complete && scan.local.is_none() && !scan.points_mode
                                && scan.repeat_check().is_none()
                                )
                        })
                    {
                        self.continue_readonly_scan_after_missing(tuner, now);
                    } else if self.automatic.as_ref().is_some_and(|a| {
                        matches!(a.phase, Phase::Verify | Phase::Reverify)
                    }) {
                        // Observe the entire planned grid before deciding
                        // where the usable portion lies. Unstable or missing
                        // pitch is a gap, never a synthetic correct reading.
                        self.continue_automatic_after_missing(tuner, now);
                    } else {
                        self.stop_verify(tuner, reason);
                    }
                } else if let Some(summary) = self
                    .deviation
                    .filter(|_| self.error_cents.is_some() && value.end_age_ms <= 100)
                {
                    if let Some(r) = self.refinement.as_mut().filter(|r| r.active()) {
                        let profile = if self.automatic.as_ref().is_some_and(|a| a.active()) {
                            self.pending_profile.as_ref().unwrap()
                        } else {
                            self.profile.as_ref().unwrap()
                        };
                        r.record(profile, summary);
                        if let Some(point) = r.request(profile) {
                            self.apply_target(tuner, point.millicents, now);
                        } else {
                            let reason = r.reason;
                            self.stop_verify(tuner, reason);
                        }
                        return;
                    }
                    let scan = self.scan.as_mut().unwrap();
                    if scan.repeat_check().is_some() {
                        if scan.record_repeat(self.profile.as_ref().unwrap(), summary) {
                            if scan.complete {
                                self.stop_verify(tuner, "REPEAT DONE - OUTPUT ZERO");
                            } else {
                                let target = scan.target;
                                self.apply_target(tuner, target, now);
                            }
                        }
                        return;
                    }
                    if let Some(check) = scan.local.as_mut() {
                        if check.record(summary) {
                            if let Some(point) = check.next() {
                                let target = point.millicents;
                                self.apply_target(tuner, target, now);
                            } else {
                                let reason = if scan.missing == 0 {
                                    "SCAN DONE - OUTPUT ZERO"
                                } else {
                                    "SCAN DONE - MISSING TARGETS"
                                };
                                self.stop_verify(tuner, reason);
                            }
                        }
                        return;
                    }
                    if scan.record(summary) {
                        if scan.complete {
                            if scan.missing != 0 {
                                self.stop_verify(tuner, "SCAN DONE - MISSING TARGETS");
                                return;
                            }
                            let recover_grid = self.automatic.as_ref()
                                .is_some_and(|a| a.skip_local_for_grid_recovery(scan));
                            if recover_grid {
                                let auto = self.automatic.as_mut().unwrap();
                                auto.skipped_local_checks = auto.skipped_local_checks.saturating_add(1);
                            }
                            if !scan.points_mode && !recover_grid {
                                scan.local=crate::oscillator_calibration::verification_scan::LocalCheck::new(
                                    if self.automatic.as_ref().is_some_and(|a|a.active()) {
                                        self.pending_profile.as_ref().unwrap()
                                    } else {self.profile.as_ref().unwrap()},scan.worst_pitch);
                            }
                            if let Some(check) = scan.local.as_ref() {
                                let target = check.targets[0].millicents;
                                self.apply_target(tuner, target, now);
                            } else {
                                self.stop_verify(tuner, "SCAN DONE - OUTPUT ZERO");
                            }
                        } else {
                            if scan.points_mode {
                                scan.target = self.profile.as_ref().unwrap().points()
                                    [scan.tested as usize]
                                    .millicents;
                            }
                            let target = scan.target;
                            self.apply_target(tuner, target, now);
                        }
                    }
                }
            }
            return;
        }
    }
    #[inline(never)]
    fn tick_sweep(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        value: ChannelMeasurement,
        controls: RuntimeControls,
        now: u64,
    ) {
        let Some(s) = self.sweep.as_mut() else {
            return;
        };
        if controls.mode != OperatingMode::Calibrator
            || controls.calibration_input != self.input
            || controls.calibration_output != self.output
        {
            s.cancel();
        }
        let status = tuner.cal_status().read().value().bits();
        if status & 512 != 0 {
            if self.failure_output_status.is_none() {
                self.failure_output_status = Some(status);
                self.failure_output_cause = "DAC FAULT";
            }
            s.output_failed();
        }
        let sample = if self.previous_sequence != Some(value.sequence) {
            self.previous_sequence = Some(value.sequence);
            self.sequence += 1;
            Some(Measurement {
                input: self.input,
                sequence: self.sequence,
                window_start_ms: now.saturating_sub(value.window_age_ms as u64),
                window_end_ms: now.saturating_sub(value.end_age_ms as u64),
                millicents: if value.valid {
                    pitch_math::millicents(value.frequency_hz, 440.0)
                } else {
                    0
                },
                qualified: value.qualified && value.valid,
            })
        } else {
            None
        };
        let mut request = s.poll(now, sample);
        self.period_family_corrections = s.period_family_corrections();
        self.scan_warnings = s.warnings();
        self.tracking_failure = s.tracking_failure();
        self.zero_error_cents = s.origin_error().map(|v| v as f32 / 1000.0);
        let acknowledged = match request {
            Request::Apply { token, .. } => {
                self.waiting == Some(token) && status & 255 == token as u32 && status & 256 != 0
            }
            Request::Disable { token, .. } => {
                self.waiting == Some(token) && status & 255 == token as u32 && status & 256 == 0
            }
            _ => false,
        };
        if acknowledged {
            s.acknowledge(self.waiting.unwrap(), now);
            request = s.poll(now, None);
        }
        self.failure_voltage = s.failure_voltage();
        match request {
            Request::Apply {
                output,
                microvolts,
                token,
            } => {
                self.status = "SETTLING / MEASURING";
                self.millivolts = microvolts / 1000;
                self.point = s.point_count() as u8;
                let Some(bits) = bipolar::encode_profile_voltage(microvolts) else {
                    self.failure_output_status = Some(status);
                    self.failure_output_cause = "CV ENCODE RANGE";
                    s.output_failed();
                    tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
                    return;
                };
                let command = bits as u32
                    | ((output as u32) << 16)
                    | (1 << 18)
                    | ((self.input as u32) << 19)
                    | ((token as u32) << 21);
                self.sweep_command = command;
                tuner
                    .cal_command()
                    .write(|w| unsafe { w.value().bits(command) });
                self.waiting = Some(token);
            }
            Request::Wait => {
                // Renew the current output even between fresh detector windows.
                // Re-send the exact DAC command, never reconstruct it from
                // the rounded display value (dense points have fractional mV).
                tuner
                    .cal_command()
                    .write(|w| unsafe { w.value().bits(self.sweep_command) });
            }
            Request::Disable { output, token } => {
                self.sweep_command = 0;
                if self.failure_output_status.is_none() {
                    self.failure_output_status = Some(status);
                    self.failure_output_cause = "DISABLE / PENDING";
                }
                self.status = "RESTORING ZERO";
                tuner.cal_command().write(|w| unsafe {
                    w.value()
                        .bits(((output as u32) << 16) | ((token as u32) << 21))
                });
                self.waiting = Some(token);
            }
            Request::Finished(outcome) => {
                if matches!(outcome, Outcome::Failed(Failure::Output))
                    && self.failure_output_cause == "DISABLE / PENDING"
                {
                    self.failure_output_cause = "NO ACK / TIMEOUT";
                }
                if !matches!(outcome, Outcome::Failed(Failure::Output)) {
                    self.failure_output_status = None;
                    self.failure_output_cause = "";
                }
                if matches!(outcome, Outcome::Failed(_)) {
                    self.failure_acquisition = Some(s.acquisition_diagnostic());
                }
                self.sweep_timing = s.timing();
                let ambiguous_acquisition = self.failure_acquisition.is_some_and(|d| {
                    self.point == 0 && d.qualified == 0 && d.unqualified >= 16 && d.tight_count == 0
                });
                let mut limited = false;
                let zero_pitch = s.zero_pitch();
                if let Some(curve) = s.take_curve() {
                    let mut profile =
                        Profile::new("RAM profile", bipolar::MIN_UV, bipolar::MAX_UV).unwrap();
                    for point in curve.points() {
                        profile.push(*point).unwrap();
                    }
                    if let Some(pitch) = zero_pitch { profile.set_zero_pitch(Some(pitch)).ok(); }
                    profile.limited_low = curve.limited_low;
                    profile.limited_high = curve.limited_high;
                    limited = profile.limited_low || profile.limited_high;
                    self.point = profile.points().len() as u8;
                    self.point_count = self.point;
                    self.pending_profile = Some(profile);
                    self.pending_route = Route::new(self.input, self.output).ok();
                }
                self.status = match outcome {
                    Outcome::Complete if limited => "REVIEW LIMITED RANGE - ACCEPT?",
                    Outcome::Complete => "REVIEW RANGE - ACCEPT?",
                    Outcome::Cancelled => "CANCELLED - OUTPUT ZERO",
                    Outcome::Failed(Failure::NoOrigin) => "FAILED - NO USABLE PITCH",
                    Outcome::Failed(Failure::OriginLost) if ambiguous_acquisition => {
                        "FAILED - AMBIGUOUS WAVEFORM"
                    }
                    Outcome::Failed(Failure::OriginLost) => "FAILED - REFERENCE PITCH LOST",
                    Outcome::Failed(Failure::OriginChanged) => "FAILED - REFERENCE PITCH CHANGED",
                    Outcome::Failed(Failure::NotTracking) => "FAILED - NOT TRACKING",
                    Outcome::Failed(Failure::UnstablePitch) => "FAILED - PITCH NOT STABLE",
                    Outcome::Failed(Failure::RangeBeforeZero) => {
                        "FAILED - RANGE ENDED BEFORE REFERENCE"
                    }
                    _ => "FAILED - OUTPUT/CLOCK",
                };
                self.sweep = None;
                self.sweep_command = 0;
                self.waiting = None;
                self.millivolts = 0;
            }
        }
    }
}
