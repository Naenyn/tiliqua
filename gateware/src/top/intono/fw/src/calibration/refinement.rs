//! Bounded candidate acquisition and paired independent validation. No DAC or
//! persistence access; the live adapter owns settling, cancellation and consent.
use super::{deviation::Summary, verification_scan::LocalCheck, Point, Profile, MAX_POINTS};

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Stage {
    Acquire,
    Seek,
    Validate,
    Ready,
    Rejected,
}
pub struct Refinement {
    pub stage: Stage,
    pub check: LocalCheck,
    candidate: Option<Point>,
    pitches: [i32; 5],
    count: usize,
    pub tested: usize,
    // Validation only needs paired means; keep the bounded refinement state
    // below the firmware's stack budget even with the added target check.
    results: [Option<f32>; 20],
    pub original_worst: f32,
    pub candidate_worst: f32,
    pub reason: &'static str,
    seek_attempted: bool,
    seek_voltage: i32,
    seek_count: u8,
    seek_sum: f32,
    seek_low: f32,
    seek_high: f32,
}

#[cfg(test)]
mod tests {
    use super::*;
    fn profile() -> Profile {
        let mut p = Profile::new("refine", -100000, 200000).unwrap();
        for uv in [-100000, 0, 100000, 200000] {
            p.push(Point {
                microvolts: uv,
                millicents: 6000000 + uv,
            })
            .unwrap();
        }
        p
    }
    fn acquire(r: &mut Refinement, p: &Profile, offset: f32) {
        for mean in [0.0, -2.0, 0.0, 0.0, -2.0, 0.0, 0.0, -2.0, 0.0] {
            r.record(
                p,
                Summary {
                    averaged: false,
                    mean: mean + offset,
                    spread: 1.0,
                    count: 8,
                },
            );
        }
    }
    #[test]
    fn automatic_refinement_reuses_checked_local_measurements_but_still_validates() {
        let p = profile();
        let mut check = LocalCheck::new(&p, 6_050_000).unwrap();
        for target in LocalCheck::ORDER {
            assert!(check.record(Summary {
                mean: if target == 2 { -8.0 } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            }));
        }
        let mut refinement = Refinement::from_verified_check(&p, &check).unwrap();
        assert_eq!(refinement.stage, Stage::Validate);
        assert_eq!(refinement.total(), 20);
        assert_eq!(refinement.tested, 0);
        assert!(refinement.take_candidate(&p).is_none());
        for _ in 0..refinement.total() {
            let request = refinement.request(&p).unwrap();
            let old_target = request.millicents == 6_050_000
                && !matches!(refinement.tested % 4, 1 | 2);
            refinement.record(&p, Summary {
                mean: if old_target { -8.0 } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(refinement.stage, Stage::Ready);
        assert!(refinement.take_candidate(&p).is_some());
        let mut incomplete = check;
        incomplete.tested = 8;
        assert!(Refinement::from_verified_check(&p, &incomplete).is_err());
    }
    #[test]
    fn paired_validation_requires_repeatability_and_gain_without_regression() {
        for scenario in 0..4 {
            let p = profile();
            let original = p.points().to_vec();
            let mut r = Refinement::new(&p, 6050000).unwrap();
            acquire(&mut r, &p, 0.0);
            assert_eq!(r.stage, Stage::Validate);
            assert_eq!(r.total(), 20);
            assert!(r.diagnostic().is_none());
            assert!(r.take_candidate(&p).is_none());
            for i in 0..20 {
                let request = r.request(&p).unwrap();
                assert_ne!(request.millicents, 6048000);
                if i / 4 != 4 {
                    assert_ne!(request.millicents, 6050000);
                }
                let candidate = matches!(i % 4, 1 | 2);
                let mut mean = if i / 4 < 2 {
                    if candidate {
                        -0.4
                    } else {
                        -1.5
                    }
                } else {
                    0.0
                };
                if scenario == 1 && i == 3 {
                    mean += 1.0;
                }
                if scenario == 2 && candidate && i / 4 == 2 {
                    mean = 0.8;
                }
                if scenario == 3 && candidate && i / 4 < 2 {
                    mean = -1.5;
                }
                r.record(
                    &p,
                    Summary {
                        averaged: false,
                        mean,
                        spread: 1.0,
                        count: 8,
                    },
                );
            }
            assert_eq!(p.points(), original);
            let (_, old, new, repeat) = r.diagnostic().unwrap();
            if scenario == 0 {
                assert_eq!((old, new, repeat), (0.0, 0.0, 0.0));
            }
            if scenario == 1 {
                assert_eq!(repeat, 1.0);
            }
            if scenario == 2 {
                assert_eq!((old, new), (0.0, 0.8));
            }
            assert_eq!(
                r.stage,
                if scenario == 0 {
                    Stage::Ready
                } else {
                    Stage::Rejected
                }
            );
            if scenario == 1 {
                assert_eq!(r.reason, "REFINE COMPARE UNSTABLE");
            }
            if scenario == 2 {
                assert_eq!(r.reason, "REFINE WORSE - BEST KEPT");
            }
            if scenario == 3 {
                assert_eq!(r.reason, "REFINE NO GAIN - BEST KEPT");
            }
            assert_eq!(r.take_candidate(&p).is_some(), scenario == 0);
            assert!(r.take_candidate(&p).is_none());
        }
    }
    #[test]
    fn refusal_of_drift_noise_capacity_and_incomplete_acquisition() {
        // Retaining a whole second profile previously consumed loading/ISR
        // stack headroom. Keep the proposal as a single measured point.
        assert!(core::mem::size_of::<Refinement>() <= 768);
        let p = profile();
        for offset in [-4.0, 4.0] {
            let mut r = Refinement::new(&p, 6050000).unwrap();
            acquire(&mut r, &p, offset);
            assert_eq!(r.stage, Stage::Rejected);
            assert!(r.take_candidate(&p).is_none());
        }
        let mut r = Refinement::new(&p, 6050000).unwrap();
        assert!(r.diagnostic().is_none());
        for mean in [f32::NAN, f32::INFINITY] {
            r.record(
                &p,
                Summary {
                    averaged: false,
                    mean,
                    spread: 0.0,
                    count: 8,
                },
            );
        }
        assert_eq!(r.check.tested, 0);
        r.reject("cancel");
        assert!(r.request(&p).is_none());
        assert!(Refinement::new(&p, 6100000).is_err());
        let mut full = Profile::new("full", 0, 200000).unwrap();
        for n in 0..MAX_POINTS as i32 {
            full.push(Point {
                microvolts: n * 1000,
                millicents: n * 1000,
            })
            .unwrap();
        }
        assert!(Refinement::new(&full, 500).is_err());
    }
    #[test]
    fn small_local_error_never_proposes_a_curve_change() {
        let p = profile();
        let original = p.points().to_vec();
        let mut r = Refinement::new(&p, 6050000).unwrap();
        for (i, target) in LocalCheck::ORDER.into_iter().enumerate() {
            let mean = 3.2
                + if target == 2 {
                    [0.32, 0.17, 0.13][i / 3]
                } else {
                    0.0
                };
            r.record(
                &p,
                Summary {
                    averaged: false,
                    mean,
                    spread: 1.0,
                    count: 8,
                },
            );
        }
        assert_eq!(r.stage, Stage::Rejected);
        assert_eq!(r.reason, "LOCAL ERROR <1C - NO REFINE");
        assert!(r.take_candidate(&p).is_none());
        assert_eq!(p.points(), original);
    }
    #[test]
    fn repeatable_error_at_exact_target_counts_as_independent_gain() {
        let p = profile();
        let mut r = Refinement::new(&p, 6050000).unwrap();
        for index in LocalCheck::ORDER {
            r.record(&p, Summary {
                mean: if index == 2 { -8.0 } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Validate);
        assert_eq!(r.total(), 20);
        for i in 0..r.total() {
            let target = i / 4 == 4;
            r.record(&p, Summary {
                mean: if target && i % 4 == 0 || target && i % 4 == 3 {
                    -8.0
                } else {
                    0.0
                },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Ready);
        assert!(r.take_candidate(&p).is_some());
    }
    #[test]
    fn repeatable_full_step_overshoot_seeks_a_physically_measured_point() {
        let p = profile();
        let mut r = Refinement::new(&p, 6050000).unwrap();
        for index in LocalCheck::ORDER {
            r.record(&p, Summary {
                mean: if index == 2 { 10.0 } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Validate);
        assert_eq!(r.candidate.unwrap().millicents, 6_060_000);
        let total = r.total();
        for i in 0..total {
            let at_target = i / 4 == total / 4 - 1;
            let candidate = matches!(i % 4, 1 | 2);
            r.record(&p, Summary {
                mean: if at_target {
                    if candidate { -11.5 } else { 10.0 }
                } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Seek);
        assert_eq!(r.reason, "REFINE SEEK MEASURE");
        let seek_uv = r.request(&p).unwrap().microvolts;
        assert!((41_667..50_000).contains(&seek_uv));
        for _ in 0..3 {
            r.record(&p, Summary {
                mean: -0.25,
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Validate);
        assert_eq!(r.candidate.unwrap().microvolts, seek_uv);
        assert_eq!(r.candidate.unwrap().millicents, 6_049_750);
        for i in 0..r.total() {
            let at_target = i / 4 == r.total() / 4 - 1;
            let candidate = matches!(i % 4, 1 | 2);
            r.record(&p, Summary {
                mean: if at_target {
                    if candidate { -0.75 } else { 10.0 }
                } else { 0.0 },
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert_eq!(r.stage, Stage::Ready);
        assert!(r.take_candidate(&p).is_some());
    }
    #[test]
    fn physical_seek_can_resolve_a_monotonic_between_anchor_kink() {
        let p = profile();
        let target = 6_050_000;
        let response = |uv: i32| {
            let (lo_uv, lo_pitch, hi_uv, hi_pitch) = if uv < 0 {
                (-100_000, -100_000, 0, 0)
            } else if uv < 41_667 {
                (0, 0, 41_667, 38_500)
            } else if uv < 50_000 {
                (41_667, 38_500, 50_000, 60_000)
            } else if uv < 100_000 {
                (50_000, 60_000, 100_000, 100_000)
            } else {
                (100_000, 100_000, 200_000, 200_000)
            };
            6_000_000 + lo_pitch
                + ((uv - lo_uv) as i64 * (hi_pitch - lo_pitch) as i64
                    / (hi_uv - lo_uv) as i64) as i32
        };
        let mut r = Refinement::new(&p, target).unwrap();
        let mut sought = false;
        for _ in 0..100 {
            if !r.active() {
                break;
            }
            sought |= r.stage == Stage::Seek;
            let request = r.request(&p).unwrap();
            r.record(&p, Summary {
                mean: (response(request.microvolts) - request.millicents) as f32 / 1000.0,
                spread: 0.2,
                count: 8,
                averaged: false,
            });
        }
        assert!(sought);
        assert_eq!(r.stage, Stage::Ready, "{}", r.reason);
        let refined = r.take_candidate(&p).unwrap();
        let predicted = refined.voltage_for_pitch(target).unwrap();
        assert!((response(predicted) - target).abs() < 1_000);
        assert!(refined.points().iter().any(|point| {
            point.microvolts > 41_667
                && point.microvolts < 50_000
                && point.millicents == response(point.microvolts)
        }));
    }
}
impl Refinement {
    pub fn new(profile: &Profile, pitch: i32) -> Result<Self, &'static str> {
        if profile.points().len() >= MAX_POINTS {
            return Err("REFINE FULL - KEEP ORIGINAL");
        }
        let check = LocalCheck::new(profile, pitch).ok_or("REFINE TARGET OUT OF RANGE")?;
        if check.targets[2].microvolts <= check.targets[0].microvolts
            || check.targets[2].microvolts >= check.targets[1].microvolts
        {
            return Err("REFINE NEEDS INTERIOR TARGET");
        }
        Ok(Self {
            stage: Stage::Acquire,
            check,
            candidate: None,
            pitches: [0; 5],
            count: 0,
            tested: 0,
            results: [None; 20],
            original_worst: 0.0,
            candidate_worst: 0.0,
            reason: "REFINE ACQUIRE",
            seek_attempted: false,
            seek_voltage: 0,
            seek_count: 0,
            seek_sum: 0.0,
            seek_low: f32::INFINITY,
            seek_high: f32::NEG_INFINITY,
        })
    }
    /// The automatic check has already measured this interleaved local trio
    /// three times. Reuse those observations to propose a *measured* anchor;
    /// the separate paired old/new validation below still has to succeed.
    pub fn from_verified_check(
        profile: &Profile,
        check: &LocalCheck,
    ) -> Result<Self, &'static str> {
        let mut refinement = Self::new(profile, check.targets[2].millicents)?;
        if refinement.check.targets != check.targets || check.tested != LocalCheck::ORDER.len() {
            return Err("REFINE LOCAL CHECK INCOMPLETE");
        }
        refinement.check = check.clone();
        refinement.finish_acquisition(profile);
        if refinement.stage == Stage::Validate {
            Ok(refinement)
        } else {
            Err(refinement.reason)
        }
    }
    pub fn active(&self) -> bool {
        matches!(self.stage, Stage::Acquire | Stage::Seek | Stage::Validate)
    }
    pub fn total(&self) -> usize {
        if self.stage == Stage::Seek { 3 } else { self.count * 4 }
    }
    pub fn comparison(&self, index: usize) -> Option<(i32, f32, f32, f32)> {
        if index >= self.count {
            return None;
        }
        let r = &self.results[index * 4..index * 4 + 4];
        let (a, b, c, d) = (r[0]?, r[1]?, r[2]?, r[3]?);
        Some((
            self.pitches[index],
            (a + d) * 0.5,
            (b + c) * 0.5,
            (a - d).abs().max((b - c).abs()),
        ))
    }
    /// Retain the least-improved paired test and maximum repeat discrepancy.
    /// Diagnostics only: never changes candidate acceptance or the curve.
    pub fn diagnostic(&self) -> Option<(i32, f32, f32, f32)> {
        if self.total() == 0 || self.tested != self.total() {
            return None;
        }
        let mut worst = self.comparison(0)?;
        let mut repeat = worst.3;
        for i in 1..self.count {
            let next = self.comparison(i)?;
            repeat = repeat.max(next.3);
            if next.2.abs() - next.1.abs() > worst.2.abs() - worst.1.abs() {
                worst = next;
            }
        }
        Some((worst.0, worst.1, worst.2, repeat))
    }
    pub fn request(&self, original: &Profile) -> Option<Point> {
        match self.stage {
            Stage::Acquire => self.check.next().copied(),
            Stage::Seek => Some(Point {
                microvolts: self.seek_voltage,
                millicents: self.check.targets[2].millicents,
            }),
            Stage::Validate => {
                let pitch = *self.pitches.get(self.tested / 4)?;
                let candidate = matches!(self.tested % 4, 1 | 2);
                let uv = if candidate {
                    original.refinement_voltage_for_pitch(self.candidate?, pitch)
                } else {
                    original.voltage_for_pitch(pitch)
                }
                .ok()?;
                let uv =
                    crate::bipolar::decode_voltage(crate::bipolar::encode_profile_voltage(uv)?)?;
                Some(Point {
                    microvolts: uv,
                    millicents: pitch,
                })
            }
            _ => None,
        }
    }
    pub fn reject(&mut self, reason: &'static str) {
        self.stage = Stage::Rejected;
        self.reason = reason;
        self.candidate = None;
    }
    pub fn ready_point(&self) -> Option<Point> {
        if self.stage == Stage::Ready {
            self.candidate
        } else {
            None
        }
    }
    pub fn take_candidate(&mut self, original: &Profile) -> Option<Profile> {
        if self.stage != Stage::Ready {
            return None;
        }
        original.refined_with(self.candidate.take()?).ok()
    }
    fn prepare_validation(&mut self, original: &Profile, measured: Point) -> bool {
        if original
            .refinement_voltage_for_pitch(measured, measured.millicents)
            .is_err()
        {
            return false;
        }
        let points = original.points();
        let Some(i) = points
            .iter()
            .position(|p| p.microvolts == self.check.targets[0].microvolts)
        else {
            return false;
        };
        let pairs = [
            Some((points[i].millicents, measured.millicents)),
            Some((measured.millicents, points[i + 1].millicents)),
            if i > 0 {
                Some((points[i - 1].millicents, points[i].millicents))
            } else {
                None
            },
            points
                .get(i + 2)
                .map(|p| (points[i + 1].millicents, p.millicents)),
        ];
        let mut pitches = [0; 5];
        let mut count = 0;
        for (a, b) in pairs.into_iter().flatten() {
            let pitch = ((a as i64 + b as i64) / 2) as i32;
            if pitch <= a || pitch >= b {
                return false;
            }
            pitches[count] = pitch;
            count += 1;
        }
        pitches[count] = self.check.targets[2].millicents;
        count += 1;
        self.pitches = pitches;
        self.count = count;
        self.candidate = Some(measured);
        self.tested = 0;
        self.results = [None; 20];
        self.original_worst = 0.0;
        self.candidate_worst = 0.0;
        self.stage = Stage::Validate;
        true
    }
    fn finish_acquisition(&mut self, original: &Profile) {
        if let Some(reason) = self.check.refinement_issue() {
            self.reject(reason);
            return;
        }
        // Absolute measured pitch, NOT a fitted compensating offset.
        let mean = self.check.aggregate(2).unwrap().0;
        let mut measured = self.check.targets[2];
        let mc = measured.millicents as i64 + (mean * 1000.0) as i64;
        let Ok(mc) = i32::try_from(mc) else {
            self.reject("REFINE INVALID PITCH");
            return;
        };
        measured.millicents = mc;
        if self.prepare_validation(original, measured) {
            self.reason = "REFINE COMPARE";
        } else {
            self.reject("REFINE INVALID CANDIDATE");
        }
    }
    #[inline(never)]
    pub fn record(&mut self, original: &Profile, s: Summary) {
        if !self.active() {
            return;
        }
        if !self
            .request(original)
            .is_some_and(|p| s.settled(p.millicents))
        {
            return;
        }
        if self.stage == Stage::Acquire {
            if !self.check.record(s) || self.check.next().is_some() {
                return;
            }
            self.finish_acquisition(original);
            return;
        }
        if self.stage == Stage::Seek {
            self.seek_count += 1;
            self.tested = self.seek_count as usize;
            self.seek_sum += s.mean;
            self.seek_low = self.seek_low.min(s.mean);
            self.seek_high = self.seek_high.max(s.mean);
            if self.seek_count < 3 {
                return;
            }
            if self.seek_high - self.seek_low > 0.75 {
                self.reject("REFINE SEEK UNSTABLE");
                return;
            }
            let target = self.check.targets[2].millicents;
            let measured_pitch = target as i64 + (self.seek_sum / 3.0 * 1000.0) as i64;
            let Ok(millicents) = i32::try_from(measured_pitch) else {
                self.reject("REFINE SEEK INVALID PITCH");
                return;
            };
            let measured = Point {
                microvolts: self.seek_voltage,
                millicents,
            };
            if self.prepare_validation(original, measured) {
                self.reason = "REFINE SEEK COMPARE";
            } else {
                self.reject("REFINE SEEK INVALID CANDIDATE");
            }
            return;
        }
        self.results[self.tested] = Some(s.mean);
        self.tested += 1;
        if self.tested < self.total() {
            return;
        }
        let mut stable = true;
        let mut untouched_regression = false;
        for i in 0..self.count {
            let r = &self.results[i * 4..i * 4 + 4];
            let (a, b, c, d) = (
                r[0].unwrap(),
                r[1].unwrap(),
                r[2].unwrap(),
                r[3].unwrap(),
            );
            let old = (a + d) * 0.5;
            let new = (b + c) * 0.5;
            stable &= (a - d).abs() <= 0.75 && (b - c).abs() <= 0.75;
            if (2..self.count - 1).contains(&i) {
                untouched_regression |= new.abs() > old.abs() + 0.5;
            }
            self.original_worst = self.original_worst.max(old.abs());
            self.candidate_worst = self.candidate_worst.max(new.abs());
        }
        // A narrow response kink can make the first measured-point insertion
        // overshoot. The two paired target results then bracket a voltage that
        // should be closer. Probe it physically: never invent a pitch for an
        // existing voltage merely to make the curve look better.
        if stable && !self.seek_attempted {
            if let Some((_, old, new, _)) = self.comparison(self.count - 1) {
                if old * new < 0.0 && new.abs() > old.abs() + 0.5 {
                    let target = self.check.targets[2].millicents;
                    let original_uv = self.check.targets[2].microvolts;
                    if let Ok(candidate_uv) =
                        original.refinement_voltage_for_pitch(self.candidate.unwrap(), target)
                    {
                        let fraction = old.abs() / (old.abs() + new.abs());
                        let estimate = original_uv as f32
                            + fraction * (candidate_uv - original_uv) as f32;
                        if let Some(uv) = crate::bipolar::encode_profile_voltage(estimate as i32)
                            .and_then(crate::bipolar::decode_voltage)
                        {
                            if uv != original_uv && uv != candidate_uv {
                                self.seek_attempted = true;
                                self.seek_voltage = uv;
                                self.seek_count = 0;
                                self.seek_sum = 0.0;
                                self.seek_low = f32::INFINITY;
                                self.seek_high = f32::NEG_INFINITY;
                                self.tested = 0;
                                self.stage = Stage::Seek;
                                self.reason = "REFINE SEEK MEASURE";
                                return;
                            }
                        }
                    }
                }
            }
        }
        if !stable {
            self.reject("REFINE COMPARE UNSTABLE");
        } else if untouched_regression || self.candidate_worst > self.original_worst {
            self.reject("REFINE WORSE - BEST KEPT");
        } else if self.candidate_worst + 0.5 > self.original_worst {
            self.reject("REFINE NO GAIN - BEST KEPT");
        } else {
            self.stage = Stage::Ready;
            self.reason = "REFINE READY - ACCEPT/DISCARD";
        }
    }
}
