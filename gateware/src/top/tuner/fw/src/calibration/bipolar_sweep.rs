//! Bipolar acquisition protocol used by the live firmware.
//! Check the patch at zero, then acquire monotonically from -5 V to +5 V.
//! Discover the responsive lower boundary before retaining a curve.
//! Skip unmeasurable leading points; stop at the first gap after acquisition.
//! No candidate escapes until a final disabled/zero request is acknowledged.
use crate::bipolar::{self,Density,Direction};
use crate::oscillator_calibration::{Point,Route,sweep::{Measurement,Policy}};
use crate::oscillator_calibration::averaging::{Average,LOW_PITCH};

#[derive(Clone,Copy,Debug,PartialEq)]
pub enum Failure {NoOrigin,OriginChanged,NotTracking,UnstablePitch,RangeBeforeZero,Output,Clock}
#[derive(Clone,Copy,Debug,PartialEq)]
pub enum Outcome {Complete,Cancelled,Failed(Failure)}
#[derive(Clone,Copy,Debug,PartialEq)]
pub enum Request {
    Apply {output:u8,microvolts:i32,token:u8},
    Wait,
    Disable {output:u8,token:u8},
    Finished(Outcome),
}
#[derive(Clone,Copy)]
enum Phase {Origin,Ascending,CheckEnd}
#[derive(Clone,Copy)]
enum State {Applying,Measuring{since:u64},Restoring(Outcome),Finished(Outcome)}

#[derive(Clone,Copy)]
pub struct TrackingFailure {
    pub rejected:Point,
    pub neighbour:Option<Point>,
}

pub struct Curve {
    points:[Point;bipolar::MAX_POINTS],
    count:usize,
    pub limited_low:bool,
    pub limited_high:bool,
}
impl Curve {
    pub fn points(&self)->&[Point] {&self.points[..self.count]}
    pub(crate) fn new()->Self {Self{points:[Point::default();bipolar::MAX_POINTS],count:0,
        limited_low:false,limited_high:false}}
    pub(crate) fn add(&mut self,p:Point)->bool {
        if self.count==self.points.len() || !(bipolar::MIN_UV..=bipolar::MAX_UV).contains(&p.microvolts) {
            return false;
        }
        let index=self.points().partition_point(|old|old.microvolts<p.microvolts);
        if index>0 && self.points[index-1].millicents>=p.millicents {return false;}
        if index<self.count && (self.points[index].microvolts==p.microvolts
            || self.points[index].millicents<=p.millicents) {return false;}
        self.points.copy_within(index..self.count,index+1);
        self.points[index]=p;self.count+=1;true
    }
}

pub struct Sweep {
    candidate:Option<Curve>,route:Route,density:Density,policy:Policy,
    phase:Phase,state:State,index:usize,token:u8,point_started:u64,last_now:u64,
    last_sequence:Option<u64>,count:u8,minimum:i32,maximum:i32,sum:i64,
    origin:i32,origin_tolerance:u32,origin_error:Option<i32>,
    tracking_failure:Option<TrackingFailure>,
    measured_zero:bool,
    upper_flat_points:u8,
    saw_qualified:bool,
    average:Average,needs_average:bool,
    failure_voltage:Option<i32>,
}
impl Sweep {
    pub fn failure_voltage(&self)->Option<i32> {self.failure_voltage}
    pub fn tracking_failure(&self)->Option<TrackingFailure> {self.tracking_failure}
    pub fn origin_error(&self)->Option<i32> {self.origin_error}
    pub fn point_count(&self)->usize {self.candidate.as_ref().map_or(0,|c|c.points().len())}
    pub fn new(route:Route,density:Density,policy:Policy,origin_tolerance:u32,now:u64)->Option<Self> {
        if policy.stable_samples<2 || policy.point_timeout_ms<=policy.settle_ms {return None;}
        Some(Self{candidate:Some(Curve::new()),route,density,policy,phase:Phase::Origin,
            state:State::Applying,index:0,token:1,point_started:now,last_now:now,
            last_sequence:None,count:0,minimum:0,maximum:0,sum:0,origin:0,origin_tolerance,origin_error:None,
            tracking_failure:None,measured_zero:false,upper_flat_points:0,saw_qualified:false,
            average:Average::new(),needs_average:false,failure_voltage:None})
    }
    fn voltage(&self)->i32 {
        match self.phase {
            Phase::Ascending=>{
                let n=bipolar::intervals(self.density);
                if self.index<=n {bipolar::voltage(self.density,Direction::Down,n-self.index).unwrap()}
                else {bipolar::voltage(self.density,Direction::Up,self.index-n).unwrap()}
            }
            _=>0,
        }
    }
    fn advance(&mut self,phase:Phase,index:usize,now:u64) {
        if matches!(phase,Phase::CheckEnd) {self.origin_error=None;}
        self.phase=phase;self.index=index;self.token+=1;self.point_started=now;
        self.state=State::Applying;self.count=0;self.saw_qualified=false;
        self.average.clear();self.needs_average=false;
    }
    fn restore(&mut self,outcome:Outcome) {
        if matches!(self.state,State::Finished(_)) {return;}
        if matches!(outcome,Outcome::Failed(_)) && self.failure_voltage.is_none() {
            self.failure_voltage=Some(self.voltage());
        }
        if !matches!(self.state,State::Restoring(_)) {self.token+=1;}
        self.state=State::Restoring(outcome);
        if outcome!=Outcome::Complete {self.candidate=None;}
    }
    pub fn cancel(&mut self) {
        if matches!(self.state,State::Finished(_)) {return;}
        self.restore(Outcome::Cancelled);self.state=State::Restoring(Outcome::Cancelled);
    }
    pub fn output_failed(&mut self) {
        if matches!(self.state,State::Finished(_)) {return;}
        self.restore(Outcome::Failed(Failure::Output));
        self.state=State::Restoring(Outcome::Failed(Failure::Output));
    }
    fn clock(&mut self,now:u64)->bool {
        if now<self.last_now {self.restore(Outcome::Failed(Failure::Clock));return false;}
        self.last_now=now;
        // Leading range discovery need not spend the full unstable-pitch
        // deadline on silence/out-of-band inputs. Wait two seconds AFTER DAC
        // acknowledgment, and never accelerate a point with qualified evidence.
        // Keep origin/final checks, established curves and ACK failures intact.
        let empty_leading=matches!(self.phase,Phase::Ascending)
            && self.candidate.as_ref().map_or(false,|c|c.count<2)
            && !self.saw_qualified && self.tracking_failure.is_none()
            && self.upper_flat_points==0
            && matches!(self.state,State::Measuring{since}
                if now-since>=2000 && now-since>self.policy.settle_ms);
        if matches!(self.state,State::Applying|State::Measuring{..})
            && (now-self.point_started>=self.policy.point_timeout_ms || empty_leading) {
            // No DAC acknowledgment is an output failure, not a range boundary.
            if matches!(self.state,State::Applying) {self.output_failed();return true;}
            match self.phase {
                Phase::Ascending=>{
                    if self.tracking_failure.is_some() || self.upper_flat_points>0 {
                        self.restore(Outcome::Failed(Failure::NotTracking));return true;
                    }
                    // Once a responsive range exists, qualified but
                    // nonrepeatable pitch is not an upper range boundary.
                    // Before that, intermittent qualification near the 20Hz
                    // floor remains leading-range discovery, not a fatal gap.
                    if self.saw_qualified && self.point_count()>=2 {
                        self.restore(Outcome::Failed(Failure::UnstablePitch));return true;
                    }
                    if self.point_count()>=2 && !self.measured_zero {
                        self.restore(Outcome::Failed(Failure::RangeBeforeZero));return true;
                    }
                    let curve=self.candidate.as_mut().unwrap();
                    if curve.count<2 && self.index<2*bipolar::intervals(self.density) {
                        // A single point has not established a responsive range.
                        // Do not bridge an unmeasurable gap with that provisional point.
                        curve.count=0;
                        curve.limited_low=true;
                        self.advance(Phase::Ascending,self.index+1,now);
                    } else {
                        curve.limited_high=true;
                        self.advance(Phase::CheckEnd,0,now);
                    }
                }
                Phase::CheckEnd if self.origin_error.is_some()=>
                    self.restore(Outcome::Failed(Failure::OriginChanged)),
                _=>self.restore(Outcome::Failed(Failure::NoOrigin)),
            }
        }
        true
    }
    pub fn acknowledge(&mut self,token:u8,now:u64)->bool {
        if !self.clock(now) || token!=self.token {return false;}
        match self.state {
            State::Applying=>{self.state=State::Measuring{since:now};true}
            State::Restoring(outcome)=>{self.state=State::Finished(outcome);true}
            _=>false,
        }
    }
    fn accept(&mut self,pitch:i32,now:u64) {
        match self.phase {
            Phase::Origin=>{
                self.origin=pitch;
                // Preflight only: all stored points come from the same upward pass.
                self.advance(Phase::Ascending,0,now);
            }
            Phase::Ascending=>{
                let uv=self.voltage();
                let curve=self.candidate.as_mut().unwrap();
                if curve.count==1 {
                    let previous=curve.points[0];
                    // An audible oscillator can still be below its CV input range.
                    // Treat small bidirectional movement as a leading plateau,
                    // not useful tracking (nor an octave-error exemption).
                    let flat_limit=self.policy.tolerance_millicents.max(10000) as u64;
                    if (pitch as i64-previous.millicents as i64).unsigned_abs()<=flat_limit {
                        curve.points[0]=Point{microvolts:uv,millicents:pitch};
                        curve.limited_low=true;
                        self.tracking_failure=None;
                        if uv==0 {self.origin=pitch;self.measured_zero=true;}
                        if self.index<2*bipolar::intervals(self.density) {
                            self.advance(Phase::Ascending,self.index+1,now);
                        } else {self.advance(Phase::CheckEnd,0,now);}
                        return;
                    }
                }
                if curve.count>=2 && uv>0 && self.measured_zero {
                    let previous=curve.points[curve.count-1];
                    // Confirm an upper plateau against the SAME last retained
                    // pitch at three successive voltages. Never accumulate
                    // small steps into a spurious plateau or store flat points.
                    let flat_limit=self.policy.tolerance_millicents.max(10000) as u64;
                    if (pitch as i64-previous.millicents as i64).unsigned_abs()<=flat_limit {
                        self.tracking_failure=None;
                        self.upper_flat_points+=1;
                        if self.upper_flat_points>=3 {
                            // The anchor is itself already at the ceiling. Its
                            // preceding interval may contain an unmeasured knee:
                            // replay works, but linear inversion there does not.
                            // Keep the last point known to precede saturation.
                            curve.count-=1;
                            curve.limited_high=true;
                            self.advance(Phase::CheckEnd,0,now);
                        } else if self.index<2*bipolar::intervals(self.density) {
                            self.advance(Phase::Ascending,self.index+1,now);
                        } else {
                            self.restore(Outcome::Failed(Failure::NotTracking));
                        }
                        return;
                    }
                    if self.upper_flat_points>0 {
                        // An isolated flat spot followed by changed pitch is
                        // not a confirmed endpoint. Do not bridge it.
                        self.tracking_failure=Some(TrackingFailure {
                            rejected:Point{microvolts:uv,millicents:pitch},neighbour:Some(previous)});
                        self.count=0;return;
                    }
                }
                if !self.candidate.as_mut().unwrap().add(Point{microvolts:uv,millicents:pitch}) {
                    let points=self.candidate.as_ref().unwrap().points();
                    let neighbour=points.last();
                    self.tracking_failure=Some(TrackingFailure {
                        rejected:Point{microvolts:uv,millicents:pitch},neighbour:neighbour.copied()});
                    // Retry within this point's original deadline. Never insert,
                    // octave-shift or skip a non-monotonic observation.
                    self.count=0;return;
                }
                self.tracking_failure=None;
                if uv==0 {self.origin=pitch;self.measured_zero=true;}
                if self.index<2*bipolar::intervals(self.density) {self.advance(Phase::Ascending,self.index+1,now);}
                else {self.advance(Phase::CheckEnd,0,now);}
            }
            Phase::CheckEnd=>{
                if (pitch as i64-self.origin as i64).unsigned_abs()>self.origin_tolerance as u64 {
                    self.count=0;return;
                }
                if self.candidate.as_ref().unwrap().count<2 {self.restore(Outcome::Failed(Failure::NotTracking));}
                else if !self.measured_zero {self.restore(Outcome::Failed(Failure::RangeBeforeZero));}
                else {self.restore(Outcome::Complete);}
            }
        }
    }
    pub fn poll(&mut self,now:u64,sample:Option<Measurement>)->Request {
        if self.clock(now) {
            if let (State::Measuring{since},Some(s))=(self.state,sample) {
                if s.input==self.route.input() && s.window_start_ms>=since
                    && s.window_start_ms-since>=self.policy.settle_ms
                    && s.window_start_ms<=s.window_end_ms && s.window_end_ms<=now
                    && now-s.window_end_ms<=100
                    && self.last_sequence.map_or(true,|last|s.sequence>last) {
                    self.last_sequence=Some(s.sequence);
                    self.saw_qualified|=s.qualified;
                    let checking=matches!(self.phase,Phase::CheckEnd);
                    if checking && s.qualified {
                        self.origin_error=Some(s.millicents.saturating_sub(self.origin));
                    }
                    // A repeatable transient is not proof that zero changed.
                    // Require every accepted recheck sample to match the origin,
                    // and retain the existing deadline for recovery or failure.
                    if !s.qualified || (checking && self.origin_error.unwrap_or(0).unsigned_abs()>self.origin_tolerance) {
                        self.count=0;self.average.clear();
                    }
                    else {
                        let averaged=if s.millicents<=LOW_PITCH {
                            self.average.observe(s.millicents,s.window_start_ms,s.window_end_ms)
                        } else {self.average.clear();None};
                        let lo=if self.count==0 {s.millicents} else {self.minimum.min(s.millicents)};
                        let hi=if self.count==0 {s.millicents} else {self.maximum.max(s.millicents)};
                        if (hi as i64-lo as i64)>self.policy.tolerance_millicents as i64 {
                            if s.millicents<=LOW_PITCH {self.needs_average=true;}
                            self.count=1;self.minimum=s.millicents;self.maximum=s.millicents;self.sum=s.millicents as i64;
                        } else {
                            if self.count==0 {self.sum=0;}
                            self.minimum=lo;self.maximum=hi;self.sum+=s.millicents as i64;self.count+=1;
                        }
                        if self.needs_average {
                            if let Some(mean)=averaged {self.accept(mean.mean,now);}
                        } else if self.count>=self.policy.stable_samples {
                            self.accept((self.sum/self.count as i64) as i32,now);
                        }
                    }
                }
            }
        }
        match self.state {
            State::Applying=>Request::Apply{output:self.route.output(),microvolts:self.voltage(),token:self.token},
            State::Measuring{..}=>Request::Wait,
            State::Restoring(_)=>Request::Disable{output:self.route.output(),token:self.token},
            State::Finished(o)=>Request::Finished(o),
        }
    }
    pub fn take_curve(&mut self)->Option<Curve> {
        if matches!(self.state,State::Finished(Outcome::Complete)) {self.candidate.take()} else {None}
    }
}

#[cfg(test)] mod tests {
    use super::*;
    fn make(d:Density)->Sweep {
        Sweep::new(Route::new(2,3).unwrap(),d,Policy{settle_ms:2,point_timeout_ms:20,
            stable_samples:3,tolerance_millicents:1000},5000,0).unwrap()
    }
    fn sample(now:u64,pitch:Option<i32>)->Measurement {
        Measurement{input:2,sequence:now,window_start_ms:now.saturating_sub(1),
            window_end_ms:now,millicents:pitch.unwrap_or(0),qualified:pitch.is_some()}
    }
    fn walk(d:Density,mut measure:impl FnMut(i32)->Option<i32>)->(Outcome,Option<Curve>,Vec<i32>) {
        let mut s=make(d);let mut uv=0;let mut trace=Vec::new();let mut last_token=0;
        for now in 0..10000 {
            let r=s.poll(now,Some(sample(now,measure(uv))));
            match r {
                Request::Apply{output,microvolts,token}=>{
                    assert_eq!(output,3);assert!(token>last_token);last_token=token;
                    uv=microvolts;trace.push(uv);assert!(s.acknowledge(token,now));
                }
                Request::Disable{output,token}=>{
                    assert_eq!(output,3);assert!(token>last_token);
                    assert!(s.take_curve().is_none());assert!(s.acknowledge(token,now));
                }
                Request::Finished(o)=>{
                    let curve=s.take_curve();assert!(s.take_curve().is_none());return (o,curve,trace);
                }
                Request::Wait=>{},
            }
        }
        panic!("bounded sweep did not finish")
    }
    fn ideal(uv:i32)->i32 {6000000+(uv as i64*1200000/1000000) as i32}
    #[test] fn signal_gap_below_zero_does_not_claim_zero_pitch_loss() {
        let (outcome,curve,_)=walk(Density::Semitone,|uv|
            if (-1_000_000..=-500_000).contains(&uv) {None}else{Some(ideal(uv))});
        assert_eq!(outcome,Outcome::Failed(Failure::RangeBeforeZero));
        assert!(curve.is_none());
    }
    #[test] fn only_empty_leading_points_use_short_discovery_deadline() {
        let make_live=||Sweep::new(Route::new(2,3).unwrap(),Density::Semitone,
            Policy{settle_ms:350,point_timeout_ms:5000,stable_samples:8,
                tolerance_millicents:3000},5000,0).unwrap();
        let mut s=make_live();
        // An unacknowledged output is never mistaken for a range boundary.
        s.advance(Phase::Ascending,0,0);
        assert!(matches!(s.poll(2000,None),Request::Apply{microvolts:-5000000,..}));
        assert!(s.acknowledge(s.token,2100));
        assert_eq!(s.poll(4099,None),Request::Wait);
        assert!(matches!(s.poll(4100,None),Request::Apply{..}));
        assert_eq!(s.index,1);
        for phase in [Phase::Origin,Phase::CheckEnd] {
            let mut s=make_live();s.advance(phase,0,0);s.acknowledge(s.token,0);
            assert_eq!(s.poll(2000,None),Request::Wait);
        }
        let mut s=make_live();s.advance(Phase::Ascending,0,0);s.acknowledge(s.token,0);
        // Even one settled qualified observation retains the full deadline.
        assert_eq!(s.poll(500,Some(sample(500,Some(6000000)))),Request::Wait);
        assert_eq!(s.poll(2000,None),Request::Wait);
        let mut s=make_live();
        s.candidate.as_mut().unwrap().add(Point{microvolts:-5000000,millicents:0});
        s.candidate.as_mut().unwrap().add(Point{microvolts:-4916667,millicents:100000});
        s.advance(Phase::Ascending,2,0);s.acknowledge(s.token,0);
        assert_eq!(s.poll(2000,None),Request::Wait);
    }
    #[test] fn full_bipolar_sweeps_acquire_strictly_upward_after_zero_preflight() {
        for d in [Density::QuarterVolt,Density::Semitone] {
            let (o,curve,trace)=walk(d,|uv|Some(ideal(uv)));
            assert_eq!(o,Outcome::Complete);let c=curve.unwrap();
            assert_eq!(c.count,2*bipolar::intervals(d)+1);
            assert_eq!(c.points()[0].microvolts,-5000000);
            assert_eq!(c.points().last().unwrap().microvolts,5000000);
            assert!(!c.limited_low && !c.limited_high);
            for pair in c.points().windows(2) {
                assert!(pair[0].microvolts<pair[1].microvolts);
                assert!(pair[0].millicents<pair[1].millicents);
            }
            assert_eq!(trace[0],0);assert_eq!(trace[1],-5000000);
            let pass=&trace[1..trace.len()-1];
            assert_eq!(pass.len(),2*bipolar::intervals(d)+1);
            assert!(pass.windows(2).all(|p|p[1]>p[0]));
            assert_eq!(trace.last(),Some(&0));
            assert!(core::mem::size_of::<Sweep>()<1280);
        }
    }
    #[test] fn boundaries_are_independent_and_keep_only_contiguous_measured_points() {
        for (lo,hi) in [(-1000000,2000000),(0,2000000),(-1000000,0)] {
            let (o,c,_)=walk(Density::Semitone,|uv|if (lo..=hi).contains(&uv) {Some(ideal(uv))} else {None});
            assert_eq!(o,Outcome::Complete);let c=c.unwrap();
            assert_eq!(c.points()[0].microvolts,lo);assert_eq!(c.points().last().unwrap().microvolts,hi);
            assert!(c.limited_low && c.limited_high);
        }
    }
    #[test] fn ascending_pass_stops_at_first_interior_gap() {
        let (o,c,trace)=walk(Density::Semitone,|uv|if uv==1000000 {None} else {Some(ideal(uv))});
        assert_eq!(o,Outcome::Complete);let c=c.unwrap();
        assert_eq!(c.points().last().unwrap().microvolts,916750);
        assert!(c.limited_high);assert!(!trace.iter().any(|v|*v>1000000));
    }
    #[test] fn audible_lower_plateau_is_discovered_without_saving_flat_points() {
        for noise in [-1000,0,1000] {
            let (o,c,_)=walk(Density::Semitone,|uv|Some(if uv < -4000000 {
                ideal(-4000000)+if uv == -5000000 {0} else {noise}
            } else {ideal(uv)}));
            assert_eq!(o,Outcome::Complete);
            let c=c.unwrap();
            assert!(c.limited_low && !c.limited_high);
            assert_eq!(c.points()[0].microvolts,-4000000);
            assert_eq!(c.count,109);
        }
    }
    #[test] fn established_curve_does_not_skip_flat_or_octave_dropping_points() {
        for drop in [100000,1200000] {
            let (o,c,_)=walk(Density::Semitone,|uv|Some(ideal(uv)-if uv==1000000 {drop} else {0}));
            assert_eq!(o,Outcome::Failed(Failure::NotTracking));
            assert!(c.is_none());
        }
    }
    #[test] fn discovery_does_not_hide_an_initial_octave_drop_or_bridge_a_gap() {
        let (o,c,_)=walk(Density::Semitone,|uv|Some(ideal(uv)-if uv==-4916750 {1200000} else {0}));
        assert_eq!(o,Outcome::Failed(Failure::NotTracking));assert!(c.is_none());
        let (o,c,_)=walk(Density::Semitone,|uv|if uv==-4916750 {None} else {Some(ideal(uv))});
        assert_eq!(o,Outcome::Complete);
        let c=c.unwrap();assert!(c.limited_low);
        assert_eq!(c.points()[0].microvolts,-4833250);
    }
    #[test] fn upper_plateau_requires_three_qualified_points_and_retains_only_tracking_range() {
        for noise in [-1000,0,1000] {
            let (o,c,trace)=walk(Density::Semitone,|uv|Some(if uv>3000000 {
                ideal(3000000)+noise
            } else {ideal(uv)}));
            assert_eq!(o,Outcome::Complete);let c=c.unwrap();
            assert!(c.limited_high);
            assert_eq!(c.points().last().unwrap().microvolts,2916750);
            assert!(trace.contains(&3250000));
            assert!(!trace.iter().any(|v|*v>3250000));
        }
    }
    #[test] fn incomplete_or_unqualified_upper_plateau_is_not_accepted() {
        for missing in [false,true] {
            let (o,c,_)=walk(Density::Semitone,|uv| {
                if missing && uv==3166750 {return None;}
                Some(if (missing && uv>3000000) || (!missing && uv>4916750) {
                    ideal(if missing {3000000} else {4916750})
                } else {ideal(uv)})
            });
            assert_eq!(o,Outcome::Failed(Failure::NotTracking));assert!(c.is_none());
        }
    }
    #[test] fn lost_origin_drift_flat_tracking_and_no_usable_span_fail_without_curve() {
        let mut went_negative=false;
        let (o,c,_)=walk(Density::QuarterVolt,|uv| {
            if uv<0 {went_negative=true;None} else if went_negative {None} else {Some(ideal(uv))}
        });
        assert_eq!(o,Outcome::Failed(Failure::NoOrigin));assert!(c.is_none());
        let mut went_positive=false;
        let (o,c,_)=walk(Density::QuarterVolt,|uv|{
            if uv>0 {went_positive=true;}
            Some(ideal(uv)+if went_positive && uv==0 {6000} else {0})
        });
        assert_eq!(o,Outcome::Failed(Failure::OriginChanged));assert!(c.is_none());
        let (o,c,_)=walk(Density::QuarterVolt,|_|Some(6000000));
        assert_eq!(o,Outcome::Failed(Failure::NotTracking));assert!(c.is_none());
        let (o,c,_)=walk(Density::QuarterVolt,|uv|if uv==0 {Some(6000000)} else {None});
        assert_eq!(o,Outcome::Failed(Failure::NotTracking));assert!(c.is_none());
    }
    #[test] fn output_ack_timeout_cancel_and_restoration_are_not_measured_boundaries() {
        let mut s=make(Density::Semitone);
        assert!(matches!(s.poll(20,None),Request::Disable{token:2,..}));
        assert!(s.acknowledge(2,20));
        assert_eq!(s.poll(21,None),Request::Finished(Outcome::Failed(Failure::Output)));
        assert!(s.take_curve().is_none());
        for failure in [false,true] {
            let mut s=make(Density::Semitone);s.acknowledge(1,0);
            if failure {s.output_failed();} else {s.cancel();s.cancel();}
            let request=s.poll(2,None);
            assert!(matches!(request,Request::Disable{token:2,..}));
            assert!(!s.acknowledge(1,2));assert_eq!(s.poll(100,None),request);
            assert!(s.take_curve().is_none());assert!(s.acknowledge(2,100));
        }
    }
    #[test] fn wrong_channel_cached_old_or_unstable_samples_cannot_record_origin() {
        for bad in 0..5 {
            let mut s=make(Density::Semitone);s.acknowledge(1,0);
            for now in 1..20 {
                let mut m=sample(now,Some(6000000));
                match bad {
                    0=>m.input=1,
                    1=>m.sequence=1,
                    2=>m.window_start_ms=0,
                    3=>m.millicents+=if now%2==0 {2000} else {0},
                    _=>m.qualified=false,
                }
                assert_eq!(s.poll(now,Some(m)),Request::Wait);
            }
            assert!(matches!(s.poll(20,None),Request::Disable{..}));
            assert!(s.take_curve().is_none());
        }
        let mut s=make(Density::QuarterVolt);s.acknowledge(1,5);
        assert!(matches!(s.poll(4,None),Request::Disable{token:2,..}));
        s.acknowledge(2,6);
        assert_eq!(s.poll(6,None),Request::Finished(Outcome::Failed(Failure::Clock)));
    }
}
