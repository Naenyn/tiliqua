//! Bounded automatic calibration policy. No allocation, flash or DAC access.
use super::{verification_scan::Scan, CalibrationGrade, CalibrationQuality, Point};
use crate::options::CalibrationPolicy;

pub const TARGET_CENTS: f32 = 2.0;
// Empirical headroom for sequential-check variation, not an uncertainty bound.
pub const COMPLETION_MARGIN_CENTS: f32 = 0.5;
pub const COMPLETION_CENTS: f32 = TARGET_CENTS - COMPLETION_MARGIN_CENTS;
// A complex but consistent response can need several measured interior
// anchors. Keep the automatic pass budget aligned with the spare capacity of
// a typical semitone-density profile; the user should see one final review.
pub const MAX_PASSES: u8 = 16;
pub const VERIFY_TIMEOUT_MS: u64 = 5000;
pub const MAX_EDGE_TRIM_POINTS: u8 = 4;
pub const MAX_EDGE_RETRIES: u8 = 2;
pub const MAX_PARTIAL_RECOVERIES: u8 = 16;
// A wildly inconsistent region is not a curve-fitting problem. Salvage a
// contiguous measured range, but do not spend the whole scan chasing it.
pub const MAX_DISAGREEMENT_TRIMS: u8 = 2;
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phase {
    Sweep,
    Verify,
    Refine,
    Reverify,
    Review,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CheckTiming {
    /// I: initial full check; F: later full check; B: boundary check; R: recheck.
    pub kind: char,
    pub ms: u32,
    pub tested: u16,
    pub total: u16,
}
pub const MAX_CHECK_TIMINGS: usize = 24;
pub struct Automatic {
    pub policy: CalibrationPolicy,
    pub phase: Phase,
    pub passes: u8,
    pub started: u64,
    pub phase_ms: [u32; 4],
    pub check_timings: [Option<CheckTiming>; MAX_CHECK_TIMINGS],
    pub check_timing_count: u8,
    pub check_timing_overflow: u8,
    check_started: Option<u64>,
    check_kind: char,
    pub last_recheck: Option<(f32, f32, bool)>,
    pub recheck_missing_uv: Option<i32>,
    pub review_reason: Option<&'static str>,
    pub last_refine: Option<(i32, f32, f32, f32)>,
    pub unstable_retries: u8,
    pub edge_retries: u8,
    pub edge_trim_low: u8,
    pub edge_trim_high: u8,
    pub partial_recoveries: u8,
    pub skipped_local_checks: u8,
    pub recovery_limit: u8,
    pub partial_recovered_sides: u8,
    pub disagreement_trims: u8,
    /// Intermediate boundary probe; never publish its grade as full coverage.
    pub regional_check: bool,
    pub last_recovery: Option<(i32, &'static str)>,
    last_tick: u64,
    pub best: Option<Scan>,
    pub undo: Option<Point>,
}
impl Automatic {
    pub fn new(now: u64) -> Self {
        Self::new_with_policy(now, CalibrationPolicy::Auto)
    }
    pub fn new_with_policy(now: u64, policy: CalibrationPolicy) -> Self {
        Self {
            policy,
            phase: Phase::Sweep,
            passes: 0,
            started: now,
            phase_ms: [0; 4],
            check_timings: [None; MAX_CHECK_TIMINGS],
            check_timing_count: 0,
            check_timing_overflow: 0,
            check_started: None,
            check_kind: 'I',
            last_recheck: None,
            recheck_missing_uv: None,
            review_reason: None,
            last_refine: None,
            unstable_retries: 0,
            edge_retries: 0,
            edge_trim_low: 0,
            edge_trim_high: 0,
            partial_recoveries: 0,
            skipped_local_checks: 0,
            recovery_limit: MAX_PARTIAL_RECOVERIES,
            partial_recovered_sides: 0,
            disagreement_trims: 0,
            regional_check: false,
            last_recovery: None,
            last_tick: now,
            best: None,
            undo: None,
        }
    }
    pub fn target_cents(&self) -> f32 {
        match self.policy {
            CalibrationPolicy::Auto | CalibrationPolicy::Fast | CalibrationPolicy::Precision => TARGET_CENTS,
            CalibrationPolicy::Forgiving => 10.0,
        }
    }
    pub fn policy_label(&self) -> &'static str {
        match self.policy {
            CalibrationPolicy::Auto => "AUTO",
            CalibrationPolicy::Precision => "PRECISION",
            CalibrationPolicy::Forgiving => "FORGIVING",
            CalibrationPolicy::Fast => "FAST",
        }
    }
    pub fn completion_cents(&self) -> f32 {
        (self.target_cents() - COMPLETION_MARGIN_CENTS).max(0.5)
    }
    pub fn repeatability_cents(&self) -> f32 {
        match self.policy {
            CalibrationPolicy::Auto | CalibrationPolicy::Fast | CalibrationPolicy::Precision => 0.75,
            CalibrationPolicy::Forgiving => 5.0,
        }
    }
    pub fn quality_allowed(&self, quality: CalibrationQuality) -> bool {
        match self.policy {
            CalibrationPolicy::Precision => quality.grade == CalibrationGrade::Precision,
            CalibrationPolicy::Auto | CalibrationPolicy::Fast | CalibrationPolicy::Forgiving => quality.acceptable(),
        }
    }
    /// A grid already containing an unsafe spread cannot be certified or
    /// refined. Its local repeats would not change the region-selection
    /// decision below. Save those nine visits only when recovery is allowed;
    /// good grids, strict policy and post-edit rechecks keep every repeat.
    pub fn skip_local_for_grid_recovery(&self, scan: &Scan) -> bool {
        self.policy != CalibrationPolicy::Precision
            && self.phase == Phase::Verify
            && self.best.is_none()
            && self.undo.is_none()
            && self.partial_recoveries < self.recovery_limit
            && scan.complete
            && scan.targeted_plan().is_some()
            && scan.unstable_grid_mask != 0
    }
    /// Account only active time; review must not inflate the completed result.
    /// Called before the live adapter advances the phase on each tick.
    pub fn account_time(&mut self, now: u64) {
        let Some(delta) = now.checked_sub(self.last_tick) else {
            return;
        };
        self.last_tick = now;
        let index = match self.phase {
            Phase::Sweep => 0,
            Phase::Verify => 1,
            Phase::Refine => 2,
            Phase::Reverify => 3,
            Phase::Review => return,
        };
        self.phase_ms[index] =
            self.phase_ms[index].saturating_add(delta.min(u32::MAX as u64) as u32);
    }
    pub fn start_check_timing(&mut self, now: u64) {
        self.check_started = Some(now);
        self.check_kind = if self.phase == Phase::Reverify {
            'R'
        } else if self.regional_check {
            'B'
        } else if self.check_timing_count == 0 {
            'I'
        } else {
            'F'
        };
    }
    pub fn finish_check_timing(&mut self, now: u64, tested: u16, total: u16) {
        let Some(started) = self.check_started.take() else { return };
        let timing = CheckTiming {
            kind: self.check_kind,
            ms: now.saturating_sub(started).min(u32::MAX as u64) as u32,
            tested,
            total,
        };
        if let Some(slot) = self.check_timings.get_mut(self.check_timing_count as usize) {
            *slot = Some(timing);
            self.check_timing_count += 1;
        } else {
            self.check_timing_overflow = self.check_timing_overflow.saturating_add(1);
        }
    }
    pub fn active(&self) -> bool {
        self.phase != Phase::Review
    }
    pub fn can_retry_unstable(&self) -> bool {
        self.phase == Phase::Refine
            && self.unstable_retries == 0
            && self.passes < MAX_PASSES
            && self.undo.is_none()
            && self.best.as_ref().is_some_and(|s| s.complete)
    }
    /// A replay failure may identify an acquisition boundary that was barely
    /// trackable once but is not repeatable. Recover only at the outer three
    /// verification targets, only during the initial check, and remove at most
    /// four real anchors across two retries. Interior failures remain fatal.
    pub fn recover_edge(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
        failure_uv: i32,
    ) -> bool {
        if self.phase != Phase::Verify
            || self.best.is_some()
            || self.undo.is_some()
            || self.edge_retries >= MAX_EDGE_RETRIES
            || scan.complete
            || scan.local.is_some()
            || scan.targeted_plan().is_none()
        {
            return false;
        }
        let budget = usize::from(
            MAX_EDGE_TRIM_POINTS
                .saturating_sub(self.edge_trim_low.saturating_add(self.edge_trim_high)),
        );
        if budget == 0 {
            return false;
        }
        let removed = if scan.tested <= 2 {
            let n = profile.trim_low_through(failure_uv, budget);
            self.edge_trim_low = self.edge_trim_low.saturating_add(n as u8);
            n
        } else if scan.tested.saturating_add(3) >= scan.total {
            let n = profile.trim_high_from(failure_uv, budget);
            self.edge_trim_high = self.edge_trim_high.saturating_add(n as u8);
            n
        } else {
            0
        };
        if removed == 0 {
            return false;
        }
        self.edge_retries += 1;
        self.regional_check = true;
        self.last_recovery = Some((failure_uv, "EDGE REPLAY FAILURE"));
        true
    }
    /// AUTO/FORGIVING may retain the larger contiguous region on either side
    /// of an unstable replay target, including a repeated local-check target.
    /// Repeated failures can continue narrowing that region, but the number
    /// of destructive retries is firmly bounded.
    /// We never bridge across a bad point, and every shortened candidate is
    /// independently replayed from scratch.
    pub fn recover_partial(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
        failure_uv: i32,
    ) -> bool {
        if self.policy == CalibrationPolicy::Precision
            || self.phase != Phase::Verify
            || self.best.is_some()
            || self.undo.is_some()
            || scan.targeted_plan().is_none()
            || self.partial_recoveries >= self.recovery_limit
        {
            return false;
        }
        let removable = profile.points().len().saturating_sub(super::MIN_PROFILE_POINTS);
        if removable == 0 {
            return false;
        }
        const LOW_RECOVERED: u8 = 1;
        const HIGH_RECOVERED: u8 = 2;
        let below = profile
            .points()
            .partition_point(|p| p.microvolts < failure_uv);
        let above_start = profile
            .points()
            .partition_point(|p| p.microvolts <= failure_uv);
        let above = profile.points().len().saturating_sub(above_start);
        let (side, removed) = if above >= below {
            (
                LOW_RECOVERED,
                profile.trim_low_through(failure_uv, removable),
            )
        } else {
            (
                HIGH_RECOVERED,
                profile.trim_high_from(failure_uv, removable),
            )
        };
        if removed == 0 {
            return false;
        }
        self.partial_recoveries += 1;
        self.regional_check = true;
        self.partial_recovered_sides |= side;
        self.last_recovery = Some((failure_uv, "INCOMPLETE REPLAY"));
        true
    }
    /// After visiting the entire target grid, exclude its missing voltages
    /// and retain the widest contiguous span backed by measured anchors.
    /// A missing local-repeat visit is a single gap at its commanded CV.
    /// No synthetic pitch is inserted; the retained region still needs fresh
    /// boundary and whole-range checks before it can be accepted.
    pub fn recover_missing_regions(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
    ) -> bool {
        if scan.missing == 0 { return false; }
        // Use all uncorrectable observations from this same pass together.
        // Selecting around only gaps can retain a known unstable region and
        // needlessly rediscover it on the very next replay.
        self.recover_grid_regions(scan, profile, scan.missing_grid_mask | scan.unstable_grid_mask,
            scan.first_missing_uv, "GAP REGION SELECTED")
    }
    /// One completed replay can identify several unstable windows. Select the
    /// widest measured region between all of them in a single recovery step.
    pub fn recover_unstable_regions(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
    ) -> bool {
        if scan.unstable_grid_mask == 0 { return false; }
        self.recover_grid_regions(scan, profile, scan.unstable_grid_mask | scan.missing_grid_mask,
            None, "UNSTABLE REGION SELECTED")
    }
    fn recover_grid_regions(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
        bad_mask: u64,
        fallback_uv: Option<i32>,
        cause: &'static str,
    ) -> bool {
        if self.policy == CalibrationPolicy::Precision
            || self.phase != Phase::Verify
            || self.best.is_some()
            || self.undo.is_some()
            || !scan.complete
            || scan.targeted_plan().is_none()
            || self.partial_recoveries >= self.recovery_limit
        {
            return false;
        }
        fn span(
            points: &[Point],
            low_bad: Option<i32>,
            high_bad: Option<i32>,
        ) -> Option<i32> {
            let start = low_bad.map_or(0, |uv| points.partition_point(|p| p.microvolts <= uv));
            let end = high_bad.map_or(points.len(), |uv| {
                points.partition_point(|p| p.microvolts < uv)
            });
            if end.saturating_sub(start) < super::MIN_PROFILE_POINTS {
                return None;
            }
            Some(points[end - 1].microvolts - points[start].microvolts)
        }
        let plan = scan.targeted_plan().unwrap();
        let points = profile.points();
        // With no missing grid location, the gap came from a local repeat.
        // Merge that commanded CV into the sorted grid faults as well.
        let mut local_gap = fallback_uv.filter(|_| scan.missing_grid_mask == 0);
        if bad_mask == 0 && local_gap.is_none() { return false; }
        let mut previous_bad = None;
        let mut selected = None;
        let mut best_span = -1;
        let mut consider = |bad_uv| {
            if let Some(width) = span(points, previous_bad, Some(bad_uv)) {
                if width > best_span {
                    best_span = width;
                    selected = Some((previous_bad, Some(bad_uv)));
                }
            }
            previous_bad = Some(bad_uv);
        };
        for i in 0..plan.len as usize {
            if bad_mask & (1u64 << i) == 0 {
                continue;
            }
            let Ok(bad_uv) = profile.voltage_for_pitch(plan.pitches[i]) else {
                return false;
            };
            if local_gap.is_some_and(|uv| uv <= bad_uv) {
                consider(local_gap.take().unwrap());
            }
            consider(bad_uv);
        }
        if let Some(uv) = local_gap {
            consider(uv);
        }
        if let Some(width) = span(points, previous_bad, None) {
            if width > best_span {
                selected = Some((previous_bad, None));
            }
        }
        let Some((low_bad, high_bad)) = selected else { return false };
        let mut removed = 0;
        if let Some(uv) = low_bad {
            let n = profile.trim_low_through(uv, usize::MAX);
            if n == 0 { return false; }
            removed += n;
            self.partial_recovered_sides |= 1;
        }
        if let Some(uv) = high_bad {
            let n = profile.trim_high_from(uv, usize::MAX);
            if n == 0 { return false; }
            removed += n;
            self.partial_recovered_sides |= 2;
        }
        if removed == 0 { return false; }
        self.partial_recoveries += 1;
        self.regional_check = true;
        self.last_recovery = high_bad.or(low_bad).map(|uv| (uv, cause));
        true
    }
    /// A completed replay can still expose a bad portion of an otherwise
    /// useful curve. Keep only the larger contiguous side of a demonstrably
    /// unsafe target, then independently replay the shortened candidate.
    /// Never convert an unrepeatable interior measurement into an accepted
    /// profile merely by omitting that target from the reported grade.
    pub fn recover_completed(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
    ) -> bool {
        self.recover_completed_inner(scan, profile, true)
    }
    /// A localized error gets one paired refinement attempt first. If that
    /// attempt fails and the retained scan is still unsafe, recover the larger
    /// contiguous side instead of ending with an unsaveable candidate.
    pub fn recover_failed_refinement(&mut self, profile: &mut super::Profile) -> bool {
        if self.phase != Phase::Refine
            || self.policy == CalibrationPolicy::Precision
            || self.undo.is_some()
        {
            return false;
        }
        let Some(best) = self.best.take() else { return false };
        if best.quality().acceptable() {
            self.best = Some(best);
            return false;
        }
        self.phase = Phase::Verify;
        if self.recover_completed_inner(&best, profile, false) {
            true
        } else {
            self.phase = Phase::Refine;
            self.best = Some(best);
            false
        }
    }
    /// A tentative insertion may pass its paired local test yet make the
    /// independent whole-range recheck worse. After the adapter rolls that
    /// point back, salvage a contiguous side of the *previously checked*
    /// unsafe curve rather than ending the one-shot run at the rejected edit.
    pub fn recover_rejected_recheck(&mut self, profile: &mut super::Profile) -> bool {
        if self.phase != Phase::Reverify
            || self.policy == CalibrationPolicy::Precision
            || self.undo.is_some()
        {
            return false;
        }
        let Some(best) = self.best.take() else { return false };
        if best.quality().acceptable() {
            self.best = Some(best);
            return false;
        }
        self.phase = Phase::Verify;
        if self.recover_completed_inner(&best, profile, false) {
            self.last_recovery = self.last_recovery.map(|(uv, _)| (uv, "REJECTED EDIT; SELECT REGION"));
            true
        } else {
            self.phase = Phase::Reverify;
            self.best = Some(best);
            false
        }
    }
    /// A recheck that disagrees with its own earlier grid measurement cannot
    /// justify another fitted anchor. Keep only the larger measured side of
    /// that target and require a fresh, complete verification of the subset.
    pub fn recover_recheck_disagreement(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
    ) -> bool {
        if self.phase != Phase::Reverify
            || self.disagreement_trims >= MAX_DISAGREEMENT_TRIMS
            || !scan.grid_local_disagreement().is_some_and(|d| d > 10.0)
        {
            return false;
        }
        let old_best = self.best.take();
        self.phase = Phase::Verify;
        if self.recover_completed_inner(scan, profile, false) {
            self.disagreement_trims += 1;
            self.last_recovery = self.last_recovery.map(|(uv, _)| (uv, "INCONSISTENT REGION"));
            true
        } else {
            self.phase = Phase::Reverify;
            self.best = old_best;
            false
        }
    }
    fn recover_completed_inner(
        &mut self,
        scan: &Scan,
        profile: &mut super::Profile,
        prefer_refinement: bool,
    ) -> bool {
        if self.policy == CalibrationPolicy::Precision
            || self.phase != Phase::Verify
            || self.best.is_some()
            || self.undo.is_some()
            || !scan.complete
            || scan.targeted_plan().is_none()
            || scan.quality().acceptable()
            || self.partial_recoveries >= self.recovery_limit
        {
            return false;
        }
        if scan.unstable_grid_mask != 0 {
            return self.recover_unstable_regions(scan, profile);
        }
        // Prefer a bounded local correction when the nine interleaved checks
        // prove that an interior midpoint error repeats while its two anchors
        // remain stable. Refinement still requires a paired comparison and a
        // complete independent replay; an unsafe profile cannot be accepted.
        if prefer_refinement
            && scan.max_spread <= 10.0
            && !scan.grid_local_disagreement().is_some_and(|d| d > 10.0)
            && scan.local.as_ref().is_some_and(|check| {
            check.refinement_issue().is_none()
                && super::refinement::Refinement::new(profile, scan.checked_worst().0).is_ok()
        }) {
            return false;
        }
        // A large window spread without a localized bad target cannot tell us
        // where to cut. Keep that result rejected for diagnosis.
        let (mut pitch, mut severity) = scan.checked_worst();
        let mut unsafe_amount = severity.abs();
        if let Some(check) = scan.local.as_ref() {
            for index in 0..3 {
                if let Some((mean, span, repeat)) = check.aggregate(index) {
                    let amount = mean.abs().max(span).max(repeat);
                    if amount > unsafe_amount {
                        pitch = check.targets[index].millicents;
                        severity = mean;
                        unsafe_amount = amount;
                    }
                }
            }
        }
        // A large within-window spread is an unsafe observation even when
        // its mean pitch happens to be close to the curve. Keep its target so
        // a stable section can be selected and independently checked.
        if scan.max_spread > unsafe_amount {
            if let Some(spread_pitch) = scan.max_spread_pitch {
                pitch = spread_pitch;
                severity = scan.max_spread;
                unsafe_amount = scan.max_spread;
            }
        }
        if unsafe_amount <= 10.0 || !severity.is_finite() {
            return false;
        }
        let Ok(failure_uv) = profile.voltage_for_pitch(pitch) else {
            return false;
        };
        let removable = profile.points().len().saturating_sub(super::MIN_PROFILE_POINTS);
        if removable == 0 {
            return false;
        }
        let below = profile.points().partition_point(|p| p.microvolts < failure_uv);
        let above_start = profile.points().partition_point(|p| p.microvolts <= failure_uv);
        let above = profile.points().len().saturating_sub(above_start);
        let (side, removed) = if above >= below {
            (1, profile.trim_low_through(failure_uv, removable))
        } else {
            (2, profile.trim_high_from(failure_uv, removable))
        };
        if removed == 0 {
            return false;
        }
        self.partial_recoveries += 1;
        self.regional_check = true;
        self.partial_recovered_sides |= side;
        self.last_recovery = Some((failure_uv, "UNSAFE COMPLETE REPLAY"));
        true
    }
    pub fn label(&self) -> &'static str {
        match self.phase {
            Phase::Sweep => "MEASURING RANGE",
            Phase::Verify => "CHECKING SAMPLED PITCHES",
            Phase::Refine => "IMPROVING CURVE",
            Phase::Reverify => "RECHECKING SAME PITCHES",
            Phase::Review => "REVIEW RESULT",
        }
    }
    pub fn improves(&self, scan: &Scan) -> bool {
        scan.complete
            && scan.worst_error.is_finite()
            && self.best.as_ref().map_or(true, |old| {
                // A tentative point exists only after independent paired local
                // tests demonstrate >=0.5c gain. A different pitch may now be
                // worst: require no global regression, not another 0.5c gain.
                self.undo.is_some()
                    && scan.checked_worst().1.abs() <= old.checked_worst().1.abs()
                    && scan.local.as_ref().is_some_and(|c| {
                        c.worst_absolute().is_some()
                            && (0..3).all(|i| {
                                c.aggregate(i)
                                    .is_some_and(|(_, _, r)| r <= self.repeatability_cents())
                            })
                    })
            })
    }
    pub fn stop_reason(&self, scan: &Scan, points: usize) -> Option<&'static str> {
        if scan.meets_policy(self.completion_cents(), self.repeatability_cents()) {
            return Some(if scan.targeted_plan().is_some() && self.target_cents() == TARGET_CENTS {
                "READY - SAMPLED CHECK WITHIN 2C"
            } else if scan.targeted_plan().is_some() {
                "READY - SAMPLED CHECK PASSED"
            } else if self.target_cents() == TARGET_CENTS {
                "READY - WITHIN 2C TARGET"
            } else {
                "READY - ACCURACY TARGET PASSED"
            });
        }
        if self.passes >= MAX_PASSES {
            return Some("REVIEW - IMPROVEMENT LIMIT");
        }
        if points >= super::MAX_POINTS {
            return Some("REVIEW - POINT CAPACITY");
        }
        if scan.grid_local_disagreement().is_some_and(|d| d > self.repeatability_cents().max(3.0)) {
            return Some("REVIEW - GRID/LOCAL DISAGREE");
        }
        let Some(check) = scan.local.as_ref() else {
            return Some("REVIEW - NO LOCAL CHECK");
        };
        let issue = check.refinement_issue();
        // The tighter completion margin decides whether refinement is worth
        // attempting; it is not the advertised acceptance limit. If this
        // profile already satisfies two cents and a local curve edit would
        // not be repeatable, report success rather than making the rejected
        // refinement look like a failed calibration.
        if issue.is_some()
            && scan.meets_policy(self.target_cents(), self.repeatability_cents())
        {
            return Some(if self.target_cents() == TARGET_CENTS {
                "READY - WITHIN 2C; NO REFINE"
            } else {
                "READY - TARGET MET; NO REFINE"
            });
        }
        if issue.is_some() && self.quality_allowed(scan.quality()) {
            return Some("REVIEW - USABLE GRADED RESULT");
        }
        issue
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn mixed_gaps_and_unstable_grid_use_one_contiguous_selection() {
        for local_gap in [false, true] {
            for reverse in [false, true] {
                let mut profile = super::super::Profile::new("mixed", -5_000_000, 8_000_000).unwrap();
                for i in 0..100 {
                    profile.push(Point {
                        microvolts: -1_000_000 + i * 83_333,
                        millicents: 4_000_000 + i * 100_000,
                    }).unwrap();
                }
                let mut scan = Scan::targeted(&profile).unwrap();
                let (low, high) = (7, scan.total as usize - 8);
                let (gap, unstable) = if reverse { (high, low) } else { (low, high) };
                let uv = |index: usize| profile.voltage_for_pitch(scan.targeted_plan().unwrap().pitches[index]).unwrap();
                let (low_uv, high_uv, gap_uv) = (uv(low), uv(high), uv(gap));
                let expected: Vec<_> = profile.points().iter().copied()
                    .filter(|p| low_uv < p.microvolts && p.microvolts < high_uv).collect();
                scan.complete = true;
                scan.tested = scan.total;
                scan.missing = 1;
                scan.missing_grid_mask = if local_gap { 0 } else { 1u64 << gap };
                scan.first_missing_uv = Some(gap_uv);
                scan.unstable_grid_mask = 1u64 << unstable;
                scan.max_spread = 12.0;
                let mut auto = Automatic::new(0);
                auto.phase = Phase::Verify;
                assert!(auto.recover_missing_regions(&scan, &mut profile));
                assert_eq!(profile.points(), expected);
                assert_eq!(auto.partial_recoveries, 1);
                assert!(auto.regional_check);
                assert!(auto.best.is_none());
                assert!(!Scan::targeted(&profile).unwrap().quality().acceptable());
            }
        }
    }
    #[test]
    fn local_repeat_shortcut_is_only_for_recoverable_unsafe_grids() {
        let mut profile = super::super::Profile::new("grid", 0, 2_000_000).unwrap();
        for i in 0..25 {
            profile.push(Point { microvolts: i * 83_333, millicents: 6_000_000 + i * 100_000 }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        scan.unstable_grid_mask = 1;
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        scan.complete = true;
        assert!(auto.skip_local_for_grid_recovery(&scan));
        scan.unstable_grid_mask = 0;
        scan.worst_error = 20.0; // a correctable curve error still gets its repeats
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        scan.unstable_grid_mask = 1;
        auto.policy = CalibrationPolicy::Precision;
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        auto.policy = CalibrationPolicy::Fast;
        assert!(auto.skip_local_for_grid_recovery(&scan));
        auto.phase = Phase::Reverify;
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        auto.phase = Phase::Verify;
        auto.partial_recoveries = auto.recovery_limit;
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        auto.partial_recoveries = 0;
        auto.best = Some(scan.clone());
        assert!(!auto.skip_local_for_grid_recovery(&scan));
        auto.best = None;
        auto.undo = Some(profile.points()[0]);
        assert!(!auto.skip_local_for_grid_recovery(&scan));
    }
    #[test]
    fn timing_accumulates_retries_and_freezes_in_review() {
        let mut a = Automatic::new(100);
        a.account_time(150);
        a.phase = Phase::Verify;
        a.account_time(250);
        a.phase = Phase::Refine;
        a.account_time(280);
        a.phase = Phase::Reverify;
        a.account_time(380);
        a.phase = Phase::Refine;
        a.account_time(400);
        assert_eq!(a.phase_ms, [50, 100, 50, 100]);
        a.account_time(399);
        assert_eq!(a.phase_ms, [50, 100, 50, 100]);
        a.phase = Phase::Review;
        a.account_time(9999);
        assert_eq!(a.phase_ms, [50, 100, 50, 100]);
    }
    #[test]
    fn bounded_policy_never_accepts_an_unverified_or_worse_candidate() {
        let mut profile = super::super::Profile::new("test", 0, 1000000).unwrap();
        profile
            .push(Point {
                microvolts: 0,
                millicents: 6000000,
            })
            .unwrap();
        profile
            .push(Point {
                microvolts: 1000000,
                millicents: 7200000,
            })
            .unwrap();
        let mut scan = Scan::new(&profile).unwrap();
        let mut auto = Automatic::new(10);
        assert!(!auto.improves(&scan));
        scan.complete = true;
        scan.worst_error = 4.0;
        assert!(auto.improves(&scan));
        auto.best = Some(scan.clone());
        scan.worst_error = 3.8;
        assert!(!auto.improves(&scan));
        scan.worst_error = -3.5;
        assert!(!auto.improves(&scan)); // no paired local proof
        scan.worst_error = f32::NAN;
        assert!(!auto.improves(&scan));
        scan.worst_error = 1.5;
        assert_eq!(auto.stop_reason(&scan, 2), Some("REVIEW - NO LOCAL CHECK"));
        let mut check =
            super::super::verification_scan::LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for _ in 0..9 {
            check.record(super::super::deviation::Summary {
                mean: 0.0,
                spread: 0.1,
                count: 8,
                averaged: false,
            });
        }
        scan.local = Some(check);
        assert_eq!(
            auto.stop_reason(&scan, 129),
            Some("READY - WITHIN 2C TARGET")
        );
        auto.undo = Some(Point {
            microvolts: 500000,
            millicents: 6600000,
        });
        scan.worst_pitch = 6600000; // another pitch becomes the limiting error
        scan.worst_error = 3.8;
        assert!(auto.improves(&scan));
        scan.worst_error = 4.0;
        assert!(auto.improves(&scan)); // tied max can hide local gain
        scan.worst_error = 4.01;
        assert!(!auto.improves(&scan));
        scan.worst_error = -3.5;
        assert!(auto.improves(&scan));
        scan.local.as_mut().unwrap().tested = 8;
        assert!(!auto.improves(&scan));
        scan.local.as_mut().unwrap().tested = 9;
        scan.worst_error = 4.0;
        auto.passes = MAX_PASSES;
        assert_eq!(
            auto.stop_reason(&scan, 121),
            Some("REVIEW - IMPROVEMENT LIMIT")
        );
    }
    #[test]
    fn local_absolute_repeat_can_override_a_marginal_grid_pass() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("test", 0, 1000000).unwrap();
        profile
            .push(Point {
                microvolts: 0,
                millicents: 6000000,
            })
            .unwrap();
        profile
            .push(Point {
                microvolts: 1000000,
                millicents: 7200000,
            })
            .unwrap();
        let mut scan = Scan::new(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 6600000;
        scan.worst_error = 1.97;
        let mut check = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            check.record(Summary {
                mean: if target == 2 { 2.17 } else { 0.12 },
                spread: 0.45,
                count: 8,
                averaged: false,
            });
        }
        scan.local = Some(check);
        let auto = Automatic::new(0);
        assert!(!scan.meets_target(TARGET_CENTS));
        assert_eq!(scan.checked_worst(), (6600000, 2.17));
        assert_eq!(auto.stop_reason(&scan, 2), None);
    }
    #[test]
    fn automatic_completion_requires_headroom_but_manual_target_stays_two_cents() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut p = super::super::Profile::new("margin", 0, 1000000).unwrap();
        for (microvolts, millicents) in [(0, 6000000), (1000000, 7200000)] {
            p.push(Point {
                microvolts,
                millicents,
            })
            .unwrap();
        }
        for error in [-2.0, -1.51, -1.5, 1.5, 1.51, 2.0] {
            let mut scan = Scan::targeted(&p).unwrap();
            scan.complete = true;
            scan.worst_error = error;
            scan.worst_pitch = 6600000;
            let mut local = LocalCheck::new(&p, scan.worst_pitch).unwrap();
            for target in LocalCheck::ORDER {
                local.record(Summary {
                    mean: if target == 2 { error } else { 0.0 },
                    spread: 0.3,
                    count: 8,
                    averaged: false,
                });
            }
            scan.local = Some(local);
            let a = Automatic::new(0);
            assert!(scan.meets_target(TARGET_CENTS));
            assert_eq!(
                a.stop_reason(&scan, 2),
                if error.abs() <= COMPLETION_CENTS {
                    Some("READY - SAMPLED CHECK WITHIN 2C")
                } else {
                    None
                }
            );
        }
    }
    #[test]
    fn marginal_pass_with_unrepeatable_refinement_is_still_ready() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut p = super::super::Profile::new("margin", 0, 1000000).unwrap();
        p.push(Point {
            microvolts: 0,
            millicents: 6000000,
        })
        .unwrap();
        p.push(Point {
            microvolts: 1000000,
            millicents: 7200000,
        })
        .unwrap();
        let mut scan = Scan::targeted(&p).unwrap();
        scan.complete = true;
        scan.worst_error = 1.2;
        scan.worst_pitch = 6600000;
        let mut local = LocalCheck::new(&p, scan.worst_pitch).unwrap();
        // All absolute errors are inside two cents, but target-repeat
        // variation makes a corrective edit unsafe.
        for (i, target) in LocalCheck::ORDER.into_iter().enumerate() {
            let round = i / 3;
            let mean = if target == 2 {
                [1.3, 1.65, 2.0][round]
            } else {
                [0.35, 0.0, -0.35][round]
            };
            assert!(local.record(Summary {
                mean,
                spread: 0.3,
                count: 8,
                averaged: false
            }));
        }
        scan.local = Some(local);
        let a = Automatic::new(0);
        assert!(scan.meets_target(TARGET_CENTS));
        assert_eq!(
            a.stop_reason(&scan, 2),
            Some("READY - WITHIN 2C; NO REFINE")
        );
    }
    #[test]
    fn unstable_retry_keeps_mutation_guards_without_a_wall_clock_limit() {
        let mut p = super::super::Profile::new("test", 0, 1000000).unwrap();
        p.push(Point {
            microvolts: 0,
            millicents: 6000000,
        })
        .unwrap();
        p.push(Point {
            microvolts: 1000000,
            millicents: 7200000,
        })
        .unwrap();
        let mut a = Automatic::new(100);
        a.phase = Phase::Refine;
        assert!(!a.can_retry_unstable());
        a.best = Some(Scan::new(&p).unwrap());
        assert!(!a.can_retry_unstable());
        a.best.as_mut().unwrap().complete = true;
        assert!(a.can_retry_unstable());
        a.unstable_retries = 1;
        assert!(!a.can_retry_unstable());
        a.unstable_retries = 0;
        a.passes = MAX_PASSES;
        assert!(!a.can_retry_unstable());
        a.passes = 1;
        a.undo = Some(p.points()[0]);
        assert!(!a.can_retry_unstable());
        a.undo = None;
        a.phase = Phase::Review;
        assert!(!a.can_retry_unstable());
    }
    #[test]
    fn edge_recovery_trims_only_failed_measured_boundaries_with_a_fixed_budget() {
        let mut profile = super::super::Profile::new("edge", -5000000, 5000000).unwrap();
        for i in 0..40 {
            profile
                .push(Point {
                    microvolts: i * 83333,
                    millicents: i * 100000,
                })
                .unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.tested = 2;
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(auto.recover_edge(&scan, &mut profile, 166666));
        assert_eq!(auto.edge_trim_low, 3);
        assert_eq!(profile.points()[0].microvolts, 249999);
        // The one remaining anchor in the global budget cannot partially trim
        // a two-anchor failed region and leave the actual failure in range.
        scan = Scan::targeted(&profile).unwrap();
        scan.tested = 1;
        assert!(!auto.recover_edge(&scan, &mut profile, 333332));
        assert_eq!(profile.points()[0].microvolts, 249999);

        let mut upper = profile.clone();
        let mut upper_scan = Scan::targeted(&upper).unwrap();
        upper_scan.tested = upper_scan.total - 1;
        let mut upper_auto = Automatic::new(0);
        upper_auto.phase = Phase::Verify;
        assert!(upper_auto.recover_edge(&upper_scan, &mut upper, 3166654));
        assert_eq!(upper_auto.edge_trim_high, 2);
        assert_eq!(upper.points().last().unwrap().microvolts, 3083321);
    }
    #[test]
    fn grid_local_disagreement_trims_even_when_local_shape_looks_refinable() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("mismatch", -1_000_000, 7_000_000).unwrap();
        for i in 0..90 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let old_len = profile.points().len();
        let pitch = (profile.points()[85].millicents + profile.points()[86].millicents) / 2;
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.tested = scan.total;
        scan.complete = true;
        scan.worst_pitch = pitch;
        scan.worst_error = 56.6;
        let mut check = LocalCheck::new(&profile, pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(check.record(Summary {
                mean: if target == 2 { -14.1 } else { 0.1 },
                spread: 0.1,
                count: 8,
                averaged: false,
            }));
        }
        assert!(check.refinement_issue().is_none());
        scan.local = Some(check);
        assert!(scan.grid_local_disagreement().unwrap() > 70.0);
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(auto.recover_completed(&scan, &mut profile));
        assert!(auto.regional_check);
        assert!(profile.points().len() < old_len);
        assert!(profile.limited_high);
    }
    #[test]
    fn graded_policy_distinguishes_precision_musical_and_character_results() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("graded", 0, 1_000_000).unwrap();
        for (uv, mc) in [(0, 6_000_000), (1_000_000, 7_200_000)] {
            profile.push(Point { microvolts: uv, millicents: mc }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 6_600_000;
        scan.worst_error = 4.2;
        scan.max_spread = 1.2;
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            local.record(Summary {
                mean: if target == 2 { 4.2 } else { 0.2 },
                spread: 0.8,
                count: 8,
                averaged: false,
            });
        }
        scan.local = Some(local);
        assert_eq!(scan.quality().grade, CalibrationGrade::Musical);
        assert!(!Automatic::new_with_policy(0, CalibrationPolicy::Precision)
            .quality_allowed(scan.quality()));
        assert!(Automatic::new_with_policy(0, CalibrationPolicy::Auto)
            .quality_allowed(scan.quality()));
        scan.worst_error = 8.0;
        assert_eq!(scan.quality().grade, CalibrationGrade::Character);
        scan.worst_error = 10.1;
        assert_eq!(scan.quality().grade, CalibrationGrade::Unsafe);
    }

    #[test]
    fn auto_partial_recovery_keeps_the_larger_contiguous_side_and_can_narrow_again() {
        let mut profile = super::super::Profile::new("partial", 0, 4_000_000).unwrap();
        for i in 0..40 {
            profile
                .push(Point {
                    microvolts: i * 83_333,
                    millicents: i * 100_000,
                })
                .unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.tested = scan.total - 10;
        let mut auto = Automatic::new_with_policy(0, CalibrationPolicy::Auto);
        auto.phase = Phase::Verify;
        assert!(auto.recover_partial(&scan, &mut profile, 20 * 83_333));
        assert_eq!(profile.points().len(), 20);
        assert!(profile.limited_high);

        scan = Scan::targeted(&profile).unwrap();
        // A failure among the first edge targets may exceed the deliberately
        // tiny edge-retry budget. The contiguous recovery must still be able
        // to advance the low boundary rather than throwing away the profile.
        scan.tested = 2;
        assert!(auto.recover_partial(&scan, &mut profile, 5 * 83_333));
        assert_eq!(profile.points().first().unwrap().microvolts, 6 * 83_333);
        assert_eq!(profile.points().len(), 14);
        assert!(profile.limited_low);
        assert_eq!(auto.partial_recoveries, 2);
        assert_eq!(auto.partial_recovered_sides, 3);
        assert!(auto.recover_partial(&scan, &mut profile, 6 * 83_333));
        assert_eq!(profile.points().len(), super::super::MIN_PROFILE_POINTS);
        assert_eq!(auto.partial_recoveries, 3);
        assert!(!auto.recover_partial(&scan, &mut profile, 7 * 83_333));

        let mut strict = Automatic::new_with_policy(0, CalibrationPolicy::Precision);
        strict.phase = Phase::Verify;
        assert!(!strict.recover_partial(&scan, &mut profile, 15 * 83_333));
    }
    #[test]
    fn auto_partial_recovery_has_a_firm_retry_limit() {
        let mut profile = super::super::Profile::new("bounded", 0, 6_000_000).unwrap();
        for i in 0..60 {
            profile
                .push(Point {
                    microvolts: i * 83_333,
                    millicents: i * 100_000,
                })
                .unwrap();
        }
        let scan = Scan::targeted(&profile).unwrap();
        let mut auto = Automatic::new_with_policy(0, CalibrationPolicy::Auto);
        auto.phase = Phase::Verify;
        auto.partial_recoveries = MAX_PARTIAL_RECOVERIES;
        assert!(!auto.recover_partial(&scan, &mut profile, 30 * 83_333));
        assert_eq!(profile.points().len(), 60);
    }
    #[test]
    fn whole_grid_gaps_select_the_widest_measured_region_once() {
        let mut profile = super::super::Profile::new("regions", 0, 10_000_000).unwrap();
        for i in 0..=120 {
            profile.push(Point {
                microvolts: i * 83_333,
                millicents: 2_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        let plan = scan.targeted_plan().unwrap();
        let low_bad = profile.voltage_for_pitch(plan.pitches[10]).unwrap();
        let high_bad = profile.voltage_for_pitch(plan.pitches[25]).unwrap();
        scan.tested = scan.total;
        scan.complete = true;
        scan.missing = 2;
        scan.missing_grid_mask = (1u64 << 10) | (1u64 << 25);
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(auto.recover_missing_regions(&scan, &mut profile));
        assert!(profile.points().first().unwrap().microvolts > low_bad);
        assert!(profile.points().last().unwrap().microvolts < high_bad);
        assert!(profile.limited_low && profile.limited_high);
        assert_eq!(auto.partial_recoveries, 1);
        assert!(auto.regional_check);
    }
    #[test]
    fn rejected_recheck_can_salvage_the_pre_edit_unsafe_curve() {
        let mut profile = super::super::Profile::new("pre-edit", 0, 4_000_000).unwrap();
        for i in 0..40 {
            profile.push(Point {
                microvolts: i * 83_333,
                millicents: 6_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut checked = Scan::targeted(&profile).unwrap();
        checked.tested = checked.total;
        checked.complete = true;
        checked.worst_pitch = profile.points()[34].millicents;
        checked.worst_error = -21.0;
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Reverify;
        auto.best = Some(checked);
        // The live adapter has already undone the tentative insertion.
        assert!(auto.recover_rejected_recheck(&mut profile));
        assert_eq!(auto.phase, Phase::Verify);
        assert!(auto.best.is_none());
        assert!(profile.points().last().unwrap().microvolts < 34 * 83_333);
        assert!(auto.regional_check);
    }
    #[test]
    fn one_shot_recovery_budget_is_bounded_without_user_extension() {
        let auto = Automatic::new(0);
        assert_eq!(auto.recovery_limit, MAX_PARTIAL_RECOVERIES);
        assert_eq!(MAX_PARTIAL_RECOVERIES, 16);
        assert_eq!(MAX_PASSES, 16);
    }
    #[test]
    fn completed_unsafe_check_offers_only_a_reverified_contiguous_subset() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 4_000_000 + 85 * 100_000;
        scan.worst_error = -42.0;
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                mean: if target == 2 { -42.0 } else { 0.2 },
                spread: 0.2,
                count: 8,
                averaged: false,
            }));
        }
        scan.local = Some(local);
        assert!(!scan.quality().acceptable());
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Verify;
        assert!(automatic.recover_completed(&scan, &mut profile));
        assert!(profile.limited_high);
        assert_eq!(profile.points().len(), 85);
        assert_eq!(automatic.partial_recoveries, 1);
        assert_eq!(automatic.last_recovery, Some((6_083_305, "UNSAFE COMPLETE REPLAY")));
        assert!(!automatic.recover_completed(&scan, &mut profile));
        // The shortened profile is only a candidate: quality requires a new
        // completed replay and cannot inherit the old unsafe result.
        assert!(!Scan::targeted(&profile).unwrap().quality().acceptable());
    }
    #[test]
    fn disagreeing_recheck_trims_once_then_requires_a_fresh_check() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 4_000_000 + 85 * 100_000;
        scan.worst_error = 19.0;
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                mean: if target == 2 { -21.0 } else { 0.2 },
                spread: 0.2,
                count: 8,
                averaged: false,
            }));
        }
        scan.local = Some(local);
        assert_eq!(scan.grid_local_disagreement(), Some(40.0));
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Reverify;
        automatic.best = Some(scan.clone());
        assert!(automatic.recover_recheck_disagreement(&scan, &mut profile));
        assert_eq!(automatic.phase, Phase::Verify);
        assert!(automatic.best.is_none());
        assert_eq!(automatic.disagreement_trims, 1);
        assert_eq!(automatic.last_recovery, Some((6_083_305, "INCONSISTENT REGION")));
        assert_eq!(profile.points().len(), 85);
        assert!(profile.limited_high);
        automatic.phase = Phase::Reverify;
        automatic.best = Some(scan.clone());
        automatic.disagreement_trims = MAX_DISAGREEMENT_TRIMS;
        assert!(!automatic.recover_recheck_disagreement(&scan, &mut profile));
        assert_eq!(profile.points().len(), 85);
    }
    #[test]
    fn unreachable_high_pitch_gap_trims_only_pending_high_range() {
        let mut profile = super::super::Profile::new("step", -5_000_000, 5_000_000).unwrap();
        let actual = |uv: i32| {
            6_000_000 + uv * 6 / 5 + if uv >= 2_457_500 { 48_800 } else { 0 }
        };
        for i in 0..=120 {
            let uv = -5_000_000 + i * 10_000_000 / 120;
            profile.push(Point { microvolts: uv, millicents: actual(uv) }).unwrap();
        }
        let pair = &profile.points()[89..=90];
        let gap_pitch = (pair[0].millicents + pair[1].millicents) / 2;
        let commanded = profile.voltage_for_pitch(gap_pitch).unwrap();
        let mut scan = Scan::targeted(&profile).unwrap();
        assert!(scan.targeted_plan().unwrap().pitches[..scan.total as usize]
            .contains(&gap_pitch));
        scan.complete = true;
        scan.worst_pitch = gap_pitch;
        scan.worst_error = (actual(commanded) - gap_pitch) as f32 / 1000.0;
        assert!(scan.worst_error.abs() > 10.0);
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(auto.recover_completed(&scan, &mut profile));
        assert!(profile.limited_high);
        assert!(profile.points().last().unwrap().microvolts < 2_457_500);
        assert!(auto.best.is_none());
        assert!(!Scan::targeted(&profile).unwrap().quality().acceptable());
    }
    #[test]
    fn repeatable_interior_error_is_refined_before_any_range_trim() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 4_000_000 + 85 * 100_000;
        scan.worst_error = 17.7;
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                mean: if target == 2 { 17.7 } else { 0.2 },
                spread: 0.2,
                count: 8,
                averaged: false,
            }));
        }
        assert_eq!(local.refinement_issue(), None);
        scan.local = Some(local);
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Verify;
        assert!(!automatic.recover_completed(&scan, &mut profile));
        assert_eq!(automatic.stop_reason(&scan, profile.points().len()), None);
        assert_eq!(profile.points().len(), 100);
        assert_eq!(automatic.partial_recoveries, 0);
    }
    #[test]
    fn failed_unsafe_refinement_falls_back_to_independently_checked_subset() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 4_000_000 + 85 * 100_000;
        scan.worst_error = 19.9;
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                mean: if target == 2 { 19.9 } else { 0.2 },
                spread: 0.2,
                count: 8,
                averaged: false,
            }));
        }
        assert_eq!(local.refinement_issue(), None);
        scan.local = Some(local);
        assert!(!scan.quality().acceptable());
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Refine;
        automatic.best = Some(scan);
        assert!(automatic.recover_failed_refinement(&mut profile));
        assert_eq!(automatic.phase, Phase::Verify);
        assert!(automatic.best.is_none());
        assert!(profile.limited_high);
        assert_eq!(profile.points().len(), 85);
        assert!(!Scan::targeted(&profile).unwrap().quality().acceptable());
    }
    #[test]
    fn unstable_grid_window_trims_at_its_own_location_not_the_worst_mean() {
        use super::super::{deviation::Summary, verification_scan::LocalCheck};
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 12_500_000;
        scan.worst_error = 4.85;
        scan.max_spread = 11.57;
        scan.max_spread_pitch = Some(11_000_000);
        let mut local = LocalCheck::new(&profile, scan.worst_pitch).unwrap();
        for target in LocalCheck::ORDER {
            assert!(local.record(Summary {
                mean: if target == 2 { 4.84 } else { 0.08 },
                spread: 0.17,
                count: 8,
                averaged: false,
            }));
        }
        scan.local = Some(local);
        assert!(!scan.quality().acceptable());
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Verify;
        // The local midpoint error is repeatable, but editing its curve
        // cannot fix a different grid target's 11.57c measurement spread.
        assert!(automatic.recover_completed(&scan, &mut profile));
        assert_eq!(profile.points().len(), 70);
        assert!(profile.limited_high);
        assert!(!Scan::targeted(&profile).unwrap().quality().acceptable());
    }
    #[test]
    fn completed_grid_selects_widest_measured_section_between_all_unstable_targets() {
        let mut profile = super::super::Profile::new("measured", -5_000_000, 8_000_000).unwrap();
        for i in 0..100 {
            profile.push(Point {
                microvolts: -1_000_000 + i * 83_333,
                millicents: 4_000_000 + i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        let low_pitch = scan.targeted_plan().unwrap().pitches[10];
        let high_index = scan.targeted_plan().unwrap().len as usize - 9;
        let high_pitch = scan.targeted_plan().unwrap().pitches[high_index];
        let low_bad = profile.voltage_for_pitch(low_pitch).unwrap();
        let high_bad = profile.voltage_for_pitch(high_pitch).unwrap();
        let expected = profile.points().iter()
            .filter(|p| low_bad < p.microvolts && p.microvolts < high_bad)
            .count();
        scan.complete = true;
        scan.max_spread = 12.0;
        scan.max_spread_pitch = Some(low_pitch);
        scan.unstable_grid_mask = (1u64 << 10) | (1u64 << high_index);
        let mut automatic = Automatic::new(0);
        automatic.phase = Phase::Verify;
        assert!(automatic.recover_completed(&scan, &mut profile));
        assert_eq!(profile.points().len(), expected);
        assert!(profile.points()[0].microvolts > low_bad);
        assert!(profile.points().last().unwrap().microvolts < high_bad);
        assert_eq!(automatic.partial_recoveries, 1);
        assert_eq!(automatic.partial_recovered_sides, 3);
        assert!(automatic.regional_check);
    }
    #[test]
    fn completed_recovery_never_trims_a_nonlocalized_or_strict_failure() {
        let mut profile = super::super::Profile::new("measured", 0, 4_000_000).unwrap();
        for i in 0..40 {
            profile.push(Point {
                microvolts: i * 83_333,
                millicents: i * 100_000,
            }).unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.complete = true;
        scan.worst_pitch = 2_000_000;
        scan.worst_error = 2.0;
        scan.max_spread = 20.0;
        let original = profile.points().len();
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(!auto.recover_completed(&scan, &mut profile));
        scan.worst_error = 42.0;
        let mut precision = Automatic::new_with_policy(0, CalibrationPolicy::Precision);
        precision.phase = Phase::Verify;
        assert!(!precision.recover_completed(&scan, &mut profile));
        assert_eq!(profile.points().len(), original);
    }
    #[test]
    fn edge_recovery_rejects_interior_recheck_and_sub_octave_candidates() {
        let mut profile = super::super::Profile::new("edge", 0, 3000000).unwrap();
        for i in 0..20 {
            profile
                .push(Point {
                    microvolts: i * 100000,
                    millicents: 2_000_000 + i * 100000,
                })
                .unwrap();
        }
        let mut scan = Scan::targeted(&profile).unwrap();
        scan.tested = scan.total / 2;
        let mut auto = Automatic::new(0);
        auto.phase = Phase::Verify;
        assert!(!auto.recover_edge(&scan, &mut profile, 900000));
        auto.phase = Phase::Reverify;
        scan.tested = 0;
        assert!(!auto.recover_edge(&scan, &mut profile, 0));

        let mut short = super::super::Profile::new("short", 0, 2000000).unwrap();
        for i in 0..13 {
            short
                .push(Point {
                    microvolts: i * 100000,
                    millicents: 2_000_000 + i * 100000,
                })
                .unwrap();
        }
        let short_scan = Scan::targeted(&short).unwrap();
        auto.phase = Phase::Verify;
        assert!(!auto.recover_edge(&short_scan, &mut short, 0));
        assert_eq!(short.points().len(), 13);
    }
}
