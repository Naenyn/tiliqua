//! Read-only result formatting shared by serial diagnostics and host tests.
use crate::{calibration_live::Live, pitch_units};
use core::fmt::{self, Write};

pub fn verification(out: &mut impl Write, cal: &Live) -> fmt::Result {
    let warnings = cal.scan_warnings;
    if warnings.any() {
        writeln!(
            out,
            "CAL CHARACTERIZATION_WARNINGS MISSING={} UNSTABLE={} FLAT={} DISCONTINUITIES={}",
            warnings.missing, warnings.unstable, warnings.flat, warnings.discontinuities
        )?;
    }
    if cal.period_family_corrections > 0 {
        writeln!(
            out,
            "CAL PERIOD_FAMILY_CORRECTIONS={}; TRAJECTORY_BOUNDED",
            cal.period_family_corrections
        )?;
    }
    if let Some(uv) = cal.failure_voltage {
        writeln!(out, "CAL FAILED_AT_UV={}", uv)?;
    }
    if cal
        .tracking_failure
        .as_ref()
        .is_some_and(|f| f.octave_sized_drop())
    {
        writeln!(
            out,
            "CAL HINT=OCTAVE-SIZED DROP OUTSIDE TRAJECTORY BOUND; CHECK SIGNAL"
        )?;
    }
    if cal.verify_retried {
        writeln!(
            out,
            "VERIFY FIRST_TARGET_RETRY=1/1; SAME VOLTAGE; FRESH ACQUISITION"
        )?;
    }
    if let Some(a) = cal.failure_verification.as_ref() {
        writeln!(out, "VERIFY FAILED_TARGET_MC={}", cal.target_millicents)?;
        writeln!(
            out,
            "VERIFY AVG COUNT={} SEEN={} OVERLAP={} SPAN_RESETS={} GAP_RESETS={}",
            a.count, a.seen, a.overlap, a.span_resets, a.gap_resets
        )?;
        writeln!(
            out,
            "VERIFY AVG RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",
            a.raw_span, a.quarter_delta, a.half_delta
        )?;
        write!(out, "VERIFY AVG ERRORS_MC=")?;
        for (i, value) in a.values[..a.count].iter().enumerate() {
            write!(out, "{}{}", if i == 0 { "" } else { "," }, value)?;
        }
        writeln!(out)?;
    }
    if let Some(d) = cal.failure_verification_diagnostic.as_ref() {
        writeln!(
            out,
            "VERIFY DETECTOR FRAMES={} VALID={} QUALIFIED={} FRESH={} WINDOW_AGE_MS={} END_AGE_MS={}",
            d.frames, d.valid, d.qualified, d.fresh, d.last_window_age_ms, d.last_end_age_ms
        )?;
        if let Some((low, high)) = d.hz_range() {
            writeln!(out, "VERIFY DETECTOR HZ={:.2}..{:.2}", low, high)?;
        }
    }
    if let Some(d) = cal.failure_acquisition.as_ref() {
        let a = &d.average;
        writeln!(
            out,
            "CAL ACQUIRE QUAL={} UNQUAL={} TIGHT={} AVERAGING={}",
            d.qualified, d.unqualified, d.tight_count, d.needs_average
        )?;
        writeln!(
            out,
            "CAL AVG COUNT={} SEEN={} OVERLAP={} SPAN_RESETS={} GAP_RESETS={}",
            a.count, a.seen, a.overlap, a.span_resets, a.gap_resets
        )?;
        writeln!(
            out,
            "CAL AVG RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",
            a.raw_span, a.quarter_delta, a.half_delta
        )?;
        write!(out, "CAL AVG PITCH_MC=")?;
        for (i, value) in a.values[..a.count].iter().enumerate() {
            write!(out, "{}{}", if i == 0 { "" } else { "," }, value)?;
        }
        writeln!(out)?;
    }
    if let Some(auto) = cal.automatic.as_ref() {
        writeln!(
            out,
            "AUTO PHASE={} POLICY={} PASSES={}/8 STATUS={}",
            auto.label(),
            auto.policy_label(),
            auto.passes,
            cal.status
        )?;
        let t = auto.phase_ms;
        if auto.unstable_retries > 0 {
            writeln!(out, "AUTO UNSTABLE_RETRY=1/1")?;
        }
        if auto.edge_retries > 0 {
            writeln!(
                out,
                "AUTO EDGE_RECOVERY RETRIES={}/2 LOW_TRIM={} HIGH_TRIM={} MAX_TOTAL=4",
                auto.edge_retries, auto.edge_trim_low, auto.edge_trim_high
            )?;
        }
        writeln!(
            out,
            "AUTO TIME_MS ACQUIRE={} CHECK={} REFINE={} RECHECK={}",
            t[0], t[1], t[2], t[3]
        )?;
        if let Some((old, new, accepted)) = auto.last_recheck {
            writeln!(
                out,
                "AUTO RECHECK OLD_C={:+.2} NEW_C={:+.2} KEPT={}",
                old, new, accepted
            )?;
        }
        if let Some((pitch, old, new, repeat)) = auto.last_refine {
            writeln!(
                out,
                "AUTO REFINE_TEST MC={} OLD_C={:+.2} NEW_C={:+.2} MAX_REPEAT_C={:.2}",
                pitch, old, new, repeat
            )?;
        }
        if let Some(scan) = auto.best.as_ref() {
            writeln!(
                out,
                "AUTO COVERAGE={}",
                if scan.targeted_plan().is_some() {
                    "TARGETED; UNSAMPLED PITCHES NOT CERTIFIED"
                } else {
                    "EXHAUSTIVE 50-CENT GRID"
                }
            )?;
            writeln!(
                out,
                "AUTO BEST_WORST_C={:+.2} TARGET_C={:.1} AIM_C={:.1} VERIFIED={}/{}",
                scan.checked_worst().1,
                auto.target_cents(),
                auto.completion_cents(),
                scan.tested,
                scan.total
            )?;
            if !auto.active() {
                write!(out, "AUTO WORST_AT=")?;
                pitch_units::write_pitch(out, scan.checked_worst().0)?;
                writeln!(out, " GRID_WORST_C={:+.2}", scan.worst_error)?;
                writeln!(out, " MAX_SPAN_C={:.2}", scan.max_spread)?;
                // Review returns early below. Keep absolute repeat errors and
                // endpoint-relative interpolation error visible before then.
                if let Some(check) = scan.local.as_ref() {
                    writeln!(out, "AUTO LOCAL TESTED={}/9", check.tested)?;
                    for index in 0..3 {
                        if let Some((mean, span, repeat)) = check.aggregate(index) {
                            writeln!(
                                out,
                                "AUTO LOCAL {} MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                                ["LOW", "HIGH", "TARGET"][index],
                                mean,
                                span,
                                repeat
                            )?;
                        }
                    }
                    if let Some(residual) = check.residual() {
                        writeln!(
                            out,
                            "AUTO LOCAL ENDPOINT_ADJUSTED_C={:+.2}; NOT ABSOLUTE ERROR",
                            residual
                        )?;
                    }
                }
            }
        }
        if auto.active() {
            if let Some(scan) = cal.scan.as_ref() {
                writeln!(
                    out,
                    "AUTO CHECK={}/{} MODE={}",
                    scan.tested,
                    scan.total,
                    if scan.targeted_plan().is_some() {
                        "TARGETED"
                    } else {
                        "EXHAUSTIVE"
                    }
                )?;
            }
            return Ok(());
        }
    }
    if let Some(profile) = cal.pending_profile.as_ref() {
        let points = profile.points();
        let low = points[0];
        let high = points[points.len() - 1];
        writeln!(
            out,
            "CAL REVIEW POINTS={} LOW_UV={} HIGH_UV={}",
            points.len(),
            low.microvolts,
            high.microvolts
        )?;
        writeln!(
            out,
            "CAL REVIEW GRADE={} WORST_C={:.3} STABILITY_C={:.3} ACCEPTABLE={}",
            cal.pending_quality.grade.label(),
            cal.pending_quality.worst_cents(),
            cal.pending_quality.stability_cents(),
            cal.pending_quality.acceptable()
        )?;
        if let Some(auto) = cal.automatic.as_ref() {
            writeln!(
                out,
                "CAL REVIEW EDGE_TRIM_LOW={} EDGE_TRIM_HIGH={} PARTIAL_RECOVERIES={} RECOVERED_LOW={} RECOVERED_HIGH={}",
                auto.edge_trim_low,
                auto.edge_trim_high,
                auto.partial_recoveries,
                auto.partial_recovered_sides & 1 != 0,
                auto.partial_recovered_sides & 2 != 0,
            )?;
        }
        write!(out, "CAL REVIEW LOW=")?;
        pitch_units::write_pitch(out, low.millicents)?;
        write!(out, " HIGH=")?;
        pitch_units::write_pitch(out, high.millicents)?;
        writeln!(out)?;
        writeln!(
            out,
            "CAL ADVICE={}",
            crate::oscillator_calibration::discovery::advice(profile)
        )?;
        if let Some(mv) = crate::oscillator_calibration::discovery::millivolts_per_octave(profile) {
            writeln!(
                out,
                "CAL RESPONSE MV_PER_OCTAVE={} CONVENTIONAL={}",
                mv,
                !crate::oscillator_calibration::discovery::nonstandard_response(profile)
            )?;
        }
        writeln!(
            out,
            "CAL REVIEW ACCEPT=RAM RUN=RESCAN DISCARD=PRIOR; RETUNING REQUIRES RESCAN"
        )?;
        return Ok(());
    }
    if let Some(profile) = cal.profile.as_ref() {
        writeln!(
            out,
            "PROFILE GRADE={} ERROR_C={:.3} STABILITY_C={:.3}",
            cal.profile_quality.grade.label(),
            cal.profile_quality.worst_cents(),
            cal.profile_quality.stability_cents()
        )?;
        let points = profile.points();
        if let (Some(lo), Some(hi)) = (points.first(), points.last()) {
            write!(
                out,
                "PROFILE POINTS={} LOW_UV={} LOW=",
                points.len(),
                lo.microvolts
            )?;
            pitch_units::write_pitch(out, lo.millicents)?;
            write!(out, " HIGH_UV={} HIGH=", hi.microvolts)?;
            pitch_units::write_pitch(out, hi.millicents)?;
            writeln!(out)?;
        }
    }
    if let Some(r) = cal.refinement.as_ref() {
        writeln!(out, "REFINE STATUS={}", r.reason)?;
        writeln!(
            out,
            "REFINE ACQUIRED={}/9 VALIDATED={}/{}",
            r.check.tested,
            r.tested,
            r.total()
        )?;
        if let Some(residual) = r.check.residual() {
            writeln!(out, "REFINE LOCAL_C={:+.2}", residual)?;
        }
        for index in 0..4 {
            if let Some((pitch, old, new, repeat)) = r.comparison(index) {
                write!(out, "REFINE TEST {} ", index + 1)?;
                pitch_units::write_pitch(out, pitch)?;
                writeln!(
                    out,
                    " OLD_C={:+.2} NEW_C={:+.2} REPEAT_C={:.2}",
                    old, new, repeat
                )?;
            }
        }
        if r.total() > 0 && r.tested == r.total() {
            writeln!(
                out,
                "REFINE WORST_ABS_C ORIGINAL={:.2} CANDIDATE={:.2}",
                r.original_worst, r.candidate_worst
            )?;
        }
        writeln!(
            out,
            "REFINE ORIGINAL PRESERVED; ACCEPT RAM ONLY; SAVE EXPLICIT"
        )?;
        return Ok(());
    }
    if let Some(scan) = cal.scan.as_ref() {
        if let Some(repeat) = scan.repeat_check() {
            writeln!(
                out,
                "REPEAT TESTED={}/{} COMPLETE={} SETTLE_MS=2000; CURVE UNCHANGED",
                scan.tested, scan.total, scan.complete
            )?;
            for (i, p) in repeat.targets.iter().enumerate() {
                writeln!(
                    out,
                    "REPEAT TARGET {} UV={} PITCH_MC={}",
                    i, p.microvolts, p.millicents
                )?;
            }
            for (i, s) in repeat.stats.iter().enumerate().filter(|(_, s)| s.count > 0) {
                writeln!(
                    out,
                    "REPEAT {} N={} MEAN_C={:+.2} FIRST_C={:+.2} LAST_C={:+.2} RANGE_C={:.2}",
                    [
                        "LOW_UP",
                        "LOW_DOWN",
                        "MID_UP",
                        "MID_DOWN",
                        "HIGH_UP",
                        "HIGH_DOWN",
                        "REF_ZERO"
                    ][i],
                    s.count,
                    s.sum / s.count as f32,
                    s.first,
                    s.last,
                    s.high - s.low
                )?;
            }
            return Ok(());
        }
        writeln!(
            out,
            "VERIFY MODE={} TESTED={} TOTAL={} COMPLETE={} MAX_SPAN_C={:.2}",
            if scan.points_mode { "POINTS" } else { "SCAN" },
            scan.tested,
            scan.total,
            scan.complete,
            scan.max_spread
        )?;
        if scan.tested > 0 {
            let (pitch, error) = scan.checked_worst();
            write!(out, "VERIFY WORST_C={:+.2} AT=", error)?;
            pitch_units::write_pitch(out, pitch)?;
            if scan.points_mode {
                if let Some(point) = cal
                    .profile
                    .as_ref()
                    .and_then(|p| p.points().get(scan.worst_index))
                {
                    write!(out, " STORED_UV={}", point.microvolts)?;
                }
            }
            writeln!(out)?;
            if scan.local.is_some() {
                write!(out, "VERIFY GRID_WORST_C={:+.2} AT=", scan.worst_error)?;
                pitch_units::write_pitch(out, scan.worst_pitch)?;
                writeln!(out)?;
                writeln!(out, "VERIFY RESULT={}", scan.accuracy_label())?;
            }
            if !scan.points_mode && scan.local.is_none() {
                if let Some(profile) = cal.profile.as_ref() {
                    if let Ok(uv) = profile.voltage_for_pitch(scan.worst_pitch) {
                        let commanded = crate::bipolar::encode_profile_voltage(uv)
                            .and_then(crate::bipolar::decode_voltage);
                        if let Some(commanded) = commanded {
                            writeln!(
                                out,
                                "VERIFY WORST_REQUEST_UV={} COMMAND_UV={}",
                                uv, commanded
                            )?;
                            if let Some(pair) = profile.points().windows(2).find(|p| {
                                p[0].millicents <= scan.worst_pitch
                                    && scan.worst_pitch <= p[1].millicents
                            }) {
                                for (label, point) in [("LOW", pair[0]), ("HIGH", pair[1])] {
                                    write!(
                                        out,
                                        "VERIFY BRACKET_{} UV={} PITCH=",
                                        label, point.microvolts
                                    )?;
                                    pitch_units::write_pitch(out, point.millicents)?;
                                    writeln!(out)?;
                                }
                                // Estimated rounding contribution on this segment,
                                // not a physical voltage-accuracy measurement.
                                let cents = (commanded as i64 - uv as i64) as f32
                                    * (pair[1].millicents as i64 - pair[0].millicents as i64)
                                        as f32
                                    / ((pair[1].microvolts as i64 - pair[0].microvolts as i64)
                                        as f32
                                        * 1000.0);
                                writeln!(out, "VERIFY DAC_ROUNDING_C={:+.3}", cents)?;
                            }
                        }
                    }
                }
            }
            for (index, error) in scan.first_errors.iter().enumerate() {
                if let Some(error) = error {
                    writeln!(out, "VERIFY P{}_C={:+.2}", index, error)?;
                }
            }
        }
        write!(out, "VERIFY TARGET=")?;
        pitch_units::write_pitch(out, scan.target)?;
        writeln!(out)?;
        if let Some(check) = scan.local.as_ref() {
            writeln!(out, "LOCAL CHECK TESTED={} TOTAL=9", check.tested)?;
            for index in 0..3 {
                if let Some((mean, span, repeat)) = check.aggregate(index) {
                    write!(
                        out,
                        "LOCAL {} UV={} PITCH=",
                        ["LOW", "HIGH", "TARGET"][index],
                        check.targets[index].microvolts
                    )?;
                    pitch_units::write_pitch(out, check.targets[index].millicents)?;
                    writeln!(
                        out,
                        " MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                        mean, span, repeat
                    )?;
                }
            }
            if let Some(residual) = check.residual() {
                writeln!(out, "LOCAL ENDPOINT_ADJUSTED_C={:+.2}", residual)?;
            }
            if let Some(r) = check.residuals() {
                writeln!(out, "LOCAL PASSES_C={:+.2},{:+.2},{:+.2}", r[0], r[1], r[2])?;
            }
            if check.tested == 9 {
                writeln!(out, "LOCAL ADVICE={}", check.advice())?;
            }
        }
    }
    if let Some(error) = cal.error_cents {
        writeln!(out, "VERIFY CURRENT_C={:+.2}", error)?;
    }
    if let Some(s) = cal.deviation {
        writeln!(
            out,
            "VERIFY MEAN_C={:+.2} SPAN_C={:.2} SAMPLES={} AVERAGED={}",
            s.mean, s.spread, s.count, s.averaged
        )?;
    }
    if let Some(error) = cal.zero_error_cents {
        writeln!(out, "CAL ZERO_CHECK_C={:+.2}", error)?;
    }
    Ok(())
}
