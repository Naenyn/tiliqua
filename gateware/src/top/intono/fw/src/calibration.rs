//! Allocation-free profile math, independent of UI focus, flash and hardware.
//! Acquisition must qualify settled pitches before inserting points. These
//! types alone do not establish confidence or authorize a DAC write.

pub const INITIAL_POINTS: usize = 121;
pub const REFINEMENT_POINTS: usize = 8;
pub const MAX_POINTS: usize = INITIAL_POINTS + REFINEMENT_POINTS;
pub const NAME_BYTES: usize = 24;
/// A useful profile must cover at least one octave at semitone density.
pub const MIN_PROFILE_POINTS: usize = 13;

#[path = "calibration/automatic.rs"]
pub mod automatic;
#[path = "calibration/averaging.rs"]
pub mod averaging;
#[path = "calibration/deviation.rs"]
pub mod deviation;
#[path = "calibration/discovery.rs"]
pub mod discovery;
#[path = "calibration/name.rs"]
pub mod name;
#[path = "calibration/plan.rs"]
pub mod plan;
#[path = "calibration/playback.rs"]
pub mod playback;
#[path = "calibration/refinement.rs"]
pub mod refinement;
#[path = "calibration/storage.rs"]
pub mod storage;
#[path = "calibration/sweep.rs"]
pub mod sweep;
#[path = "calibration/verification_scan.rs"]
pub mod verification_scan;

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Error {
    InvalidName,
    InvalidChannel,
    InvalidLimits,
    VoltageOutsideLimits,
    NonMonotonic,
    Full,
    Incomplete,
    PitchOutsideRange,
}

/// Actual applied output voltage and measured pitch in logarithmic units.
/// Pitch is milli-cents relative to MIDI note zero (100_000 per semitone).
#[derive(Clone, Copy, Default, Debug, PartialEq)]
pub struct Point {
    pub microvolts: i32,
    pub millicents: i32,
}

/// Result of the independent replay check stored alongside a calibration
/// profile. `Unverified` is reserved for legacy records. `Unsafe` means the
/// automatic quality target was missed, not that a completed curve is unusable.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
#[repr(u8)]
pub enum CalibrationGrade {
    #[default]
    Unverified = 0,
    Precision = 1,
    Musical = 2,
    Character = 3,
    Unsafe = 4,
    UserAccepted = 5,
}

impl CalibrationGrade {
    pub fn from_u8(value: u8) -> Option<Self> {
        Some(match value {
            0 => Self::Unverified,
            1 => Self::Precision,
            2 => Self::Musical,
            3 => Self::Character,
            4 => Self::Unsafe,
            5 => Self::UserAccepted,
            _ => return None,
        })
    }

    pub fn label(self) -> &'static str {
        match self {
            Self::Unverified => "UNVERIFIED",
            Self::Precision => "PRECISION",
            Self::Musical => "MUSICAL",
            Self::Character => "CHARACTER",
            Self::Unsafe => "UNSAFE",
            Self::UserAccepted => "USER-KEPT",
        }
    }

    pub fn acceptable(self) -> bool {
        matches!(self, Self::Precision | Self::Musical | Self::Character | Self::UserAccepted)
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct CalibrationQuality {
    pub grade: CalibrationGrade,
    pub worst_millicents: u32,
    pub stability_millicents: u32,
}

impl CalibrationQuality {
    pub fn acceptable(self) -> bool {
        self.grade.acceptable()
    }

    pub fn worst_cents(self) -> f32 {
        self.worst_millicents as f32 / 1000.0
    }

    pub fn stability_cents(self) -> f32 {
        self.stability_millicents as f32 / 1000.0
    }

    /// Advisory score: 100 at zero error, losing one point per cent of the
    /// larger of worst replay error and repeatability span. One semitone or
    /// more is zero. It is not a probability or an acceptance threshold.
    pub fn score_percent(self) -> Option<u8> {
        if matches!(self.grade, CalibrationGrade::Unverified)
            || (self.grade == CalibrationGrade::Unsafe
                && self.worst_millicents == 0 && self.stability_millicents == 0)
        {
            return None;
        }
        let cents = self.worst_millicents.max(self.stability_millicents)
            .saturating_add(500) / 1000;
        Some(100u32.saturating_sub(cents).min(100) as u8)
    }
}

/// Select the small-integer period-family reading nearest a known pitch.
///
/// Autocorrelation can expose competing integer-related periods for some
/// otherwise stable waveforms.  This helper is deliberately calibration-only:
/// callers must already have an independent expected pitch (an established
/// sweep trajectory or a verification target).  It never changes the live
/// tuner's stateless reading.
pub fn period_family_near(measured: i32, expected: i32, tolerance: i32) -> Option<(i32, i8)> {
    if tolerance < 0 {
        return None;
    }
    // Pitch offsets between the first four integer-related periods. Besides
    // octave and third-period errors, selectors can move directly between e.g.
    // the third and fourth harmonic (4/3) or second and third (3/2). Values
    // are milli-cents; the compact family id is diagnostic only.
    const FAMILIES: [(i32, i8); 11] = [
        (-2_400_000, -4),
        (-1_901_955, -3),
        (-1_200_000, -2),
        (-701_955, -6),
        (-498_045, -5),
        (0, 1),
        (498_045, 5),
        (701_955, 6),
        (1_200_000, 2),
        (1_901_955, 3),
        (2_400_000, 4),
    ];
    let mut best = None;
    for (offset, family) in FAMILIES {
        let candidate = measured as i64 + offset as i64;
        if !(i32::MIN as i64..=i32::MAX as i64).contains(&candidate) {
            continue;
        }
        let error = (candidate - expected as i64).unsigned_abs();
        if error <= tolerance as u64 && best.map_or(true, |(_, _, old)| error < old) {
            best = Some((candidate as i32, family, error));
        }
    }
    best.map(|(pitch, family, _)| (pitch, family))
}

/// Explicit patch routing, never derived from the tuner's focused input.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Route {
    input: u8,
    output: u8,
}

impl Route {
    pub fn new(input: u8, output: u8) -> Result<Self, Error> {
        if input > 3 || output > 3 {
            return Err(Error::InvalidChannel);
        }
        Ok(Self { input, output })
    }
    pub fn input(self) -> u8 {
        self.input
    }
    pub fn output(self) -> u8 {
        self.output
    }
}

/// A measured, increasing V/oct response. Storage serialization is deliberately
/// separate: future recall must validate all points rather than trust raw bytes.
#[derive(Clone)]
pub struct Profile {
    // i32::MIN means no qualified 0 V observation (never extrapolate one).
    zero_pitch: i32,
    pub limited_low: bool,
    pub limited_high: bool,
    name: [u8; NAME_BYTES],
    name_len: u8,
    points: [Point; MAX_POINTS],
    count: u8,
    min_uv: i32,
    max_uv: i32,
}

impl Profile {
    /// Limits must come from the configured/calibrated output capability and
    /// user's allowed sweep range. No universal hardware voltage is assumed.
    pub fn new(name: &str, min_uv: i32, max_uv: i32) -> Result<Self, Error> {
        if min_uv >= max_uv {
            return Err(Error::InvalidLimits);
        }
        let mut profile = Self {
            zero_pitch: i32::MIN,
            limited_low: false,
            limited_high: false,
            name: [0; NAME_BYTES],
            name_len: 0,
            points: [Point::default(); MAX_POINTS],
            count: 0,
            min_uv,
            max_uv,
        };
        profile.rename(name)?;
        Ok(profile)
    }

    /// Printable ASCII matches the renderer; reject rather than silently
    /// truncate names or accept characters that cannot be displayed.
    pub fn rename(&mut self, name: &str) -> Result<(), Error> {
        if name.is_empty()
            || name.len() > NAME_BYTES
            || name.trim().is_empty()
            || !name.bytes().all(|b| (b' '..=b'~').contains(&b))
        {
            return Err(Error::InvalidName);
        }
        self.name.fill(0);
        self.name[..name.len()].copy_from_slice(name.as_bytes());
        self.name_len = name.len() as u8;
        Ok(())
    }

    pub fn name(&self) -> &str {
        // rename is the only writer, and accepts only ASCII.
        core::str::from_utf8(&self.name[..self.name_len as usize]).unwrap_or("")
    }

    pub fn points(&self) -> &[Point] {
        &self.points[..self.count as usize]
    }

    /// Remove measured anchors through an unreliable replay boundary. This is
    /// deliberately destructive only to a pending candidate: it never invents
    /// points, extrapolates, or permits a sub-octave profile to survive.
    pub fn trim_low_through(&mut self, microvolts: i32, max_remove: usize) -> usize {
        let remove = self
            .points()
            .partition_point(|p| p.microvolts <= microvolts);
        if remove == 0
            || remove > max_remove
            || self.points().len().saturating_sub(remove) < MIN_PROFILE_POINTS
        {
            return 0;
        }
        self.points.copy_within(remove..self.count as usize, 0);
        self.count -= remove as u8;
        self.points[self.count as usize..].fill(Point::default());
        self.limited_low = true;
        remove
    }
    pub fn trim_high_from(&mut self, microvolts: i32, max_remove: usize) -> usize {
        let first = self.points().partition_point(|p| p.microvolts < microvolts);
        let remove = self.points().len().saturating_sub(first);
        if remove == 0
            || remove > max_remove
            || self.points().len().saturating_sub(remove) < MIN_PROFILE_POINTS
        {
            return 0;
        }
        self.count -= remove as u8;
        self.points[self.count as usize..].fill(Point::default());
        self.limited_high = true;
        remove
    }

    pub fn zero_pitch(&self) -> Option<i32> {
        (self.zero_pitch != i32::MIN).then_some(self.zero_pitch)
    }
    pub fn set_zero_pitch(&mut self, pitch: Option<i32>) -> Result<(), Error> {
        if pitch.is_some_and(|p| !(0..=12_800_000).contains(&p)) {
            return Err(Error::PitchOutsideRange);
        }
        self.zero_pitch = pitch.unwrap_or(i32::MIN);
        Ok(())
    }
    /// Nearest concert-pitch note, not the middle of the usable curve.
    pub fn natural_note(&self) -> Option<u8> {
        let note = (self.zero_pitch()? as i64 + 50_000).div_euclid(100_000);
        (12..=108).contains(&note).then_some(note as u8)
    }

    pub fn suggested_note(&self) -> Option<u8> {
        let points = self.points();
        if points.len() < 2 {
            return None;
        }
        let low = ((points[0].millicents as i64 + 99999).div_euclid(100000)).max(12);
        let high = (points.last()?.millicents as i64)
            .div_euclid(100000)
            .min(108);
        if low > high {
            None
        } else {
            Some(((low + high) / 2) as u8)
        }
    }

    /// Append only an already-qualified measurement. Reject duplicate voltage,
    /// pitch reversals and flat tracking; never sort away a failed sweep.
    pub fn push(&mut self, point: Point) -> Result<(), Error> {
        if point.microvolts < self.min_uv || point.microvolts > self.max_uv {
            return Err(Error::VoltageOutsideLimits);
        }
        if let Some(last) = self.points().last() {
            if point.microvolts <= last.microvolts || point.millicents <= last.millicents {
                return Err(Error::NonMonotonic);
            }
        }
        if self.count as usize == MAX_POINTS {
            return Err(Error::Full);
        }
        self.points[self.count as usize] = point;
        self.count += 1;
        if point.microvolts == 0 && (0..=12_800_000).contains(&point.millicents) {
            self.zero_pitch = point.millicents;
        }
        Ok(())
    }

    /// Build an independent candidate with one qualified interior measurement.
    /// Never replace existing anchors, extend the range, or mutate the source.
    /// This does not qualify a measurement or accept/save a candidate: a live
    /// caller must independently verify it before offering it to the user.
    #[inline(never)]
    pub fn refined_with(&self, measured: Point) -> Result<Self, Error> {
        let index = self.refinement_index(measured)?;
        let mut candidate = self.clone();
        candidate
            .points
            .copy_within(index..self.count as usize, index + 1);
        candidate.points[index] = measured;
        candidate.count += 1;
        Ok(candidate)
    }
    /// Undo only the exact interior point added by the automatic controller.
    /// The original measured anchors are never replaced or resampled.
    pub fn undo_refinement(&mut self, measured: Point) -> bool {
        let Some(index) = self.points().iter().position(|p| *p == measured) else {
            return false;
        };
        if index == 0 || index + 1 == self.count as usize {
            return false;
        }
        self.points
            .copy_within(index + 1..self.count as usize, index);
        self.count -= 1;
        self.points[self.count as usize] = Point::default();
        true
    }
    fn refinement_index(&self, measured: Point) -> Result<usize, Error> {
        let points = self.points();
        if points.len() < 2 {
            return Err(Error::Incomplete);
        }
        if points.len() == MAX_POINTS {
            return Err(Error::Full);
        }
        if measured.microvolts <= points[0].microvolts
            || measured.microvolts >= points[points.len() - 1].microvolts
        {
            return Err(Error::VoltageOutsideLimits);
        }
        let index = points
            .iter()
            .position(|p| p.microvolts >= measured.microvolts)
            .ok_or(Error::VoltageOutsideLimits)?;
        if measured.microvolts == points[index].microvolts
            || measured.millicents <= points[index - 1].millicents
            || measured.millicents >= points[index].millicents
        {
            return Err(Error::NonMonotonic);
        }
        Ok(index)
    }
    /// Evaluate a one-point candidate without storing a second full profile.
    /// Identical integer interpolation to refined_with, with the same checks.
    pub fn refinement_voltage_for_pitch(&self, measured: Point, pitch: i32) -> Result<i32, Error> {
        let index = self.refinement_index(measured)?;
        let (lo, hi) = (self.points[index - 1], self.points[index]);
        if pitch < lo.millicents || pitch > hi.millicents {
            return self.voltage_for_pitch(pitch);
        }
        let (a, b) = if pitch <= measured.millicents {
            (lo, measured)
        } else {
            (measured, hi)
        };
        let dx = (pitch as i64 - a.millicents as i64) as u64;
        let span = (b.millicents as i64 - a.millicents as i64) as u64;
        let dv = (b.microvolts as i64 - a.microvolts as i64) as u64;
        let product = dx * dv;
        let offset = product / span + u64::from(product % span >= span / 2 + span % 2);
        Ok((a.microvolts as i64 + offset as i64) as i32)
    }

    /// Inverse piecewise-linear interpolation for tuning or quantization.
    /// No extrapolation or silent clamping: the caller must handle range errors.
    /// Integer arithmetic keeps this small and deterministic on the CPU.
    pub fn voltage_for_pitch(&self, pitch: i32) -> Result<i32, Error> {
        let points = self.points();
        if points.len() < 2 {
            return Err(Error::Incomplete);
        }
        if pitch < points[0].millicents || pitch > points[points.len() - 1].millicents {
            return Err(Error::PitchOutsideRange);
        }
        // Lower-bound search: at most seven comparisons for 121 anchors.
        // Preserve the previous segment choice at exact anchors and rounding.
        let (mut low, mut high) = (1, points.len() - 1);
        while low < high {
            let mid = low + (high - low) / 2;
            if points[mid].millicents < pitch {
                low = mid + 1;
            } else {
                high = mid;
            }
        }
        let (a, b) = (points[low - 1], points[low]);
        // Each difference fits u32. Their product fits u64 even at
        // opposite i32 extremes; signed i64 multiplication would not.
        let dx = (pitch as i64 - a.millicents as i64) as u64;
        let span = (b.millicents as i64 - a.millicents as i64) as u64;
        let dv = (b.microvolts as i64 - a.microvolts as i64) as u64;
        let product = dx * dv;
        let offset = product / span + u64::from(product % span >= span / 2 + span % 2);
        Ok((a.microvolts as i64 + offset as i64) as i32)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn point(v: i32, p: i32) -> Point {
        Point {
            microvolts: v,
            millicents: p,
        }
    }

    #[test]
    fn edge_trimming_is_measured_bounded_and_preserves_a_full_octave() {
        let mut p = Profile::new("trim", -5000000, 5000000).unwrap();
        for i in 0..20 {
            p.push(point(i * 83333, i * 100000)).unwrap();
        }
        assert_eq!(p.trim_low_through(166666, 3), 3);
        assert_eq!(p.points()[0], point(249999, 300000));
        assert!(p.limited_low);
        assert_eq!(p.trim_high_from(1499994, 2), 2);
        assert_eq!(p.points().last().unwrap(), &point(1416661, 1700000));
        assert!(p.limited_high);
        // Fifteen anchors remain; removing three more would violate the
        // thirteen-anchor / one-octave minimum and must be refused atomically.
        assert_eq!(p.trim_low_through(416665, 3), 0);
        assert_eq!(p.points().len(), 15);
    }

    #[test]
    fn period_family_selection_is_bounded_and_target_driven() {
        assert_eq!(
            period_family_near(6_000_000, 7_205_000, 10_000),
            Some((7_200_000, 2))
        );
        assert_eq!(
            period_family_near(8_405_000, 7_200_000, 10_000),
            Some((7_205_000, -2))
        );
        assert_eq!(
            period_family_near(5_300_000, 7_205_000, 10_000),
            Some((7_201_955, 3))
        );
        assert_eq!(
            period_family_near(9_103_000, 7_200_000, 10_000),
            Some((7_201_045, -3))
        );
        assert_eq!(
            period_family_near(7_198_000, 7_200_000, 10_000),
            Some((7_198_000, 1))
        );
        assert_eq!(period_family_near(6_000_000, 7_220_000, 10_000), None);
        assert_eq!(period_family_near(6_000_000, 7_200_000, -1), None);
    }

    #[test]
    fn nonlinear_tracking_and_boundaries() {
        let mut p = Profile::new("Local Parks", -1_000_000, 2_000_000).unwrap();
        p.push(point(-1_000_000, 0)).unwrap();
        p.push(point(0, 1_200_000)).unwrap();
        p.push(point(1_100_000, 2_400_000)).unwrap();
        assert_eq!(p.voltage_for_pitch(600_000), Ok(-500_000));
        assert_eq!(p.voltage_for_pitch(1_800_000), Ok(550_000));
        assert_eq!(p.voltage_for_pitch(0), Ok(-1_000_000));
        assert_eq!(p.voltage_for_pitch(2_400_000), Ok(1_100_000));
        assert_eq!(p.voltage_for_pitch(-1), Err(Error::PitchOutsideRange));
        assert_eq!(
            p.voltage_for_pitch(2_400_001),
            Err(Error::PitchOutsideRange)
        );
    }

    #[test]
    fn binary_lookup_matches_linear_reference_for_variable_full_table() {
        let mut p = Profile::new("lookup", -5_000_000, 5_000_000).unwrap();
        let mut mc = -500_000;
        for i in 0..MAX_POINTS {
            mc += 71_003 + (i as i32 * 739) % 40_000;
            p.push(point(-5_000_000 + i as i32 * 77_001, mc)).unwrap();
        }
        let reference = |pitch: i32| {
            let pair = p
                .points()
                .windows(2)
                .find(|a| pitch <= a[1].millicents)
                .unwrap();
            let a = pair[0];
            let b = pair[1];
            let dx = (pitch as i64 - a.millicents as i64) as u64;
            let span = (b.millicents as i64 - a.millicents as i64) as u64;
            let product = dx * (b.microvolts as i64 - a.microvolts as i64) as u64;
            (a.microvolts as i64
                + (product / span + u64::from(product % span >= span / 2 + span % 2)) as i64)
                as i32
        };
        let first = p.points()[0].millicents;
        let last = p.points().last().unwrap().millicents;
        for pitch in (first..=last)
            .step_by(137)
            .chain(
                p.points()
                    .iter()
                    .flat_map(|a| [a.millicents - 1, a.millicents, a.millicents + 1]),
            )
            .filter(|v| *v >= first && *v <= last)
        {
            assert_eq!(p.voltage_for_pitch(pitch), Ok(reference(pitch)));
        }
    }

    #[test]
    fn refinement_is_an_independent_bounded_candidate_and_preserves_storage() {
        let mut p = Profile::new("candidate", -5000000, 5000000).unwrap();
        p.limited_low = true;
        p.limited_high = true;
        for (uv, mc) in [(-100000, 6000000), (0, 6100000), (100000, 6200000)] {
            p.push(point(uv, mc)).unwrap();
        }
        let before = p.points().to_vec();
        let candidate = p.refined_with(point(-50000, 6048000)).unwrap();
        assert_eq!(p.points(), before);
        assert_eq!(
            candidate.points(),
            &[before[0], point(-50000, 6048000), before[1], before[2]]
        );
        assert_eq!(candidate.voltage_for_pitch(6048000), Ok(-50000));
        // Original anchors and all segments outside the refined pair stay exact.
        for pitch in (6100000..=6200000).step_by(1000) {
            assert_eq!(
                candidate.voltage_for_pitch(pitch),
                p.voltage_for_pitch(pitch)
            );
        }
        let mut bytes = [0; storage::MAX_BYTES];
        let n = storage::encode(
            &candidate,
            Route::new(0, 1).unwrap(),
            60,
            CalibrationQuality::default(),
            candidate.name(),
            &mut bytes,
        )
        .unwrap();
        let recalled = storage::decode(&bytes[..n]).unwrap();
        assert_eq!(recalled.profile.points(), candidate.points());
        assert!(recalled.profile.limited_low && recalled.profile.limited_high);
        assert_eq!(recalled.profile.name(), p.name());
        for bad in [
            point(-100001, 5999999),
            point(-100000, 6000000),
            point(100000, 6200000),
            point(100001, 6200001),
            point(0, 6100001),
            point(-50000, 6000000),
            point(-50000, 6100000),
        ] {
            assert!(p.refined_with(bad).is_err());
            assert_eq!(p.points(), before);
        }
        let mut full = Profile::new("full", -5000000, 5000000).unwrap();
        for i in 0..MAX_POINTS as i32 {
            full.push(point(i * 1000, i * 1000)).unwrap();
        }
        assert!(matches!(
            full.refined_with(point(500, 500)),
            Err(Error::Full)
        ));
        assert_eq!(full.points().len(), MAX_POINTS);
    }

    #[test]
    fn measured_refinement_reduces_modeled_curvature_without_a_global_offset() {
        // Smooth monotonic response with a 2-cent midpoint departure. Use fresh
        // interior targets for validation, not the inserted anchor itself.
        fn response(uv: i32) -> i32 {
            let x = uv as f64 / 100000.0;
            (6000000.0 + 100000.0 * x - 8000.0 * x * (1.0 - x)).round() as i32
        }
        let mut p = Profile::new("curved", 0, 100000).unwrap();
        p.push(point(0, response(0))).unwrap();
        p.push(point(100000, response(100000))).unwrap();
        let candidate = p.refined_with(point(50000, response(50000))).unwrap();
        let mut old_worst = 0;
        let mut new_worst = 0;
        for pitch in (6001000..6100000).step_by(1000) {
            let old = (response(p.voltage_for_pitch(pitch).unwrap()) - pitch).abs();
            let new = (response(candidate.voltage_for_pitch(pitch).unwrap()) - pitch).abs();
            old_worst = old_worst.max(old);
            new_worst = new_worst.max(new);
        }
        assert!(old_worst >= 1900);
        assert!(new_worst <= 510);
        assert_eq!(p.points().len(), 2);
    }
    #[test]
    fn compact_candidate_matches_materialized_curve_at_every_target() {
        for shift in [-4000000, 0, 3000000] {
            let mut p = Profile::new("compact", -5000000, 5000000).unwrap();
            for (uv, mc) in [
                (shift, 2000000),
                (shift + 83250, 2100000),
                (shift + 166750, 2200000),
            ] {
                p.push(point(uv, mc)).unwrap();
            }
            let measured = point(shift + 41750, 2048000);
            let candidate = p.refined_with(measured).unwrap();
            for pitch in 1999999..=2200001 {
                assert_eq!(
                    p.refinement_voltage_for_pitch(measured, pitch),
                    candidate.voltage_for_pitch(pitch)
                );
            }
        }
    }

    #[test]
    fn invalid_measurements_never_mutate_profile() {
        let mut p = Profile::new("VCO", -100, 100).unwrap();
        assert_eq!(p.voltage_for_pitch(0), Err(Error::Incomplete));
        p.push(point(0, 100)).unwrap();
        for bad in [point(0, 200), point(-1, 200), point(1, 100), point(1, 99)] {
            assert_eq!(p.push(bad), Err(Error::NonMonotonic));
        }
        assert_eq!(p.push(point(101, 200)), Err(Error::VoltageOutsideLimits));
        assert_eq!(p.points(), &[point(0, 100)]);
        assert_eq!(p.voltage_for_pitch(100), Err(Error::Incomplete));
    }

    #[test]
    fn bounded_names_and_capacity() {
        let mut p = Profile::new("Oscillator 1", 0, 1000).unwrap();
        for name in ["", "   ", "bad\nname", "é", "1234567890123456789012345"] {
            assert_eq!(p.rename(name), Err(Error::InvalidName));
            assert_eq!(p.name(), "Oscillator 1");
        }
        p.rename("VCO").unwrap();
        assert_eq!(p.name(), "VCO");
        for n in 0..MAX_POINTS as i32 {
            p.push(point(n, n)).unwrap();
        }
        assert_eq!(
            p.push(point(MAX_POINTS as i32, MAX_POINTS as i32)),
            Err(Error::Full)
        );
        assert_eq!(p.points().len(), MAX_POINTS);
        assert!(core::mem::size_of::<Profile>() <= 1080);
    }

    #[test]
    fn interpolation_extremes_and_rounding_do_not_overflow() {
        let mut p = Profile::new("extremes", i32::MIN, i32::MAX).unwrap();
        p.push(point(i32::MIN, i32::MIN)).unwrap();
        p.push(point(i32::MAX, i32::MAX)).unwrap();
        for n in [i32::MIN, -1, 0, 1, i32::MAX] {
            assert_eq!(p.voltage_for_pitch(n), Ok(n));
        }
        let mut p = Profile::new("round", -1, 1).unwrap();
        p.push(point(-1, 0)).unwrap();
        p.push(point(0, 2)).unwrap();
        assert_eq!(p.voltage_for_pitch(1), Ok(0));
    }

    #[test]
    fn near_zero_mapping_is_precise_but_cannot_remove_a_biased_endpoint() {
        let base = 6540000;
        let mut p = Profile::new("low end", 0, 2000000).unwrap();
        for uv in [0, 83250, 166750, 2000000] {
            p.push(point(uv, base + (uv as i64 * 1200000 / 1000000) as i32))
                .unwrap();
        }
        // Every milli-cent near the boundary, including fractional DAC counts.
        for delta in 0..100000 {
            let uv = p.voltage_for_pitch(base + delta).unwrap();
            let counts = (uv + 125) / 250;
            let actual = counts as f64 * 0.3; // cents at ideal 1 V/oct
            assert!((actual - delta as f64 / 1000.0).abs() < 0.152);
        }
        let mut biased = Profile::new("biased endpoint", 0, 2000000).unwrap();
        biased.push(point(0, base + 5000)).unwrap();
        biased.push(point(83250, base + 99900)).unwrap();
        let target = base + 14400; // actual ideal voltage 12 mV
        let uv = biased.voltage_for_pitch(target).unwrap();
        let error = uv as f64 * 0.0012 - 14.4;
        assert!(error < -4.0 && error > -5.0);
        // This demonstrates sensitivity, not proof of the hardware cause.
    }

    #[test]
    fn routing_is_explicit_and_panel_numbered() {
        for i in 0..4 {
            for o in 0..4 {
                let route = Route::new(i, o).unwrap();
                assert_eq!((route.input(), route.output()), (i, o));
            }
        }
        assert_eq!(Route::new(4, 0), Err(Error::InvalidChannel));
        assert_eq!(Route::new(0, 255), Err(Error::InvalidChannel));
        assert!(matches!(
            Profile::new("vco", 1, 1),
            Err(Error::InvalidLimits)
        ));
    }

    #[test]
    fn note_suggestion_respects_fractional_bounds_and_menu_range() {
        for (lo, hi, expected) in [
            (6541980, 8941980, Some(77)),
            (6050000, 6090000, None),
            (6000000, 6100000, Some(60)),
            (-100000, 1100000, None),
            (10900000, 12000000, None),
        ] {
            let mut p = Profile::new("test", 0, 2000000).unwrap();
            assert_eq!(p.suggested_note(), None);
            p.push(point(0, lo)).unwrap();
            p.push(point(2000000, hi)).unwrap();
            assert_eq!(p.suggested_note(), expected);
        }
    }
}
