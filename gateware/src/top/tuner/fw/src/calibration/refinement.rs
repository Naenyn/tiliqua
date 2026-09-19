//! Bounded candidate acquisition and paired independent validation. No DAC or
//! persistence access; the live adapter owns settling, cancellation and consent.
use super::{Profile,Point,MAX_POINTS,deviation::Summary,verification_scan::LocalCheck};

#[derive(Clone,Copy,PartialEq,Debug)]
pub enum Stage {Acquire,Validate,Ready,Rejected}
pub struct Refinement {
    pub stage:Stage,
    pub check:LocalCheck,
    candidate:Option<Point>,
    pitches:[i32;4],
    count:usize,
    pub tested:usize,
    results:[Option<Summary>;16],
    pub original_worst:f32,
    pub candidate_worst:f32,
    pub reason:&'static str,
}

#[cfg(test)] mod tests {
    use super::*;
    fn profile()->Profile {
        let mut p=Profile::new("refine",-100000,200000).unwrap();
        for uv in [-100000,0,100000,200000] {p.push(Point{microvolts:uv,millicents:6000000+uv}).unwrap();}p
    }
    fn acquire(r:&mut Refinement,p:&Profile,offset:f32) {
        for mean in [0.0,-2.0,0.0,0.0,-2.0,0.0,0.0,-2.0,0.0] {
            r.record(p,Summary{averaged:false,mean:mean+offset,spread:1.0,count:8});
        }
    }
    #[test] fn paired_validation_requires_repeatability_and_gain_without_regression() {
        for scenario in 0..4 {
            let p=profile();let original=p.points().to_vec();
            let mut r=Refinement::new(&p,6050000).unwrap();acquire(&mut r,&p,0.0);
            assert_eq!(r.stage,Stage::Validate);assert_eq!(r.total(),16);
            assert!(r.take_candidate(&p).is_none());
            for i in 0..16 {
                let request=r.request(&p).unwrap();assert_ne!(request.millicents,6048000);
                assert_ne!(request.millicents,6050000);
                let candidate=matches!(i%4,1|2);
                let mut mean=if i/4<2 {if candidate {-0.4} else {-1.5}} else {0.0};
                if scenario==1 && i==3 {mean+=1.0;}
                if scenario==2 && candidate && i/4==2 {mean=0.8;}
                if scenario==3 && candidate && i/4<2 {mean=-1.5;}
                r.record(&p,Summary{averaged:false,mean,spread:1.0,count:8});
            }
            assert_eq!(p.points(),original);
            assert_eq!(r.stage,if scenario==0 {Stage::Ready} else {Stage::Rejected});
            assert_eq!(r.take_candidate(&p).is_some(),scenario==0);
            assert!(r.take_candidate(&p).is_none());
        }
    }
    #[test] fn refusal_of_drift_noise_capacity_and_incomplete_acquisition() {
        // Retaining a whole second profile previously consumed loading/ISR
        // stack headroom. Keep the proposal as a single measured point.
        assert!(core::mem::size_of::<Refinement>()<=768);
        let p=profile();
        for offset in [-4.0,4.0] {
            let mut r=Refinement::new(&p,6050000).unwrap();acquire(&mut r,&p,offset);
            assert_eq!(r.stage,Stage::Rejected);assert!(r.take_candidate(&p).is_none());
        }
        let mut r=Refinement::new(&p,6050000).unwrap();
        for mean in [f32::NAN,f32::INFINITY] {r.record(&p,Summary{averaged:false,mean,spread:0.0,count:8});}
        assert_eq!(r.check.tested,0);r.reject("cancel");assert!(r.request(&p).is_none());
        assert!(Refinement::new(&p,6100000).is_err());
        let mut full=Profile::new("full",0,200000).unwrap();
        for n in 0..MAX_POINTS as i32 {full.push(Point{microvolts:n*1000,millicents:n*1000}).unwrap();}
        assert!(Refinement::new(&full,500).is_err());
    }
    #[test] fn small_local_error_never_proposes_a_curve_change() {
        let p=profile();let original=p.points().to_vec();
        let mut r=Refinement::new(&p,6050000).unwrap();
        for (i,target) in LocalCheck::ORDER.into_iter().enumerate() {
            let mean=3.2+if target==2 {[0.32,0.17,0.13][i/3]} else {0.0};
            r.record(&p,Summary{averaged:false,mean,spread:1.0,count:8});
        }
        assert_eq!(r.stage,Stage::Rejected);
        assert_eq!(r.reason,"LOCAL ERROR <1C - NO REFINE");
        assert!(r.take_candidate(&p).is_none());
        assert_eq!(p.points(),original);
    }
}
impl Refinement {
    pub fn new(profile:&Profile,pitch:i32)->Result<Self,&'static str> {
        if profile.points().len()>=MAX_POINTS {return Err("REFINE FULL - KEEP ORIGINAL");}
        let check=LocalCheck::new(profile,pitch).ok_or("REFINE TARGET OUT OF RANGE")?;
        if check.targets[2].microvolts<=check.targets[0].microvolts
            || check.targets[2].microvolts>=check.targets[1].microvolts {return Err("REFINE NEEDS INTERIOR TARGET");}
        Ok(Self{stage:Stage::Acquire,check,candidate:None,pitches:[0;4],count:0,tested:0,
            results:[None;16],original_worst:0.0,candidate_worst:0.0,reason:"REFINE ACQUIRE"})
    }
    pub fn active(&self)->bool {matches!(self.stage,Stage::Acquire|Stage::Validate)}
    pub fn total(&self)->usize {self.count*4}
    pub fn comparison(&self,index:usize)->Option<(i32,f32,f32,f32)> {
        if index>=self.count {return None;}
        let r=&self.results[index*4..index*4+4];
        let (a,b,c,d)=(r[0]?.mean,r[1]?.mean,r[2]?.mean,r[3]?.mean);
        Some((self.pitches[index],(a+d)*0.5,(b+c)*0.5,(a-d).abs().max((b-c).abs())))
    }
    pub fn request(&self,original:&Profile)->Option<Point> {
        match self.stage {
            Stage::Acquire=>self.check.next().copied(),
            Stage::Validate=>{
                let pitch=*self.pitches.get(self.tested/4)?;
                let candidate=matches!(self.tested%4,1|2);
                let uv=if candidate {original.refinement_voltage_for_pitch(self.candidate?,pitch)}
                    else {original.voltage_for_pitch(pitch)}.ok()?;
                let uv=crate::bipolar::decode_voltage(crate::bipolar::encode_voltage(uv)?)?;
                Some(Point{microvolts:uv,millicents:pitch})
            },
            _=>None,
        }
    }
    pub fn reject(&mut self,reason:&'static str) {self.stage=Stage::Rejected;self.reason=reason;self.candidate=None;}
    pub fn ready_point(&self)->Option<Point> {
        if self.stage==Stage::Ready {self.candidate} else {None}
    }
    pub fn take_candidate(&mut self,original:&Profile)->Option<Profile> {
        if self.stage!=Stage::Ready {return None;}
        original.refined_with(self.candidate.take()?).ok()
    }
    #[inline(never)]
    pub fn record(&mut self,original:&Profile,s:Summary) {
        if !self.active() {return;}
        if !self.request(original).is_some_and(|p|s.settled(p.millicents)) {return;}
        if self.stage==Stage::Acquire {
            if !self.check.record(s) || self.check.next().is_some() {return;}
            if let Some(reason)=self.check.refinement_issue() {self.reject(reason);return;}
            // Absolute measured pitch, NOT a fitted compensating offset.
            let mean=self.check.aggregate(2).unwrap().0;
            let mut measured=self.check.targets[2];
            let mc=measured.millicents as i64+(mean*1000.0) as i64;
            let Ok(mc)=i32::try_from(mc) else {self.reject("REFINE INVALID PITCH");return;};
            measured.millicents=mc;
            if original.refinement_voltage_for_pitch(measured,measured.millicents).is_err() {
                self.reject("REFINE INVALID CANDIDATE");return;
            }
            // Validate either side of the added point, never at its fitted
            // pitch. Also test each adjacent untouched segment when present.
            let points=original.points();
            let i=points.iter().position(|p|p.microvolts==self.check.targets[0].microvolts).unwrap();
            let pairs=[Some((points[i].millicents,measured.millicents)),
                Some((measured.millicents,points[i+1].millicents)),
                if i>0 {Some((points[i-1].millicents,points[i].millicents))} else {None},
                points.get(i+2).map(|p|(points[i+1].millicents,p.millicents))];
            for (a,b) in pairs.into_iter().flatten() {
                let pitch=((a as i64+b as i64)/2) as i32;
                if pitch<=a || pitch>=b {self.reject("REFINE INTERVAL TOO SMALL");return;}
                self.pitches[self.count]=pitch;self.count+=1;
            }
            self.candidate=Some(measured);self.stage=Stage::Validate;self.reason="REFINE COMPARE";
            return;
        }
        self.results[self.tested]=Some(s);self.tested+=1;
        if self.tested<self.total() {return;}
        let mut improved=false;let mut stable=true;let mut no_regression=true;
        for i in 0..self.count {
            let r=&self.results[i*4..i*4+4];
            let (a,b,c,d)=(r[0].unwrap().mean,r[1].unwrap().mean,r[2].unwrap().mean,r[3].unwrap().mean);
            let old=(a+d)*0.5;let new=(b+c)*0.5;
            stable&=(a-d).abs()<=0.75 && (b-c).abs()<=0.75;
            no_regression&=new.abs()<=old.abs()+0.5;
            if i<2 {improved|=new.abs()+0.5<=old.abs();}
            self.original_worst=self.original_worst.max(old.abs());
            self.candidate_worst=self.candidate_worst.max(new.abs());
        }
        if !stable {self.reject("REFINE COMPARE UNSTABLE");}
        else if !no_regression || !improved || self.candidate_worst>self.original_worst {
            self.reject("REFINE NO GAIN - ORIGINAL");
        } else {self.stage=Stage::Ready;self.reason="REFINE READY - ACCEPT/DISCARD";}
    }
}
