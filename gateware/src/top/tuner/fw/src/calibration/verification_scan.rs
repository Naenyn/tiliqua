//! Bounded, read-only verification plan and aggregate results. No curve edits.
use super::{Profile,Point,deviation::Summary};

/// Three read-only triplets, placing the target between endpoint measurements.
/// Reverse alternate passes to expose direction/settling sensitivity.
#[derive(Clone)]
pub struct LocalCheck {
    pub targets:[Point;3],
    pub results:[Option<Summary>;9],
    pub tested:usize,
}
impl LocalCheck {
    /// Shared acquisition gate: advice never authorizes a curve change.
    /// REFINE must still reacquire and independently validate a candidate.
    pub fn refinement_issue(&self)->Option<&'static str> {
        let Some(values)=self.residuals() else {return Some("LOCAL CHECK INCOMPLETE");};
        let residual=self.residual().unwrap();
        if values.iter().copied().fold(f32::NEG_INFINITY,f32::max)
                -values.iter().copied().fold(f32::INFINITY,f32::min)>0.75
            || (0..3).any(|i|self.aggregate(i).unwrap().2>0.75) {
            return Some("REFINE NOT REPEATABLE");
        }
        // A repeatable near-zero residual needs no curve correction. Do not
        // mislabel this as noisy acquisition, including sign flips near zero.
        if residual.abs()<1.0 {return Some("LOCAL ERROR <1C - NO REFINE");}
        if values.iter().any(|r|r.signum()!=residual.signum()) {
            return Some("REFINE NOT REPEATABLE");
        }
        if self.aggregate(2).unwrap().0.abs()>10.0
            || (0..2).any(|i|self.aggregate(i).unwrap().0.abs()>3.0) {
            return Some("REFINE DRIFT - RECALIBRATE");
        }
        None
    }
    pub fn advice(&self)->&'static str {
        self.refinement_issue().unwrap_or("LOCAL ERROR: TRY REFINE")
    }
    pub const ORDER:[usize;9]=[0,2,1,1,2,0,0,2,1];
    pub fn next(&self)->Option<&Point> {Self::ORDER.get(self.tested).map(|&i|&self.targets[i])}
    pub fn new(profile:&Profile,pitch:i32)->Option<Self> {
        let pair=profile.points().windows(2).find(|p|p[0].millicents<=pitch && pitch<=p[1].millicents)?;
        let uv=profile.voltage_for_pitch(pitch).ok()?;
        let uv=crate::bipolar::decode_voltage(crate::bipolar::encode_voltage(uv)?)?;
        Some(Self{targets:[pair[0],pair[1],Point{microvolts:uv,millicents:pitch}],results:[None;9],tested:0})
    }
    pub fn record(&mut self,s:Summary)->bool {
        if self.tested==Self::ORDER.len() || !s.settled(self.next().unwrap().millicents) {return false;}
        self.results[self.tested]=Some(s);self.tested+=1;true
    }
    pub fn residual(&self)->Option<f32> {
        let values=self.residuals()?;
        Some(values.iter().sum::<f32>()/3.0)
    }
    pub fn residuals(&self)->Option<[f32;3]> {
        if self.tested!=9 {return None;}
        let fraction=(self.targets[2].microvolts-self.targets[0].microvolts) as f32
            /(self.targets[1].microvolts-self.targets[0].microvolts) as f32;
        let mut values=[0.0;3];
        for (round,value) in values.iter_mut().enumerate() {
            let mut means=[0.0;3];
            for i in round*3..round*3+3 {means[Self::ORDER[i]]=self.results[i]?.mean;}
            *value=means[2]-(means[0]+(means[1]-means[0])*fraction);
        }
        Some(values)
    }
    /// Mean, peak within-window span, and between-repeat mean range.
    pub fn aggregate(&self,target:usize)->Option<(f32,f32,f32)> {
        let mut count=0;let mut sum=0.0;let mut span=0.0f32;
        let mut low=f32::INFINITY;let mut high=f32::NEG_INFINITY;
        for (i,result) in self.results.iter().enumerate() {
            if Self::ORDER[i]!=target {continue;}
            if let Some(s)=result {count+=1;sum+=s.mean;span=span.max(s.spread);low=low.min(s.mean);high=high.max(s.mean);}
        }
        if count==0 {None} else {Some((sum/count as f32,span,high-low))}
    }
}

#[derive(Clone)]
pub struct Scan {
    pub points_mode: bool,
    pub first_errors: [Option<f32>;2],
    pub worst_index: usize,
    pub target: i32,
    pub total: u16,
    pub tested: u16,
    pub worst_pitch: i32,
    pub worst_error: f32,
    pub max_spread: f32,
    pub complete: bool,
    pub local:Option<LocalCheck>,
}
impl Scan {
    /// Whole notes and their 50-cent midpoints, strictly inside measured bounds.
    /// Follow the measured profile, independent of manual note-menu limits.
    pub fn new(profile:&Profile)->Option<Self> {
        let p=profile.points();
        if p.len()<2 {return None;}
        let first=(p[0].millicents as i64+49999).div_euclid(50000)*50000;
        let last=(p.last()?.millicents as i64).div_euclid(50000)*50000;
        if first>last {return None;}
        let total=u16::try_from((last-first)/50000+1).ok()?;
        Some(Self{points_mode:false,first_errors:[None;2],worst_index:0,
            target:first as i32,total,tested:0,
            worst_pitch:first as i32,worst_error:0.0,max_spread:0.0,complete:false,local:None})
    }
    /// Replay stored points, including fractional-note endpoints. The adapter
    /// must advance target from the profile and replay the original DAC count.
    pub fn points(profile:&Profile)->Option<Self> {
        let p=profile.points();
        if p.len()<2 {return None;}
        Some(Self{points_mode:true,first_errors:[None;2],worst_index:0,
            target:p[0].millicents,total:p.len() as u16,tested:0,
            worst_pitch:p[0].millicents,worst_error:0.0,max_spread:0.0,complete:false,local:None})
    }
    /// Each result is a settled, fresh window from the adapter. Reject unstable
    /// windows rather than calling them an accuracy measurement.
    pub fn record(&mut self,s:Summary)->bool {
        if self.complete || !s.settled(self.target) {return false;}
        if self.tested==0 || s.mean.abs()>self.worst_error.abs() {
            self.worst_error=s.mean;self.worst_pitch=self.target;
            self.worst_index=self.tested as usize;
        }
        if self.tested<2 {self.first_errors[self.tested as usize]=Some(s.mean);}
        self.max_spread=self.max_spread.max(s.spread);
        self.tested+=1;
        self.complete=self.tested==self.total;
        if !self.complete && !self.points_mode {self.target+=50000;}
        true
    }
}

#[cfg(test)] mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    fn profile(lo:i32,hi:i32)->Profile {
        let mut p=Profile::new("test",0,2000000).unwrap();
        p.push(Point{microvolts:0,millicents:lo}).unwrap();
        p.push(Point{microvolts:2000000,millicents:hi}).unwrap();p
    }
    #[test] fn local_check_separates_common_endpoint_shift_from_local_residual() {
        let p=profile(6000000,8400000);
        let mut check=LocalCheck::new(&p,6600000).unwrap();
        assert!(LocalCheck::new(&p,5900000).is_none());
        assert_eq!(check.targets[2].microvolts,500000);
        assert!(!check.record(Summary{averaged:false,mean:0.0,spread:4.0,count:8}));
        assert_eq!(check.tested,0);assert!(check.residual().is_none());
        for mean in [-1.0,-3.0,-1.0,-1.0,-3.0,-1.0,-1.0,-3.0,-1.0] {
            assert!(check.record(Summary{averaged:false,mean,spread:1.0,count:8}));
        }
        assert_eq!(check.residual(),Some(-2.0));
        assert_eq!(check.residuals(),Some([-2.0;3]));
        assert_eq!(check.aggregate(2),Some((-3.0,1.0,0.0)));
        assert!(check.next().is_none());
        assert!(!check.record(Summary{averaged:false,mean:99.0,spread:0.0,count:8}));
    }
    #[test] fn advice_distinguishes_repeatability_and_large_endpoint_bias() {
        let p=profile(6000000,8400000);
        let make=|bias:f32,residuals:[f32;3]| {
            let mut c=LocalCheck::new(&p,6600000).unwrap();
            assert_eq!(c.advice(),"LOCAL CHECK INCOMPLETE");
            for (i,target) in LocalCheck::ORDER.into_iter().enumerate() {
                c.record(Summary{averaged:false,mean:bias+if target==2 {residuals[i/3]} else {0.0},spread:1.0,count:8});
            }
            c
        };
        assert_eq!(make(-1.3,[-1.84,-1.70,-1.94]).advice(),"LOCAL ERROR: TRY REFINE");
        // Fresh-baseline hardware residuals: too variable to recommend fitting.
        assert_eq!(make(0.0,[-0.82,-1.80,-1.67]).advice(),"REFINE NOT REPEATABLE");
        assert_eq!(make(-4.0,[-1.5;3]).advice(),"REFINE DRIFT - RECALIBRATE");
        assert_eq!(make(0.0,[-0.2;3]).advice(),"LOCAL ERROR <1C - NO REFINE");
        // Observed hardware local residuals with a shared roughly +3c bias.
        assert_eq!(make(3.2,[0.32,0.17,0.13]).advice(),"LOCAL ERROR <1C - NO REFINE");
        assert_eq!(make(0.0,[-0.1,0.1,0.0]).advice(),"LOCAL ERROR <1C - NO REFINE");
        assert_eq!(make(0.0,[-0.9,0.9,0.0]).advice(),"REFINE NOT REPEATABLE");
        assert_eq!(make(0.0,[0.99;3]).advice(),"LOCAL ERROR <1C - NO REFINE");
        assert_eq!(make(0.0,[1.0;3]).advice(),"LOCAL ERROR: TRY REFINE");
    }
    #[test] fn local_repeats_preserve_directional_results_and_reject_partial_residual() {
        let p=profile(6000000,8400000);
        let mut check=LocalCheck::new(&p,6600000).unwrap();
        // Common endpoint shift changes each pass; local residuals differ.
        for (i,mean) in [-1.0,-3.0,-1.0, 1.0,-2.0,1.0, 2.0,1.0,2.0].into_iter().enumerate() {
            assert_eq!(check.next().unwrap().millicents,check.targets[LocalCheck::ORDER[i]].millicents);
            assert!(check.residual().is_none());
            check.record(Summary{averaged:false,mean,spread:0.5,count:8});
        }
        assert_eq!(check.residuals(),Some([-2.0,-3.0,-1.0]));
        assert_eq!(check.residual(),Some(-2.0));
        assert_eq!(check.aggregate(2),Some((-4.0/3.0,0.5,4.0)));
        assert_eq!(check.aggregate(3),None);
    }
    #[test] fn plan_never_extrapolates_and_covers_half_notes() {
        for offset in [-1,0,1,49999] {
            let p=profile(6000000+offset,8400000+offset);
            let mut s=Scan::new(&p).unwrap();
            while !s.complete {
                assert!(p.voltage_for_pitch(s.target).is_ok());
                assert_eq!(s.target%50000,0);
                assert!(s.record(Summary{averaged:false,mean:-1.5,spread:1.0,count:8}));
            }
            assert_eq!(s.tested,s.total);assert_eq!(s.worst_error,-1.5);
            assert!(!s.record(Summary{averaged:false,mean:99.0,spread:0.0,count:8}));
        }
        assert!(Scan::new(&profile(6000001,6049999)).is_none());
    }
    #[test] fn rejects_unstable_or_invalid_results_and_retains_worst_signed_mean() {
        let mut s=Scan::new(&profile(6000000,8400000)).unwrap();
        for (mean,spread,count) in [(0.0,3.1,8),(f32::NAN,0.0,8),(0.0,0.0,7),(0.0,-1.0,8)] {
            assert!(!s.record(Summary{averaged:false,mean,spread,count}));assert_eq!(s.tested,0);
        }
        s.record(Summary{averaged:false,mean:1.0,spread:2.0,count:8});
        s.record(Summary{averaged:false,mean:-2.0,spread:1.0,count:8});
        assert_eq!(s.worst_pitch,6050000);assert_eq!(s.worst_error,-2.0);assert_eq!(s.max_spread,2.0);
    }
    #[test] fn covers_profile_beyond_manual_note_limits_without_counter_overflow() {
        let scan=Scan::new(&profile(-500000,11500000)).unwrap();
        assert_eq!(scan.target,-500000);assert_eq!(scan.total,241);
        assert!(Scan::new(&profile(i32::MIN,i32::MAX)).is_none());
    }
}
