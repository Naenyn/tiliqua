//! Bipolar tracking sweep, with output acknowledgments and origin rechecks.
use crate::oscillator_calibration::{Profile, Route, sweep::{Policy, Measurement}};
use crate::bipolar_sweep::{Sweep,Request,Outcome,Failure};
use crate::bipolar::{self,Density};
use crate::runtime::{ChannelMeasurement, RuntimeControls, OperatingMode};
use crate::pac;
use crate::pitch_math;
use crate::oscillator_calibration::deviation::{Deviation,Summary};
use crate::oscillator_calibration::verification_scan::Scan;
use crate::oscillator_calibration::automatic::{Automatic,Phase};
use crate::oscillator_calibration::averaging::{Average,LOW_PITCH};

/// Keep operation controls independent of the visible page. Manual VERIFY
/// may adjust its target while visible; navigation cannot retarget a run.
pub fn background_controls(mut captured:RuntimeControls,current:RuntimeControls,verifying:bool)->RuntimeControls {
    if verifying && current.mode==OperatingMode::Verify {captured.target_millicents=current.target_millicents;}
    captured
}

pub struct Live {
    pub automatic:Option<Automatic>,
    sweep: Option<Sweep>,
    pub profile: Option<Profile>,
    pub pending_profile: Option<Profile>,
    pending_route: Option<Route>,
    pub profile_route: Option<Route>,
    pub verifying: bool,
    pub scan: Option<Scan>,
    pub refinement:Option<crate::oscillator_calibration::refinement::Refinement>,
    pub target_millicents: i32,
    pub error_cents: Option<f32>,
    pub deviation: Option<Summary>,
    statistics: Deviation,
    average:Average,
    suggested_note: Option<u8>,
    verify_command: u32,
    verify_started: u64,
    verify_token: u8,
    pub status: &'static str,
    pub zero_error_cents:Option<f32>,
    pub failure_voltage:Option<i32>,
    pub failure_acquisition:Option<crate::bipolar_sweep::AcquisitionDiagnostic>,
    pub tracking_failure:Option<crate::bipolar_sweep::TrackingFailure>,
    pub rejected_detector:Option<(f32,u8)>,
    pub rejected_verifier:Option<crate::pitch_verification::Diagnostic>,
    pub input: u8,
    pub output: u8,
    pub millivolts: i32,
    pub point: u8,
    pub point_count: u8,
    sweep_command: u32,
    waiting: Option<u8>,
    previous_sequence: Option<u16>,
    sequence: u64,
}

impl Live {
    #[inline(never)]
    pub fn new() -> Self {
        Self { automatic:None,sweep:None,profile:None,pending_profile:None,pending_route:None,profile_route:None,verifying:false,scan:None,refinement:None,
            target_millicents:0,error_cents:None,verify_command:0,verify_started:0,verify_token:0,
            deviation:None,statistics:Deviation::new(),average:Average::new(),suggested_note:None,
            failure_voltage:None,failure_acquisition:None,
            status:"READY - RUN IN MENU",zero_error_cents:None,tracking_failure:None,rejected_detector:None,rejected_verifier:None,input:0,output:1,
            millivolts:0,point:0,point_count:121,sweep_command:0,waiting:None,previous_sequence:None,sequence:0 }
    }
    pub fn take_suggested_note(&mut self)->Option<u8> {self.suggested_note.take()}
    pub fn recall(&mut self,record:crate::oscillator_calibration::storage::Recalled)->bool {
        if self.active() || self.pending_profile.is_some() {return false;}
        self.automatic=None;
        self.scan=None;
        self.failure_voltage=None;
        self.failure_acquisition=None;
        self.refinement=None;
        self.input=record.route.input();self.output=record.route.output();
        self.point_count=record.profile.points().len() as u8;self.point=0;
        self.suggested_note=record.profile.suggested_note();
        self.profile=Some(record.profile);self.profile_route=Some(record.route);
        self.error_cents=None;self.deviation=None;self.statistics.clear();self.millivolts=0;
        self.status="LOADED - OUTPUT STOPPED";true
    }
    pub fn active(&self) -> bool { self.sweep.is_some() || self.verifying
        || self.automatic.as_ref().is_some_and(|a|a.active()) }
    fn operation_profile(&self)->Option<&Profile> {
        if self.automatic.as_ref().is_some_and(|a|a.active()) {self.pending_profile.as_ref()}
        else {self.profile.as_ref()}
    }
    /// Start the whole workflow without replacing the previously accepted profile.
    pub fn toggle_automatic(&mut self,tuner:&pac::TUNER_PERIPH,controls:RuntimeControls,now:u64) {
        if self.automatic.as_ref().is_some_and(|a|a.active()) {
            self.sweep=None;self.stop_verify(tuner,"CANCELLED - PRIOR PROFILE KEPT");
            self.pending_profile=None;self.pending_route=None;self.automatic=None;
            self.scan=None;self.refinement=None;return;
        }
        if self.active() {self.status="BUSY - STOP CHECK FIRST";return;}
        self.automatic=None;
        self.toggle(tuner,controls,now);
        if self.sweep.is_some() {self.automatic=Some(Automatic::new(now));}
    }
    pub fn accept_scan(&mut self,tuner:&pac::TUNER_PERIPH) {
        if self.active() || tuner.cal_status().read().value().bits()&768!=0 {
            self.status="BUSY - STOP OUTPUT FIRST";return;
        }
        if let Some(profile)=self.pending_profile.take() {
            self.suggested_note=profile.suggested_note();
            self.profile=Some(profile);self.profile_route=self.pending_route.take();
            self.status="ACCEPTED IN RAM - SAVE PROFILE";
            self.automatic=None;
        } else {self.status="NO SCAN TO ACCEPT";}
    }
    pub fn discard_scan(&mut self) {
        if self.active() {self.status="BUSY - STOP OUTPUT FIRST";return;}
        if self.pending_profile.take().is_some() {
            self.automatic=None;
            self.pending_route=None;self.status="DISCARDED - PRIOR PROFILE KEPT";
        } else {self.status="NO SCAN TO DISCARD";}
    }
    #[inline(never)]
    pub fn start_refinement(&mut self,tuner:&pac::TUNER_PERIPH,c:RuntimeControls,now:u64) {
        if self.pending_profile.is_some() {self.status="ACCEPT OR DISCARD CAL FIRST";return;}
        if self.active() {self.status="BUSY - STOP OUTPUT FIRST";return;}
        if self.refinement.as_ref().is_some_and(|r|r.stage==crate::oscillator_calibration::refinement::Stage::Ready) {
            self.status="ACCEPT OR DISCARD FIRST";return;
        }
        if c.mode!=OperatingMode::Verify || !c.verify_scan || c.verify_points {
            self.status="REFINE NEEDS VERIFY SCAN";return;
        }
        let Some(scan)=self.scan.as_ref().filter(|s|!s.points_mode && s.complete
            && s.local.as_ref().is_some_and(|l|l.tested==9)) else {
            self.status="RUN SCAN BEFORE REFINE";return;
        };
        let Some(profile)=self.profile.as_ref() else {return;};
        let Some(route)=self.profile_route else {return;};
        let r=match crate::oscillator_calibration::refinement::Refinement::new(profile,scan.worst_pitch) {
            Ok(r)=>r,Err(reason)=>{self.status=reason;return;}
        };
        let pitch=r.request(profile).unwrap().millicents;
        self.refinement=Some(r);self.input=route.input();self.output=route.output();
        self.verifying=true;self.apply_target(tuner,pitch,now);
    }
    #[inline(never)]
    pub fn accept_refinement(&mut self,tuner:&pac::TUNER_PERIPH) {
        if self.active() || tuner.cal_status().read().value().bits()&768!=0 {
            self.status="BUSY - STOP OUTPUT FIRST";return;
        }
        if let Some(candidate)=self.refinement.as_mut().and_then(|r|r.take_candidate(self.profile.as_ref()?)) {
            self.point_count=candidate.points().len() as u8;
            self.profile=Some(candidate);self.refinement=None;self.scan=None;
            self.status="REFINED IN RAM - SAVE PROFILE";
        } else {self.status="NO VERIFIED CANDIDATE";}
    }
    pub fn discard_refinement(&mut self,tuner:&pac::TUNER_PERIPH) {
        if self.refinement.is_none() {self.status="NO CANDIDATE TO DISCARD";return;}
        self.stop_verify(tuner,"DISCARDED - ORIGINAL KEPT");self.refinement=None;
    }
    fn stop_verify(&mut self,tuner:&pac::TUNER_PERIPH,status:&'static str) {
        if let Some(r)=self.refinement.as_mut().filter(|r|r.active()) {r.reject(status);}
        tuner.cal_command().write(|w| unsafe {w.value().bits(0)});
        self.verifying=false; self.error_cents=None; self.millivolts=0; self.status=status;
        self.statistics.clear();self.deviation=None;
    }
    pub fn toggle_verify(&mut self,tuner:&pac::TUNER_PERIPH,controls:RuntimeControls,now:u64) {
        if self.pending_profile.is_some() {self.status="ACCEPT OR DISCARD CAL FIRST";return;}
        if self.verifying {self.stop_verify(tuner,"STOPPED - OUTPUT ZERO");return;}
        if self.sweep.is_some() || controls.mode != OperatingMode::Verify {return;}
        if self.refinement.as_ref().is_some_and(|r|r.stage==crate::oscillator_calibration::refinement::Stage::Ready) {
            self.status="ACCEPT OR DISCARD FIRST";return;
        }
        self.refinement=None;
        let Some(route)=self.profile_route.filter(|_|self.profile.is_some()) else {
            self.status="NO COMPLETED CAL - VERIFY BLOCKED";return;
        };
        self.scan=if controls.verify_scan {self.profile.as_ref().and_then(|p|
            if controls.verify_points {Scan::points(p)} else {Scan::new(p)})} else {None};
        if controls.verify_scan && self.scan.is_none() {
            self.status="NO SCAN TARGETS IN RANGE";return;
        }
        self.input=route.input();self.output=route.output();
        // Starting requires a deliberate action, including after a fault/range
        // error. Never reinterpret an audio cable as incoming pitch CV.
        tuner.cal_command().write(|w| unsafe {w.value().bits(0)});
        self.verifying=true;
        let target=self.scan.as_ref().map_or(controls.target_millicents,|s|s.target);
        self.apply_target(tuner,target,now);
    }
    fn apply_target(&mut self,tuner:&pac::TUNER_PERIPH,pitch:i32,now:u64) {
        let voltage=self.operation_profile().and_then(|p| {
            if let Some(r)=self.refinement.as_ref().filter(|r|r.active()) {
                r.request(p).filter(|point|point.millicents==pitch).map(|point|point.microvolts)
            } else if let Some(check)=self.scan.as_ref().and_then(|s|s.local.as_ref()) {
                check.next().filter(|point|point.millicents==pitch).map(|point|point.microvolts)
            } else if let Some(scan)=self.scan.as_ref().filter(|s|s.points_mode) {
                p.points().get(scan.tested as usize)
                    .filter(|point|point.millicents==pitch).map(|point|point.microvolts)
            } else {p.voltage_for_pitch(pitch).ok()}
        });
        let Some(counts)=voltage.and_then(bipolar::encode_voltage) else {
            self.stop_verify(tuner,"OUT OF RANGE - ZERO");return;
        };
        self.target_millicents=pitch;
        self.average.clear();
        self.error_cents=None;
        self.statistics.clear();self.deviation=None;
        self.verify_token=self.verify_token.wrapping_add(1);
        self.previous_sequence=None;
        self.millivolts=bipolar::decode_voltage(counts).unwrap()/1000;
        self.verify_command=counts as u32 | ((self.output as u32)<<16) | (1<<18)
            | ((self.input as u32)<<19) | ((self.verify_token as u32)<<21);
        self.verify_started=now;
        self.status="APPLYING TARGET";
        tuner.cal_command().write(|w| unsafe {w.value().bits(self.verify_command)});
    }
    fn tick_verify(&mut self,tuner:&pac::TUNER_PERIPH,controls:RuntimeControls,now:u64) {
        if controls.mode != OperatingMode::Verify || controls.verify_scan!=self.scan.is_some()
            || self.scan.as_ref().is_some_and(|s|s.points_mode!=controls.verify_points) {
            self.stop_verify(tuner,"STOPPED - OUTPUT ZERO");return;
        }
        let status=tuner.cal_status().read().value().bits();
        if status&512!=0 || now<self.verify_started {
            self.stop_verify(tuner,"OUTPUT FAULT - ZERO");return;
        }
        if status&511 == (self.verify_token as u32|256) {
            if self.scan.is_none() && controls.target_millicents!=self.target_millicents {
                self.apply_target(tuner,controls.target_millicents,now);return;
            }
            self.status=if now-self.verify_started<550 {"SETTLING"} else {"CORRECTED TARGET ACTIVE"};
        } else if now-self.verify_started>=100 {
            self.stop_verify(tuner,"NO OUTPUT ACK - ZERO");return;
        }
        tuner.cal_command().write(|w| unsafe {w.value().bits(self.verify_command)});
    }
    #[inline(never)]
    pub fn toggle(&mut self, tuner:&pac::TUNER_PERIPH, controls:RuntimeControls, now:u64) {
        if self.refinement.as_ref().is_some_and(|r|r.stage==crate::oscillator_calibration::refinement::Stage::Ready) {
            self.status="ACCEPT OR DISCARD FIRST";return;
        }
        if self.verifying {self.stop_verify(tuner,"STOPPED - OUTPUT ZERO");}
        if let Some(s)=self.sweep.as_mut() { s.cancel(); return; }
        // RUN during review explicitly rescans; it never accepts the candidate.
        self.pending_profile=None;self.pending_route=None;
        self.scan=None;
        self.refinement=None;
        self.input=controls.calibration_input; self.output=controls.calibration_output;
        self.zero_error_cents=None;
        self.failure_voltage=None;
        self.failure_acquisition=None;
        self.tracking_failure=None;
        self.rejected_detector=None;
        self.rejected_verifier=None;
        let density=Density::Semitone;
        self.point_count=(2*bipolar::intervals(density)+1) as u8;self.suggested_note=None;
        self.sweep=Sweep::new(Route::new(self.input,self.output).unwrap(),density,
            Policy {settle_ms:350,point_timeout_ms:5000,
                stable_samples:5,tolerance_millicents:3000},3000,now);
        self.waiting=None; self.previous_sequence=None; self.sequence=0; self.point=0;
        self.status="STARTING AT ZERO";
        tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
        tuner.verify_channel().write(|w| unsafe { w.channel().bits(self.input) });
    }
    // Keep acquisition temporaries off the perpetual frame used during flash
    // save/recall. These operations are mutually exclusive, not nested.
    #[inline(never)]
    pub fn tick(&mut self,tuner:&pac::TUNER_PERIPH,value:ChannelMeasurement,
                controls:RuntimeControls,now:u64) {
        if self.automatic.as_ref().is_some_and(|a|a.active()) {
            self.tick_automatic(tuner,value,controls,now);return;
        }
        if self.verifying {self.tick_verification(tuner,value,controls,now);}
        else {self.tick_sweep(tuner,value,controls,now);}
    }
    fn begin_auto_check(&mut self,tuner:&pac::TUNER_PERIPH,now:u64) {
        self.refinement=None;
        self.scan=self.pending_profile.as_ref().and_then(Scan::new);
        if let Some(scan)=self.scan.as_ref() {
            let pitch=scan.target;self.verifying=true;self.apply_target(tuner,pitch,now);
        } else {self.finish_automatic(tuner,"CHECK FAILED - PRIOR PROFILE KEPT");}
    }
    /// Undo the single tentative insertion; no extra full-profile RAM copy.
    fn rollback_auto(&mut self) {
        if let Some(auto)=self.automatic.as_mut() {
            if let Some(point)=auto.undo.take() {
                if !self.pending_profile.as_mut().is_some_and(|p|p.undo_refinement(point)) {
                    self.pending_profile=None;auto.best=None;
                }
            }
            self.scan=auto.best.clone();
        }
    }
    fn finish_automatic(&mut self,tuner:&pac::TUNER_PERIPH,reason:&'static str) {
        self.rollback_auto();
        self.sweep=None;self.stop_verify(tuner,reason);self.refinement=None;
        let auto=self.automatic.as_mut().unwrap();
        auto.phase=Phase::Review;
        if auto.best.is_none() {self.pending_profile=None;self.pending_route=None;}
        if let Some(p)=self.pending_profile.as_ref() {self.point_count=p.points().len() as u8;}
    }
    #[inline(never)]
    fn tick_automatic(&mut self,tuner:&pac::TUNER_PERIPH,value:ChannelMeasurement,
                      mut controls:RuntimeControls,now:u64) {
        if self.automatic.as_ref().unwrap().expired(now) {
            self.finish_automatic(tuner,"STOPPED - CALIBRATION TIME LIMIT");return;
        }
        let phase=self.automatic.as_ref().unwrap().phase;
        if phase==Phase::Sweep {
            controls.mode=OperatingMode::Calibrator;
            controls.calibration_input=self.input;controls.calibration_output=self.output;
            self.tick_sweep(tuner,value,controls,now);
            if self.sweep.is_none() {
                if self.pending_profile.is_some() {
                    self.automatic.as_mut().unwrap().phase=Phase::Verify;
                    self.begin_auto_check(tuner,now);
                } else {self.finish_automatic(tuner,self.status);}
            }
            return;
        }
        controls.mode=OperatingMode::Verify;controls.verify_scan=true;controls.verify_points=false;
        self.tick_verification(tuner,value,controls,now);
        if self.verifying {return;}
        if phase==Phase::Refine {
            let point=self.refinement.as_ref().and_then(|r|r.ready_point());
            if let Some(point)=point {
                let candidate=self.refinement.as_mut().unwrap().take_candidate(self.pending_profile.as_ref().unwrap());
                if let Some(candidate)=candidate {
                    self.pending_profile=Some(candidate);
                    let auto=self.automatic.as_mut().unwrap();auto.undo=Some(point);auto.phase=Phase::Reverify;
                    self.begin_auto_check(tuner,now);return;
                }
            }
            self.finish_automatic(tuner,self.status);return;
        }
        if self.status!="SCAN DONE - OUTPUT ZERO" || !self.scan.as_ref().is_some_and(|s|s.complete) {
            self.finish_automatic(tuner,self.status);return;
        }
        let scan=self.scan.as_ref().unwrap();
        let auto=self.automatic.as_mut().unwrap();
        if !auto.improves(scan) {
            self.finish_automatic(tuner,"REVIEW - NO FULL-RANGE GAIN");return;
        }
        auto.undo=None;auto.best=Some(scan.clone());
        let profile=self.pending_profile.as_ref().unwrap();
        if let Some(reason)=auto.stop_reason(scan,profile.points().len()) {
            self.finish_automatic(tuner,reason);return;
        }
        match crate::oscillator_calibration::refinement::Refinement::new(profile,scan.worst_pitch) {
            Ok(r)=>{
                let pitch=r.request(profile).unwrap().millicents;
                auto.passes+=1;auto.phase=Phase::Refine;
                self.refinement=Some(r);self.verifying=true;self.apply_target(tuner,pitch,now);
            }
            Err(reason)=>self.finish_automatic(tuner,reason),
        }
    }
    // Verification/refinement must not nest under the sweep's profile-copy
    // temporaries. Keep these mutually exclusive stack frames separate.
    #[inline(never)]
    fn tick_verification(&mut self,tuner:&pac::TUNER_PERIPH,value:ChannelMeasurement,
                controls:RuntimeControls,now:u64) {
        if self.verifying {
            self.tick_verify(tuner,controls,now);
            self.error_cents=if self.verifying && self.status=="CORRECTED TARGET ACTIVE"
                && value.valid && value.qualified
                // Scan windows include the entire permitted 100 ms ACK delay
                // before the 350 ms settling interval, and reject stale ends.
                && (self.scan.is_none() || value.end_age_ms<=100)
                && now.saturating_sub(self.verify_started)>=
                    (if self.scan.is_some() {450} else {350})+value.window_age_ms as u64 {
                Some(pitch_math::semitones(value.frequency_hz,440.0)*100.0
                    -self.target_millicents as f32/1000.0)
            } else {None};
            let mut averaged=None;
            if !value.valid || !value.qualified {
                self.statistics.clear();
                self.average.clear();
                self.previous_sequence=Some(value.sequence);
            } else if self.previous_sequence!=Some(value.sequence) {
                self.previous_sequence=Some(value.sequence);
                self.statistics.observe(self.error_cents,value.sequence,now);
                if self.target_millicents<=LOW_PITCH {
                    if let Some(error)=self.error_cents {
                        averaged=self.average.observe((error*1000.0) as i32,
                            now.saturating_sub(value.window_age_ms as u64),
                            now.saturating_sub(value.end_age_ms as u64));
                    } else {self.average.clear();}
                }
            }
            // Low pitches publish at most once per cycle. Eight independent
            // observations may not fit the manual readout's 500 ms window.
            self.deviation=if self.scan.is_some() && self.target_millicents<=LOW_PITCH {
                averaged.map(|v|Summary{mean:v.mean as f32/1000.0,spread:v.spread as f32/1000.0,
                    count:crate::oscillator_calibration::averaging::WINDOWS,averaged:true})
            } else if self.scan.is_some() {
                self.statistics.summary_with_max_age(now,4000)
            } else {self.statistics.summary(now)};
            if self.verifying && self.scan.is_some() {
                // A missing/unstable signal must not leave a scan holding a
                // pitch forever. Manual VERIFY remains an explicitly held CV.
                if now.saturating_sub(self.verify_started)>=5000 {
                    self.stop_verify(tuner,"SCAN TIMEOUT - OUTPUT ZERO");
                } else if let Some(summary)=self.deviation.filter(|_|
                    self.error_cents.is_some() && value.end_age_ms<=100) {
                    if let Some(r)=self.refinement.as_mut().filter(|r|r.active()) {
                        let profile=if self.automatic.as_ref().is_some_and(|a|a.active()) {
                            self.pending_profile.as_ref().unwrap()
                        } else {self.profile.as_ref().unwrap()};
                        r.record(profile,summary);
                        if let Some(point)=r.request(profile) {
                            self.apply_target(tuner,point.millicents,now);
                        } else {
                            let reason=r.reason;self.stop_verify(tuner,reason);
                        }
                        return;
                    }
                    let scan=self.scan.as_mut().unwrap();
                    if let Some(check)=scan.local.as_mut() {
                        if check.record(summary) {
                            if let Some(point)=check.next() {
                                let target=point.millicents;
                                self.apply_target(tuner,target,now);
                            } else {self.stop_verify(tuner,"SCAN DONE - OUTPUT ZERO");}
                        }
                        return;
                    }
                    if scan.record(summary) {
                        if scan.complete {
                            if !scan.points_mode {
                                scan.local=crate::oscillator_calibration::verification_scan::LocalCheck::new(
                                    if self.automatic.as_ref().is_some_and(|a|a.active()) {
                                        self.pending_profile.as_ref().unwrap()
                                    } else {self.profile.as_ref().unwrap()},scan.worst_pitch);
                            }
                            if let Some(check)=scan.local.as_ref() {
                                let target=check.targets[0].millicents;
                                self.apply_target(tuner,target,now);
                            } else {self.stop_verify(tuner,"SCAN DONE - OUTPUT ZERO");}
                        }
                        else {
                            if scan.points_mode {
                                scan.target=self.profile.as_ref().unwrap().points()[scan.tested as usize].millicents;
                            }
                            let target=scan.target;self.apply_target(tuner,target,now);
                        }
                    }
                }
            }
            return;
        }
    }
    #[inline(never)]
    fn tick_sweep(&mut self,tuner:&pac::TUNER_PERIPH,value:ChannelMeasurement,
                controls:RuntimeControls,now:u64) {
        let Some(s)=self.sweep.as_mut() else {return;};
        if controls.mode != OperatingMode::Calibrator || controls.calibration_input != self.input
            || controls.calibration_output != self.output {s.cancel();}
        let status=tuner.cal_status().read().value().bits();
        if status & 512 != 0 {s.output_failed();}
        let sample=if self.previous_sequence != Some(value.sequence) {
            self.previous_sequence=Some(value.sequence); self.sequence+=1;
            Some(Measurement {input:self.input,sequence:self.sequence,
                window_start_ms:now.saturating_sub(value.window_age_ms as u64),
                window_end_ms:now.saturating_sub(value.end_age_ms as u64),
                millicents:if value.valid {pitch_math::millicents(value.frequency_hz,440.0)} else {0},
                qualified:value.qualified && value.valid})
        } else {None};
        let mut request=s.poll(now,sample);
        self.tracking_failure=s.tracking_failure();
        self.zero_error_cents=s.origin_error().map(|v|v as f32/1000.0);
        let acknowledged=match request {
            Request::Apply {token,..} => self.waiting==Some(token) && status&255==token as u32 && status&256!=0,
            Request::Disable {token,..} => self.waiting==Some(token) && status&255==token as u32 && status&256==0,
            _=>false,
        };
        if acknowledged {
            s.acknowledge(self.waiting.unwrap(),now);
            request=s.poll(now,None);
        }
        self.failure_voltage=s.failure_voltage();
        match request {
            Request::Apply {output,microvolts,token} => {
                self.status="SETTLING / MEASURING"; self.millivolts=microvolts/1000;
                self.point=s.point_count() as u8;
                let Some(bits)=bipolar::encode_voltage(microvolts) else {
                    s.output_failed();tuner.cal_command().write(|w|unsafe{w.value().bits(0)});return;
                };
                let command=bits as u32 | ((output as u32)<<16) | (1<<18)
                    | ((self.input as u32)<<19) | ((token as u32)<<21);
                self.sweep_command=command;
                tuner.cal_command().write(|w| unsafe {w.value().bits(command)});
                self.waiting=Some(token);
            }
            Request::Wait => {
                // Renew the current output even between fresh detector windows.
                // Re-send the exact DAC command, never reconstruct it from
                // the rounded display value (dense points have fractional mV).
                tuner.cal_command().write(|w| unsafe {w.value().bits(self.sweep_command)});
            }
            Request::Disable {output,token} => {
                self.status="RESTORING ZERO";
                tuner.cal_command().write(|w| unsafe {w.value().bits(((output as u32)<<16)|((token as u32)<<21))});
                self.waiting=Some(token);
            }
            Request::Finished(outcome) => {
                if matches!(outcome,Outcome::Failed(_)) {self.failure_acquisition=Some(s.acquisition_diagnostic());}
                let mut limited=false;
                if let Some(curve)=s.take_curve() {
                    let mut profile=Profile::new("RAM profile",bipolar::MIN_UV,bipolar::MAX_UV).unwrap();
                    for point in curve.points() {profile.push(*point).unwrap();}
                    profile.limited_low=curve.limited_low;profile.limited_high=curve.limited_high;
                    limited=profile.limited_low||profile.limited_high;
                    self.point=profile.points().len() as u8;self.point_count=self.point;
                    self.pending_profile=Some(profile);
                    self.pending_route=Route::new(self.input,self.output).ok();
                }
                self.status=match outcome {
                    Outcome::Complete if limited=>"REVIEW LIMITED RANGE - ACCEPT?",
                    Outcome::Complete=>"REVIEW RANGE - ACCEPT?",
                    Outcome::Cancelled=>"CANCELLED - OUTPUT ZERO",
                    Outcome::Failed(Failure::NoOrigin)=>"FAILED - ZERO PITCH LOST",
                    Outcome::Failed(Failure::OriginChanged)=>"FAILED - ZERO PITCH CHANGED",
                    Outcome::Failed(Failure::NotTracking)=>"FAILED - NOT TRACKING",
                    Outcome::Failed(Failure::UnstablePitch)=>"FAILED - PITCH NOT STABLE",
                    Outcome::Failed(Failure::RangeBeforeZero)=>"FAILED - RANGE ENDED BELOW ZERO",
                    _=>"FAILED - OUTPUT/CLOCK",
                };
                self.sweep=None;self.waiting=None;self.millivolts=0;
            }
        }
    }
}
