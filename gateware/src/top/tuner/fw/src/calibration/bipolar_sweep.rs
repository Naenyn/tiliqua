//! Bipolar acquisition protocol used by the live firmware.
//! Characterize the complete hardware-safe -5 V .. +8 V range, then retain
//! the longest contiguous monotonic response as the calibration curve.
//! Missing, unstable, flat and discontinuous regions are observations rather
//! than reasons to abort the hardware sweep.
//! No candidate escapes until a final disabled/zero request is acknowledged.
use crate::bipolar::{self, Density, Direction};
use crate::oscillator_calibration::averaging::{Average, LOW_PITCH, MAX_SPAN};
use crate::oscillator_calibration::{
    period_family_near,
    sweep::{Measurement, Policy},
    Point, Route, MIN_PROFILE_POINTS,
};
const SUBAUDIO_PITCH: i32 = 1_550_000; // Approximately 20 Hz at A4=440.

// A shorter fragment is not a useful oscillator calibration profile.  At the
// semitone acquisition density, thirteen contiguous points cover one octave
// including both endpoints.  Reject tiny detector islands before automatic
// verification rather than timing out while trying to replay them.

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Failure {
    NoOrigin,
    OriginLost,
    OriginChanged,
    NotTracking,
    UnstablePitch,
    RangeBeforeZero,
    Output,
    Clock,
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Outcome {
    Complete,
    Cancelled,
    Failed(Failure),
}
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Request {
    Apply {
        output: u8,
        microvolts: i32,
        token: u8,
    },
    Wait,
    Disable {
        output: u8,
        token: u8,
    },
    Finished(Outcome),
}
#[derive(Clone, Copy)]
enum Phase {
    Origin,
    Ascending,
    CheckEnd,
}
#[derive(Clone, Copy)]
enum State {
    Applying,
    Measuring { since: u64 },
    Restoring(Outcome),
    Finished(Outcome),
}

#[derive(Clone, Copy)]
pub struct TrackingFailure {
    pub rejected: Point,
    pub neighbour: Option<Point>,
}
impl TrackingFailure {
    /// Descriptive diagnostic for an uncorrectable octave-sized drop.
    /// An approximately one-octave downward reading during an upward voltage
    /// step can reflect period ambiguity, a real signal change, or a patch issue.
    pub fn octave_sized_drop(&self) -> bool {
        self.neighbour.is_some_and(|p| {
            let drop = p.millicents as i64 - self.rejected.millicents as i64;
            self.rejected.microvolts > p.microvolts && (900000..=1300000).contains(&drop)
        })
    }
}
#[derive(Clone, Copy)]
pub struct AcquisitionDiagnostic {
    pub qualified: u16,
    pub unqualified: u16,
    pub tight_count: u8,
    pub needs_average: bool,
    pub average: crate::oscillator_calibration::averaging::Snapshot,
}

#[derive(Clone, Copy)]
pub struct Curve {
    points: [Point; bipolar::MAX_POINTS],
    count: usize,
    pub limited_low: bool,
    pub limited_high: bool,
}

#[derive(Clone, Copy, Default)]
pub struct ScanWarnings {
    pub missing: u8,
    pub unstable: u8,
    pub discontinuities: u8,
    pub flat: u8,
}
impl ScanWarnings {
    pub fn any(&self) -> bool {
        self.missing != 0 || self.unstable != 0 || self.discontinuities != 0 || self.flat != 0
    }
}
impl Curve {
    pub fn points(&self) -> &[Point] {
        &self.points[..self.count]
    }
    fn usable(&self) -> bool {
        self.count >= MIN_PROFILE_POINTS
    }
    pub(crate) fn new() -> Self {
        Self {
            points: [Point::default(); bipolar::MAX_POINTS],
            count: 0,
            limited_low: false,
            limited_high: false,
        }
    }
    pub(crate) fn add(&mut self, p: Point) -> bool {
        if self.count == self.points.len()
            || !(bipolar::MIN_UV..=bipolar::MAX_UV).contains(&p.microvolts)
        {
            return false;
        }
        let index = self
            .points()
            .partition_point(|old| old.microvolts < p.microvolts);
        if index > 0 && self.points[index - 1].millicents >= p.millicents {
            return false;
        }
        if index < self.count
            && (self.points[index].microvolts == p.microvolts
                || self.points[index].millicents <= p.millicents)
        {
            return false;
        }
        self.points.copy_within(index..self.count, index + 1);
        self.points[index] = p;
        self.count += 1;
        true
    }
    fn make_room_for_remaining(&mut self, remaining: usize) {
        let keep = self
            .points
            .len()
            .saturating_sub(remaining)
            .max(2)
            .min(self.count);
        if keep >= self.count {
            return;
        }
        let old_count = self.count;
        for dst in 0..keep {
            let src = dst * (old_count - 1) / (keep - 1);
            self.points[dst] = self.points[src];
        }
        self.count = keep;
    }
}

pub struct Sweep {
    candidate: Option<Curve>,
    best: Curve,
    route: Route,
    density: Density,
    policy: Policy,
    phase: Phase,
    state: State,
    index: usize,
    token: u8,
    point_started: u64,
    last_now: u64,
    last_sequence: Option<u64>,
    count: u8,
    minimum: i32,
    maximum: i32,
    sum: i64,
    origin: i32,
    origin_uv: i32,
    origin_tolerance: u32,
    origin_error: Option<i32>,
    tracking_failure: Option<TrackingFailure>,
    measured_origin: bool,
    positive_only: bool,
    lower_family_plateau: bool,
    lower_flat_pitch: i32,
    lower_flat_points: u8,
    upper_flat_points: u8,
    saw_qualified: bool,
    average: Average,
    needs_average: bool,
    failure_voltage: Option<i32>,
    qualified_count: u16,
    unqualified_count: u16,
    period_family_corrections: u8,
    warnings: ScanWarnings,
}
impl Sweep {
    pub fn acquisition_diagnostic(&self) -> AcquisitionDiagnostic {
        AcquisitionDiagnostic {
            qualified: self.qualified_count,
            unqualified: self.unqualified_count,
            tight_count: self.count,
            needs_average: self.needs_average,
            average: self.average.snapshot(),
        }
    }
    pub fn failure_voltage(&self) -> Option<i32> {
        self.failure_voltage
    }
    pub fn tracking_failure(&self) -> Option<TrackingFailure> {
        self.tracking_failure
    }
    pub fn origin_error(&self) -> Option<i32> {
        self.origin_error
    }
    pub fn period_family_corrections(&self) -> u8 {
        self.period_family_corrections
    }
    pub fn warnings(&self) -> ScanWarnings {
        self.warnings
    }
    pub fn point_count(&self) -> usize {
        self.candidate.as_ref().map_or(0, |c| c.points().len())
    }
    pub fn new(
        route: Route,
        density: Density,
        policy: Policy,
        origin_tolerance: u32,
        now: u64,
    ) -> Option<Self> {
        if policy.stable_samples < 2 || policy.point_timeout_ms <= policy.settle_ms {
            return None;
        }
        Some(Self {
            candidate: Some(Curve::new()),
            best: Curve::new(),
            route,
            density,
            policy,
            phase: Phase::Origin,
            state: State::Applying,
            index: 0,
            token: 1,
            point_started: now,
            last_now: now,
            last_sequence: None,
            count: 0,
            minimum: 0,
            maximum: 0,
            sum: 0,
            origin: 0,
            origin_uv: 0,
            origin_tolerance,
            origin_error: None,
            tracking_failure: None,
            measured_origin: false,
            positive_only: false,
            lower_family_plateau: false,
            lower_flat_pitch: 0,
            lower_flat_points: 0,
            upper_flat_points: 0,
            saw_qualified: false,
            average: Average::new(),
            needs_average: false,
            failure_voltage: None,
            qualified_count: 0,
            unqualified_count: 0,
            period_family_corrections: 0,
            warnings: ScanWarnings::default(),
        })
    }
    fn voltage(&self) -> i32 {
        match self.phase {
            Phase::Ascending => bipolar::full_voltage(self.density, self.index).unwrap(),
            Phase::Origin => bipolar::voltage(self.density, Direction::Up, self.index).unwrap(),
            Phase::CheckEnd => self.origin_uv,
        }
    }
    fn last_ascending_index(&self) -> usize {
        bipolar::full_intervals(self.density)
    }
    fn finish_segment(&mut self) {
        let current = self.candidate.as_ref().map_or(0, |c| c.count);
        if current > self.best.count {
            let mut selected = *self.candidate.as_ref().unwrap();
            if let (Some(low), Some(high)) = (selected.points().first(), selected.points().last()) {
                let low_uv = low.microvolts;
                let high_uv = high.microvolts;
                selected.limited_low |= low_uv > bipolar::MIN_UV;
                selected.limited_high |= high_uv < bipolar::MAX_UV;
            }
            self.best = selected;
        }
        self.candidate = Some(Curve::new());
        self.tracking_failure = None;
        self.upper_flat_points = 0;
        self.lower_flat_points = 0;
    }
    fn next_characterization_point(&mut self, now: u64) {
        self.finish_segment();
        if self.index < self.last_ascending_index() {
            self.advance(Phase::Ascending, self.index + 1, now);
        } else {
            self.finish_segment();
            self.candidate = Some(self.best);
            self.advance(Phase::CheckEnd, 0, now);
        }
    }
    fn restart_segment_with(&mut self, p: Point, now: u64) {
        self.finish_segment();
        let _ = self.candidate.as_mut().unwrap().add(p);
        if p.microvolts == self.origin_uv {
            self.origin = p.millicents;
            self.measured_origin = true;
        }
        if self.index < self.last_ascending_index() {
            self.advance(Phase::Ascending, self.index + 1, now);
        } else {
            self.finish_segment();
            self.candidate = Some(self.best);
            self.advance(Phase::CheckEnd, 0, now);
        }
    }
    fn advance_or_finish(&mut self, now: u64) {
        if self.index < self.last_ascending_index() {
            self.advance(Phase::Ascending, self.index + 1, now);
        } else {
            self.finish_segment();
            self.candidate = Some(self.best);
            self.advance(Phase::CheckEnd, 0, now);
        }
    }
    fn advance(&mut self, phase: Phase, index: usize, now: u64) {
        if matches!(phase, Phase::CheckEnd) {
            self.origin_error = None;
        }
        self.phase = phase;
        self.index = index;
        self.token += 1;
        self.point_started = now;
        self.state = State::Applying;
        self.count = 0;
        self.saw_qualified = false;
        self.average.clear();
        self.needs_average = false;
        self.qualified_count = 0;
        self.unqualified_count = 0;
    }
    fn restore(&mut self, outcome: Outcome) {
        if matches!(self.state, State::Finished(_)) {
            return;
        }
        if matches!(outcome, Outcome::Failed(_)) && self.failure_voltage.is_none() {
            self.failure_voltage = Some(self.voltage());
        }
        if !matches!(self.state, State::Restoring(_)) {
            self.token += 1;
        }
        self.state = State::Restoring(outcome);
        if outcome != Outcome::Complete {
            self.candidate = None;
        }
    }
    pub fn cancel(&mut self) {
        if matches!(self.state, State::Finished(_)) {
            return;
        }
        self.restore(Outcome::Cancelled);
        self.state = State::Restoring(Outcome::Cancelled);
    }
    pub fn output_failed(&mut self) {
        if matches!(self.state, State::Finished(_)) {
            return;
        }
        self.restore(Outcome::Failed(Failure::Output));
        self.state = State::Restoring(Outcome::Failed(Failure::Output));
    }
    fn clock(&mut self, now: u64) -> bool {
        if now < self.last_now {
            self.restore(Outcome::Failed(Failure::Clock));
            return false;
        }
        self.last_now = now;
        // Leading range discovery need not spend the full unstable-pitch
        // deadline on silence/out-of-band inputs. Wait two seconds AFTER DAC
        // acknowledgment, and never accelerate a point with qualified evidence.
        // Keep final checks, established curves and ACK failures intact.
        let empty_leading = matches!(self.phase, Phase::Ascending)
            && self.candidate.as_ref().map_or(false, |c| c.count < 2)
            && !self.saw_qualified
            && self.tracking_failure.is_none()
            && self.upper_flat_points == 0
            && matches!(self.state,State::Measuring{since}
                if now-since>=2000 && now-since>self.policy.settle_ms);
        // Zero volts can legitimately place an oscillator below the detector's
        // 20-Hz floor. Search upward in the same voltage grid rather than
        // rejecting the patch. A qualified-but-unsettled point retains the
        // normal deadline, then the search continues at the next voltage.
        let empty_origin = matches!(self.phase, Phase::Origin)
            && !self.saw_qualified
            && matches!(self.state,State::Measuring{since}
                if now-since>=2000 && now-since>self.policy.settle_ms);
        // Low-frequency averaging can lose an early block to a real settling
        // excursion and still have ample qualified evidence. Give only that
        // path a bounded 2.5s recovery margin; silence, high-frequency
        // instability and DAC acknowledgement retain their existing deadlines.
        let point_deadline = self
            .policy
            .point_timeout_ms
            .saturating_add(if self.needs_average { 2500 } else { 0 });
        if matches!(self.state, State::Applying | State::Measuring { .. })
            && (now - self.point_started >= point_deadline || empty_leading || empty_origin)
        {
            // No DAC acknowledgment is an output failure, not a range boundary.
            if matches!(self.state, State::Applying) {
                self.output_failed();
                return true;
            }
            match self.phase {
                Phase::Ascending => {
                    if self.saw_qualified {
                        self.warnings.unstable = self.warnings.unstable.saturating_add(1);
                    } else {
                        self.warnings.missing = self.warnings.missing.saturating_add(1);
                    }
                    self.next_characterization_point(now);
                }
                Phase::Origin => {
                    let n = bipolar::intervals(self.density);
                    if self.index < n {
                        self.advance(Phase::Origin, self.index + 1, now);
                    } else {
                        self.advance(Phase::Ascending, 0, now);
                    }
                }
                Phase::CheckEnd
                    if !self.measured_origin
                        && self.candidate.as_ref().is_some_and(Curve::usable) =>
                {
                    self.restore(Outcome::Complete)
                }
                Phase::CheckEnd if self.origin_error.is_some() => {
                    self.restore(Outcome::Failed(Failure::OriginChanged))
                }
                Phase::CheckEnd => self.restore(Outcome::Failed(Failure::OriginLost)),
            }
        }
        true
    }
    pub fn acknowledge(&mut self, token: u8, now: u64) -> bool {
        if !self.clock(now) || token != self.token {
            return false;
        }
        match self.state {
            State::Applying => {
                self.state = State::Measuring { since: now };
                true
            }
            State::Restoring(outcome) => {
                self.state = State::Finished(outcome);
                true
            }
            _ => false,
        }
    }
    fn accept(&mut self, mut pitch: i32, now: u64) {
        match self.phase {
            Phase::Origin => {
                self.origin = pitch;
                self.origin_uv = self.voltage();
                // Preflight only: all stored points come from the same upward pass.
                self.advance(Phase::Ascending, 0, now);
            }
            Phase::Ascending => {
                let uv = self.voltage();
                let curve = self.candidate.as_mut().unwrap();
                // A positive-only CV input may hold one physical pitch across
                // the whole negative range while autocorrelation alternates
                // between integer-related periods.  Comparing the raw pitch
                // values would turn those harmonics into a plausible-looking
                // ascending curve.  Before zero, collapse a family-equivalent
                // repeat back onto the last retained pitch and restart lower
                // range discovery from that anchor.  A genuinely tracking
                // semitone step is far outside this deliberately tight bound.
                if uv < self.origin_uv
                    && curve.count >= 2
                    && (uv <= -4_000_000 || self.lower_family_plateau)
                {
                    let previous = curve.points[curve.count - 1];
                    let flat_limit = self.policy.tolerance_millicents.max(10000) as i32;
                    let flat_pitch = if self.lower_flat_points > 0 {
                        self.lower_flat_pitch
                    } else {
                        previous.millicents
                    };
                    if let Some((selected, _)) = period_family_near(pitch, flat_pitch, flat_limit) {
                        if self.lower_flat_points == 0 {
                            self.lower_flat_pitch = previous.millicents;
                            self.tracking_failure = Some(TrackingFailure {
                                rejected: Point {
                                    microvolts: uv,
                                    millicents: selected,
                                },
                                neighbour: Some(previous),
                            });
                        }
                        self.lower_flat_points = self.lower_flat_points.saturating_add(1);
                        if self.lower_flat_points >= 3 {
                            curve.points[0] = Point {
                                microvolts: uv,
                                millicents: selected,
                            };
                            curve.count = 1;
                            curve.limited_low = true;
                            self.lower_family_plateau = true;
                            self.lower_flat_pitch = 0;
                            self.lower_flat_points = 0;
                            self.tracking_failure = None;
                        }
                        self.advance_or_finish(now);
                        return;
                    }
                    if self.lower_flat_points > 0 {
                        self.warnings.discontinuities =
                            self.warnings.discontinuities.saturating_add(1);
                        self.restart_segment_with(
                            Point {
                                microvolts: uv,
                                millicents: pitch,
                            },
                            now,
                        );
                        return;
                    }
                }
                // Once three monotonic points establish a local V/oct
                // trajectory, resolve only a near-exact octave-family switch
                // that lands close to its linear continuation.  This is not a
                // general detector correction: early discovery, plateaus,
                // gaps and non-octave discontinuities retain fail-closed
                // behavior.  Automatic verification independently checks the
                // resulting profile against its commanded target.
                if curve.count >= 3 {
                    let a = curve.points[curve.count - 2];
                    let b = curve.points[curve.count - 1];
                    let duv = b.microvolts as i64 - a.microvolts as i64;
                    let dp = b.millicents as i64 - a.millicents as i64;
                    if duv > 0 && (10_000..=250_000).contains(&dp) && uv > b.microvolts {
                        let expected =
                            b.millicents as i64 + (uv as i64 - b.microvolts as i64) * dp / duv;
                        if let Ok(expected) = i32::try_from(expected) {
                            if let Some((selected, family)) =
                                period_family_near(pitch, expected, 150_000)
                            {
                                if family != 1 && selected > b.millicents {
                                    pitch = selected;
                                    self.period_family_corrections =
                                        self.period_family_corrections.saturating_add(1);
                                }
                            }
                        }
                    }
                }
                if curve.count == 1 {
                    let previous = curve.points[0];
                    // An audible oscillator can still be below its CV input range.
                    // Treat small bidirectional movement as a leading plateau,
                    // not useful tracking (nor an octave-error exemption). Once
                    // a lower plateau has already been confirmed, keep its
                    // canonical period family while selectors move among its
                    // harmonics. Before confirmation, retain the raw comparison
                    // so a lone octave drop still fails closed.
                    let flat_limit = self.policy.tolerance_millicents.max(10000) as u64;
                    let flat_pitch = if self.lower_family_plateau && uv < self.origin_uv {
                        period_family_near(pitch, previous.millicents, flat_limit as i32)
                            .map(|v| v.0)
                    } else if (pitch as i64 - previous.millicents as i64).unsigned_abs()
                        <= flat_limit
                    {
                        Some(pitch)
                    } else {
                        None
                    };
                    if let Some(flat_pitch) = flat_pitch {
                        curve.points[0] = Point {
                            microvolts: uv,
                            millicents: flat_pitch,
                        };
                        curve.limited_low = true;
                        self.tracking_failure = None;
                        if uv == self.origin_uv {
                            self.origin = pitch;
                            self.measured_origin = true;
                        }
                        self.advance_or_finish(now);
                        return;
                    }
                    // Some oscillators ignore every negative control voltage,
                    // hold their panel-set pitch there, then enter the actual
                    // 1 V/oct range with a downward reset at 0 V. Only a
                    // previously confirmed leading plateau authorizes replacing
                    // this provisional anchor. A lone downward/octave reading
                    // remains a tracking failure (covered below).
                    if curve.limited_low && uv >= self.origin_uv && pitch < previous.millicents {
                        curve.points[0] = Point {
                            microvolts: uv,
                            millicents: pitch,
                        };
                        // The negative half has now been measured as a dead
                        // zone. Spend the same semitone density on the useful
                        // 0..+8 V range; capacity remains bounded (97 points).
                        self.positive_only = true;
                        self.tracking_failure = None;
                        if uv == self.origin_uv {
                            self.origin = pitch;
                            self.measured_origin = true;
                        }
                        self.advance_or_finish(now);
                        return;
                    }
                }
                if curve.count >= 2 && uv > self.origin_uv && self.measured_origin {
                    let previous = curve.points[curve.count - 1];
                    // Confirm an upper plateau against the SAME last retained
                    // pitch at three successive voltages. Never accumulate
                    // small steps into a spurious plateau or store flat points.
                    let flat_limit = self.policy.tolerance_millicents.max(10000) as u64;
                    if (pitch as i64 - previous.millicents as i64).unsigned_abs() <= flat_limit {
                        self.tracking_failure = None;
                        self.upper_flat_points += 1;
                        if self.upper_flat_points >= 3 {
                            // The anchor is itself already at the ceiling. Its
                            // preceding interval may contain an unmeasured knee:
                            // replay works, but linear inversion there does not.
                            // Keep the last point known to precede saturation.
                            curve.count -= 1;
                            curve.limited_high = true;
                            self.warnings.flat = self.warnings.flat.saturating_add(1);
                            self.next_characterization_point(now);
                        } else if self.index < self.last_ascending_index() {
                            self.advance(Phase::Ascending, self.index + 1, now);
                        } else {
                            self.warnings.flat = self.warnings.flat.saturating_add(1);
                            self.next_characterization_point(now);
                        }
                        return;
                    }
                    if self.upper_flat_points > 0 {
                        // An isolated flat spot followed by changed pitch is
                        // not a confirmed endpoint. Do not bridge it.
                        self.tracking_failure = Some(TrackingFailure {
                            rejected: Point {
                                microvolts: uv,
                                millicents: pitch,
                            },
                            neighbour: Some(previous),
                        });
                        self.count = 0;
                        return;
                    }
                }
                if self.candidate.as_ref().unwrap().count == bipolar::MAX_POINTS {
                    // Profile storage is capped at 121 points, while the full
                    // semitone characterization has 157. Preserve both
                    // endpoints and evenly thin earlier observations just
                    // enough to retain every remaining upper-range point.
                    let remaining = self.last_ascending_index() - self.index + 1;
                    self.candidate
                        .as_mut()
                        .unwrap()
                        .make_room_for_remaining(remaining);
                }
                if !self.candidate.as_mut().unwrap().add(Point {
                    microvolts: uv,
                    millicents: pitch,
                }) {
                    let points = self.candidate.as_ref().unwrap().points();
                    let neighbour = points.last();
                    self.tracking_failure = Some(TrackingFailure {
                        rejected: Point {
                            microvolts: uv,
                            millicents: pitch,
                        },
                        neighbour: neighbour.copied(),
                    });
                    // Preserve the discontinuity as a warning and begin a new
                    // candidate segment at this voltage.  Never bridge a bad
                    // region, but do continue characterizing the full range.
                    self.warnings.discontinuities = self.warnings.discontinuities.saturating_add(1);
                    self.restart_segment_with(
                        Point {
                            microvolts: uv,
                            millicents: pitch,
                        },
                        now,
                    );
                    return;
                }
                self.tracking_failure = None;
                if uv == self.origin_uv {
                    self.origin = pitch;
                    self.measured_origin = true;
                }
                if self.index < self.last_ascending_index() {
                    self.advance(Phase::Ascending, self.index + 1, now);
                } else {
                    self.finish_segment();
                    self.candidate = Some(self.best);
                    self.advance(Phase::CheckEnd, 0, now);
                }
            }
            Phase::CheckEnd => {
                if !self.measured_origin {
                    if !self.candidate.as_ref().unwrap().usable() {
                        self.restore(Outcome::Failed(Failure::NotTracking));
                    } else {
                        self.restore(Outcome::Complete);
                    }
                    return;
                }
                // The final reference check must use the same family as the
                // retained zero-volt point. Otherwise a repeatable selector
                // family switch would make an unchanged oscillator look like
                // origin drift after a successfully unwrapped sweep.
                pitch = period_family_near(pitch, self.origin, self.origin_tolerance as i32)
                    .map_or(pitch, |v| v.0);
                if (pitch as i64 - self.origin as i64).unsigned_abs() > self.origin_tolerance as u64
                {
                    self.count = 0;
                    return;
                }
                if !self.candidate.as_ref().unwrap().usable() {
                    self.restore(Outcome::Failed(Failure::NotTracking));
                } else {
                    self.restore(Outcome::Complete);
                }
            }
        }
    }
    pub fn poll(&mut self, now: u64, sample: Option<Measurement>) -> Request {
        if self.clock(now) {
            if let (State::Measuring { since }, Some(s)) = (self.state, sample) {
                if s.input == self.route.input()
                    && s.window_start_ms >= since
                    && s.window_start_ms - since >= self.policy.settle_ms
                    && s.window_start_ms <= s.window_end_ms
                    && s.window_end_ms <= now
                    && now - s.window_end_ms <= 100
                    && self.last_sequence.map_or(true, |last| s.sequence > last)
                {
                    self.last_sequence = Some(s.sequence);
                    if s.qualified {
                        self.qualified_count = self.qualified_count.saturating_add(1);
                    } else {
                        self.unqualified_count = self.unqualified_count.saturating_add(1);
                    }
                    self.saw_qualified |= s.qualified;
                    let checking = matches!(self.phase, Phase::CheckEnd);
                    let measured_pitch = if checking && self.measured_origin && s.qualified {
                        period_family_near(s.millicents, self.origin, self.origin_tolerance as i32)
                            .map_or(s.millicents, |v| v.0)
                    } else {
                        s.millicents
                    };
                    if checking && self.measured_origin && s.qualified {
                        self.origin_error = Some(measured_pitch.saturating_sub(self.origin));
                    }
                    // A repeatable transient is not proof that zero changed.
                    // Require every accepted recheck sample to match the origin,
                    // and retain the existing deadline for recovery or failure.
                    if !s.qualified
                        || (checking
                            && self.measured_origin
                            && self.origin_error.unwrap_or(0).unsigned_abs()
                                > self.origin_tolerance)
                    {
                        self.count = 0;
                        self.average.clear();
                    } else {
                        // Keep an independent-window fallback warm at every
                        // pitch. At low frequencies it is the normal path; at
                        // high frequencies it recovers clean oscillators whose
                        // fractional-period quantization prevents five adjacent
                        // frames from fitting the tighter 3-cent fast path.
                        let averaged = self.average
                            .observe(measured_pitch, s.window_start_ms, s.window_end_ms);
                        let lo = if self.count == 0 {
                            measured_pitch
                        } else {
                            self.minimum.min(measured_pitch)
                        };
                        let hi = if self.count == 0 {
                            measured_pitch
                        } else {
                            self.maximum.max(measured_pitch)
                        };
                        let excursion = (hi as i64 - lo as i64).unsigned_abs();
                        if excursion > self.policy.tolerance_millicents as u64 {
                            // Audible low notes need the long-window path. A
                            // qualified sub-audio estimate already spans many
                            // cycles and cannot collect sixteen independent
                            // windows before the bounded point deadline. At
                            // higher pitches, use averaging only for the bounded
                            // fractional-period jitter seen in the exact WTF
                            // capture. Gross transients keep the original fast
                            // reset/recovery behavior.
                            if (SUBAUDIO_PITCH..=LOW_PITCH).contains(&measured_pitch)
                                || (measured_pitch > LOW_PITCH
                                    && excursion <= MAX_SPAN as u64)
                            {
                                self.needs_average = true;
                            }
                            self.count = 1;
                            self.minimum = measured_pitch;
                            self.maximum = measured_pitch;
                            self.sum = measured_pitch as i64;
                        } else {
                            if self.count == 0 {
                                self.sum = 0;
                            }
                            self.minimum = lo;
                            self.maximum = hi;
                            self.sum += measured_pitch as i64;
                            self.count += 1;
                        }
                        // An early settling excursion may enable the bounded
                        // independent-window fallback, but it must not disable
                        // the ordinary consecutive-frame path for the rest of
                        // this point.  The WTF hardware captures showed a clean
                        // stationary sine after one such excursion; making
                        // `needs_average` exclusive discarded every note below
                        // C3 even after five tightly grouped fresh estimates.
                        // Accept whichever qualified path completes first.
                        if let Some(mean) = averaged {
                            self.accept(mean.mean, now);
                        } else if self.count
                            >= if measured_pitch < SUBAUDIO_PITCH {
                                2
                            } else {
                                self.policy.stable_samples
                            }
                        {
                            self.accept((self.sum / self.count as i64) as i32, now);
                        }
                    }
                }
            }
        }
        match self.state {
            State::Applying => Request::Apply {
                output: self.route.output(),
                microvolts: self.voltage(),
                token: self.token,
            },
            State::Measuring { .. } => Request::Wait,
            State::Restoring(_) => Request::Disable {
                output: self.route.output(),
                token: self.token,
            },
            State::Finished(o) => Request::Finished(o),
        }
    }
    pub fn take_curve(&mut self) -> Option<Curve> {
        if matches!(self.state, State::Finished(Outcome::Complete)) {
            self.candidate.take()
        } else {
            None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn make(d: Density) -> Sweep {
        Sweep::new(
            Route::new(2, 3).unwrap(),
            d,
            Policy {
                settle_ms: 2,
                point_timeout_ms: 20,
                stable_samples: 3,
                tolerance_millicents: 1000,
            },
            5000,
            0,
        )
        .unwrap()
    }
    fn sample(now: u64, pitch: Option<i32>) -> Measurement {
        Measurement {
            input: 2,
            sequence: now,
            window_start_ms: now.saturating_sub(1),
            window_end_ms: now,
            millicents: pitch.unwrap_or(0),
            qualified: pitch.is_some(),
        }
    }
    fn walk(
        d: Density,
        mut measure: impl FnMut(i32) -> Option<i32>,
    ) -> (Outcome, Option<Curve>, Vec<i32>) {
        let mut s = make(d);
        let mut uv = 0;
        let mut trace = Vec::new();
        let mut last_token = 0;
        for now in 0..10000 {
            let r = s.poll(now, Some(sample(now, measure(uv))));
            match r {
                Request::Apply {
                    output,
                    microvolts,
                    token,
                } => {
                    assert_eq!(output, 3);
                    assert!(token > last_token);
                    last_token = token;
                    uv = microvolts;
                    trace.push(uv);
                    assert!(s.acknowledge(token, now));
                }
                Request::Disable { output, token } => {
                    assert_eq!(output, 3);
                    assert!(token > last_token);
                    assert!(s.take_curve().is_none());
                    assert!(s.acknowledge(token, now));
                }
                Request::Finished(o) => {
                    let curve = s.take_curve();
                    assert!(s.take_curve().is_none());
                    return (o, curve, trace);
                }
                Request::Wait => {}
            }
        }
        panic!("bounded sweep did not finish")
    }
    fn ideal(uv: i32) -> i32 {
        6000000 + (uv as i64 * 1200000 / 1000000) as i32
    }
    #[test]
    fn clean_subaudio_pitch_uses_two_qualified_consistent_windows() {
        let mut s = make(Density::Semitone);
        let Request::Apply { token, .. } = s.poll(0, None) else {
            panic!("initial output request missing");
        };
        assert!(s.acknowledge(token, 0));
        assert_eq!(s.poll(3, Some(sample(3, Some(1_000_000)))), Request::Wait);
        assert!(matches!(
            s.poll(4, Some(sample(4, Some(1_000_500)))),
            Request::Apply { .. }
        ));
        assert_eq!(s.warnings().unstable, 0);
    }
    #[test]
    fn high_pitch_quantization_uses_independent_window_fallback() {
        let mut s = make(Density::Semitone);
        let Request::Apply { token, .. } = s.poll(0, None) else {
            panic!("initial output request missing");
        };
        assert!(s.acknowledge(token, 0));
        let mut advanced = false;
        for n in 0..20u64 {
            let pitch = 12_000_000 + if n & 1 == 0 { 0 } else { 4_000 };
            if matches!(s.poll(3 + n, Some(sample(3 + n, Some(pitch)))), Request::Apply { .. }) {
                advanced = true;
                break;
            }
        }
        assert!(advanced, "bounded independent-window mean was not accepted");
        assert_eq!(s.warnings().unstable, 0);
    }
    #[test]
    fn settling_excursion_does_not_disable_tight_low_pitch_recovery() {
        let mut s = make(Density::Semitone);
        let Request::Apply { token, .. } = s.poll(0, None) else {
            panic!("initial output request missing");
        };
        assert!(s.acknowledge(token, 0));
        // The first pair exceeds the 3-cent fast-path tolerance and enables
        // averaging, as observed on the WTF around 33 Hz.
        assert_eq!(s.poll(3, Some(sample(3, Some(3_000_000)))), Request::Wait);
        assert_eq!(s.poll(4, Some(sample(4, Some(3_004_000)))), Request::Wait);
        // Once the oscillator has settled, five fresh estimates within the
        // normal tolerance are sufficient; we need not wait for sixteen
        // non-overlapping windows or time the point out.
        let mut advanced = false;
        for n in 0..5u64 {
            advanced = matches!(
                s.poll(5 + n, Some(sample(5 + n, Some(3_001_000 + n as i32 * 100)))),
                Request::Apply { .. }
            );
        }
        assert!(advanced, "tight recovery remained blocked by averaging mode");
        assert_eq!(s.warnings().unstable, 0);
    }
    #[test]
    fn signal_gap_below_zero_is_characterized_without_bridging_it() {
        let (outcome, curve, _) = walk(Density::Semitone, |uv| {
            if (-1_000_000..=-500_000).contains(&uv) {
                None
            } else {
                Some(ideal(uv))
            }
        });
        assert_eq!(outcome, Outcome::Complete);
        let curve = curve.unwrap();
        assert!(curve
            .points()
            .windows(2)
            .all(|p| p[0].microvolts < p[1].microvolts));
        assert!(!curve
            .points()
            .iter()
            .any(|p| (-1_000_000..=-500_000).contains(&p.microvolts)));
    }
    #[test]
    fn inaudible_zero_searches_upward_for_a_reference_then_scans_normally() {
        let threshold = 1_000_000;
        let (outcome, curve, trace) =
            walk(Density::Semitone, |uv| (uv >= threshold).then(|| ideal(uv)));
        assert_eq!(outcome, Outcome::Complete);
        let curve = curve.unwrap();
        assert!(curve.limited_low && !curve.limited_high);
        assert_eq!(curve.points()[0].microvolts, threshold);
        assert_eq!(curve.points().last().unwrap().microvolts, 8_000_000);
        assert_eq!(trace[0], 0);
        assert!(
            trace[..trace.iter().position(|&uv| uv == -5_000_000).unwrap()]
                .windows(2)
                .all(|p| p[1] > p[0])
        );
        assert_eq!(trace.last(), Some(&threshold));
    }
    #[test]
    fn missing_reference_still_characterizes_full_range_and_restores_zero() {
        let (outcome, curve, trace) = walk(Density::Semitone, |_| None);
        assert_eq!(outcome, Outcome::Failed(Failure::OriginLost));
        assert!(curve.is_none());
        assert_eq!(trace.first(), Some(&0));
        assert_eq!(trace.last(), Some(&0));
        assert!(trace.contains(&-5_000_000));
        assert!(trace.contains(&8_000_000));
    }
    #[test]
    fn only_empty_leading_points_use_short_discovery_deadline() {
        let make_live = || {
            Sweep::new(
                Route::new(2, 3).unwrap(),
                Density::Semitone,
                Policy {
                    settle_ms: 350,
                    point_timeout_ms: 5000,
                    stable_samples: 8,
                    tolerance_millicents: 3000,
                },
                5000,
                0,
            )
            .unwrap()
        };
        let mut s = make_live();
        // An unacknowledged output is never mistaken for a range boundary.
        s.advance(Phase::Ascending, 0, 0);
        assert!(matches!(
            s.poll(2000, None),
            Request::Apply {
                microvolts: -5000000,
                ..
            }
        ));
        assert!(s.acknowledge(s.token, 2100));
        assert_eq!(s.poll(4099, None), Request::Wait);
        assert!(matches!(s.poll(4100, None), Request::Apply { .. }));
        assert_eq!(s.index, 1);
        let mut s = make_live();
        s.advance(Phase::Origin, 0, 0);
        s.acknowledge(s.token, 0);
        assert!(matches!(s.poll(2000,None),Request::Apply{microvolts,..} if microvolts>0));
        let mut s = make_live();
        s.advance(Phase::CheckEnd, 0, 0);
        s.acknowledge(s.token, 0);
        assert_eq!(s.poll(2000, None), Request::Wait);
        let mut s = make_live();
        s.advance(Phase::Ascending, 0, 0);
        s.acknowledge(s.token, 0);
        // Even one settled qualified observation retains the full deadline.
        assert_eq!(s.poll(500, Some(sample(500, Some(6000000)))), Request::Wait);
        assert_eq!(s.poll(2000, None), Request::Wait);
        let mut s = make_live();
        s.candidate.as_mut().unwrap().add(Point {
            microvolts: -5000000,
            millicents: 0,
        });
        s.candidate.as_mut().unwrap().add(Point {
            microvolts: -4916667,
            millicents: 100000,
        });
        s.advance(Phase::Ascending, 2, 0);
        s.acknowledge(s.token, 0);
        assert_eq!(s.poll(2000, None), Request::Wait);
    }
    #[test]
    fn full_bipolar_sweeps_acquire_strictly_upward_after_zero_preflight() {
        for d in [Density::QuarterVolt, Density::Semitone] {
            let (o, curve, trace) = walk(d, |uv| Some(ideal(uv)));
            assert_eq!(o, Outcome::Complete);
            let c = curve.unwrap();
            assert_eq!(
                c.count,
                (bipolar::full_intervals(d) + 1).min(bipolar::MAX_POINTS)
            );
            assert_eq!(c.points()[0].microvolts, -5000000);
            assert_eq!(c.points().last().unwrap().microvolts, 8000000);
            assert!(!c.limited_low && !c.limited_high);
            for pair in c.points().windows(2) {
                assert!(pair[0].microvolts < pair[1].microvolts);
                assert!(pair[0].millicents < pair[1].millicents);
            }
            assert_eq!(trace[0], 0);
            assert_eq!(trace[1], -5000000);
            let pass = &trace[1..trace.len() - 1];
            assert_eq!(pass.len(), bipolar::full_intervals(d) + 1);
            assert!(pass.windows(2).all(|p| p[1] > p[0]));
            assert_eq!(trace.last(), Some(&0));
            assert!(core::mem::size_of::<Sweep>() < 2400);
        }
    }
    #[test]
    fn boundaries_are_independent_and_keep_only_contiguous_measured_points() {
        for (lo, hi) in [(-1000000, 2000000), (0, 2000000), (-1000000, 0)] {
            let (o, c, _) = walk(Density::Semitone, |uv| {
                if (lo..=hi).contains(&uv) {
                    Some(ideal(uv))
                } else {
                    None
                }
            });
            assert_eq!(o, Outcome::Complete);
            let c = c.unwrap();
            assert_eq!(c.points()[0].microvolts, lo);
            assert_eq!(c.points().last().unwrap().microvolts, hi);
            assert!(c.limited_low && c.limited_high);
        }
    }
    #[test]
    fn ascending_pass_finishes_after_an_interior_gap_without_bridging_it() {
        let (o, c, trace) = walk(Density::Semitone, |uv| {
            if uv == 1000000 {
                None
            } else {
                Some(ideal(uv))
            }
        });
        assert_eq!(o, Outcome::Complete);
        let c = c.unwrap();
        assert_eq!(c.points().last().unwrap().microvolts, 8000000);
        assert!(c.limited_low);
        assert!(trace.iter().any(|v| *v > 1000000));
        assert!(!c.points().iter().any(|p| p.microvolts == 1000000));
    }
    #[test]
    fn audible_lower_plateau_is_discovered_without_saving_flat_points() {
        for noise in [-1000, 0, 1000] {
            let (o, c, _) = walk(Density::Semitone, |uv| {
                Some(if uv < -4000000 {
                    ideal(-4000000) + if uv == -5000000 { 0 } else { noise }
                } else {
                    ideal(uv)
                })
            });
            assert_eq!(o, Outcome::Complete);
            let c = c.unwrap();
            assert!(c.limited_low && !c.limited_high);
            assert_eq!(c.points()[0].microvolts, -4000000);
            assert_eq!(c.points().last().unwrap().microvolts, 8000000);
            assert_eq!(c.count, bipolar::MAX_POINTS);
        }
    }
    #[test]
    fn negative_cv_dead_zone_can_reset_at_zero_without_saving_the_plateau() {
        let plateau = ideal(0) + 1_200_000;
        let (o, c, _) = walk(Density::Semitone, |uv| {
            Some(if uv < 0 { plateau } else { ideal(uv) })
        });
        assert_eq!(o, Outcome::Complete);
        let c = c.unwrap();
        assert!(c.limited_low && !c.limited_high);
        assert_eq!(
            c.points()[0],
            Point {
                microvolts: 0,
                millicents: ideal(0)
            }
        );
        assert_eq!(c.points().last().unwrap().microvolts, 8_000_000);
        assert_eq!(c.count, bipolar::positive_intervals(Density::Semitone) + 1);
        assert!(c
            .points()
            .windows(2)
            .all(|p| p[0].microvolts < p[1].microvolts && p[0].millicents < p[1].millicents));
    }
    #[test]
    fn negative_dead_zone_ignores_alternating_integer_period_families() {
        let plateau = ideal(0) + 1_200_000;
        let (o, c, _) = walk(Density::Semitone, |uv| {
            Some(if uv < 0 {
                let step = ((uv + 5_000_000) / 83_250) as usize;
                plateau + [0, 1_200_000, 1_901_955, 2_400_000][step & 3]
            } else {
                ideal(uv)
            })
        });
        assert_eq!(o, Outcome::Complete);
        let c = c.unwrap();
        assert!(c.limited_low && !c.limited_high);
        assert_eq!(
            c.points()[0],
            Point {
                microvolts: 0,
                millicents: ideal(0)
            }
        );
        assert_eq!(c.points().last().unwrap().microvolts, 8_000_000);
        assert_eq!(c.count, bipolar::positive_intervals(Density::Semitone) + 1);
    }
    #[test]
    fn established_curve_corrects_repeatable_period_family_switches_but_not_other_drops() {
        for offset in [1_200_000, 1_901_955, 2_400_000] {
            let (o, c, _) = walk(Density::Semitone, |uv| {
                Some(ideal(uv) - if uv >= -4416750 { offset } else { 0 })
            });
            assert_eq!(o, Outcome::Complete);
            let c = c.unwrap();
            assert!(c
                .points()
                .windows(2)
                .all(|p| p[0].millicents < p[1].millicents));
        }
        let (o, c, _) = walk(Density::Semitone, |uv| {
            Some(ideal(uv) - if uv == 1000000 { 100000 } else { 0 })
        });
        assert_eq!(o, Outcome::Complete);
        assert!(c.is_some());
    }
    #[test]
    fn discovery_does_not_hide_an_initial_octave_drop_or_bridge_a_gap() {
        let (o, c, _) = walk(Density::Semitone, |uv| {
            Some(ideal(uv) - if uv == -4916750 { 1200000 } else { 0 })
        });
        assert_eq!(o, Outcome::Complete);
        assert!(c.is_some());
        let (o, c, _) = walk(Density::Semitone, |uv| {
            if uv == -4916750 {
                None
            } else {
                Some(ideal(uv))
            }
        });
        assert_eq!(o, Outcome::Complete);
        let c = c.unwrap();
        assert!(c.limited_low);
        assert_eq!(c.points()[0].microvolts, -4833250);
    }
    #[test]
    fn upper_plateau_requires_three_qualified_points_and_retains_only_tracking_range() {
        for noise in [-1000, 0, 1000] {
            let (o, c, trace) = walk(Density::Semitone, |uv| {
                Some(if uv > 3000000 {
                    ideal(3000000) + noise
                } else {
                    ideal(uv)
                })
            });
            assert_eq!(o, Outcome::Complete);
            let c = c.unwrap();
            assert!(c.limited_high);
            assert_eq!(c.points().last().unwrap().microvolts, 2916750);
            assert!(trace.contains(&3250000));
            assert!(trace.contains(&8000000));
        }
    }
    #[test]
    fn incomplete_or_unqualified_upper_plateau_is_not_accepted() {
        for missing in [false, true] {
            let (o, c, _) = walk(Density::Semitone, |uv| {
                if missing && uv == 3166750 {
                    return None;
                }
                Some(if (missing && uv > 3000000) || (!missing && uv > 4916750) {
                    ideal(if missing { 3000000 } else { 4916750 })
                } else {
                    ideal(uv)
                })
            });
            assert_eq!(o, Outcome::Complete);
            assert!(c.is_some());
        }
    }
    #[test]
    fn lost_origin_drift_flat_tracking_and_no_usable_span_fail_without_curve() {
        let mut went_negative = false;
        let (o, c, _) = walk(Density::QuarterVolt, |uv| {
            if uv < 0 {
                went_negative = true;
                None
            } else if went_negative {
                None
            } else {
                Some(ideal(uv))
            }
        });
        assert_eq!(o, Outcome::Failed(Failure::OriginLost));
        assert!(c.is_none());
        let mut went_positive = false;
        let (o, c, _) = walk(Density::QuarterVolt, |uv| {
            if uv > 0 {
                went_positive = true;
            }
            Some(ideal(uv) + if went_positive && uv == 0 { 6000 } else { 0 })
        });
        assert_eq!(o, Outcome::Failed(Failure::OriginChanged));
        assert!(c.is_none());
        let (o, c, _) = walk(Density::QuarterVolt, |_| Some(6000000));
        assert_eq!(o, Outcome::Failed(Failure::NotTracking));
        assert!(c.is_none());
        let (o, c, _) = walk(Density::QuarterVolt, |uv| {
            if uv == 0 {
                Some(6000000)
            } else {
                None
            }
        });
        assert_eq!(o, Outcome::Failed(Failure::NotTracking));
        assert!(c.is_none());
    }
    #[test]
    fn sub_octave_detector_island_never_reaches_verification() {
        // Four otherwise clean semitone-density measurements used to escape
        // as a profile and then waste time timing out in automatic replay.
        let (o, c, _) = walk(Density::Semitone, |uv| {
            (0..=250_000).contains(&uv).then(|| ideal(uv))
        });
        assert_eq!(o, Outcome::Failed(Failure::NotTracking));
        assert!(c.is_none());
    }
    #[test]
    fn output_ack_timeout_cancel_and_restoration_are_not_measured_boundaries() {
        let mut s = make(Density::Semitone);
        assert!(matches!(
            s.poll(20, None),
            Request::Disable { token: 2, .. }
        ));
        assert!(s.acknowledge(2, 20));
        assert_eq!(
            s.poll(21, None),
            Request::Finished(Outcome::Failed(Failure::Output))
        );
        assert!(s.take_curve().is_none());
        for failure in [false, true] {
            let mut s = make(Density::Semitone);
            s.acknowledge(1, 0);
            if failure {
                s.output_failed();
            } else {
                s.cancel();
                s.cancel();
            }
            let request = s.poll(2, None);
            assert!(matches!(request, Request::Disable { token: 2, .. }));
            assert!(!s.acknowledge(1, 2));
            assert_eq!(s.poll(100, None), request);
            assert!(s.take_curve().is_none());
            assert!(s.acknowledge(2, 100));
        }
    }
    #[test]
    fn wrong_channel_cached_old_or_unstable_samples_cannot_record_origin() {
        for bad in 0..5 {
            let mut s = make(Density::Semitone);
            s.acknowledge(1, 0);
            for now in 1..20 {
                let mut m = sample(now, Some(6000000));
                match bad {
                    0 => m.input = 1,
                    1 => m.sequence = 1,
                    2 => m.window_start_ms = 0,
                    // Exceed both the 1-cent fast path and the bounded 8-cent
                    // independent-window fallback.
                    3 => m.millicents += if now % 2 == 0 { 10_000 } else { 0 },
                    _ => m.qualified = false,
                }
                assert_eq!(s.poll(now, Some(m)), Request::Wait);
            }
            let deadline = if bad == 3 { 2520 } else { 20 };
            assert!(
                matches!(s.poll(deadline,None),Request::Apply{microvolts,token:2,..}
                if microvolts>0)
            );
            assert!(s.take_curve().is_none());
        }
        let mut s = make(Density::QuarterVolt);
        s.acknowledge(1, 5);
        assert!(matches!(s.poll(4, None), Request::Disable { token: 2, .. }));
        s.acknowledge(2, 6);
        assert_eq!(
            s.poll(6, None),
            Request::Finished(Outcome::Failed(Failure::Clock))
        );
    }
}
