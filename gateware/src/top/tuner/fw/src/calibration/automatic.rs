//! Bounded automatic calibration policy. No allocation, flash or DAC access.
use super::{Point,verification_scan::Scan};

pub const TARGET_CENTS:f32=2.0;
pub const MAX_PASSES:u8=8;
pub const MAX_DURATION_MS:u64=15*60*1000;
#[derive(Clone,Copy,Debug,PartialEq)]
pub enum Phase {Sweep,Verify,Refine,Reverify,Review}
pub struct Automatic {
    pub phase:Phase,
    pub passes:u8,
    pub started:u64,
    pub best:Option<Scan>,
    pub undo:Option<Point>,
}
impl Automatic {
    pub fn new(now:u64)->Self {
        Self{phase:Phase::Sweep,passes:0,started:now,best:None,undo:None}
    }
    pub fn active(&self)->bool {self.phase!=Phase::Review}
    pub fn expired(&self,now:u64)->bool {
        now<self.started || now-self.started>=MAX_DURATION_MS
    }
    pub fn label(&self)->&'static str {match self.phase {
        Phase::Sweep=>"MEASURING RANGE",Phase::Verify=>"CHECKING ACCURACY",
        Phase::Refine=>"IMPROVING CURVE",Phase::Reverify=>"RECHECKING FULL RANGE",
        Phase::Review=>"REVIEW RESULT",
    }}
    pub fn improves(&self,scan:&Scan)->bool {
        scan.complete && scan.worst_error.is_finite() && self.best.as_ref()
            .map_or(true,|old|scan.worst_error.abs()+0.5<=old.worst_error.abs())
    }
    pub fn stop_reason(&self,scan:&Scan,points:usize)->Option<&'static str> {
        if scan.worst_error.abs()<=TARGET_CENTS {return Some("READY - WITHIN 2C TARGET");}
        if self.passes>=MAX_PASSES {return Some("REVIEW - IMPROVEMENT LIMIT");}
        if points>=super::MAX_POINTS {return Some("REVIEW - POINT CAPACITY");}
        let Some(check)=scan.local.as_ref() else {return Some("REVIEW - NO LOCAL CHECK");};
        check.refinement_issue()
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn bounded_policy_never_accepts_an_unverified_or_worse_candidate() {
        let mut profile=super::super::Profile::new("test",0,1000000).unwrap();
        profile.push(Point{microvolts:0,millicents:6000000}).unwrap();
        profile.push(Point{microvolts:1000000,millicents:7200000}).unwrap();
        let mut scan=Scan::new(&profile).unwrap();
        let mut auto=Automatic::new(10);
        assert!(!auto.improves(&scan));
        scan.complete=true;scan.worst_error=4.0;
        assert!(auto.improves(&scan));auto.best=Some(scan.clone());
        scan.worst_error=3.8;assert!(!auto.improves(&scan));
        scan.worst_error=-3.5;assert!(auto.improves(&scan));
        scan.worst_error=f32::NAN;assert!(!auto.improves(&scan));
        assert!(auto.expired(9));assert!(auto.expired(10+MAX_DURATION_MS));
        scan.worst_error=1.5;
        assert_eq!(auto.stop_reason(&scan,129),Some("READY - WITHIN 2C TARGET"));
        scan.worst_error=4.0;auto.passes=MAX_PASSES;
        assert_eq!(auto.stop_reason(&scan,121),Some("REVIEW - IMPROVEMENT LIMIT"));
    }
}
