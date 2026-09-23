//! Bounded automatic calibration policy. No allocation, flash or DAC access.
use super::{verification_scan::Scan, CalibrationGrade, CalibrationQuality, Point};
use crate::options::CalibrationPolicy;

pub const TARGET_CENTS: f32 = 2.0;
// Empirical headroom for sequential-check variation, not an uncertainty bound.
pub const COMPLETION_MARGIN_CENTS: f32 = 0.5;
pub const COMPLETION_CENTS: f32 = TARGET_CENTS - COMPLETION_MARGIN_CENTS;
pub const MAX_PASSES: u8 = 8;
pub const VERIFY_TIMEOUT_MS: u64 = 5000;
pub const MAX_DURATION_MS: u64 = 15 * 60 * 1000;
pub const MAX_EDGE_TRIM_POINTS: u8 = 4;
pub const MAX_EDGE_RETRIES: u8 = 2;
pub const MAX_PARTIAL_RECOVERIES: u8 = 4;
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Phase {
    Sweep,
    Verify,
    Refine,
    Reverify,
    Review,
}
pub struct Automatic {
    pub policy: CalibrationPolicy,
    pub phase: Phase,
    pub passes: u8,
    pub started: u64,
    pub phase_ms: [u32; 4],
    pub last_recheck: Option<(f32, f32, bool)>,
    pub last_refine: Option<(i32, f32, f32, f32)>,
    pub unstable_retries: u8,
    pub edge_retries: u8,
    pub edge_trim_low: u8,
    pub edge_trim_high: u8,
    pub partial_recoveries: u8,
    pub partial_recovered_sides: u8,
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
            last_recheck: None,
            last_refine: None,
            unstable_retries: 0,
            edge_retries: 0,
            edge_trim_low: 0,
            edge_trim_high: 0,
            partial_recoveries: 0,
            partial_recovered_sides: 0,
            last_tick: now,
            best: None,
            undo: None,
        }
    }
    pub fn target_cents(&self) -> f32 {
        match self.policy {
            CalibrationPolicy::Auto | CalibrationPolicy::Precision => TARGET_CENTS,
            CalibrationPolicy::Forgiving => 10.0,
        }
    }
    pub fn policy_label(&self) -> &'static str {
        match self.policy {
            CalibrationPolicy::Auto => "AUTO",
            CalibrationPolicy::Precision => "PRECISION",
            CalibrationPolicy::Forgiving => "FORGIVING",
        }
    }
    pub fn completion_cents(&self) -> f32 {
        (self.target_cents() - COMPLETION_MARGIN_CENTS).max(0.5)
    }
    pub fn repeatability_cents(&self) -> f32 {
        match self.policy {
            CalibrationPolicy::Auto | CalibrationPolicy::Precision => 0.75,
            CalibrationPolicy::Forgiving => 5.0,
        }
    }
    pub fn quality_allowed(&self, quality: CalibrationQuality) -> bool {
        match self.policy {
            CalibrationPolicy::Precision => quality.grade == CalibrationGrade::Precision,
            CalibrationPolicy::Auto | CalibrationPolicy::Forgiving => quality.acceptable(),
        }
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
    pub fn active(&self) -> bool {
        self.phase != Phase::Review
    }
    pub fn expired(&self, now: u64) -> bool {
        now < self.started || now - self.started >= MAX_DURATION_MS
    }
    /// Reserve a whole attempt before editing: 9 reacquisition measurements,
    /// up to 16 paired tests, the full scan and its 9 local measurements,
    /// one first-target retry, plus 30 seconds for transition overhead.
    pub fn refinement_budget_ms(targets: u16) -> u64 {
        (targets as u64 + 9 + 16 + 9 + 1) * VERIFY_TIMEOUT_MS + 30000
    }
    pub fn can_start_refinement(&self, now: u64, targets: u16) -> bool {
        now.checked_sub(self.started)
            .and_then(|elapsed| MAX_DURATION_MS.checked_sub(elapsed))
            .is_some_and(|remaining| remaining >= Self::refinement_budget_ms(targets))
    }
    pub fn can_retry_unstable(&self, now: u64) -> bool {
        self.phase == Phase::Refine
            && self.unstable_retries == 0
            && self.passes < MAX_PASSES
            && self.undo.is_none()
            && self
                .best
                .as_ref()
                .is_some_and(|s| s.complete && self.can_start_refinement(now, s.total))
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
        true
    }
    /// AUTO/FORGIVING may retain the larger contiguous region on either side
    /// of an unstable replay target. Repeated failures can continue narrowing
    /// that region, but the number of destructive retries is firmly bounded.
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
            || scan.complete
            || scan.local.is_some()
            || scan.targeted_plan().is_none()
            || self.partial_recoveries >= MAX_PARTIAL_RECOVERIES
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
        self.partial_recovered_sides |= side;
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
        assert!(auto.expired(9));
        assert!(auto.expired(10 + MAX_DURATION_MS));
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
    fn unstable_retry_keeps_attempt_time_and_mutation_guards() {
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
        assert!(!a.can_retry_unstable(100));
        a.best = Some(Scan::new(&p).unwrap());
        assert!(!a.can_retry_unstable(100));
        a.best.as_mut().unwrap().complete = true;
        assert!(a.can_retry_unstable(100));
        assert!(!a.can_retry_unstable(100 + MAX_DURATION_MS));
        assert!(!a.can_retry_unstable(99));
        a.unstable_retries = 1;
        assert!(!a.can_retry_unstable(100));
        a.unstable_retries = 0;
        a.passes = MAX_PASSES;
        assert!(!a.can_retry_unstable(100));
        a.passes = 1;
        a.undo = Some(p.points()[0]);
        assert!(!a.can_retry_unstable(100));
        a.undo = None;
        a.phase = Phase::Review;
        assert!(!a.can_retry_unstable(100));
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
    #[test]
    fn reserve_covers_full_attempt_and_never_extends_absolute_deadline() {
        let auto = Automatic::new(100);
        let required = Automatic::refinement_budget_ms(50);
        assert_eq!(required, 455000);
        assert_eq!(Automatic::refinement_budget_ms(225), 1330000);
        assert!(auto.can_start_refinement(100 + 5 * 60 * 1000, 50));
        let last = 100 + MAX_DURATION_MS - required;
        assert!(auto.can_start_refinement(last, 50));
        assert!(!auto.can_start_refinement(last + 1, 50));
        assert!(!auto.can_start_refinement(99, 50));
        assert!(!auto.can_start_refinement(100 + MAX_DURATION_MS, 50));
        assert!(!auto.can_start_refinement(u64::MAX, 50));
        assert!(!auto.can_start_refinement(100, u16::MAX));
        assert!(!auto.expired(100 + 5 * 60 * 1000));
        assert!(auto.expired(100 + MAX_DURATION_MS));
    }
}
