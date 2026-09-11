//! Hardware-independent sweep protocol. Requests are not DAC writes.
//! Caller must exclusively own the configured output and acknowledge each
//! applied voltage. A completed profile is withheld until restoration is acked.
use super::{Error, Point, Profile, Route};
const MAX_POINTS:usize=32; // Legacy monotonic acquisition plan, retained for regressions.

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Failure { Timeout, Profile(Error), ClockReversed, Output }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Outcome { Complete, Cancelled, Failed(Failure) }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Request {
    Apply { output: u8, microvolts: i32, token: u32 },
    Wait,
    Restore { output: u8, microvolts: i32, token: u32 },
    Finished(Outcome),
}

#[derive(Clone, Copy)]
pub struct Policy {
    pub settle_ms: u64,
    pub point_timeout_ms: u64,
    pub stable_samples: u8,
    pub tolerance_millicents: u32,
}

/// A fresh detector window, not a repeated display frame. `qualified` must
/// reject silence, clipping and ambiguous estimates before entering this API.
/// Window start/end use the same monotonic millisecond clock as the controller.
pub struct Measurement {
    pub input: u8,
    pub sequence: u64,
    pub window_start_ms: u64,
    pub window_end_ms: u64,
    pub millicents: i32,
    pub qualified: bool,
}

#[derive(Clone, Copy)]
enum State { Applying, Measuring { since: u64 }, Restoring(Outcome), Finished(Outcome) }

pub struct Sweep {
    candidate: Option<Profile>,
    route: Route,
    voltages: [i32; MAX_POINTS],
    count: usize,
    index: usize,
    restore_uv: i32,
    policy: Policy,
    state: State,
    token: u32,
    point_started: u64,
    last_now: u64,
    last_sequence: Option<u64>,
    stable_count: u8,
    minimum: i32,
    maximum: i32,
    sum: i64,
}

impl Sweep {
    pub fn new(name: &str, route: Route, voltages: &[i32], limits: (i32,i32),
               restore_uv: i32, policy: Policy, now: u64) -> Result<Self, Error> {
        let profile = Profile::new(name, limits.0, limits.1)?;
        if voltages.len() < 2 || voltages.len() > MAX_POINTS
            || policy.stable_samples < 2 || policy.point_timeout_ms <= policy.settle_ms {
            return Err(Error::InvalidLimits);
        }
        if restore_uv < limits.0 || restore_uv > limits.1
            || voltages.iter().any(|v| *v < limits.0 || *v > limits.1) {
            return Err(Error::VoltageOutsideLimits);
        }
        if voltages.windows(2).any(|p| p[0] >= p[1]) { return Err(Error::NonMonotonic); }
        let mut table = [0; MAX_POINTS];
        table[..voltages.len()].copy_from_slice(voltages);
        Ok(Self { candidate: Some(profile), route, voltages: table,
            count: voltages.len(), index: 0, restore_uv, policy,
            state: State::Applying, token: 1, point_started: now, last_now: now,
            last_sequence: None, stable_count: 0, minimum: 0, maximum: 0, sum: 0 })
    }

    fn restore(&mut self, outcome: Outcome) {
        self.state = State::Restoring(outcome);
        self.token += 1;
        if outcome != Outcome::Complete { self.candidate = None; }
    }

    /// Repeated cancellation cannot restart restoration or change its token.
    /// Cancellation during completion restoration discards the candidate too.
    pub fn cancel(&mut self) {
        match self.state {
            State::Finished(_) => (),
            State::Restoring(_) => {
                self.candidate = None;
                self.state = State::Restoring(Outcome::Cancelled);
            }
            _ => self.restore(Outcome::Cancelled),
        }
    }

    pub fn output_failed(&mut self) {
        if !matches!(self.state, State::Restoring(_) | State::Finished(_)) {
            self.restore(Outcome::Failed(Failure::Output));
        }
    }

    fn clock(&mut self, now: u64) -> bool {
        if now < self.last_now {
            if !matches!(self.state, State::Restoring(_) | State::Finished(_)) {
                self.restore(Outcome::Failed(Failure::ClockReversed));
            }
            return false;
        }
        self.last_now = now;
        if matches!(self.state, State::Applying | State::Measuring { .. })
            && now - self.point_started >= self.policy.point_timeout_ms {
            self.restore(Outcome::Failed(Failure::Timeout));
        }
        true
    }

    /// `token` must match the request actually applied. The output adapter must
    /// confirm conversion/range validity before acking; no assumed success.
    pub fn acknowledge(&mut self, token: u32, now: u64) -> bool {
        if !self.clock(now) || token != self.token { return false; }
        match self.state {
            State::Applying => { self.state = State::Measuring { since: now }; true }
            State::Restoring(outcome) => { self.state = State::Finished(outcome); true }
            _ => false,
        }
    }

    pub fn poll(&mut self, now: u64, sample: Option<Measurement>) -> Request {
        if self.clock(now) {
            if let State::Measuring { since } = self.state {
                if let Some(sample) = sample {
                    // Old channel data and overlapping pre-step windows cannot
                    // qualify a point. Sequence does not restart between steps.
                    if sample.input == self.route.input()
                        && sample.window_start_ms <= sample.window_end_ms
                        && sample.window_start_ms.saturating_sub(since) >= self.policy.settle_ms
                        && sample.window_start_ms >= since
                        && sample.window_end_ms <= now
                        && self.last_sequence.map_or(true, |s| sample.sequence > s) {
                        self.last_sequence = Some(sample.sequence);
                        if !sample.qualified {
                            self.stable_count = 0;
                        } else {
                            let pitch = sample.millicents;
                            let lo = if self.stable_count == 0 { pitch } else { self.minimum.min(pitch) };
                            let hi = if self.stable_count == 0 { pitch } else { self.maximum.max(pitch) };
                            if (hi as i64 - lo as i64) > self.policy.tolerance_millicents as i64 {
                                self.stable_count = 1;
                                self.minimum = pitch; self.maximum = pitch; self.sum = pitch as i64;
                            } else {
                                if self.stable_count == 0 { self.sum = 0; }
                                self.minimum = lo; self.maximum = hi;
                                self.sum += pitch as i64;
                                self.stable_count += 1;
                            }
                            if self.stable_count >= self.policy.stable_samples {
                                let point = Point { microvolts: self.voltages[self.index],
                                    millicents: (self.sum / self.stable_count as i64) as i32 };
                                match self.candidate.as_mut().unwrap().push(point) {
                                    Err(error) => self.restore(Outcome::Failed(Failure::Profile(error))),
                                    Ok(()) => {
                                        self.index += 1;
                                        self.stable_count = 0;
                                        if self.index == self.count { self.restore(Outcome::Complete); }
                                        else {
                                            self.state = State::Applying;
                                            self.point_started = now;
                                            self.token += 1;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        match self.state {
            State::Applying => Request::Apply { output: self.route.output(),
                microvolts: self.voltages[self.index], token: self.token },
            State::Measuring { .. } => Request::Wait,
            State::Restoring(_) => Request::Restore { output: self.route.output(),
                microvolts: self.restore_uv, token: self.token },
            State::Finished(outcome) => Request::Finished(outcome),
        }
    }

    pub fn take_profile(&mut self) -> Option<Profile> {
        if matches!(self.state, State::Finished(Outcome::Complete)) { self.candidate.take() }
        else { None }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn sweep() -> Sweep {
        Sweep::new("VCO", Route::new(2,3).unwrap(), &[0, 1_000_000], (-1_000_000,2_000_000),
            0, Policy { settle_ms: 10, point_timeout_ms: 100, stable_samples: 3,
                        tolerance_millicents: 1000 }, 0).unwrap()
    }
    fn sample(seq: u64, start: u64, pitch: i32) -> Measurement {
        Measurement { input: 2, sequence: seq, window_start_ms: start,
            window_end_ms: start+1, millicents: pitch, qualified: true }
    }
    #[test]
    fn complete_requires_restore_ack_and_is_one_shot() {
        let mut s = sweep();
        assert!(matches!(s.poll(0,None), Request::Apply { output:3, microvolts:0, token:1 }));
        assert!(!s.acknowledge(9,0)); assert!(s.acknowledge(1,0));
        for n in 1..=3 { s.poll(10+n,Some(sample(n,9+n,1200000))); }
        assert!(matches!(s.poll(13,None), Request::Apply { token:2, .. }));
        assert!(s.acknowledge(2,13));
        for n in 4..=6 { s.poll(20+n,Some(sample(n,19+n,2400000))); }
        assert!(matches!(s.poll(26,None),Request::Restore { token:3, microvolts:0, .. }));
        assert!(s.take_profile().is_none());
        assert!(!s.acknowledge(2,26)); assert!(s.acknowledge(3,26));
        let profile = s.take_profile().unwrap();
        assert_eq!(profile.voltage_for_pitch(1800000),Ok(500000));
        assert!(s.take_profile().is_none());
    }
    #[test]
    fn stale_wrong_input_and_pre_settle_windows_cannot_progress() {
        let mut s=sweep(); s.acknowledge(1,0);
        for n in 1..=3 { s.poll(11,Some(sample(n,9,100))); }
        let mut wrong=sample(4,10,100); wrong.input=0; s.poll(11,Some(wrong));
        for _ in 0..4 { assert_eq!(s.poll(12,Some(sample(5,10,100))),Request::Wait); }
        assert!(matches!(s.poll(100,None),Request::Restore { .. }));
        s.acknowledge(2,100);
        assert_eq!(s.poll(100,None),Request::Finished(Outcome::Failed(Failure::Timeout)));
        assert!(s.take_profile().is_none());
    }
    #[test]
    fn instability_and_invalid_quality_reset_stable_run() {
        let mut s=sweep(); s.acknowledge(1,0);
        s.poll(11,Some(sample(1,10,100)));
        s.poll(12,Some(sample(2,11,3000)));
        let mut bad=sample(3,12,3000); bad.qualified=false; s.poll(13,Some(bad));
        for n in 4..=5 { assert_eq!(s.poll(10+n,Some(sample(n,9+n,3000))),Request::Wait); }
        assert!(matches!(s.poll(16,Some(sample(6,15,3000))),Request::Apply {token:2,..}));
    }
    #[test]
    fn cancellation_is_idempotent_and_discards_candidate() {
        let mut s=sweep(); s.cancel(); s.cancel();
        assert!(matches!(s.poll(0,None),Request::Restore {token:2,..}));
        assert!(!s.acknowledge(1,0)); assert!(s.acknowledge(2,0));
        assert_eq!(s.poll(0,None),Request::Finished(Outcome::Cancelled));
        assert!(s.take_profile().is_none());
    }
    #[test]
    fn missing_output_ack_and_reversed_clock_fail_closed() {
        let mut s=sweep(); assert!(!s.acknowledge(1,100));
        assert!(matches!(s.poll(100,None),Request::Restore {..}));
        let mut s=sweep(); s.poll(20,None);
        assert!(matches!(s.poll(19,None),Request::Restore {..}));
        s.acknowledge(2,20);
        assert_eq!(s.poll(20,None),Request::Finished(Outcome::Failed(Failure::ClockReversed)));
    }

    #[test]
    fn failed_tracking_discards_partial_profile_and_restores() {
        let mut s=sweep(); s.acknowledge(1,0);
        for n in 1..=3 { s.poll(10+n,Some(sample(n,9+n,1200000))); }
        s.acknowledge(2,13);
        // A stable but flat response is not a successful calibration.
        for n in 4..=6 { s.poll(20+n,Some(sample(n,19+n,1200000))); }
        assert!(matches!(s.poll(26,None),Request::Restore { token:3,.. }));
        s.acknowledge(3,26);
        assert_eq!(s.poll(26,None),Request::Finished(Outcome::Failed(
            Failure::Profile(Error::NonMonotonic))));
        assert!(s.take_profile().is_none());
    }

    #[test]
    fn full_sweep_is_bounded_and_cancel_during_restore_prevents_publication() {
        let mut points=[0; MAX_POINTS];
        for (i,v) in points.iter_mut().enumerate() { *v=i as i32; }
        let mut s=Sweep::new("full",Route::new(2,0).unwrap(),&points,(0,100),0,
            Policy {settle_ms:1,point_timeout_ms:10,stable_samples:2,tolerance_millicents:0},0).unwrap();
        for i in 0..MAX_POINTS as u64 {
            assert!(s.acknowledge(i as u32+1,i*3));
            s.poll(i*3+2,Some(sample(i*2,i*3+1,i as i32*100000)));
            s.poll(i*3+3,Some(sample(i*2+1,i*3+2,i as i32*100000)));
        }
        assert!(matches!(s.poll(96,None),Request::Restore {token:33,..}));
        assert!(s.take_profile().is_none());
        s.cancel(); s.cancel();
        assert!(s.acknowledge(33,96));
        assert!(s.take_profile().is_none());
        assert!(core::mem::size_of::<Sweep>() <= 1400);
    }

    #[test]
    fn malformed_plan_rejected_before_any_output_request() {
        let policy=Policy { settle_ms:10,point_timeout_ms:100,stable_samples:3,tolerance_millicents:1000 };
        for plan in [&[0][..], &[1,0][..], &[0,101][..]] {
            assert!(Sweep::new("vco",Route::new(0,0).unwrap(),plan,(0,100),0,policy,0).is_err());
        }
        assert!(Sweep::new("vco",Route::new(0,0).unwrap(),&[0,1],(0,100),-1,policy,0).is_err());
        let mut s=sweep();
        for n in 1..=3 { assert!(matches!(s.poll(n+10,Some(sample(n,n+9,100))),Request::Apply {token:1,..})); }
        assert!(s.take_profile().is_none());
    }
}
