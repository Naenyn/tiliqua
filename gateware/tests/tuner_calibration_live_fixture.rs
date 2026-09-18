//! Host integration of the real live adapter with simulated CSR acknowledgments.
#[path="../src/top/tuner/fw/src/scale.rs"] mod scale;
#[path="../src/top/tuner/fw/src/note_pattern.rs"] mod note_pattern;
#[path="../src/top/tuner/fw/src/pitch_math.rs"] mod pitch_math;
#[path="../src/top/tuner/fw/src/pitch_verification.rs"] mod pitch_verification;
#[path="../src/top/tuner/fw/src/calibration.rs"] mod oscillator_calibration;
#[path="../src/top/tuner/fw/src/calibration_live.rs"] mod calibration_live;
#[path="../src/top/tuner/fw/src/serial_report.rs"] mod serial_report;
#[path="../src/top/tuner/fw/src/pitch_units.rs"] mod pitch_units;
#[path="../src/top/tuner/fw/src/nsdf_publish.rs"] mod nsdf_publish;
#[path="../src/top/tuner/fw/src/nsdf_sequence.rs"] mod nsdf_sequence;
// The same bipolar controller and signed conversion used by the live firmware.
#[path="../src/top/tuner/fw/src/calibration/bipolar.rs"] mod bipolar;
#[path="../src/top/tuner/fw/src/calibration/bipolar_sweep.rs"] mod bipolar_sweep;
#[path="../src/top/tuner/fw/src/calibration/bipolar_storage.rs"] mod bipolar_storage;
mod runtime {
    #[derive(Clone,Copy,PartialEq)] pub enum OperatingMode {Tuner,Calibrator,Verify}
    #[derive(Clone,Copy)] pub struct RuntimeControls {pub mode:OperatingMode,pub calibration_input:u8,pub calibration_output:u8,pub target_millicents:i32,pub verify_scan:bool,pub verify_points:bool}
    #[derive(Clone,Copy,Default)] pub struct ChannelMeasurement {pub sequence:u16,pub window_age_ms:u32,pub end_age_ms:u32,pub valid:bool,pub frequency_hz:f32,pub qualified:bool}
}
#[allow(non_camel_case_types)]
mod pac {
    use core::cell::Cell;
    #[derive(Default)] pub struct TUNER_PERIPH {pub command:Cell<u32>, pub status:Cell<u32>,channel:Cell<u32>}
    pub struct Reg<'a>(&'a Cell<u32>);
    pub struct Writer(u32);
    pub struct Reader(u32);
    impl Writer {pub fn value(&mut self)->&mut Self{self} pub fn channel(&mut self)->&mut Self{self}
        pub unsafe fn bits<T:TryInto<u32>>(&mut self,n:T)->&mut Self{self.0=n.try_into().ok().unwrap();self}}
    impl Reader {pub fn value(&self)->&Self{self} pub fn bits(&self)->u32{self.0}}
    impl Reg<'_> {pub fn write(&self,f:impl FnOnce(&mut Writer)->&mut Writer){let mut w=Writer(0);f(&mut w);self.0.set(w.0);}
        pub fn read(&self)->Reader{Reader(self.0.get())}}
    impl TUNER_PERIPH {
        pub fn cal_command(&self)->Reg<'_>{Reg(&self.command)}
        pub fn cal_status(&self)->Reg<'_>{Reg(&self.status)}
        pub fn verify_channel(&self)->Reg<'_>{Reg(&self.channel)}
        pub fn ack(&self){let c=self.command.get();self.status.set(((c>>21)&255)|(((c>>18)&1)<<8));}
    }
}

#[cfg(test)] mod tests {
    use super::*;
    #[test] fn nsdf_window_and_generation_handoff_completes_sweep() {
        let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
        let mut identity=nsdf_sequence::Sequence::default();
        let empty=nsdf_publish::Frame{mhz:0,count:0,completed:0,request_ms:4,qualified:false};
        let mut native=empty;let mut low=empty;let mut generation=0;
        live.toggle(&p,c,0);
        for tick in 1..30000u64 {
            let now=tick*10;p.ack();
            // Approximately the measured per-bank cadence; UI reads repeat
            // each frame many times and must not create extra observations.
            if tick%9==0 {
                generation+=1;
                let volts=p.command.get() as u16 as i16 as f64/4000.0;
                let mhz=(440000.0*2.0f64.powf(volts)) as u32;
                native=nsdf_publish::Frame{mhz,count:generation,completed:now,request_ms:4,
                    qualified:(600000..=20000000).contains(&mhz)};
                low=nsdf_publish::Frame{qualified:(20000..=1500000).contains(&mhz),..native};
            }
            let pitch=nsdf_publish::display(native,low,now);
            let sequence=identity.observe(pitch.source,pitch.generation);
            live.tick(&p,ChannelMeasurement{sequence:sequence.unwrap_or(0),
                frequency_hz:pitch.mhz as f32/1000.0,valid:sequence.is_some(),qualified:sequence.is_some(),
                window_age_ms:pitch.window_age_ms,end_age_ms:pitch.end_age_ms},c,now);
            if !live.active(){break;}
        }
        assert!(live.pending_profile.is_some(),"{}",live.status);
        assert!(!live.active());
        assert!(live.pending_profile.as_ref().unwrap().points().len()>100);
        assert_eq!(p.command.get()&(1<<18),0);
        p.ack();live.accept_scan(&p);assert!(live.pending_profile.is_none());
        for (pass,points) in [true,false].iter().enumerate() {
            let mut verify=c;verify.mode=OperatingMode::Verify;
            verify.verify_scan=true;verify.verify_points=*points;
            let start=(pass as u64+1)*400000;
            live.toggle_verify(&p,verify,start);assert!(live.verifying,"{}",live.status);
            for tick in 1..30000u64 {
                let now=start+tick*10;p.ack();
                if tick%9==0 {
                    generation+=1;
                    let volts=p.command.get() as u16 as i16 as f64/4000.0;
                    let mhz=(440000.0*2.0f64.powf(volts)) as u32;
                    native=nsdf_publish::Frame{mhz,count:generation,completed:now,request_ms:4,
                        qualified:(600000..=20000000).contains(&mhz)};
                    low=nsdf_publish::Frame{qualified:(20000..=1500000).contains(&mhz),..native};
                }
                let pitch=nsdf_publish::display(native,low,now);
                let sequence=identity.observe(pitch.source,pitch.generation);
                live.tick(&p,ChannelMeasurement{sequence:sequence.unwrap_or(0),
                    frequency_hz:pitch.mhz as f32/1000.0,valid:sequence.is_some(),qualified:sequence.is_some(),
                    window_age_ms:pitch.window_age_ms,end_age_ms:pitch.end_age_ms},verify,now);
                if !live.verifying {break;}
            }
            assert_eq!(live.status,"SCAN DONE - OUTPUT ZERO");
            assert!(live.scan.as_ref().unwrap().complete);
            assert_eq!(p.command.get(),0);
        }
    }
    #[test] fn completed_scan_requires_review_and_keeps_prior_until_accept() {
        for accept in [false,true] {
            let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
            let old=live.profile.as_ref().unwrap().points().to_vec();
            live.toggle(&p,c,0);let mut now=0;
            for seq in 0..10000u16 {
                now+=20;p.ack();let v=p.command.get() as u16 as i16 as f64/4000.0;
                live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                    valid:true,qualified:true,frequency_hz:(357.8*2.0f64.powf(v)) as f32},c,now);
                if !live.active(){break;}
            }
            assert!(live.pending_profile.is_some());assert!(!live.active());
            assert_eq!(live.profile.as_ref().unwrap().points(),old);
            assert_eq!(p.command.get()&(1<<18),0);
            let mut verify=c;verify.mode=OperatingMode::Verify;
            live.toggle_verify(&p,verify,now);assert!(!live.verifying);
            let mut report=String::new();serial_report::verification(&mut report,&live).unwrap();
            assert!(report.contains("CAL REVIEW POINTS=121"));
            assert!(report.contains("RETUNING REQUIRES RESCAN"));
            if accept {
                p.status.set(256);live.accept_scan(&p);
                assert!(live.pending_profile.is_some());
                p.status.set(0);live.accept_scan(&p);
                assert!(live.pending_profile.is_none());
                assert_ne!(live.profile.as_ref().unwrap().points(),old);
                assert_eq!(live.status,"ACCEPTED IN RAM - SAVE PROFILE");
            } else {
                live.discard_scan();assert!(live.pending_profile.is_none());
                assert_eq!(live.profile.as_ref().unwrap().points(),old);
            }
        }
    }
    use runtime::*;
    fn controls()->RuntimeControls{RuntimeControls{mode:OperatingMode::Calibrator,calibration_input:2,calibration_output:3,target_millicents:6000000,verify_scan:false,verify_points:false}}
    #[test] fn serial_reports_match_points_and_scan_results_without_changing_them() {
        for points_mode in [false,true] {
            let mut live=ready();
            let profile=live.profile.as_ref().unwrap();
            let mut scan=if points_mode {
                oscillator_calibration::verification_scan::Scan::points(profile).unwrap()
            } else {oscillator_calibration::verification_scan::Scan::new(profile).unwrap()};
            scan.tested=scan.total;scan.complete=true;
            scan.worst_error=-1.27;scan.worst_pitch=7200000;scan.worst_index=1;
            scan.max_spread=1.80;scan.first_errors=[Some(0.0),Some(-0.07)];
            live.scan=Some(scan);
            let mut out=String::new();serial_report::verification(&mut out,&live).unwrap();
            assert!(out.contains(if points_mode {"VERIFY MODE=POINTS"} else {"VERIFY MODE=SCAN"}));
            assert!(out.contains("COMPLETE=true MAX_SPAN_C=1.80"));
            assert!(out.contains("VERIFY WORST_C=-1.27 AT=C5 +0.0c"));
            assert_eq!(out.contains("STORED_UV=800000"),points_mode);
            assert!(out.contains("VERIFY P1_C=-0.07"));
            assert!(out.contains("PROFILE POINTS=3 LOW_UV=0 LOW=C4 +0.0c"));
            if !points_mode {
                assert!(out.contains("VERIFY WORST_REQUEST_UV=800000 COMMAND_UV=800000"));
                assert!(out.contains("VERIFY BRACKET_LOW UV=0 PITCH=C4 +0.0c"));
                assert!(out.contains("VERIFY BRACKET_HIGH UV=800000 PITCH=C5 +0.0c"));
                assert!(out.contains("VERIFY DAC_ROUNDING_C=+0.000"));
            }
            assert!(out.len()<768,"reserve status space in the fixed 1024-byte serial buffer");
            assert_eq!(live.scan.as_ref().unwrap().worst_error,-1.27);
        }
        let mut out=String::new();serial_report::verification(&mut out,&calibration_live::Live::new()).unwrap();
        assert!(out.is_empty());
    }
    #[test] fn serial_rounding_is_signed_and_an_unstarted_scan_has_no_worst_result() {
        let mut live=ready();
        let mut scan=oscillator_calibration::verification_scan::Scan::new(live.profile.as_ref().unwrap()).unwrap();
        live.scan=Some(scan);
        let mut out=String::new();serial_report::verification(&mut out,&live).unwrap();
        assert!(out.contains("TESTED=0"));assert!(!out.contains("WORST_C="));
        scan=live.scan.take().unwrap();scan.tested=1;scan.worst_pitch=6000050;
        live.scan=Some(scan);out.clear();serial_report::verification(&mut out,&live).unwrap();
        assert!(out.contains("WORST_REQUEST_UV=33 COMMAND_UV=0"));
        assert!(out.contains("DAC_ROUNDING_C=-0.049") || out.contains("DAC_ROUNDING_C=-0.050"));
        live.scan.as_mut().unwrap().worst_pitch=6000300;
        out.clear();serial_report::verification(&mut out,&live).unwrap();
        assert!(out.contains("WORST_REQUEST_UV=200 COMMAND_UV=250"));
        assert!(out.contains("DAC_ROUNDING_C=+0.075"));
    }
    fn ready()->calibration_live::Live {
        use oscillator_calibration::*;
        let mut live=calibration_live::Live::new();
        let mut profile=Profile::new("nonlinear",0,2000000).unwrap();
        for (microvolts,millicents) in [(0,6000000),(800000,7200000),(2000000,8400000)] {
            profile.push(Point{microvolts,millicents}).unwrap();
        }
        live.profile=Some(profile);live.profile_route=Some(Route::new(1,2).unwrap());live
    }
    fn refinement_ready()->calibration_live::Live {
        use oscillator_calibration::{Profile,Point,verification_scan::{Scan,LocalCheck},deviation::Summary};
        let mut live=ready();let mut profile=Profile::new("curved",-100000,200000).unwrap();
        for uv in [-100000,0,100000,200000] {profile.push(Point{microvolts:uv,millicents:6000000+uv}).unwrap();}
        let mut scan=Scan::new(&profile).unwrap();scan.complete=true;scan.tested=scan.total;scan.worst_pitch=6050000;
        let mut local=LocalCheck::new(&profile,6050000).unwrap();
        for _ in 0..9 {local.record(Summary{mean:0.0,spread:0.0,count:8});}
        scan.local=Some(local);live.profile=Some(profile);live.scan=Some(scan);live
    }
    fn refinement_measurement(command:u32,n:u16)->ChannelMeasurement {
        let uv=bipolar::decode_voltage((command&65535) as u16).unwrap();
        let x=uv as f64/100000.0;
        let mc=6000000.0+uv as f64-if (0..=100000).contains(&uv) {8000.0*x*(1.0-x)} else {0.0};
        ChannelMeasurement{frequency_hz:(440.0*2.0f64.powf((mc/100000.0-69.0)/12.0)) as f32,
            valid:true,qualified:true,sequence:n,window_age_ms:180,end_age_ms:1}
    }
    #[test] fn live_refinement_compares_then_requires_explicit_accept_or_discard() {
        for accept in [false,true] {
            let mut live=refinement_ready();let original=live.profile.as_ref().unwrap().points().to_vec();
            let p=pac::TUNER_PERIPH::default();let mut c=controls();c.mode=OperatingMode::Verify;c.verify_scan=true;
            live.start_refinement(&p,c,0);assert!(live.active());
            live.accept_refinement(&p);assert_eq!(live.profile.as_ref().unwrap().points(),original);
            for n in 1..4000u16 {
                p.ack();assert_eq!((p.command.get()>>16)&3,2);assert_eq!((p.command.get()>>19)&3,1);
                live.tick(&p,refinement_measurement(p.command.get(),n),c,n as u64*20);
                assert_eq!(live.profile.as_ref().unwrap().points(),original);
                if !live.active() {break;}
            }
            assert!(!live.active());assert_eq!(p.command.get(),0);
            let r=live.refinement.as_ref().unwrap();assert_eq!(r.stage,oscillator_calibration::refinement::Stage::Ready);
            assert!(r.candidate_worst<r.original_worst);
            let mut report=String::new();serial_report::verification(&mut report,&live).unwrap();
            assert!(report.contains("REFINE WORST_ABS_C"));assert!(report.len()<768);
            live.accept_refinement(&p); // stop command not yet acknowledged
            assert_eq!(live.profile.as_ref().unwrap().points(),original);
            p.ack();
            live.toggle_verify(&p,c,100000);assert!(!live.active());assert!(live.refinement.is_some());
            if accept {
                live.accept_refinement(&p);assert_eq!(live.profile.as_ref().unwrap().points().len(),original.len()+1);
                assert!(live.scan.is_none());assert_eq!(live.status,"REFINED IN RAM - SAVE PROFILE");
            } else {
                live.discard_refinement(&p);assert_eq!(live.profile.as_ref().unwrap().points(),original);
            }
            assert!(live.refinement.is_none());assert_eq!(p.command.get(),0);
        }
    }
    #[test] fn refinement_failure_paths_stop_output_and_keep_original() {
        for late in [false,true] {for scenario in 0..5 {
            let mut live=refinement_ready();let original=live.profile.as_ref().unwrap().points().to_vec();
            let p=pac::TUNER_PERIPH::default();let mut c=controls();c.mode=OperatingMode::Verify;c.verify_scan=true;
            live.start_refinement(&p,c,0);let mut injected=false;
            for n in 1..4000u16 {
                let fail=!late || live.refinement.as_ref().unwrap().stage==oscillator_calibration::refinement::Stage::Validate;
                p.ack();let mut m=refinement_measurement(p.command.get(),n);
                if fail {
                    injected=true;
                    match scenario {
                        0=>{m.valid=false;m.qualified=false;},
                        1=>c.mode=OperatingMode::Tuner,
                        2=>p.status.set(512),
                        3=>{live.discard_refinement(&p);break;},
                        _=>p.status.set(0),
                    }
                }
                live.tick(&p,m,c,n as u64*20);if !live.active() {break;}
            }
            assert!(injected);assert!(!live.active());assert_eq!(p.command.get(),0);
            live.accept_refinement(&p);assert_eq!(live.profile.as_ref().unwrap().points(),original);
        }}
    }
    #[test] fn verify_requires_a_completed_profile_in_every_mode() {
        for (scan,points) in [(false,false),(true,false),(true,true)] {
            for dangling_route in [false,true] {
                let mut live=calibration_live::Live::new();
                if dangling_route {live.profile_route=ready().profile_route;}
                let p=pac::TUNER_PERIPH::default();let mut c=controls();
                c.mode=OperatingMode::Verify;c.verify_scan=scan;c.verify_points=points;
                live.toggle_verify(&p,c,0);
                assert!(!live.active());assert_eq!(p.command.get(),0);
                assert_eq!(live.status,"NO COMPLETED CAL - VERIFY BLOCKED");
            }
        }
    }
    #[test] fn recall_restores_route_without_arming_and_rejects_replacement_while_running() {
        use oscillator_calibration::{storage,Route};
        let source=ready();let mut bytes=[0;storage::MAX_BYTES];
        let n=storage::encode(source.profile.as_ref().unwrap(),Route::new(3,0).unwrap(),48,"Generate 3",&mut bytes).unwrap();
        let mut live=calibration_live::Live::new();let p=pac::TUNER_PERIPH::default();
        assert!(live.recall(storage::decode(&bytes[..n]).unwrap()));
        assert!(!live.active());assert_eq!(p.command.get(),0);
        assert_eq!((live.input,live.output),(3,0));assert_eq!(live.profile.as_ref().unwrap().name(),"Generate 3");
        let mut c=controls();c.mode=OperatingMode::Verify;live.toggle_verify(&p,c,0);
        assert!(live.active());assert!(!live.recall(storage::decode(&bytes[..n]).unwrap()));
        assert!(live.active());assert_eq!((p.command.get()>>16)&3,0);
    }
    #[test] fn verify_interpolates_every_semitone_and_intermediate_cents_on_original_route() {
        let mut c=controls();c.mode=OperatingMode::Verify;
        for pitch in (6000000..=8400000).step_by(25000) {
            let mut live=ready();let p=pac::TUNER_PERIPH::default();
            c.target_millicents=pitch;
            live.toggle_verify(&p,c,0);assert!(live.active());p.ack();
            let uv=live.profile.as_ref().unwrap().voltage_for_pitch(pitch).unwrap();
            assert_eq!(p.command.get()&65535,((uv+125)/250) as u32);
            assert_eq!((p.command.get()>>16)&3,2);
            assert_eq!((p.command.get()>>19)&3,1);
            live.tick(&p,ChannelMeasurement::default(),c,20);
            live.toggle_verify(&p,c,40);assert!(!live.active());assert_eq!(p.command.get(),0);
        }
    }
    #[test] fn verification_scan_finishes_all_half_notes_without_mutating_profile() {
        let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=controls();
        c.mode=OperatingMode::Verify;c.verify_scan=true;
        // Manual controls do not steer a running automatic scan.
        c.target_millicents=1200000;
        let original=live.profile.as_ref().unwrap().points().to_vec();
        live.toggle_verify(&p,c,0);assert!(live.verifying);
        let mut previous_target=0;let mut targets=Vec::new();
        for n in 1..4000u16 {
            let target=live.target_millicents;
            if target!=previous_target {targets.push(target);previous_target=target;}
            let uv=live.profile.as_ref().unwrap().voltage_for_pitch(target).unwrap();
            assert_eq!(p.command.get()&65535,((uv+125)/250) as u32);
            assert_eq!((p.command.get()>>16)&3,2);
            assert_eq!((p.command.get()>>19)&3,1);
            p.ack();
            let m=ChannelMeasurement{frequency_hz:(440.0f64*2.0f64.powf((target as f64/100000.0-69.0+0.0075)/12.0)) as f32,
                valid:true,qualified:true,sequence:n,window_age_ms:180,end_age_ms:1};
            live.tick(&p,m,c,n as u64*20);
            if !live.verifying {break;}
        }
        assert_eq!(live.status,"SCAN DONE - OUTPUT ZERO");assert_eq!(p.command.get(),0);
        let scan=live.scan.as_ref().unwrap();assert!(scan.complete);
        assert_eq!((scan.tested,scan.total),(49,49));
        assert!((scan.worst_error-0.75).abs()<0.01);
        let mut expected=(6000000..=8400000).step_by(50000).collect::<Vec<_>>();
        let check=scan.local.as_ref().unwrap();
        expected.extend(oscillator_calibration::verification_scan::LocalCheck::ORDER.iter().map(|&i|check.targets[i].millicents));
        expected.dedup();
        assert_eq!(targets,expected);assert_eq!(check.tested,9);
        assert!(check.residual().unwrap().abs()<0.02);
        let mut report=String::new();serial_report::verification(&mut report,&live).unwrap();
        assert!(report.contains("LOCAL CHECK TESTED=9 TOTAL=9"));
        assert!(report.contains("LOCAL ENDPOINT_ADJUSTED_C="));
        assert!(report.len()<768);
        assert_eq!(live.profile.as_ref().unwrap().points(),original);
        live.tick(&p,ChannelMeasurement::default(),c,90000);
        assert!(!live.active());assert_eq!(p.command.get(),0);
    }
    #[test] fn verification_scan_times_out_on_missing_stale_cached_or_unstable_pitch() {
        for scenario in 0..5 {
            let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=controls();
            c.mode=OperatingMode::Verify;c.verify_scan=true;live.toggle_verify(&p,c,0);
            for n in 1..=250u16 {
                p.ack();
                let cents=if scenario==4 && n%2==0 {10.0} else {0.0};
                let mut m=ChannelMeasurement{frequency_hz:440.0*2.0f32.powf((-9.0+cents/100.0)/12.0),
                    valid:true,qualified:true,sequence:n,window_age_ms:180,end_age_ms:1};
                match scenario {
                    0=>m.valid=false,
                    1=>m.window_age_ms=6000,
                    2=>m.sequence=0,
                    3=>m.end_age_ms=101,
                    _=>{},
                }
                live.tick(&p,m,c,n as u64*20);
            }
            assert_eq!(live.status,"SCAN TIMEOUT - OUTPUT ZERO","scenario {scenario}");
            assert_eq!(p.command.get(),0);assert!(!live.active());
            assert_eq!(live.scan.as_ref().unwrap().tested,0);
        }
    }
    #[test] fn local_followup_timeout_and_leaving_verify_stop_output_without_curve_edits() {
        for fail_after in [0,6] {
        for cancel in [false,true] {
            let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=controls();
            c.mode=OperatingMode::Verify;c.verify_scan=true;
            let original=live.profile.as_ref().unwrap().points().to_vec();
            live.toggle_verify(&p,c,0);let mut saw_local=false;
            for n in 1..8000u16 {
                let local=live.scan.as_ref().and_then(|s|s.local.as_ref()).is_some_and(|c|c.tested>=fail_after);
                saw_local|=local;
                if local && cancel {c.mode=OperatingMode::Tuner;}
                p.ack();
                let hz=(440.0f64*2.0f64.powf((live.target_millicents as f64/100000.0-69.0)/12.0)) as f32;
                live.tick(&p,ChannelMeasurement{frequency_hz:hz,valid:!local,qualified:!local,
                    sequence:n,window_age_ms:180,end_age_ms:1},c,n as u64*20);
                if !live.verifying {break;}
            }
            assert!(saw_local);assert!(!live.active());assert_eq!(p.command.get(),0);
            assert_eq!(live.status,if cancel {"STOPPED - OUTPUT ZERO"} else {"SCAN TIMEOUT - OUTPUT ZERO"});
            assert_eq!(live.profile.as_ref().unwrap().points(),original);
            assert!(live.scan.as_ref().unwrap().local.as_ref().unwrap().residual().is_none());
        }
        }
    }
    #[test] fn stored_point_scan_replays_exact_zero_and_dense_counts_and_reports_endpoint_bias() {
        use oscillator_calibration::{Profile,Point,Route,plan};
        for dense in [false,true] {
            let (voltages,count)=plan::plan(dense);
            let mut profile=Profile::new("endpoint test",0,2000000).unwrap();
            for uv in &voltages[..count] {
                // Fractional starting pitch reproduces a profile whose first
                // in-range half-note is only a few millivolts above zero.
                profile.push(Point{microvolts:*uv,millicents:6540000+(*uv as i64*1200000/1000000) as i32}).unwrap();
            }
            let original=profile.points().to_vec();
            let mut live=calibration_live::Live::new();
            live.profile=Some(profile);live.profile_route=Some(Route::new(1,2).unwrap());
            let p=pac::TUNER_PERIPH::default();let mut c=controls();
            c.mode=OperatingMode::Verify;c.verify_scan=true;c.verify_points=true;
            live.toggle_verify(&p,c,0);
            for n in 1..3000u16 {
                let index=live.scan.as_ref().unwrap().tested as usize;
                assert_eq!(p.command.get()&65535,(voltages[index]/250) as u32);
                assert_eq!(live.target_millicents,original[index].millicents);
                let error=if index==0 {-5.0} else {0.0};
                p.ack();
                let m=ChannelMeasurement{frequency_hz:(440.0f64*2.0f64.powf(
                    (live.target_millicents as f64/100000.0-69.0+error/100.0)/12.0)) as f32,
                    valid:true,qualified:true,sequence:n,window_age_ms:180,end_age_ms:1};
                live.tick(&p,m,c,n as u64*20);
                if !live.verifying {break;}
            }
            let scan=live.scan.as_ref().unwrap();assert!(scan.complete);
            assert_eq!(scan.tested as usize,count);assert_eq!(scan.worst_index,0);
            assert!((scan.first_errors[0].unwrap()+5.0).abs()<0.01);
            assert!(scan.first_errors[1].unwrap().abs()<0.01);
            assert_eq!(p.command.get(),0);assert_eq!(live.profile.as_ref().unwrap().points(),original);
            live.toggle_verify(&p,c,70000);assert!(live.verifying);
            c.verify_points=false;p.ack();live.tick(&p,ChannelMeasurement::default(),c,70020);
            assert!(!live.verifying);assert_eq!(p.command.get(),0);
        }
    }
    #[test] fn background_scan_ignores_navigation_but_explicit_stop_still_works() {
        let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut started=controls();
        started.mode=OperatingMode::Verify;started.verify_scan=true;
        live.toggle_verify(&p,started,0);p.ack();
        let mut viewed=started;viewed.mode=OperatingMode::Tuner;viewed.verify_scan=false;
        viewed.calibration_input=3;viewed.calibration_output=3;
        let active=calibration_live::background_controls(started,viewed,true);
        live.tick(&p,ChannelMeasurement::default(),active,120);
        assert!(live.active());assert_ne!(p.command.get()&(1<<18),0);
        live.toggle_verify(&p,started,140);assert!(!live.active());assert_eq!(p.command.get(),0);
        let mut sweep=calibration_live::Live::new();started=controls();
        sweep.toggle(&p,started,0);p.ack();
        let active=calibration_live::background_controls(started,viewed,false);
        sweep.tick(&p,ChannelMeasurement::default(),active,20);p.ack();
        sweep.tick(&p,ChannelMeasurement::default(),active,40);
        assert!(sweep.active());assert_eq!(sweep.input,started.calibration_input);
        assert_eq!(sweep.output,started.calibration_output);
    }
    #[test] fn verification_scan_cancels_on_exit_mode_change_output_fault_or_second_run() {
        for scenario in 0..6 {
            let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=controls();
            c.mode=OperatingMode::Verify;c.verify_scan=true;
            live.toggle_verify(&p,c,if scenario==5 {100} else {0});p.ack();
            match scenario {
                0=>c.mode=OperatingMode::Tuner,
                1=>c.verify_scan=false,
                2=>p.status.set(512),
                3=>p.status.set(0),
                4=>live.toggle_verify(&p,c,20),
                _=>{},
            }
            let now=if scenario==5 {20} else {120};
            live.tick(&p,ChannelMeasurement::default(),c,now);
            assert!(!live.active(),"scenario {scenario}");assert_eq!(p.command.get(),0);
            assert!(!live.scan.as_ref().unwrap().complete);
        }
    }
    #[test] fn verify_requires_explicit_start_and_fails_closed() {
        let mut c=controls();c.mode=OperatingMode::Verify;
        let p=pac::TUNER_PERIPH::default();let mut live=calibration_live::Live::new();
        live.toggle_verify(&p,c,0);assert!(!live.active());assert_eq!(p.command.get(),0);
        for scenario in 0..6 {
            let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=c;
            live.tick(&p,ChannelMeasurement::default(),c,0);assert_eq!(p.command.get(),0);
            live.toggle_verify(&p,c,0);p.ack();
            match scenario {
                0=>c.target_millicents=5999999,
                1=>c.target_millicents=8400001,
                2=>c.mode=OperatingMode::Tuner,
                3=>p.status.set(512),
                4=>p.status.set(0),
                _=>c.mode=OperatingMode::Calibrator,
            }
            live.tick(&p,ChannelMeasurement::default(),c,120);
            assert!(!live.active(),"scenario {scenario}");assert_eq!(p.command.get(),0);
            c.mode=OperatingMode::Verify;c.target_millicents=7200000;
            live.tick(&p,ChannelMeasurement::default(),c,140);
            assert!(!live.active());assert_eq!(p.command.get(),0);
        }
    }
    #[test] fn verify_reports_only_fresh_settled_qualified_pitch() {
        let mut live=ready();let p=pac::TUNER_PERIPH::default();let mut c=controls();c.mode=OperatingMode::Verify;
        live.toggle_verify(&p,c,0);p.ack();
        let mut m=ChannelMeasurement{frequency_hz:440.0*2.0f32.powf(-9.0/12.0),valid:true,qualified:true,
            window_age_ms:180,..Default::default()};
        live.tick(&p,m,c,540);assert!(live.error_cents.is_none());
        live.tick(&p,m,c,560);assert!(live.error_cents.unwrap().abs()<0.001);
        m.qualified=false;live.tick(&p,m,c,580);assert!(live.error_cents.is_none());
        m.qualified=true;m.window_age_ms=600;live.tick(&p,m,c,600);assert!(live.error_cents.is_none());
        c.target_millicents=7200000;live.tick(&p,m,c,620);
        assert!(live.error_cents.is_none());assert_eq!(p.command.get()&65535,3200);
        p.ack();c.target_millicents=7800000;live.tick(&p,m,c,640);
        assert_eq!(p.command.get()&65535,5600);
    }
    #[test] fn calibrate_then_verify_crosses_a4_without_conversion_bias() {
        for base_hz in [110.0f32,267.9,357.8] {
            let p=pac::TUNER_PERIPH::default();let mut live=calibration_live::Live::new();let mut c=controls();
            live.toggle(&p,c,0);let mut now=0;
            for n in 0..6000u16 {
                now+=20;p.ack();
                let volts=p.command.get() as u16 as i16 as f64/4000.0;
                let m=ChannelMeasurement{sequence:n,window_age_ms:180,end_age_ms:1,valid:true,
                    frequency_hz:(base_hz as f64*2.0f64.powf(volts)) as f32,qualified:true};
                live.tick(&p,m,c,now);
                if !live.active(){break;}
            }
            assert_eq!(live.status,"REVIEW RANGE - ACCEPT?");live.accept_scan(&p);
            let expected_base=69.0+12.0*(base_hz as f64/440.0).log2();
            let points=live.profile.as_ref().unwrap().points();
            assert!((points[0].millicents as f64/1000.0-(expected_base-60.0)*100.0).abs()<0.003);
            let first=((points[0].millicents+24999)/25000)*25000;
            let last=points.last().unwrap().millicents;
            c.mode=OperatingMode::Verify;
            for pitch in (first..=last).step_by(25000) {
                c.target_millicents=pitch;live.toggle_verify(&p,c,now);
                assert!(live.verifying);
                let volts=p.command.get() as u16 as i16 as f64/4000.0;
                let actual_hz=base_hz as f64*2.0f64.powf(volts);
                let physical_error=(69.0+12.0*(actual_hz/440.0).log2())*100.0-pitch as f64/1000.0;
                // Half a DAC count is 0.15 cents at ideal 1 V/oct.
                assert!(physical_error.abs()<0.16,"base {base_hz}, pitch {pitch}: {physical_error}");
                for _ in 0..30 {
                    now+=20;p.ack();
                    let m=ChannelMeasurement{frequency_hz:actual_hz as f32,valid:true,qualified:true,
                        window_age_ms:180,end_age_ms:1,..Default::default()};
                    live.tick(&p,m,c,now);
                }
                assert!((live.error_cents.unwrap() as f64-physical_error).abs()<0.003);
                live.toggle_verify(&p,c,now);p.ack();
            }
        }
    }
    #[test] fn dense_sweep_keeps_exact_fractional_mv_outputs_and_suggests_in_range_note() {
        use bipolar::{Density,Direction};
        {
            let p=pac::TUNER_PERIPH::default();let mut live=calibration_live::Live::new();let mut c=controls();
            live.toggle(&p,c,0);
            c.target_millicents=20000000; // Force an in-range suggestion.
            let density=Density::Semitone;
            let intervals=bipolar::intervals(density);
            let count=intervals*2+1;
            let mut commands=std::collections::BTreeMap::new();
            let mut now=0;
            for seq in 0..6000u16 {
                p.ack();now+=20;
                let command=p.command.get();
                if command&(1<<18)!=0 {
                    let token=(command>>21)&255;
                    if let Some(previous)=commands.insert(token,command) {
                        assert_eq!(previous,command,"heartbeat changed token {token}");
                    }
                }
                let v=command as u16 as i16 as f64/4000.0;
                let m=ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,valid:true,qualified:true,
                    frequency_hz:(357.8*2.0f64.powf(v)) as f32};
                live.tick(&p,m,c,now);
                if !live.active(){break;}
            }
            assert_eq!(live.status,"REVIEW RANGE - ACCEPT?");live.accept_scan(&p);assert_eq!(p.command.get()&(1<<18),0);
            let profile=live.profile.as_ref().unwrap();assert_eq!(profile.points().len(),count);
            for (i,point) in profile.points().iter().enumerate() {
                let expected=if i<intervals {bipolar::voltage(density,Direction::Down,intervals-i)}
                    else {bipolar::voltage(density,Direction::Up,i-intervals)};
                assert_eq!(Some(point.microvolts),expected);
            }
            let note=live.take_suggested_note().unwrap();
            assert!(live.profile.as_ref().unwrap().voltage_for_pitch(note as i32*100000).is_ok());
            assert!(live.take_suggested_note().is_none());
            // Choosing the suggestion never starts an output by itself.
            assert!(!live.active());
        }
    }
    #[test] fn verification_statistics_do_not_adjust_voltage_and_reset_on_target_change() {
        let p=pac::TUNER_PERIPH::default();let mut live=ready();let mut c=controls();c.mode=OperatingMode::Verify;
        live.toggle_verify(&p,c,0);p.ack();let command=p.command.get();
        for seq in 0..16 {
            let cents=if seq%2==0 {-1.0} else {1.0};
            let m=ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,valid:true,qualified:true,
                frequency_hz:(440.0*2.0f64.powf((-900.0+cents)/1200.0)) as f32};
            live.tick(&p,m,c,600+seq as u64*20);assert_eq!(p.command.get(),command);
        }
        let summary=live.deviation.unwrap();assert_eq!(summary.count,16);
        assert!(summary.mean.abs()<0.003);assert!((summary.spread-2.0).abs()<0.003);
        c.target_millicents=7200000;live.tick(&p,ChannelMeasurement::default(),c,940);
        assert!(live.deviation.is_none());
    }
    #[test] fn live_sweep_completes_restores_and_keeps_previous_on_cancel() {
        let p=pac::TUNER_PERIPH::default();let mut live=calibration_live::Live::new();let c=controls();
        live.toggle(&p,c,0);p.ack();
        let mut now=0;
        for n in 0..6000u16 {
            now+=20;p.ack();
            let volts=p.command.get() as u16 as i16 as f32/4000.0;
            let m=ChannelMeasurement{sequence:n,window_age_ms:180,end_age_ms:1,valid:true,
                frequency_hz:110.0*2.0f32.powf(volts),qualified:true};
            live.tick(&p,m,c,now);
            if !live.active(){break;}
        }
        assert!(!live.active());assert_eq!(live.status,"REVIEW RANGE - ACCEPT?");live.accept_scan(&p);
        assert_eq!(p.command.get()&(1<<18),0);
        assert_eq!(live.profile.as_ref().unwrap().points().len(),121);
        let last=live.profile.as_ref().unwrap().points()[8].millicents;
        let route=live.profile_route;
        let mut new_route=c;new_route.calibration_input=0;new_route.calibration_output=0;
        live.toggle(&p,new_route,now);p.ack();live.toggle(&p,new_route,now);
        live.tick(&p,ChannelMeasurement::default(),c,now+20);p.ack();
        live.tick(&p,ChannelMeasurement::default(),c,now+40);
        assert!(!live.active());assert_eq!(live.status,"CANCELLED - OUTPUT ZERO");
        assert_eq!(live.profile.as_ref().unwrap().points()[8].millicents,last);
        assert_eq!(live.profile_route,route);
    }
    #[test] fn route_change_and_output_fault_cannot_complete() {
        for fault in [false,true] {
            let p=pac::TUNER_PERIPH::default();let mut live=calibration_live::Live::new();let mut c=controls();
            live.toggle(&p,c,0);p.ack();
            live.tick(&p,ChannelMeasurement::default(),c,20);p.ack();
            if fault {p.status.set(512);} else {c.mode=OperatingMode::Tuner;}
            live.tick(&p,ChannelMeasurement::default(),c,40);
            assert_eq!(p.command.get()&(1<<18),0);p.ack();
            live.tick(&p,ChannelMeasurement::default(),c,60);
            assert!(!live.active());assert!(live.profile.is_none());
        }
    }
    #[test] fn low_frequency_scan_collects_eight_distinct_slow_readings() {
        for period_ms in [100u64,250,450] {
            let p=pac::TUNER_PERIPH::default();let mut live=ready();let mut c=controls();
            c.mode=OperatingMode::Verify;c.verify_scan=true;
            live.toggle_verify(&p,c,0);
            for now in (20..5000).step_by(20) {
                p.ack();
                let target=live.target_millicents;
                live.tick(&p,ChannelMeasurement{sequence:(now/period_ms) as u16,
                    window_age_ms:(period_ms+now%period_ms+2) as u32,
                    end_age_ms:(now%period_ms+1) as u32,valid:true,qualified:true,
                    frequency_hz:(440.0*2.0f64.powf((target as f64/100000.0-69.0)/12.0)) as f32},c,now);
                if live.scan.as_ref().unwrap().tested>0 {break;}
            }
            assert!(live.verifying,"period {period_ms}: {}",live.status);
            assert_eq!(live.scan.as_ref().unwrap().tested,1,"period {period_ms}");
        }
    }
    #[test] fn ascending_scan_retries_transient_octave_drop_without_inserting_it() {
        let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
        live.toggle(&p,c,0);let mut started=None;let mut saw_rejection=false;
        for seq in 0..10000u16 {
            let now=(seq as u64+1)*20;p.ack();
            let v=p.command.get() as u16 as i16 as f64/4000.0;
            if v==3.0 && started.is_none() {started=Some(now);}
            let transient=v==3.0 && started.map_or(false,|t|now-t<1600);
            live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                valid:true,qualified:true,frequency_hz:(440.0*2.0f64.powf(v-if transient {1.0} else {0.0})) as f32},c,now);
            saw_rejection|=live.tracking_failure.is_some();
            if !live.active(){break;}
        }
        assert!(saw_rejection);assert_eq!(live.status,"REVIEW RANGE - ACCEPT?");live.accept_scan(&p);
        assert!(live.tracking_failure.is_none());
        let point=live.profile.as_ref().unwrap().points().iter().find(|p|p.microvolts==3000000).unwrap();
        assert!((point.millicents-10500000).abs()<3);
        assert_eq!(p.command.get()&(1<<18),0);
    }
    #[test] fn digital_oscillator_lower_cv_and_upper_pitch_limits_produce_usable_profile() {
        let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
        live.toggle(&p,c,0);
        for seq in 0..10000u16 {
            let now=(seq as u64+1)*20;p.ack();
            let v=p.command.get() as u16 as i16 as f64/4000.0;
            let hz=(1000.0*2.0f64.powf(v.max(-4.0))).min(10000.0);
            live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                valid:true,qualified:true,frequency_hz:hz as f32},c,now);
            if !live.active(){break;}
        }
        assert!(!live.active());assert_eq!(live.status,"REVIEW LIMITED RANGE - ACCEPT?");live.accept_scan(&p);
        assert!(live.tracking_failure.is_none());
        let points=live.profile.as_ref().unwrap().points();
        assert_eq!(points[0].microvolts,-4000000);
        assert_eq!(points.last().unwrap().microvolts,3250000);
        assert!(points.windows(2).all(|p|p[0].millicents<p[1].millicents));
        assert_eq!(p.command.get()&(1<<18),0);
        // Independently evaluate every half-semitone target against the model,
        // including DAC quantization, rather than only replaying stored points.
        let profile=live.profile.as_ref().unwrap();
        let plan=oscillator_calibration::verification_scan::Scan::new(profile).unwrap();
        for index in 0..plan.total {
            let target=plan.target+index as i32*50000;
            let uv=profile.voltage_for_pitch(target).unwrap();
            let actual_uv=bipolar::decode_voltage(bipolar::encode_voltage(uv).unwrap()).unwrap();
            let hz=(1000.0*2.0f64.powf((actual_uv as f64/1e6).max(-4.0))).min(10000.0);
            let actual=6900000.0+1200000.0*(hz/440.0).log2();
            assert!((actual-target as f64).abs()<200.0,"target {target}: {} cents",(actual-target as f64)/1000.0);
        }
        assert!(profile.voltage_for_pitch(12300000).is_err(),"do not promise interpolation through the clipped endpoint");
    }
    #[test] fn saturated_endpoint_reproduces_reported_seven_cent_interpolation_error() {
        use oscillator_calibration::{Profile,Point};
        let mut profile=Profile::new("clipped",0,5000000).unwrap();
        for uv in [3166750,3250000,3333250] {
            let hz=(1000.0*2.0f64.powf(uv as f64/1e6)).min(10000.0);
            profile.push(Point{microvolts:uv,millicents:pitch_math::millicents(hz as f32,440.0)}).unwrap();
        }
        let target=12300000; // D#9, represented internally in millicents.
        let uv=profile.voltage_for_pitch(target).unwrap();
        let hz=(1000.0*2.0f64.powf(uv as f64/1e6)).min(10000.0);
        let error=(6900000.0+1200000.0*(hz/440.0).log2()-target as f64)/1000.0;
        assert!((error-7.62).abs()<0.1,"observed endpoint mechanism: {error} cents");
    }
    #[test] fn tracking_failure_retains_rejected_and_neighbour_points_after_zero_restore() {
        for down in [false,true] {
            let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
            let old=live.profile.as_ref().unwrap().points().to_vec();
            live.toggle(&p,c,0);
            let mut end=0;
            for seq in 0..40000u16 {
                let now=(seq as u64+1)*20;end=now;p.ack();
                let v=p.command.get() as u16 as i16 as f64/4000.0;
                let measured=if down && v>=-0.5 && v<0.0 {-0.58325} else if !down && v>3.0 {v-1.0} else {v};
                let valid=v>=-1.0;
                live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                    valid,qualified:valid,frequency_hz:(440.0*2.0f64.powf(measured)) as f32},c,now);
                if !live.active(){break;}
            }
            assert_eq!(live.status,"FAILED - NOT TRACKING");
            assert_eq!(p.command.get()&(1<<18),0);
            assert_eq!(live.profile.as_ref().unwrap().points(),old);
            let failure=live.tracking_failure.unwrap();let previous=failure.neighbour.unwrap();
            if down {
                assert_eq!(failure.rejected.microvolts,-500000);
                assert_eq!(previous.microvolts,-583250);
                assert_eq!(failure.rejected.millicents,previous.millicents);
            } else {
                assert_eq!(failure.rejected.microvolts,3083250);
                assert_eq!(previous.microvolts,3000000);
                assert!((failure.rejected.millicents-previous.millicents+1100100).abs()<3);
            }
            live.tick(&p,ChannelMeasurement::default(),c,end+20);
            assert_eq!(live.tracking_failure.unwrap().rejected.microvolts,failure.rejected.microvolts);
            live.toggle(&p,c,end+40);assert!(live.tracking_failure.is_none());
        }
    }
    #[test] fn zero_recheck_waits_for_recovery_but_rejects_persistent_drift() {
        for persistent in [false,true] {
            let p=pac::TUNER_PERIPH::default();let mut live=ready();let c=controls();
            let old=live.profile.as_ref().unwrap().points().to_vec();
            live.toggle(&p,c,0);
            let mut previous_v=0.0;let mut return_at=None;
            for seq in 0..40000u16 {
                let now=(seq as u64+1)*20;p.ack();
                let v=p.command.get() as u16 as i16 as f64/4000.0;
                if previous_v>0.0 && v==0.0 {return_at=Some(now);}
                previous_v=v;
                let biased=v==0.0 && return_at.map_or(false,|t|persistent||now-t<1500);
                let valid=(-1.0..=2.0).contains(&v);
                live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                    valid,qualified:valid,
                    frequency_hz:(440.0*2.0f64.powf(v+if biased {8.0/1200.0} else {0.0})) as f32},c,now);
                if !live.active(){break;}
            }
            assert!(!live.active());assert_eq!(p.command.get()&(1<<18),0);
            if persistent {
                assert_eq!(live.status,"FAILED - ZERO PITCH CHANGED");
                assert!((live.zero_error_cents.unwrap()-8.0).abs()<0.02);
                assert_eq!(live.profile.as_ref().unwrap().points(),old);
            } else {
                assert_eq!(live.status,"REVIEW LIMITED RANGE - ACCEPT?");
                assert!(live.zero_error_cents.unwrap().abs()<0.02);
            }
        }
    }
    #[test] fn limited_bipolar_sweep_rechecks_origin_and_verifies_negative_saved_points() {
        for lose_origin in [false,true] {
            let p=pac::TUNER_PERIPH::default();let mut live=ready();let mut c=controls();
            let old=live.profile.as_ref().unwrap().points().to_vec();
            live.toggle(&p,c,0);let mut hit_edge=false;let mut now=0;
            for seq in 0..40000u16 {
                now+=20;p.ack();let v=p.command.get() as u16 as i16 as f64/4000.0;
                if v > 2.0 {hit_edge=true;}
                let valid=(-1.0..=2.0).contains(&v) && !(lose_origin&&hit_edge);
                live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                    valid,qualified:valid,frequency_hz:(440.0*2.0f64.powf(v)) as f32},c,now);
                if !live.active(){break;}
            }
            assert!(!live.active());assert_eq!(p.command.get()&(1<<18),0);
            if lose_origin {
                assert_eq!(live.status,"FAILED - ZERO PITCH LOST");
                assert_eq!(live.profile.as_ref().unwrap().points(),old);continue;
            }
            assert_eq!(live.status,"REVIEW LIMITED RANGE - ACCEPT?");live.accept_scan(&p);
            let profile=live.profile.as_ref().unwrap();
            assert!(profile.limited_low&&profile.limited_high);
            assert_eq!(profile.points().first().unwrap().microvolts,-1000000);
            assert_eq!(profile.points().last().unwrap().microvolts,2000000);
            c.mode=OperatingMode::Verify;c.verify_scan=true;c.verify_points=true;
            live.toggle_verify(&p,c,now);
            assert_eq!(p.command.get() as u16 as i16,-4000);
            for seq in 0..6000u16 {
                now+=20;p.ack();let v=p.command.get() as u16 as i16 as f64/4000.0;
                live.tick(&p,ChannelMeasurement{sequence:seq,window_age_ms:180,end_age_ms:1,
                    valid:true,qualified:true,frequency_hz:(440.0*2.0f64.powf(v)) as f32},c,now);
                if !live.verifying {break;}
            }
            assert_eq!(live.status,"SCAN DONE - OUTPUT ZERO");
            let scan=live.scan.as_ref().unwrap();assert_eq!(scan.tested,37);
            assert!(scan.worst_error.abs()<0.01);
        }
    }
}
