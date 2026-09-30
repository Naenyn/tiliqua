//! Bounded, read-only verification plan and aggregate results. No curve edits.
use super::{deviation::Summary, CalibrationGrade, CalibrationQuality, Point, Profile};

/// Automatic release checks certify the stated audio-frequency operating
/// range. Characterization may retain useful observations outside it, but a
/// multi-second LFO period must not make an otherwise valid audio profile fail
/// because sixteen independent estimates cannot fit inside the bounded replay
/// timeout.
pub const AUDIO_LOW_MC: i32 = 1_548_682; // 20 Hz at A4=440 Hz
pub const AUDIO_HIGH_MC: i32 = 13_507_623; // 20 kHz at A4=440 Hz

/// Fixed, bounded coverage plus curvature probes. This is a sampled check,
/// not a certificate of every pitch between probes. Freeze it across retries.
#[derive(Clone)]
pub struct TargetedPlan {
    pub pitches: [i32; 50],
    pub len: u8,
}
impl TargetedPlan {
    fn insert(&mut self, pitch: i32) {
        let n = self.len as usize;
        if self.pitches[..n].contains(&pitch) {
            return;
        }
        assert!(n < self.pitches.len());
        let i = self.pitches[..n]
            .iter()
            .position(|&v| v > pitch)
            .unwrap_or(n);
        self.pitches.copy_within(i..n, i + 1);
        self.pitches[i] = pitch;
        self.len += 1;
    }
    pub fn new(profile: &Profile) -> Option<Self> {
        let p = profile.points();
        if p.len() < 2 {
            return None;
        }
        let lo = p[0].millicents.max(AUDIO_LOW_MC) as i64;
        let hi = p.last()?.millicents.min(AUDIO_HIGH_MC) as i64;
        if lo >= hi {
            return None;
        }
        let mut plan = Self {
            pitches: [0; 50],
            len: 0,
        };
        plan.insert(lo as i32);
        plan.insert(hi as i32);
        // 31 interior coverage probes, never more than 1/32 of the measured
        // pitch span apart. Their locations do not depend on note naming.
        for i in 1..32 {
            plan.insert((lo + (hi - lo) * i / 32) as i32);
        }
        if let Some(reference) = RepeatCheck::at_voltage(profile, 0)
            .filter(|point| lo <= point.millicents as i64 && point.millicents as i64 <= hi)
        {
            plan.insert(reference.millicents);
        }
        // Reserve one probe for the steepest measured interval. A pitch
        // discontinuity can hide between two acquisition anchors even when
        // the normal coverage grid misses its narrow voltage neighborhood.
        let steepest = p.windows(2).enumerate().max_by_key(|(_, pair)| {
            (pair[1].millicents as i64 - pair[0].millicents as i64) * 1_000_000
                / (pair[1].microvolts as i64 - pair[0].microvolts as i64)
        });
        if let Some((_, pair)) = steepest {
            let midpoint = (pair[0].millicents as i64 + pair[1].millicents as i64) / 2;
            if lo <= midpoint && midpoint <= hi {
                plan.insert(midpoint as i32);
            }
        }
        // Seven curvature centers (at most fourteen neighbors) plus the
        // steepest-interval probe fit within the fixed 50-target budget.
        let mut ranked = [(0i64, 0usize); 7];
        for i in 1..p.len() - 1 {
            let (a, b, c) = (p[i - 1], p[i], p[i + 1]);
            let linear = a.millicents as i64
                + (b.microvolts as i64 - a.microvolts as i64)
                    * (c.millicents as i64 - a.millicents as i64)
                    / (c.microvolts as i64 - a.microvolts as i64);
            let score = (b.millicents as i64 - linear).abs();
            if let Some(pos) = ranked.iter().position(|&(s, _)| score > s) {
                ranked.copy_within(pos..6, pos + 1);
                ranked[pos] = (score, i);
            }
        }
        for (score, i) in ranked {
            if score == 0 {
                continue;
            }
            for pair in [&p[i - 1..=i], &p[i..=i + 1]] {
                let midpoint = (pair[0].millicents as i64 + pair[1].millicents as i64) / 2;
                if lo <= midpoint && midpoint <= hi {
                    plan.insert(midpoint as i32);
                }
            }
        }
        Some(plan)
    }
}

#[derive(Clone)]
pub enum ExtraPlan {
    Repeat(RepeatCheck),
    Targeted(TargetedPlan),
}

/// Temporary engineering check: two rounds, both approach directions, three
/// nearby voltages, and a zero-volt reference before each approach. No edits.
#[derive(Clone, Copy, Default)]
pub struct RepeatStats {
    pub count: u8,
    pub sum: f32,
    pub first: f32,
    pub last: f32,
    pub low: f32,
    pub high: f32,
}
#[derive(Clone)]
pub struct RepeatCheck {
    pub targets: [Point; 3],
    pub stats: [RepeatStats; 7], // low/up, low/down, target/up/down, high/up/down, reference
}
impl RepeatCheck {
    pub const TOTAL: u16 = 36;
    fn at_voltage(profile: &Profile, uv: i32) -> Option<Point> {
        let uv = crate::bipolar::decode_voltage(crate::bipolar::encode_profile_voltage(uv)?)?;
        let pair = profile
            .points()
            .windows(2)
            .find(|p| p[0].microvolts <= uv && uv <= p[1].microvolts)?;
        let pitch = pair[0].millicents as i64
            + (uv - pair[0].microvolts) as i64 * (pair[1].millicents - pair[0].millicents) as i64
                / (pair[1].microvolts - pair[0].microvolts) as i64;
        Some(Point {
            microvolts: uv,
            millicents: i32::try_from(pitch).ok()?,
        })
    }
    pub fn request(&self, profile: &Profile, step: u16) -> Option<Point> {
        if step >= Self::TOTAL {
            return None;
        }
        let group = (step / 3) % 6;
        let point = self.targets[(group / 2) as usize];
        match step % 3 {
            0 => Self::at_voltage(profile, 0),
            1 => Self::at_voltage(
                profile,
                point.microvolts + if group % 2 == 0 { -83333 } else { 83333 },
            ),
            _ => Some(point),
        }
    }
    fn record(&mut self, step: u16, s: Summary) {
        let index = match step % 3 {
            0 => 6,
            2 => ((step / 3) % 6) as usize,
            _ => return,
        };
        let a = &mut self.stats[index];
        if a.count == 0 {
            a.first = s.mean;
            a.low = s.mean;
            a.high = s.mean;
        }
        a.count += 1;
        a.sum += s.mean;
        a.last = s.mean;
        a.low = a.low.min(s.mean);
        a.high = a.high.max(s.mean);
    }
}

/// Three read-only triplets, placing the target between endpoint measurements.
/// Reverse alternate passes to expose direction/settling sensitivity.
#[derive(Clone)]
pub struct LocalCheck {
    pub targets: [Point; 3],
    pub results: [Option<Summary>; 9],
    pub tested: usize,
}
impl LocalCheck {
    /// A timed-out visit is an observation with no qualified pitch, not a
    /// reason to abandon the rest of an automatic check.
    pub fn record_missing(&mut self) -> bool {
        if self.tested >= Self::ORDER.len() {
            return false;
        }
        self.tested += 1;
        self.tested == Self::ORDER.len()
    }
    /// Worst signed individual repeat mean, including endpoints. This is not
    /// the endpoint-adjusted interpolation residual used to propose edits.
    pub fn worst_absolute(&self) -> Option<(i32, f32)> {
        if self.tested != 9 {
            return None;
        }
        let mut worst = (self.targets[0].millicents, 0.0f32);
        for i in 0..9 {
            let s = self.results[i]?;
            let pitch = self.targets[Self::ORDER[i]].millicents;
            if !s.settled(pitch) {
                return None;
            }
            if s.mean.abs() > worst.1.abs() {
                worst = (pitch, s.mean);
            }
        }
        worst.1.is_finite().then_some(worst)
    }
    /// Shared acquisition gate: advice never authorizes a curve change.
    /// REFINE must still reacquire and independently validate a candidate.
    pub fn refinement_issue(&self) -> Option<&'static str> {
        let Some(values) = self.residuals() else {
            return Some("LOCAL CHECK INCOMPLETE");
        };
        let residual = self.residual().unwrap();
        if values.iter().copied().fold(f32::NEG_INFINITY, f32::max)
            - values.iter().copied().fold(f32::INFINITY, f32::min)
            > 0.75
            || (0..3).any(|i| self.aggregate(i).unwrap().2 > 0.75)
        {
            return Some("REFINE NOT REPEATABLE");
        }
        // A repeatable near-zero residual needs no curve correction. Do not
        // mislabel this as noisy acquisition, including sign flips near zero.
        if residual.abs() < 1.0 {
            return Some("LOCAL ERROR <1C - NO REFINE");
        }
        if values.iter().any(|r| r.signum() != residual.signum()) {
            return Some("REFINE NOT REPEATABLE");
        }
        // A repeatable, isolated midpoint error is precisely what an inserted
        // calibration point can correct. Keep a conservative bound on the
        // proposed edit; larger jumps may be detector or oscillator faults.
        if self.aggregate(2).unwrap().0.abs() > 25.0
            || (0..2).any(|i| self.aggregate(i).unwrap().0.abs() > 3.0)
        {
            return Some("REFINE DRIFT - RECALIBRATE");
        }
        None
    }
    pub fn advice(&self) -> &'static str {
        self.refinement_issue().unwrap_or("LOCAL ERROR: TRY REFINE")
    }
    pub const ORDER: [usize; 9] = [0, 2, 1, 1, 2, 0, 0, 2, 1];
    pub fn next(&self) -> Option<&Point> {
        Self::ORDER.get(self.tested).map(|&i| &self.targets[i])
    }
    pub fn new(profile: &Profile, pitch: i32) -> Option<Self> {
        let pair = profile
            .points()
            .windows(2)
            .find(|p| p[0].millicents <= pitch && pitch <= p[1].millicents)?;
        let uv = profile.voltage_for_pitch(pitch).ok()?;
        let uv = crate::bipolar::decode_voltage(crate::bipolar::encode_profile_voltage(uv)?)?;
        Some(Self {
            targets: [
                pair[0],
                pair[1],
                Point {
                    microvolts: uv,
                    millicents: pitch,
                },
            ],
            results: [None; 9],
            tested: 0,
        })
    }
    pub fn record(&mut self, s: Summary) -> bool {
        if self.tested == Self::ORDER.len() || !s.settled(self.next().unwrap().millicents) {
            return false;
        }
        self.results[self.tested] = Some(s);
        self.tested += 1;
        true
    }
    pub fn residual(&self) -> Option<f32> {
        let values = self.residuals()?;
        Some(values.iter().sum::<f32>() / 3.0)
    }
    pub fn residuals(&self) -> Option<[f32; 3]> {
        if self.tested != 9 {
            return None;
        }
        let fraction = (self.targets[2].microvolts - self.targets[0].microvolts) as f32
            / (self.targets[1].microvolts - self.targets[0].microvolts) as f32;
        let mut values = [0.0; 3];
        for (round, value) in values.iter_mut().enumerate() {
            let mut means = [0.0; 3];
            for i in round * 3..round * 3 + 3 {
                means[Self::ORDER[i]] = self.results[i]?.mean;
            }
            *value = means[2] - (means[0] + (means[1] - means[0]) * fraction);
        }
        Some(values)
    }
    /// Mean, peak within-window span, and between-repeat mean range.
    pub fn aggregate(&self, target: usize) -> Option<(f32, f32, f32)> {
        let mut count = 0;
        let mut sum = 0.0;
        let mut span = 0.0f32;
        let mut low = f32::INFINITY;
        let mut high = f32::NEG_INFINITY;
        for (i, result) in self.results.iter().enumerate() {
            if Self::ORDER[i] != target {
                continue;
            }
            if let Some(s) = result {
                count += 1;
                sum += s.mean;
                span = span.max(s.spread);
                low = low.min(s.mean);
                high = high.max(s.mean);
            }
        }
        if count == 0 {
            None
        } else {
            Some((sum / count as f32, span, high - low))
        }
    }
}

#[derive(Clone)]
pub struct Scan {
    pub extra: Option<ExtraPlan>,
    pub points_mode: bool,
    pub first_errors: [Option<f32>; 2],
    pub worst_index: usize,
    pub target: i32,
    pub total: u16,
    pub tested: u16,
    /// Targets visited without a qualified pitch. Never fill these in from
    /// the calibration curve or call such a replay fully verified.
    pub missing: u16,
    /// Missing grid targets in a targeted verification (at most 50 targets).
    /// Keep every gap so range selection is based on the whole replay, not
    /// whichever target happened to fail first.
    pub missing_grid_mask: u64,
    /// Targeted-grid observations with >10c within-window spread. A single
    /// worst-spread value cannot reveal several separated unstable sections.
    pub unstable_grid_mask: u64,
    /// Physical CV of the first missing observation, when supplied by the
    /// live adapter. Retained for diagnosis if recovery cannot continue.
    pub first_missing_uv: Option<i32>,
    pub worst_pitch: i32,
    pub worst_error: f32,
    pub max_spread: f32,
    /// Grid target responsible for max_spread, if observed by record().
    pub max_spread_pitch: Option<i32>,
    pub complete: bool,
    pub local: Option<LocalCheck>,
}
impl Scan {
    pub fn repeat_check(&self) -> Option<&RepeatCheck> {
        match self.extra.as_ref() {
            Some(ExtraPlan::Repeat(r)) => Some(r),
            _ => None,
        }
    }
    pub fn targeted_plan(&self) -> Option<&TargetedPlan> {
        match self.extra.as_ref() {
            Some(ExtraPlan::Targeted(p)) => Some(p),
            _ => None,
        }
    }
    pub fn targeted(profile: &Profile) -> Option<Self> {
        let mut scan = Self::new(profile)?;
        let plan = TargetedPlan::new(profile)?;
        scan.target = plan.pitches[0];
        scan.total = plan.len as u16;
        scan.extra = Some(ExtraPlan::Targeted(plan));
        Some(scan)
    }
    /// Check only the half-volt of measured response adjacent to a newly
    /// trimmed boundary. This is a recovery probe, never a full-profile
    /// quality certificate; the adapter must follow it with targeted().
    pub fn targeted_boundary(profile: &Profile, high: bool) -> Option<Self> {
        let points = profile.points();
        let edge_uv = if high { points.last()?.microvolts } else { points.first()?.microvolts };
        let inner_uv = if high { edge_uv.saturating_sub(500_000) }
            else { edge_uv.saturating_add(500_000) };
        let index = points.partition_point(|p| p.microvolts < inner_uv);
        let inner = points[index.min(points.len() - 1)];
        let edge = if high { *points.last()? } else { *points.first()? };
        let lo = inner.millicents.min(edge.millicents).max(AUDIO_LOW_MC);
        let hi = inner.millicents.max(edge.millicents).min(AUDIO_HIGH_MC);
        if hi <= lo { return None; }
        let mut plan = TargetedPlan { pitches: [0; 50], len: 0 };
        // This is only a quick guard on the newly exposed edge, never the
        // independent certificate. Five evenly spaced pitches plus the two
        // adjacent acquisition-interval midpoints catch a renewed boundary
        // fault without paying for a dense replay that the final full check
        // must repeat anyway.
        for i in 0..=4 {
            plan.insert((lo as i64 + (hi - lo) as i64 * i / 4) as i32);
        }
        // Probe the two intervals nearest the cut even if uniform spacing
        // misses a steep measured bend there.
        let nearest = if high { points.len() - 1 } else { 0 };
        for offset in 0..2 {
            let i = if high { nearest.checked_sub(offset + 1)? } else { nearest + offset };
            if let Some(pair) = points.get(i..=i + 1) {
                let mid = ((pair[0].millicents as i64 + pair[1].millicents as i64) / 2) as i32;
                if lo <= mid && mid <= hi { plan.insert(mid); }
            }
        }
        let mut scan = Self::new(profile)?;
        scan.target = plan.pitches[0];
        scan.total = plan.len as u16;
        scan.extra = Some(ExtraPlan::Targeted(plan));
        Some(scan)
    }
    pub fn recheck(&self, profile: &Profile) -> Option<Self> {
        let mut scan = Self::new(profile)?;
        if let Some(plan) = self.targeted_plan() {
            for &pitch in &plan.pitches[..plan.len as usize] {
                profile.voltage_for_pitch(pitch).ok()?;
            }
            scan.target = plan.pitches[0];
            scan.total = plan.len as u16;
            scan.extra = Some(ExtraPlan::Targeted(plan.clone()));
        }
        Some(scan)
    }
    pub fn checked_worst(&self) -> (i32, f32) {
        let initial = (self.worst_pitch, self.worst_error);
        self.local
            .as_ref()
            .and_then(LocalCheck::worst_absolute)
            .filter(|(_, error)| error.abs() > initial.1.abs())
            .unwrap_or(initial)
    }
    /// Compare the grid's worst target with its later interleaved repeat at
    /// the identical commanded voltage. A stable local trio alone does not
    /// make the whole check repeatable if the earlier grid read differed.
    pub fn grid_local_disagreement(&self) -> Option<f32> {
        let check = self.local.as_ref()?;
        if check.tested != LocalCheck::ORDER.len()
            || check.targets[2].millicents != self.worst_pitch
        {
            return None;
        }
        Some((self.worst_error - check.aggregate(2)?.0).abs())
    }
    pub fn meets_target(&self, target: f32) -> bool {
        self.meets_policy(target, 0.75)
    }

    pub fn meets_policy(&self, target: f32, repeatability: f32) -> bool {
        self.complete
            && self.missing == 0
            && self.worst_error.is_finite()
            && self.worst_error.abs() <= target
            && self
                .local
                .as_ref()
                .and_then(LocalCheck::worst_absolute)
                .is_some_and(|(_, error)| error.abs() <= target)
            && self.local.as_ref().is_some_and(|c| {
                (0..3).all(|i| {
                    c.aggregate(i)
                        .is_some_and(|(_, _, repeat)| repeat <= repeatability)
                })
            })
            // Both readings can legitimately be within the pitch target
            // while differing by more than the much tighter local-repeat
            // tolerance. Use the Precision stability limit here; quality()
            // still grades the actual disagreement at 3/5/10 cents.
            && self.grid_local_disagreement().is_some_and(|d| d <= repeatability.max(3.0))
    }

    /// Grade only a completed independent replay.  Accuracy and stability are
    /// reported separately so a repeatable character oscillator is not
    /// misrepresented as precision, while detector ambiguity still fails
    /// before a quality result can be produced.
    pub fn quality(&self) -> CalibrationQuality {
        if !self.complete || self.missing != 0 || self.local.as_ref().map_or(true, |c| c.tested != 9) {
            return CalibrationQuality {
                grade: CalibrationGrade::Unsafe,
                ..CalibrationQuality::default()
            };
        }
        let worst = self.checked_worst().1.abs();
        let local_repeat = self
            .local
            .as_ref()
            .map(|c| {
                (0..3)
                    .filter_map(|i| c.aggregate(i).map(|(_, _, repeat)| repeat))
                    .fold(0.0f32, f32::max)
            })
            .unwrap_or(f32::INFINITY);
        let stability = self.max_spread.max(local_repeat)
            .max(self.grid_local_disagreement().unwrap_or(f32::INFINITY));
        let grade = if worst <= 2.0 && stability <= 3.0 {
            CalibrationGrade::Precision
        } else if worst <= 5.0 && stability <= 5.0 {
            CalibrationGrade::Musical
        } else if worst <= 10.0 && stability <= 10.0 {
            CalibrationGrade::Character
        } else {
            CalibrationGrade::Unsafe
        };
        CalibrationQuality {
            grade,
            worst_millicents: (worst.max(0.0) * 1000.0 + 0.5) as u32,
            stability_millicents: (stability.max(0.0) * 1000.0 + 0.5) as u32,
        }
    }
    /// Shared display/serial conclusion, distinct from operation completion.
    pub fn accuracy_label(&self) -> &'static str {
        if !self.complete || self.missing != 0 || self.local.as_ref().map_or(true, |c| c.tested != 9) {
            "ACCURACY CHECK INCOMPLETE"
        } else if self.meets_target(super::automatic::TARGET_CENTS) {
            "CHECKED PITCHES WITHIN 2C"
        } else {
            "OUTSIDE 2C OR NOT REPEATABLE"
        }
    }
    /// Whole notes and their 50-cent midpoints, strictly inside measured bounds.
    /// Follow the measured profile, independent of manual note-menu limits.
    pub fn new(profile: &Profile) -> Option<Self> {
        let p = profile.points();
        if p.len() < 2 {
            return None;
        }
        let first = (p[0].millicents as i64 + 49999).div_euclid(50000) * 50000;
        let last = (p.last()?.millicents as i64).div_euclid(50000) * 50000;
        if first > last {
            return None;
        }
        let total = u16::try_from((last - first) / 50000 + 1).ok()?;
        Some(Self {
            extra: None,
            points_mode: false,
            first_errors: [None; 2],
            worst_index: 0,
            target: first as i32,
            total,
            tested: 0,
            missing: 0,
            missing_grid_mask: 0,
            unstable_grid_mask: 0,
            first_missing_uv: None,
            worst_pitch: first as i32,
            worst_error: 0.0,
            max_spread: 0.0,
            max_spread_pitch: None,
            complete: false,
            local: None,
        })
    }
    /// Replay stored points, including fractional-note endpoints. The adapter
    /// must advance target from the profile and replay the original DAC count.
    pub fn points(profile: &Profile) -> Option<Self> {
        let p = profile.points();
        if p.len() < 2 {
            return None;
        }
        Some(Self {
            extra: None,
            points_mode: true,
            first_errors: [None; 2],
            worst_index: 0,
            target: p[0].millicents,
            total: p.len() as u16,
            tested: 0,
            missing: 0,
            missing_grid_mask: 0,
            unstable_grid_mask: 0,
            first_missing_uv: None,
            worst_pitch: p[0].millicents,
            worst_error: 0.0,
            max_spread: 0.0,
            max_spread_pitch: None,
            complete: false,
            local: None,
        })
    }
    /// Each result is a settled, fresh window from the adapter. Reject unstable
    /// windows rather than calling them an accuracy measurement.
    pub fn record(&mut self, s: Summary) -> bool {
        if self.complete || !s.settled(self.target) {
            return false;
        }
        if self.tested == 0 || s.mean.abs() > self.worst_error.abs() {
            self.worst_error = s.mean;
            self.worst_pitch = self.target;
            self.worst_index = self.tested as usize;
        }
        if self.tested < 2 {
            self.first_errors[self.tested as usize] = Some(s.mean);
        }
        if s.spread > self.max_spread {
            self.max_spread = s.spread;
            self.max_spread_pitch = Some(self.target);
        }
        if s.spread > 10.0 && self.targeted_plan().is_some() && self.tested < 64 {
            self.unstable_grid_mask |= 1u64 << self.tested;
        }
        self.tested += 1;
        self.complete = self.tested == self.total;
        if !self.complete && !self.points_mode {
            self.target = self
                .targeted_plan()
                .map_or(self.target + 50000, |p| p.pitches[self.tested as usize]);
        }
        true
    }
    /// Advance an automatic replay after a bounded per-target timeout. The
    /// target is counted as missing, not assigned a synthetic pitch/error.
    pub fn record_missing(&mut self) -> bool {
        if self.complete || self.tested >= self.total {
            return false;
        }
        if self.targeted_plan().is_some() && self.tested < 64 {
            self.missing_grid_mask |= 1u64 << self.tested;
        }
        self.missing += 1;
        self.tested += 1;
        self.complete = self.tested == self.total;
        if !self.complete && !self.points_mode {
            self.target = self
                .targeted_plan()
                .map_or(self.target + 50000, |p| p.pitches[self.tested as usize]);
        }
        true
    }
    pub fn repeat(profile: &Profile, uv: i32) -> Option<Self> {
        let target = RepeatCheck::at_voltage(profile, uv)?;
        let pair = profile
            .points()
            .windows(2)
            .find(|p| p[0].microvolts < uv && uv < p[1].microvolts)?;
        let repeat = RepeatCheck {
            targets: [pair[0], target, pair[1]],
            stats: [RepeatStats::default(); 7],
        };
        // Validate every request before arming any output; never extrapolate.
        for step in 0..RepeatCheck::TOTAL {
            repeat.request(profile, step)?;
        }
        let mut scan = Self::new(profile)?;
        scan.target = repeat.request(profile, 0)?.millicents;
        scan.total = RepeatCheck::TOTAL;
        scan.extra = Some(ExtraPlan::Repeat(repeat));
        Some(scan)
    }
    pub fn record_repeat(&mut self, profile: &Profile, s: Summary) -> bool {
        if self.complete || !s.settled(self.target) {
            return false;
        }
        let Some(ExtraPlan::Repeat(repeat)) = self.extra.as_mut() else {
            return false;
        };
        repeat.record(self.tested, s);
        self.tested += 1;
        self.complete = self.tested == self.total;
        if let Some(point) = repeat.request(profile, self.tested) {
            self.target = point.millicents;
        }
        true
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    fn profile(lo: i32, hi: i32) -> Profile {
        let mut p = Profile::new("test", 0, 2000000).unwrap();
        p.push(Point {
            microvolts: 0,
            millicents: lo,
        })
        .unwrap();
        p.push(Point {
            microvolts: 2000000,
            millicents: hi,
        })
        .unwrap();
        p
    }
    #[test]
    fn boundary_check_samples_only_the_trimmed_edge_neighborhood() {
        let mut p = Profile::new("measured", 0, 2_000_000).unwrap();
        for i in 0..=24 {
            p.push(Point {
                microvolts: i * 83_333,
                millicents: 6_000_000 + i * 100_000,
            }).unwrap();
        }
        let full = Scan::targeted(&p).unwrap();
        let high = Scan::targeted_boundary(&p, true).unwrap();
        let low = Scan::targeted_boundary(&p, false).unwrap();
        assert!(high.total < full.total);
        assert!(low.total < full.total);
        assert!(high.total <= 7 && low.total <= 7);
        assert!(high.target >= 7_700_000);
        assert!(low.target <= 6_100_000);
        assert_eq!(high.targeted_plan().unwrap().pitches[high.total as usize - 1], 8_400_000);
    }
    #[test]
    fn missing_targets_advance_without_claiming_verified_accuracy() {
        let p = profile(6_000_000, 8_400_000);
        let mut scan = Scan::targeted(&p).unwrap();
        let total = scan.total;
        let first = scan.target;
        assert!(scan.record_missing());
        assert_eq!(scan.missing, 1);
        assert!(scan.target > first);
        for _ in 1..total {
            assert!(scan.record_missing());
        }
        assert!(scan.complete);
        assert_eq!(scan.tested, total);
        assert_eq!(scan.missing, total);
        assert_eq!(scan.missing_grid_mask, (1u64 << total) - 1);
        assert_eq!(scan.quality().grade, CalibrationGrade::Unsafe);
        assert!(!scan.meets_target(2.0));
        assert_eq!(scan.accuracy_label(), "ACCURACY CHECK INCOMPLETE");

        let mut local = LocalCheck::new(&p, 7_200_000).unwrap();
        for _ in 0..LocalCheck::ORDER.len() {
            local.record_missing();
        }
        assert_eq!(local.tested, 9);
        assert!(local.worst_absolute().is_none());
    }
    #[test]
    fn targeted_plan_is_bounded_sorted_covers_edges_and_freezes_across_edits() {
        let mut p = Profile::new("curved", -5000000, 5000000).unwrap();
        for i in 0..=120 {
            let uv = -5000000 + i * 10000000 / 120;
            let bend = if i >= 90 { (i - 90) * (i - 90) * 20 } else { 0 };
            p.push(Point {
                microvolts: uv,
                millicents: 7000000 + uv + bend,
            })
            .unwrap();
        }
        let scan = Scan::targeted(&p).unwrap();
        let plan = scan.targeted_plan().unwrap();
        assert!((33..=50).contains(&plan.len));
        let pitches = &plan.pitches[..plan.len as usize];
        assert_eq!(pitches.first().unwrap(), &p.points()[0].millicents);
        assert_eq!(
            pitches.last().unwrap(),
            &p.points().last().unwrap().millicents
        );
        assert!(pitches.windows(2).all(|w| w[0] < w[1]));
        let max_gap = (pitches.last().unwrap() - pitches[0] + 31) / 32;
        assert!(pitches.windows(2).all(|w| w[1] - w[0] <= max_gap));
        assert!(pitches.contains(&RepeatCheck::at_voltage(&p, 0).unwrap().millicents));
        let pair = &p.points()[90..92];
        let added = Point {
            microvolts: (pair[0].microvolts + pair[1].microvolts) / 2,
            millicents: (pair[0].millicents + pair[1].millicents) / 2 + 1000,
        };
        let edited = p.refined_with(added).unwrap();
        let again = scan.recheck(&edited).unwrap();
        assert_eq!(again.targeted_plan().unwrap().pitches, plan.pitches);
        assert_eq!(again.total, scan.total);
        let mut running = scan.clone();
        for &pitch in pitches {
            assert_eq!(running.target, pitch);
            assert!(running.record(Summary {
                mean: 0.0,
                spread: 0.1,
                count: 8,
                averaged: false
            }));
        }
        assert!(running.complete);
        assert_eq!(running.tested, plan.len as u16);
        assert!(
            core::mem::size_of::<ExtraPlan>() <= 224,
            "bounded shared storage, not two plans"
        );
    }
    #[test]
    fn targeted_replay_tracks_every_excessive_grid_spread() {
        let p = profile(6_000_000, 8_400_000);
        let mut scan = Scan::targeted(&p).unwrap();
        let first = scan.target;
        assert!(scan.record(Summary {
            mean: 0.1,
            spread: 12.0,
            count: 16,
            averaged: true,
        }));
        assert_eq!(scan.unstable_grid_mask, 1);
        assert_eq!(scan.tested, 1);
        assert_eq!(scan.max_spread_pitch, Some(first));
        assert_eq!(scan.max_spread, 12.0);
        assert!(!scan.record(Summary {
            mean: 0.0,
            spread: 26.0,
            count: 16,
            averaged: true,
        }));
        assert_eq!(scan.unstable_grid_mask, 1);
        assert_eq!(scan.tested, 1);
        assert!(scan.record(Summary {
            mean: 0.2,
            spread: 11.0,
            count: 16,
            averaged: true,
        }));
        assert_eq!(scan.unstable_grid_mask, 3);
        assert_eq!(scan.tested, 2);
    }
    #[test]
    fn targeted_plan_certifies_only_the_stated_twenty_hz_to_twenty_khz_range() {
        let mut p = Profile::new("wide", -5000000, 8000000).unwrap();
        p.push(Point {
            microvolts: -5000000,
            millicents: -2200000,
        })
        .unwrap();
        p.push(Point {
            microvolts: 8000000,
            millicents: 14000000,
        })
        .unwrap();
        let plan = TargetedPlan::new(&p).unwrap();
        let pitches = &plan.pitches[..plan.len as usize];
        assert_eq!(pitches.first(), Some(&AUDIO_LOW_MC));
        assert_eq!(pitches.last(), Some(&AUDIO_HIGH_MC));
        assert!(pitches
            .iter()
            .all(|pitch| (AUDIO_LOW_MC..=AUDIO_HIGH_MC).contains(pitch)));
    }
    #[test]
    fn sparse_checks_explicitly_cannot_certify_a_hidden_narrow_error() {
        let p = profile(6000000, 8400000);
        let sparse = Scan::targeted(&p).unwrap();
        let full = Scan::new(&p).unwrap();
        let targets = sparse.targeted_plan().unwrap();
        let missed = (0..full.total)
            .map(|i| full.target + i as i32 * 50000)
            .find(|pitch| !targets.pitches[..targets.len as usize].contains(pitch))
            .unwrap();
        let error = |pitch: i32| {
            if (pitch - missed).abs() < 1000 {
                8.0f32
            } else {
                0.0
            }
        };
        assert!(targets.pitches[..targets.len as usize]
            .iter()
            .all(|&p| error(p) == 0.0));
        assert_eq!(error(missed), 8.0);
        // This is why a sampled pass must not be labeled an exhaustive pass.
    }
    #[test]
    fn strongest_measured_bend_adds_neighboring_midpoint_probes() {
        let mut p = Profile::new("bend", 0, 2000000).unwrap();
        for i in 0..=24 {
            let uv = i * 2000000 / 24;
            p.push(Point {
                microvolts: uv,
                millicents: 6000000 + uv + if i == 17 { 12000 } else { 0 },
            })
            .unwrap();
        }
        let plan = TargetedPlan::new(&p).unwrap();
        for i in [16, 17] {
            let midpoint = (p.points()[i].millicents + p.points()[i + 1].millicents) / 2;
            assert!(plan.pitches[..plan.len as usize].contains(&midpoint));
        }
    }
    #[test]
    fn steepest_interval_probe_exposes_an_unreachable_pitch_gap() {
        // 83-mV acquisition anchors straddle a 48.8-cent jump like the one
        // observed on ACRONYM. The ordinary pitch grid need not land in it.
        let mut profile = Profile::new("step", -5_000_000, 5_000_000).unwrap();
        let actual = |uv: i32| {
            6_000_000 + uv * 6 / 5 + if uv >= 2_457_500 { 48_800 } else { 0 }
        };
        for i in 0..=120 {
            let uv = -5_000_000 + i * 10_000_000 / 120;
            profile.push(Point { microvolts: uv, millicents: actual(uv) }).unwrap();
        }
        let pair = &profile.points()[89..=90];
        let target = (pair[0].millicents + pair[1].millicents) / 2;
        let plan = TargetedPlan::new(&profile).unwrap();
        assert!(plan.pitches[..plan.len as usize].contains(&target));
        let commanded = profile.voltage_for_pitch(target).unwrap();
        let error_cents = (actual(commanded) - target).abs() / 1000;
        assert!(error_cents > 10, "gap must not certify as CHARACTER");
    }
    #[test]
    fn targeted_checks_expose_smooth_local_bends_in_synthetic_curves() {
        let mut worst_miss = 0.0f64;
        for sign in [-1.0f64, 1.0] {
            for center_index in 0..24 {
                let center = 3.9 + center_index as f64 / 240.0;
                let actual = |uv: i32| {
                    let v = uv as f64 / 1e6;
                    let x = (v - center) / 0.06;
                    6000000.0 + 1200000.0 * v + sign * 10000.0 * (-x * x).exp()
                };
                let mut p = Profile::new("smooth bend", -4000000, 5000000).unwrap();
                for i in 0..=108 {
                    let uv = -4000000 + i * 9000000 / 108;
                    p.push(Point {
                        microvolts: uv,
                        millicents: actual(uv).round() as i32,
                    })
                    .unwrap();
                }
                let sparse = Scan::targeted(&p).unwrap();
                let full = Scan::new(&p).unwrap();
                let error = |pitch| {
                    let uv = p.voltage_for_pitch(pitch).unwrap();
                    (actual(uv) - pitch as f64).abs() / 1000.0
                };
                let plan = sparse.targeted_plan().unwrap();
                let sampled = plan.pitches[..plan.len as usize]
                    .iter()
                    .map(|&p| error(p))
                    .fold(0.0f64, f64::max);
                let exhaustive = (0..full.total)
                    .map(|i| error(full.target + i as i32 * 50000))
                    .fold(0.0f64, f64::max);
                worst_miss = worst_miss.max(exhaustive - sampled);
                assert!(
                    sampled >= exhaustive - 1.0,
                    "center={center} sign={sign}: sampled={sampled}, grid={exhaustive}"
                );
            }
        }
        println!(
            "48 smooth-bend models: largest sampled undershoot vs 50-cent grid {worst_miss:.3}c"
        );
    }
    #[test]
    fn repeat_requests_are_in_range_and_approach_each_target_from_both_directions() {
        let p = profile(6000000, 8400000);
        // First bracket touches 0 V: negative preconditioning must be rejected.
        assert!(Scan::repeat(&p, 500000).is_none());
        // Last bracket touches the maximum: positive preconditioning must be rejected.
        assert!(Scan::repeat(&p, 1500000).is_none());
        let mut p = Profile::new("test", -5000000, 5000000).unwrap();
        for uv in [-5000000, 0, 4000000, 4500000, 5000000] {
            p.push(Point {
                microvolts: uv,
                millicents: 6000000 + uv,
            })
            .unwrap();
        }
        let scan = Scan::repeat(&p, 4454000).unwrap();
        let repeat = scan.repeat_check().unwrap();
        for step in (0..36).step_by(3) {
            assert_eq!(repeat.request(&p, step).unwrap().microvolts, 0);
            let before = repeat.request(&p, step + 1).unwrap().microvolts;
            let target = repeat.request(&p, step + 2).unwrap().microvolts;
            assert_eq!(before < target, (step / 3) % 2 == 0);
        }
        assert!(repeat.request(&p, 36).is_none());
    }
    #[test]
    fn local_check_separates_common_endpoint_shift_from_local_residual() {
        let p = profile(6000000, 8400000);
        let mut check = LocalCheck::new(&p, 6600000).unwrap();
        assert!(LocalCheck::new(&p, 5900000).is_none());
        assert_eq!(check.targets[2].microvolts, 500000);
        assert!(!check.record(Summary {
            averaged: false,
            mean: 0.0,
            spread: 4.0,
            count: 8
        }));
        assert_eq!(check.tested, 0);
        assert!(check.residual().is_none());
        for mean in [-1.0, -3.0, -1.0, -1.0, -3.0, -1.0, -1.0, -3.0, -1.0] {
            assert!(check.record(Summary {
                averaged: false,
                mean,
                spread: 1.0,
                count: 8
            }));
        }
        assert_eq!(check.residual(), Some(-2.0));
        assert_eq!(check.residuals(), Some([-2.0; 3]));
        assert_eq!(check.aggregate(2), Some((-3.0, 1.0, 0.0)));
        assert!(check.next().is_none());
        assert!(!check.record(Summary {
            averaged: false,
            mean: 99.0,
            spread: 0.0,
            count: 8
        }));
    }
    #[test]
    fn stable_local_repeats_do_not_hide_grid_to_local_disagreement() {
        let p = profile(6000000, 8400000);
        let mut scan = Scan::new(&p).unwrap();
        scan.tested = scan.total;
        scan.complete = true;
        scan.worst_pitch = 6600000;
        scan.worst_error = 29.34;
        let mut local = LocalCheck::new(&p, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                averaged: false,
                mean: if target == 2 { -18.12 } else { -0.03 },
                spread: 0.19,
                count: 8,
            }));
        }
        scan.local = Some(local);
        assert!((scan.grid_local_disagreement().unwrap() - 47.46).abs() < 0.01);
        assert!(!scan.meets_policy(30.0, 0.75));
        assert_eq!(scan.quality().grade, super::super::CalibrationGrade::Unsafe);
        assert!(scan.quality().stability_cents() > 47.0);
    }
    #[test]
    fn advice_distinguishes_repeatability_and_large_endpoint_bias() {
        let p = profile(6000000, 8400000);
        let make = |bias: f32, residuals: [f32; 3]| {
            let mut c = LocalCheck::new(&p, 6600000).unwrap();
            assert_eq!(c.advice(), "LOCAL CHECK INCOMPLETE");
            for (i, target) in LocalCheck::ORDER.into_iter().enumerate() {
                c.record(Summary {
                    averaged: false,
                    mean: bias + if target == 2 { residuals[i / 3] } else { 0.0 },
                    spread: 1.0,
                    count: 8,
                });
            }
            c
        };
        assert_eq!(
            make(-1.3, [-1.84, -1.70, -1.94]).advice(),
            "LOCAL ERROR: TRY REFINE"
        );
        // Fresh-baseline hardware residuals: too variable to recommend fitting.
        assert_eq!(
            make(0.0, [-0.82, -1.80, -1.67]).advice(),
            "REFINE NOT REPEATABLE"
        );
        assert_eq!(make(-4.0, [-1.5; 3]).advice(), "REFINE DRIFT - RECALIBRATE");
        assert_eq!(make(0.0, [-0.2; 3]).advice(), "LOCAL ERROR <1C - NO REFINE");
        // Observed hardware local residuals with a shared roughly +3c bias.
        assert_eq!(
            make(3.2, [0.32, 0.17, 0.13]).advice(),
            "LOCAL ERROR <1C - NO REFINE"
        );
        assert_eq!(
            make(0.0, [-0.1, 0.1, 0.0]).advice(),
            "LOCAL ERROR <1C - NO REFINE"
        );
        assert_eq!(
            make(0.0, [-0.9, 0.9, 0.0]).advice(),
            "REFINE NOT REPEATABLE"
        );
        assert_eq!(make(0.0, [0.99; 3]).advice(), "LOCAL ERROR <1C - NO REFINE");
        assert_eq!(make(0.0, [1.0; 3]).advice(), "LOCAL ERROR: TRY REFINE");
    }
    #[test]
    fn local_repeats_preserve_directional_results_and_reject_partial_residual() {
        let p = profile(6000000, 8400000);
        let mut check = LocalCheck::new(&p, 6600000).unwrap();
        // Common endpoint shift changes each pass; local residuals differ.
        for (i, mean) in [-1.0, -3.0, -1.0, 1.0, -2.0, 1.0, 2.0, 1.0, 2.0]
            .into_iter()
            .enumerate()
        {
            assert_eq!(
                check.next().unwrap().millicents,
                check.targets[LocalCheck::ORDER[i]].millicents
            );
            assert!(check.residual().is_none());
            check.record(Summary {
                averaged: false,
                mean,
                spread: 0.5,
                count: 8,
            });
        }
        assert_eq!(check.residuals(), Some([-2.0, -3.0, -1.0]));
        assert_eq!(check.residual(), Some(-2.0));
        assert_eq!(check.aggregate(2), Some((-4.0 / 3.0, 0.5, 4.0)));
        assert_eq!(check.aggregate(3), None);
    }
    #[test]
    fn plan_never_extrapolates_and_covers_half_notes() {
        for offset in [-1, 0, 1, 49999] {
            let p = profile(6000000 + offset, 8400000 + offset);
            let mut s = Scan::new(&p).unwrap();
            while !s.complete {
                assert!(p.voltage_for_pitch(s.target).is_ok());
                assert_eq!(s.target % 50000, 0);
                assert!(s.record(Summary {
                    averaged: false,
                    mean: -1.5,
                    spread: 1.0,
                    count: 8
                }));
            }
            assert_eq!(s.tested, s.total);
            assert_eq!(s.worst_error, -1.5);
            assert!(!s.record(Summary {
                averaged: false,
                mean: 99.0,
                spread: 0.0,
                count: 8
            }));
        }
        assert!(Scan::new(&profile(6000001, 6049999)).is_none());
    }
    #[test]
    fn rejects_unstable_or_invalid_results_and_retains_worst_signed_mean() {
        let mut s = Scan::new(&profile(6000000, 8400000)).unwrap();
        for (mean, spread, count) in [
            (0.0, 3.1, 8),
            (f32::NAN, 0.0, 8),
            (0.0, 0.0, 7),
            (0.0, -1.0, 8),
        ] {
            assert!(!s.record(Summary {
                averaged: false,
                mean,
                spread,
                count
            }));
            assert_eq!(s.tested, 0);
        }
        s.record(Summary {
            averaged: false,
            mean: 1.0,
            spread: 2.0,
            count: 8,
        });
        s.record(Summary {
            averaged: false,
            mean: -2.0,
            spread: 1.0,
            count: 8,
        });
        assert_eq!(s.worst_pitch, 6050000);
        assert_eq!(s.worst_error, -2.0);
        assert_eq!(s.max_spread, 2.0);
    }
    #[test]
    fn covers_profile_beyond_manual_note_limits_without_counter_overflow() {
        let scan = Scan::new(&profile(-500000, 11500000)).unwrap();
        assert_eq!(scan.target, -500000);
        assert_eq!(scan.total, 241);
        assert!(Scan::new(&profile(i32::MIN, i32::MAX)).is_none());
    }
}
