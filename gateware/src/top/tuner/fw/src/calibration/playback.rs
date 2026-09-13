//! Shared corrected-pitch mapping for calibrator playback and future quantizer.
//! No hardware writes, allocation, retained curve copy or automatic arming.
//! The adapter must own the output and qualify fresh calibrated CV snapshots.
use super::{Error,Profile};

#[derive(Clone,Copy,Debug,PartialEq)]
pub enum MappingError { InvalidOrigin, InputOverflow, Profile(Error), OutputOutsideLimits }

/// 0 V's musical meaning is independent of the oscillator's physical 0 V pitch.
/// This initial input convention is 1 V/oct, without quantization or clamping.
pub fn pitch_from_cv(microvolts:i32,zero_note:u8)->Result<i32,MappingError> {
    if !(12..=108).contains(&zero_note) {return Err(MappingError::InvalidOrigin);}
    let scaled=microvolts as i64*1_200_000;
    let delta=if scaled>=0 {(scaled+500_000)/1_000_000}
        else {-((-scaled+500_000)/1_000_000)};
    i32::try_from(zero_note as i64*100_000+delta).map_err(|_|MappingError::InputOverflow)
}

#[derive(Clone,Copy,Debug,PartialEq)]
pub struct Target {
    pub pitch_millicents:i32,
    pub requested_microvolts:i32,
    pub applied_microvolts:i32,
    pub dac_bits:u16,
}

/// The quantizer will supply its chosen pitch here; continuous playback supplies
/// pitch_from_cv directly. Both use exactly the same variable measured curve.
pub fn map_pitch(profile:&Profile,pitch:i32)->Result<Target,MappingError> {
    let uv=profile.voltage_for_pitch(pitch).map_err(MappingError::Profile)?;
    let bits=crate::bipolar::encode_voltage(uv).ok_or(MappingError::OutputOutsideLimits)?;
    Ok(Target{pitch_millicents:pitch,requested_microvolts:uv,
        applied_microvolts:crate::bipolar::decode_voltage(bits).unwrap(),dac_bits:bits})
}

pub fn map_cv(profile:&Profile,microvolts:i32,zero_note:u8)->Result<Target,MappingError> {
    map_pitch(profile,pitch_from_cv(microvolts,zero_note)?)
}

/// Nominal 1 V/oct output, independent of an oscillator calibration profile.
pub fn map_nominal(pitch:i32,zero_note:u8)->Result<Target,MappingError> {
    if !(12..=108).contains(&zero_note) {return Err(MappingError::InvalidOrigin);}
    let delta=pitch as i64-zero_note as i64*100_000;
    let uv=if delta>=0 {(delta*5+3)/6} else {-((-delta*5+3)/6)};
    let uv=i32::try_from(uv).map_err(|_|MappingError::OutputOutsideLimits)?;
    let bits=crate::bipolar::encode_voltage(uv).ok_or(MappingError::OutputOutsideLimits)?;
    Ok(Target{pitch_millicents:pitch,requested_microvolts:uv,
        applied_microvolts:crate::bipolar::decode_voltage(bits).unwrap(),dac_bits:bits})
}

/// Nearest chromatic note, ties upward. Five cents of hysteresis beyond each
/// midpoint prevents ADC noise from retriggering adjacent notes. Euclidean
/// division preserves the same behavior below note zero.
pub fn chromatic_pitch(pitch:i32,previous:Option<i32>)->i32 {
    if let Some(note)=previous {
        if (pitch as i64-note as i64).abs()<=55_000 {return note;}
    }
    (((pitch as i64+50_000).div_euclid(100_000))*100_000)
        .clamp(i32::MIN as i64,i32::MAX as i64) as i32
}

/// One output owner, serviced at 1 kHz. No UI/flash operations in tick.
pub struct Engine {
    profile:Option<Profile>,
    pub active:bool,
    pub status:&'static str,
    pub input:u8,
    pub output:u8,
    pub zero_note:u8,
    pub input_uv:i32,
    pub output_uv:i32,
    pub pitch:i32,
    sequence:Option<u16>,
    last_sample:u32,
    pending:Option<(u8,u32)>,
    token:u8,
    counts_per_v:i32,
    pub updates:u32,
    pub max_cycles:usize,
    pub last_irq_cycle:usize,
    pub max_gap_cycles:usize,
    pub chromatic:bool,
    pub standalone:bool,
    quantized_pitch:Option<i32>,
    last_command:Option<u32>,
    target_since:u32,
}
impl Engine {
    pub const fn new()->Self {Self{profile:None,active:false,status:"STOPPED - RUN TO START",
        input:0,output:0,zero_note:60,input_uv:0,output_uv:0,pitch:0,sequence:None,
        last_sample:0,pending:None,token:0,counts_per_v:4000,updates:0,max_cycles:0,last_irq_cycle:0,max_gap_cycles:0,
        chromatic:false,standalone:false,quantized_pitch:None,last_command:None,target_since:0}}
    pub fn arm(&mut self,profile:&Profile,input:u8,output:u8,zero:u8,counts:i32,now:u32,status:u32)->bool {
        if self.active || status&768!=0 || input>3 || output>3 || counts<=0
            || profile.points().len()<2 || !(12..=108).contains(&zero) {
            self.status="CANNOT ARM - CHECK PROFILE";return false;
        }
        self.profile=Some(profile.clone());self.standalone=false;
        self.start(input,output,zero,counts,now)
    }
    pub fn arm_nominal(&mut self,input:u8,output:u8,zero:u8,counts:i32,now:u32,status:u32)->bool {
        if self.active || status&768!=0 || input>3 || output>3 || counts<=0 || !(12..=108).contains(&zero) {
            self.status="CANNOT ARM - CHECK ROUTE";return false;
        }
        self.profile=None;self.standalone=true;self.chromatic=true;
        self.start(input,output,zero,counts,now)
    }
    fn start(&mut self,input:u8,output:u8,zero:u8,counts:i32,now:u32)->bool {
        self.input=input;self.output=output;self.zero_note=zero;
        self.counts_per_v=counts;self.sequence=None;self.last_sample=now;self.pending=None;
        self.quantized_pitch=None;
        self.last_command=None;self.target_since=now;self.output_uv=0;
        self.active=true;self.status="WAITING FOR CV";self.updates=0;self.max_cycles=0;
        self.last_irq_cycle=0;self.max_gap_cycles=0;true
    }
    pub fn stop(&mut self,reason:&'static str)->u32 {
        self.active=false;self.pending=None;self.quantized_pitch=None;self.last_command=None;self.output_uv=0;self.status=reason;0
    }
    /// Whole measurement window must follow the output change and settling.
    /// Include output acknowledgment and foreground publication latency margin.
    pub fn feedback_ready(&self,now:u32,window_age:u32,end_age:u32)->bool {
        self.active && self.last_command.is_some()
            && end_age<=100 && now.wrapping_sub(self.target_since) as u64>=450+window_age as u64
    }
    pub fn tick(&mut self,now:u32,packed:u32,status:u32,allowed:bool)->Option<u32> {
        if !self.active {return None;}
        if !allowed {return Some(self.stop("STOPPED - CONTROLS CHANGED"));}
        if status&512!=0 {return Some(self.stop("STOPPED - OUTPUT FAULT"));}
        if let Some((token,at))=self.pending {
            if status&511==(token as u32|256) {self.pending=None;}
            else if now.wrapping_sub(at)>=3 {return Some(self.stop("STOPPED - OUTPUT NO ACK"));}
            else {return None;}
        }
        let sequence=((packed>>16)&0x7fff) as u16;
        if packed>>31==0 || self.sequence==Some(sequence) {
            if now.wrapping_sub(self.last_sample)>=10 {return Some(self.stop("STOPPED - CV STALE"));}
            return None;
        }
        self.sequence=Some(sequence);self.last_sample=now;
        let counts=packed as u16 as i16 as i32;
        if counts.abs()>=32760 {return Some(self.stop("STOPPED - INPUT AT RAIL"));}
        let Ok(uv)=i32::try_from(counts as i64*1_000_000/self.counts_per_v as i64) else {
            return Some(self.stop("STOPPED - INPUT CONVERSION"));
        };
        self.input_uv=uv;
        let Ok(mut pitch)=pitch_from_cv(self.input_uv,self.zero_note) else {
            return Some(self.stop("STOPPED - INPUT CONVERSION"));
        };
        if self.chromatic {
            pitch=chromatic_pitch(pitch,self.quantized_pitch);
        }
        let mapping=if self.standalone {map_nominal(pitch,self.zero_note)}
            else {map_pitch(self.profile.as_ref().unwrap(),pitch)};
        let target=match mapping {
            Ok(target)=>target,
            Err(MappingError::Profile(Error::PitchOutsideRange))=>{
                self.quantized_pitch=None;
                self.status=if self.last_command.is_some() {"HOLDING - PITCH OUT OF RANGE"}
                    else {"WAITING FOR IN-RANGE PITCH"};
                // Renew the last acknowledged command's hardware watchdog.
                // Before any valid target there is nothing to hold: stay off.
                return Some(self.last_command.unwrap_or(0));
            }
            Err(MappingError::OutputOutsideLimits) if self.standalone=>{
                self.quantized_pitch=None;
                self.status=if self.last_command.is_some() {"HOLDING - OUTPUT OUT OF RANGE"}
                    else {"WAITING FOR IN-RANGE PITCH"};
                return Some(self.last_command.unwrap_or(0));
            }
            Err(_)=>return Some(self.stop("STOPPED - INVALID MAPPING")),
        };
        if self.last_command.is_none() || target.applied_microvolts!=self.output_uv || target.pitch_millicents!=self.pitch {
            self.target_since=now;
        }
        if self.chromatic {self.quantized_pitch=Some(pitch);}
        self.output_uv=target.applied_microvolts;self.pitch=target.pitch_millicents;
        self.token=self.token.wrapping_add(1);self.pending=Some((self.token,now));
        self.updates=self.updates.wrapping_add(1);
        self.status=if self.standalone {"QUANTIZING - NOMINAL CV"} else {"PLAYING - CORRECTED CV"};
        let command=target.dac_bits as u32 | ((self.output as u32)<<16) | (1<<18)
            | ((self.input as u32)<<19) | ((self.token as u32)<<21) | (1<<29);
        self.last_command=Some(command);Some(command)
    }
}

#[cfg(test)] mod tests {
    use super::*;
    use crate::oscillator_calibration::Point;
    #[test] fn nominal_mapping_covers_bipolar_notes_without_profile() {
        for origin in 12..=108 {
            for step in -60..=60 {
                let target=map_nominal(origin as i32*100_000+step*100_000,origin).unwrap();
                let ideal=step as f64*1_000_000.0/12.0;
                assert!((target.applied_microvolts as f64-ideal).abs()<=126.0);
            }
            assert!(map_nominal(origin as i32*100_000+6_100_000,origin).is_err());
            assert!(map_nominal(origin as i32*100_000-6_100_000,origin).is_err());
        }
        assert!(map_nominal(0,0).is_err());
    }
    #[test] fn standalone_arms_without_profile_and_preserves_safety_and_hysteresis() {
        let mut e=Engine::new();
        assert!(e.arm_nominal(1,2,60,4000,0,0));assert!(e.profile.is_none());
        let command=e.tick(1,sample(1,200),0,true).unwrap();
        assert_eq!(e.pitch,6_100_000);assert_eq!(e.output_uv,83_250);
        let command=e.tick(2,sample(2,160),ack(command),true).unwrap();
        assert_eq!(e.pitch,6_100_000);
        assert_eq!((command>>16)&3,2);
        assert_eq!(e.tick(3,sample(3,24000),ack(command),true),Some(command));
        assert!(e.active);assert_eq!(e.output_uv,83_250);
        let command=e.tick(4,sample(4,-4000),ack(command),true).unwrap();
        assert_eq!(e.output_uv,-1_000_000);
        assert_eq!(e.tick(14,sample(4,-4000),ack(command),true),Some(0));
        assert_eq!(e.status,"STOPPED - CV STALE");
        assert!(e.arm_nominal(0,3,60,4000,20,0));
        assert_eq!(e.tick(21,sample(5,0),0,false),Some(0));
        assert!(!e.active);
        assert!(e.arm(&curve(),1,1,60,4000,30,0));assert!(!e.standalone);
        e.stop("test");
        assert!(!e.arm_nominal(4,0,60,4000,31,0));
        assert!(!e.arm_nominal(0,4,60,4000,31,0));
        assert!(!e.arm_nominal(0,1,60,4000,31,512));
    }
    #[test] fn chromatic_rounding_and_hysteresis_are_symmetric_across_zero() {
        for note in -24..140 {
            let center=note*100_000;
            assert_eq!(chromatic_pitch(center+49_999,None),center);
            assert_eq!(chromatic_pitch(center+50_000,None),center+100_000);
            assert_eq!(chromatic_pitch(center-50_000,None),center);
            assert_eq!(chromatic_pitch(center+55_000,Some(center)),center);
            assert_eq!(chromatic_pitch(center+55_001,Some(center)),center+100_000);
            assert_eq!(chromatic_pitch(center-55_001,Some(center)),center-100_000);
        }
    }
    #[test] fn chromatic_engine_uses_measured_curve_and_clears_history_on_stop() {
        let p=curve();let mut e=Engine::new();e.chromatic=true;
        assert!(e.arm(&p,1,2,60,4000,0,0));
        let command=e.tick(1,sample(1,200),0,true).unwrap(); // 60 cents -> next note
        assert_eq!(e.pitch,6_100_000);
        assert_eq!(command as u16,map_pitch(&p,6_100_000).unwrap().dac_bits);
        e.tick(2,sample(2,160),ack(command),true); // 48 cents retains upper note
        assert_eq!(e.pitch,6_100_000);
        e.stop("test");assert!(e.arm(&p,1,2,60,4000,3,0));
        e.tick(4,sample(3,160),0,true);assert_eq!(e.pitch,6_000_000);
    }
    #[test] fn chromatic_outside_profile_waits_instead_of_clamping_note() {
        let mut p=Profile::new("partial",-5_000_000,5_000_000).unwrap();
        p.push(Point{microvolts:0,millicents:6_030_000}).unwrap();
        p.push(Point{microvolts:1_000_000,millicents:7_230_000}).unwrap();
        let mut e=Engine::new();e.chromatic=true;
        assert!(e.arm(&p,1,1,60,4000,0,0));
        // Input is within measured pitch range, but nearest note is not.
        assert_eq!(e.tick(1,sample(1,120),0,true),Some(0));
        assert!(e.active);assert_eq!(e.status,"WAITING FOR IN-RANGE PITCH");
    }
    fn curve()->Profile {
        let mut p=Profile::new("variable",-5_000_000,5_000_000).unwrap();
        for (uv,mc) in [(-2_000_000,4_800_000),(-900_000,6_000_000),
                         (200_000,7_200_000),(1_500_000,8_400_000)] {
            p.push(Point{microvolts:uv,millicents:mc}).unwrap();
        }
        p
    }
    fn sample(sequence:u32,counts:i16)->u32 {(1<<31)|(sequence<<16)|counts as u16 as u32}
    fn ack(command:u32)->u32 {((command>>21)&255)|256}
    #[test] fn range_hold_renews_command_and_resumes_but_stale_cv_still_stops() {
        for chromatic in [false,true] {
            let mut e=Engine::new();e.chromatic=chromatic;
            assert!(e.arm(&curve(),1,1,60,4000,0,0));
            // No valid note yet: remain disabled but keep listening.
            assert_eq!(e.tick(1,sample(1,20000),0,true),Some(0));assert!(e.active);
            let command=e.tick(2,sample(2,0),0,true).unwrap();
            let voltage=e.output_uv;let pitch=e.pitch;
            for now in 3..1003 {
                let counts=if now%2==0 {20000} else {-20000};
                assert_eq!(e.tick(now,sample(now,counts),ack(command),true),Some(command));
                assert!(e.active);assert_eq!(e.output_uv,voltage);assert_eq!(e.pitch,pitch);
            }
            let resumed=e.tick(1003,sample(1003,4000),ack(command),true).unwrap();
            assert_ne!(resumed as u16,command as u16);assert_eq!(e.pitch,7_200_000);
            assert_eq!(e.tick(1004,sample(1004,20000),ack(resumed),true),Some(resumed));
            assert_eq!(e.tick(1014,sample(1004,20000),ack(resumed),true),Some(0));
            assert_eq!(e.status,"STOPPED - CV STALE");
        }
    }
    #[test] fn settled_audio_requires_whole_fresh_window_after_last_target_change() {
        let mut e=Engine::new();e.chromatic=true;
        assert!(e.arm(&curve(),1,1,60,4000,0,0));
        assert!(!e.feedback_ready(1000,20,1));
        let mut command=e.tick(1,sample(1,0),0,true).unwrap();
        for now in 2..500 {command=e.tick(now,sample(now,0),ack(command),true).unwrap();}
        assert!(e.feedback_ready(500,20,1));
        assert!(!e.feedback_ready(500,60,1));
        assert!(!e.feedback_ready(500,20,101));
        e.tick(500,sample(500,4000),ack(command),true);
        assert!(!e.feedback_ready(501,20,1));
        e.stop("test");assert!(!e.feedback_ready(2000,20,1));
    }
    #[test] fn engine_requires_arm_fresh_samples_and_ack_and_keeps_route() {
        let p=curve();let mut e=Engine::new();
        assert_eq!(e.tick(0,sample(1,0),0,true),None);
        assert!(!e.arm(&p,1,2,60,4000,0,256));
        assert!(e.arm(&p,1,2,60,4000,0,0));
        let c=e.tick(1,sample(1,0),0,true).unwrap();
        assert_eq!((c>>16)&3,2);assert_eq!((c>>19)&3,1);
        assert_eq!(crate::bipolar::decode_voltage(c as u16),Some(-900000));
        assert_eq!(e.tick(2,sample(2,2000),0,true),None);
        let d=e.tick(3,sample(2,2000),ack(c),true).unwrap();
        assert_eq!(crate::bipolar::decode_voltage(d as u16),Some(-350000));
        assert_eq!(e.tick(4,sample(2,2000),ack(d),true),None);
        assert_eq!(e.tick(13,sample(2,2000),ack(d),true),Some(0));
        assert_eq!(e.status,"STOPPED - CV STALE");
        assert_eq!(e.tick(14,sample(3,0),0,true),None);
    }
    #[test] fn playback_faults_latch_and_clock_wrap_is_bounded() {
        let p=curve();
        for reason in 0..4 {
            let mut e=Engine::new();assert!(e.arm(&p,1,1,60,4000,u32::MAX-1,0));
            let c=e.tick(u32::MAX,sample(32767,0),0,true).unwrap();
            let result=match reason {
                0=>e.tick(2,sample(0,0),0,true),
                1=>e.tick(0,sample(0,0),512,true),
                2=>e.tick(0,sample(0,0),ack(c),false),
                _=>e.tick(0,sample(0,32767),ack(c),true),
            };
            assert_eq!(result,Some(0));assert!(!e.active);assert_eq!(e.output_uv,0);
            assert_eq!(e.tick(3,sample(1,0),0,true),None);
        }
    }
    #[test] fn cv_origin_and_negative_rounding_are_explicit() {
        assert_eq!(pitch_from_cv(0,60),Ok(6_000_000));
        assert_eq!(pitch_from_cv(-1_000_000,60),Ok(4_800_000));
        assert_eq!(pitch_from_cv(1_000_000,60),Ok(7_200_000));
        for uv in 0..100_000 {
            assert_eq!(pitch_from_cv(uv,60).unwrap()-6_000_000,
                6_000_000-pitch_from_cv(-uv,60).unwrap());
        }
        for note in [0,11,109,255] {assert_eq!(pitch_from_cv(0,note),Err(MappingError::InvalidOrigin));}
        assert_eq!(pitch_from_cv(i32::MAX,60),Err(MappingError::InputOverflow));
        assert_eq!(pitch_from_cv(i32::MIN,60),Err(MappingError::InputOverflow));
    }
    #[test] fn continuous_and_quantized_pitch_share_variable_curve() {
        let p=curve();let before=p.points().to_vec();
        assert_eq!(map_cv(&p,0,60).unwrap().applied_microvolts,-900_000);
        assert_eq!(map_cv(&p,500_000,60).unwrap().applied_microvolts,-350_000);
        assert_eq!(map_cv(&p,1_500_000,60).unwrap().applied_microvolts,850_000);
        for uv in (-1_000_000..=2_000_000).step_by(125) {
            let target=map_cv(&p,uv,60).unwrap();
            assert_eq!(target,map_pitch(&p,pitch_from_cv(uv,60).unwrap()).unwrap());
            assert!((target.applied_microvolts-target.requested_microvolts).abs()<=125);
        }
        assert_eq!(p.points(),before);
        for uv in [-1_000_001,2_000_001] {
            assert_eq!(map_cv(&p,uv,60),Err(MappingError::Profile(Error::PitchOutsideRange)));
        }
    }
    #[test] fn invalid_or_unrepresentable_profiles_never_produce_commands() {
        let empty=Profile::new("empty",0,1).unwrap();
        assert_eq!(map_pitch(&empty,0),Err(MappingError::Profile(Error::Incomplete)));
        let mut p=Profile::new("outside",5_000_001,6_000_000).unwrap();
        p.push(Point{microvolts:5_000_001,millicents:0}).unwrap();
        p.push(Point{microvolts:6_000_000,millicents:100_000}).unwrap();
        assert_eq!(map_pitch(&p,0),Err(MappingError::OutputOutsideLimits));
    }
}
