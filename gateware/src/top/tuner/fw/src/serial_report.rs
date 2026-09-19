//! Read-only result formatting shared by serial diagnostics and host tests.
use core::fmt::{self,Write};
use crate::{calibration_live::Live,pitch_units};

pub fn verification(out:&mut impl Write,cal:&Live)->fmt::Result {
    if let Some(uv)=cal.failure_voltage {writeln!(out,"CAL FAILED_AT_UV={}",uv)?;}
    if let Some(d)=cal.failure_acquisition.as_ref() {
        let a=&d.average;
        writeln!(out,"CAL ACQUIRE QUAL={} UNQUAL={} TIGHT={} AVERAGING={}",d.qualified,d.unqualified,d.tight_count,d.needs_average)?;
        writeln!(out,"CAL AVG COUNT={} SEEN={} OVERLAP={} SPAN_RESETS={} GAP_RESETS={}",a.count,a.seen,a.overlap,a.span_resets,a.gap_resets)?;
        writeln!(out,"CAL AVG RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",a.raw_span,a.quarter_delta,a.half_delta)?;
        write!(out,"CAL AVG PITCH_MC=")?;
        for (i,value) in a.values[..a.count].iter().enumerate() {write!(out,"{}{}",if i==0 {""}else{","},value)?;}
        writeln!(out)?;
    }
    if let Some(auto)=cal.automatic.as_ref() {
        writeln!(out,"AUTO PHASE={} PASSES={}/8 STATUS={}",auto.label(),auto.passes,cal.status)?;
        if let Some(scan)=auto.best.as_ref() {
            writeln!(out,"AUTO BEST_WORST_C={:+.2} TARGET_C=2.0 VERIFIED={}/{}",scan.worst_error,scan.tested,scan.total)?;
        }
        if auto.active() {
            if let Some(scan)=cal.scan.as_ref() {writeln!(out,"AUTO CHECK={}/{}",scan.tested,scan.total)?;}
            return Ok(());
        }
    }
    if let Some(profile)=cal.pending_profile.as_ref() {
        let points=profile.points();let low=points[0];let high=points[points.len()-1];
        writeln!(out,"CAL REVIEW POINTS={} LOW_UV={} HIGH_UV={}",points.len(),low.microvolts,high.microvolts)?;
        write!(out,"CAL REVIEW LOW=")?;pitch_units::write_pitch(out,low.millicents)?;
        write!(out," HIGH=")?;pitch_units::write_pitch(out,high.millicents)?;writeln!(out)?;
        writeln!(out,"CAL ADVICE={}",crate::oscillator_calibration::discovery::advice(profile))?;
        writeln!(out,"CAL REVIEW ACCEPT=RAM RUN=RESCAN DISCARD=PRIOR; RETUNING REQUIRES RESCAN")?;
        return Ok(());
    }
    if let Some(profile)=cal.profile.as_ref() {
        let points=profile.points();
        if let (Some(lo),Some(hi))=(points.first(),points.last()) {
            write!(out,"PROFILE POINTS={} LOW_UV={} LOW=",points.len(),lo.microvolts)?;
            pitch_units::write_pitch(out,lo.millicents)?;
            write!(out," HIGH_UV={} HIGH=",hi.microvolts)?;
            pitch_units::write_pitch(out,hi.millicents)?;
            writeln!(out)?;
        }
    }
    if let Some(r)=cal.refinement.as_ref() {
        writeln!(out,"REFINE STATUS={}",r.reason)?;
        writeln!(out,"REFINE ACQUIRED={}/9 VALIDATED={}/{}",r.check.tested,r.tested,r.total())?;
        if let Some(residual)=r.check.residual() {writeln!(out,"REFINE LOCAL_C={:+.2}",residual)?;}
        for index in 0..4 {
            if let Some((pitch,old,new,repeat))=r.comparison(index) {
                write!(out,"REFINE TEST {} ",index+1)?;pitch_units::write_pitch(out,pitch)?;
                writeln!(out," OLD_C={:+.2} NEW_C={:+.2} REPEAT_C={:.2}",old,new,repeat)?;
            }
        }
        if r.total()>0 && r.tested==r.total() {
            writeln!(out,"REFINE WORST_ABS_C ORIGINAL={:.2} CANDIDATE={:.2}",r.original_worst,r.candidate_worst)?;
        }
        writeln!(out,"REFINE ORIGINAL PRESERVED; ACCEPT RAM ONLY; SAVE EXPLICIT")?;
        return Ok(());
    }
    if let Some(scan)=cal.scan.as_ref() {
        writeln!(out,"VERIFY MODE={} TESTED={} TOTAL={} COMPLETE={} MAX_SPAN_C={:.2}",
            if scan.points_mode {"POINTS"} else {"SCAN"},scan.tested,scan.total,scan.complete,scan.max_spread)?;
        if scan.tested>0 {
            write!(out,"VERIFY WORST_C={:+.2} AT=",scan.worst_error)?;
            pitch_units::write_pitch(out,scan.worst_pitch)?;
            if scan.points_mode {
                if let Some(point)=cal.profile.as_ref().and_then(|p|p.points().get(scan.worst_index)) {
                    write!(out," STORED_UV={}",point.microvolts)?;
                }
            }
            writeln!(out)?;
            if !scan.points_mode && scan.local.is_none() {
                if let Some(profile)=cal.profile.as_ref() {
                    if let Ok(uv)=profile.voltage_for_pitch(scan.worst_pitch) {
                        let commanded=crate::bipolar::encode_voltage(uv).and_then(crate::bipolar::decode_voltage);
                        if let Some(commanded)=commanded {
                            writeln!(out,"VERIFY WORST_REQUEST_UV={} COMMAND_UV={}",uv,commanded)?;
                            if let Some(pair)=profile.points().windows(2).find(|p|
                                p[0].millicents<=scan.worst_pitch && scan.worst_pitch<=p[1].millicents) {
                                for (label,point) in [("LOW",pair[0]),("HIGH",pair[1])] {
                                    write!(out,"VERIFY BRACKET_{} UV={} PITCH=",label,point.microvolts)?;
                                    pitch_units::write_pitch(out,point.millicents)?;
                                    writeln!(out)?;
                                }
                                // Estimated rounding contribution on this segment,
                                // not a physical voltage-accuracy measurement.
                                let cents=(commanded as i64-uv as i64) as f32
                                    *(pair[1].millicents as i64-pair[0].millicents as i64) as f32
                                    /((pair[1].microvolts as i64-pair[0].microvolts as i64) as f32*1000.0);
                                writeln!(out,"VERIFY DAC_ROUNDING_C={:+.3}",cents)?;
                            }
                        }
                    }
                }
            }
            for (index,error) in scan.first_errors.iter().enumerate() {
                if let Some(error)=error {writeln!(out,"VERIFY P{}_C={:+.2}",index,error)?;}
            }
        }
        write!(out,"VERIFY TARGET=")?;
        pitch_units::write_pitch(out,scan.target)?;
        writeln!(out)?;
        if let Some(check)=scan.local.as_ref() {
            writeln!(out,"LOCAL CHECK TESTED={} TOTAL=9",check.tested)?;
            for index in 0..3 {
                if let Some((mean,span,repeat))=check.aggregate(index) {
                    write!(out,"LOCAL {} UV={} PITCH=",["LOW","HIGH","TARGET"][index],check.targets[index].microvolts)?;
                    pitch_units::write_pitch(out,check.targets[index].millicents)?;
                    writeln!(out," MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",mean,span,repeat)?;
                }
            }
            if let Some(residual)=check.residual() {writeln!(out,"LOCAL ENDPOINT_ADJUSTED_C={:+.2}",residual)?;}
            if let Some(r)=check.residuals() {writeln!(out,"LOCAL PASSES_C={:+.2},{:+.2},{:+.2}",r[0],r[1],r[2])?;}
            if check.tested==9 {writeln!(out,"LOCAL ADVICE={}",check.advice())?;}
        }
    }
    if let Some(error)=cal.error_cents {writeln!(out,"VERIFY CURRENT_C={:+.2}",error)?;}
    if let Some(s)=cal.deviation {
        writeln!(out,"VERIFY MEAN_C={:+.2} SPAN_C={:.2} SAMPLES={} AVERAGED={}",s.mean,s.spread,s.count,s.averaged)?;
    }
    if let Some(error)=cal.zero_error_cents {writeln!(out,"CAL ZERO_CHECK_C={:+.2}",error)?;}
    Ok(())
}
