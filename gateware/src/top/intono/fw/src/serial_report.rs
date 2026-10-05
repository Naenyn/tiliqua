//! Read-only result formatting shared by serial diagnostics and host tests.
use crate::{calibration_live::Live, pitch_units};
use core::fmt::{self, Write};

/// Kept separate so the bounded serial fallback can always retain timings
/// even when verbose detector/local-repeat diagnostics overflow its buffer.
pub fn timing(out: &mut impl Write, cal: &Live) -> fmt::Result {
    let sweep = cal.sweep_timing;
    if sweep.measured_points != 0 || sweep.missing_points != 0 {
        writeln!(out,
            "CAL SWEEP_TIMING MEASURED={} MS={} SLOW_GE_1S={} AVG16={} MISSING={} MS={}",
            sweep.measured_points, sweep.measured_ms, sweep.slow_points,
            sweep.averaged_points, sweep.missing_points, sweep.missing_ms)?;
    }
    if let Some(auto) = cal.automatic.as_ref() {
        writeln!(out, "AUTO SPEED POLICY={} SKIPPED_LOCAL_CHECKS={}",
            auto.policy_label(), auto.skipped_local_checks)?;
        let t = auto.phase_ms;
        writeln!(out, "AUTO TIME_MS ACQUIRE={} CHECK={} REFINE={} RECHECK={}",
            t[0], t[1], t[2], t[3])?;
        write!(out, "AUTO CHECK_PASSES_MS")?;
        for timing in auto.check_timings[..auto.check_timing_count as usize].iter().flatten() {
            write!(out, " {}:{}:{}/{}", timing.kind, timing.ms, timing.tested, timing.total)?;
        }
        writeln!(out, " OVERFLOW={}", auto.check_timing_overflow)?;
    }
    Ok(())
}

pub fn verification(out: &mut impl Write, cal: &Live) -> fmt::Result {
    timing(out, cal)?;
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
    if let Some(status) = cal.failure_output_status {
        writeln!(out, "CAL OUTPUT CAUSE={} STATUS_RAW=0x{:03X} TOKEN={} ACTIVE={} FAULT={}",
            cal.failure_output_cause, status, status & 255,
            status & 256 != 0, status & 512 != 0)?;
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
            "VERIFY SAME_CV_RETRY=1/1; FRESH ACQUISITION"
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
            writeln!(out, "VERIFY DETECTOR HZ={:.2}..{:.2}", crate::pitch_units::Decimal(low), crate::pitch_units::Decimal(high))?;
        }
        writeln!(out, "VERIFY SETTLED FRESH={} TARGET_NEAR={}", d.settled_fresh, d.target_near)?;
        if let Some((low, high)) = d.settled_hz_range() {
            writeln!(out, "VERIFY SETTLED_HZ={:.2}..{:.2}", crate::pitch_units::Decimal(low), crate::pitch_units::Decimal(high))?;
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
            "AUTO PHASE={} POLICY={} PASSES={}/{} STATUS={}",
            auto.label(),
            auto.policy_label(),
            auto.passes,
            crate::oscillator_calibration::automatic::MAX_PASSES,
            cal.status
        )?;
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
        if let Some((uv, cause)) = auto.last_recovery {
            writeln!(out, "AUTO LAST_RECOVERY_UV={} CAUSE={}", uv, cause)?;
            if let Some(d) = cal.recovered_verification_diagnostic.as_ref() {
                writeln!(out,
                    "AUTO RECOVERED_DETECTOR FRAMES={} VALID={} QUALIFIED={} FRESH={} WINDOW_AGE_MS={} END_AGE_MS={}",
                    d.frames, d.valid, d.qualified, d.fresh,
                    d.last_window_age_ms, d.last_end_age_ms)?;
                if let Some((low, high)) = d.hz_range() {
                    writeln!(out, "AUTO RECOVERED_HZ={:.2}..{:.2}", crate::pitch_units::Decimal(low), crate::pitch_units::Decimal(high))?;
                }
                writeln!(out, "AUTO RECOVERED_SETTLED FRESH={} TARGET_NEAR={}",
                    d.settled_fresh, d.target_near)?;
                if let Some((low, high)) = d.settled_hz_range() {
                    writeln!(out, "AUTO RECOVERED_SETTLED_HZ={:.2}..{:.2}", crate::pitch_units::Decimal(low), crate::pitch_units::Decimal(high))?;
                }
            }
            if let Some(a) = cal.recovered_verification.as_ref() {
                writeln!(out, "AUTO RECOVERED_AVG COUNT={} SEEN={} OVERLAP={} SPAN_RESETS={} GAP_RESETS={} RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",
                    a.count, a.seen, a.overlap, a.span_resets, a.gap_resets,
                    a.raw_span, a.quarter_delta, a.half_delta)?;
            }
        }
        if let Some((old, new, accepted)) = auto.last_recheck {
            writeln!(
                out,
                "AUTO RECHECK OLD_C={:+.2} NEW_C={:+.2} KEPT={}", crate::pitch_units::Decimal(old), crate::pitch_units::Decimal(new), accepted
            )?;
        }
        if let Some(uv) = auto.recheck_missing_uv {
            writeln!(out, "AUTO RECHECK_FIRST_MISSING_UV={}", uv)?;
        }
        if let Some((pitch, old, new, repeat)) = auto.last_refine {
            writeln!(
                out,
                "AUTO REFINE_TEST MC={} OLD_C={:+.2} NEW_C={:+.2} MAX_REPEAT_C={:.2}",
                pitch, crate::pitch_units::Decimal(old), crate::pitch_units::Decimal(new), crate::pitch_units::Decimal(repeat))?;
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
                "AUTO BEST_WORST_C={:+.2} TARGET_C={:.1} AIM_C={:.1} VERIFIED={}/{}", crate::pitch_units::Decimal(scan.checked_worst().1), crate::pitch_units::Decimal(auto.target_cents()), crate::pitch_units::Decimal(auto.completion_cents()),
                scan.tested,
                scan.total
            )?;
            if !auto.active() {
                write!(out, "AUTO WORST_AT=")?;
                pitch_units::write_pitch(out, scan.checked_worst().0)?;
                writeln!(out, " GRID_WORST_C={:+.2}", crate::pitch_units::Decimal(scan.worst_error))?;
                writeln!(out, " MAX_SPAN_C={:.2}", crate::pitch_units::Decimal(scan.max_spread))?;
                if let Some(pitch) = scan.max_spread_pitch {
                    write!(out, "AUTO MAX_SPREAD_AT=")?;
                    pitch_units::write_pitch(out, pitch)?;
                    writeln!(out, " SPAN_C={:.2}", crate::pitch_units::Decimal(scan.max_spread))?;
                }
                if scan.unstable_grid_mask != 0 {
                    writeln!(out, "AUTO UNSTABLE_GRID_MASK={:013X}", scan.unstable_grid_mask)?;
                }
                // Review returns early below. Keep absolute repeat errors and
                // endpoint-relative interpolation error visible before then.
                if let Some(check) = scan.local.as_ref() {
                    writeln!(out, "AUTO LOCAL TESTED={}/9", check.tested)?;
                    for index in 0..3 {
                        if let Some((mean, span, repeat)) = check.aggregate(index) {
                            writeln!(
                                out,
                                "AUTO LOCAL {} MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                                ["LOW", "HIGH", "TARGET"][index], crate::pitch_units::Decimal(mean), crate::pitch_units::Decimal(span), crate::pitch_units::Decimal(repeat))?;
                        }
                    }
                    if let Some(residual) = check.residual() {
                        writeln!(
                            out,
                            "AUTO LOCAL ENDPOINT_ADJUSTED_C={:+.2}; NOT ABSOLUTE ERROR", crate::pitch_units::Decimal(residual))?;
                    }
                }
            }
        } else if !auto.active() {
            // A rejected review has no `best`, but its completed scan is the
            // only evidence explaining why the preview cannot be accepted.
            // Report the local repeats rather than only its aggregate grade.
            if let Some(scan) = cal.scan.as_ref() {
                writeln!(out, "AUTO CANDIDATE_WORST_MC={} ERROR_C={:+.2} MAX_SPAN_C={:.2}",
                    scan.checked_worst().0, crate::pitch_units::Decimal(scan.checked_worst().1), crate::pitch_units::Decimal(scan.max_spread))?;
                writeln!(out, "AUTO CANDIDATE_CHECKED={}/{} MISSING={}; MISSING TARGETS NOT CERTIFIED",
                    scan.tested, scan.total, scan.missing)?;
                if scan.missing_grid_mask != 0 {
                    writeln!(out, "AUTO CANDIDATE_GAP_MASK={:013X}", scan.missing_grid_mask)?;
                }
                if let Some(uv) = scan.first_missing_uv {
                    writeln!(out, "AUTO CANDIDATE_FIRST_MISSING_UV={}", uv)?;
                }
                if let Some(check) = scan.local.as_ref() {
                    writeln!(out, "AUTO CANDIDATE_LOCAL TESTED={}/9 ADVICE={}",
                        check.tested, check.advice())?;
                    for index in 0..3 {
                        if let Some((mean, span, repeat)) = check.aggregate(index) {
                            writeln!(out,
                                "AUTO CANDIDATE_LOCAL {} UV={} MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                                ["LOW", "HIGH", "TARGET"][index],
                                check.targets[index].microvolts, crate::pitch_units::Decimal(mean), crate::pitch_units::Decimal(span), crate::pitch_units::Decimal(repeat))?;
                        }
                    }
                    if let Some(delta) = scan.grid_local_disagreement() {
                        writeln!(out, "AUTO CANDIDATE_GRID_LOCAL_DELTA_C={:.2}", crate::pitch_units::Decimal(delta))?;
                    }
                    // Preserve visit order: the same target is approached
                    // from alternating neighboring CVs, which distinguishes
                    // a direction-dependent response from random variation.
                    for (visit, result) in check.results.iter().enumerate() {
                        if let Some(result) = result {
                            let target = crate::oscillator_calibration::verification_scan::LocalCheck::ORDER[visit];
                            writeln!(out,
                                "AUTO CANDIDATE_LOCAL VISIT={} TARGET={} UV={} MEAN_C={:+.2} SPAN_C={:.2}",
                                visit + 1, ["LOW", "HIGH", "MID"][target],
                                check.targets[target].microvolts, crate::pitch_units::Decimal(result.mean), crate::pitch_units::Decimal(result.spread))?;
                        }
                    }
                    if let Some(residual) = check.residual() {
                        writeln!(out, "AUTO CANDIDATE_LOCAL ENDPOINT_ADJUSTED_C={:+.2}", crate::pitch_units::Decimal(residual))?;
                    }
                }
            }
        }
        if auto.active() {
            if let Some(scan) = cal.scan.as_ref() {
                writeln!(
                    out,
                    "AUTO CHECK={}/{} MISSING={} GAPS={:013X} UNSTABLE={:013X} MODE={}",
                    scan.tested,
                    scan.total,
                    scan.missing,
                    scan.missing_grid_mask,
                    scan.unstable_grid_mask,
                    if auto.regional_check {
                        "REGION"
                    } else if scan.targeted_plan().is_some() {
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
            cal.pending_quality.grade.label(), crate::pitch_units::Decimal(cal.pending_quality.worst_cents()), crate::pitch_units::Decimal(cal.pending_quality.stability_cents()),
            cal.pending_quality.acceptable()
        )?;
        if let Some(score) = cal.pending_quality.score_percent() {
            writeln!(out, "CAL REVIEW SCORE={}PCT BASIS=MAX(WORST_C,STABILITY_C) 100C=0PCT ADVISORY_ONLY", score)?;
        }
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
        if cal.pending_quality.acceptable() {
            writeln!(
                out,
                "CAL REVIEW ACCEPT=RAM RUN=RESCAN DISCARD=PRIOR; RETUNING REQUIRES RESCAN"
            )?;
            return Ok(());
        }
        if cal.can_accept_imperfect() {
            writeln!(out, "CAL REVIEW OFF TARGET; ACCEPT=KEEP AS-IS IN RAM RUN=IMPROVE DISCARD=PRIOR; RETUNING REQUIRES RESCAN")?;
        } else {
            writeln!(out, "CAL REVIEW INCOMPLETE; ACCEPT/SAVE BLOCKED; RETUNING REQUIRES RESCAN")?;
        }
        // Continue to the independent check below: the retained curve is
        // diagnostic, and its failed target is the most useful next clue.
    }
    if let Some(profile) = cal.profile.as_ref() {
        writeln!(
            out,
            "PROFILE GRADE={} ERROR_C={:.3} STABILITY_C={:.3}",
            cal.profile_quality.grade.label(), crate::pitch_units::Decimal(cal.profile_quality.worst_cents()), crate::pitch_units::Decimal(cal.profile_quality.stability_cents()))?;
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
            writeln!(out, "REFINE LOCAL_C={:+.2}", crate::pitch_units::Decimal(residual))?;
        }
        for index in 0..4 {
            if let Some((pitch, old, new, repeat)) = r.comparison(index) {
                write!(out, "REFINE TEST {} ", index + 1)?;
                pitch_units::write_pitch(out, pitch)?;
                writeln!(
                    out,
                    " OLD_C={:+.2} NEW_C={:+.2} REPEAT_C={:.2}", crate::pitch_units::Decimal(old), crate::pitch_units::Decimal(new), crate::pitch_units::Decimal(repeat))?;
            }
        }
        if r.total() > 0 && r.tested == r.total() {
            writeln!(
                out,
                "REFINE WORST_ABS_C ORIGINAL={:.2} CANDIDATE={:.2}", crate::pitch_units::Decimal(r.original_worst), crate::pitch_units::Decimal(r.candidate_worst))?;
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
                    s.count, crate::pitch_units::Decimal(s.sum / s.count as f32), crate::pitch_units::Decimal(s.first), crate::pitch_units::Decimal(s.last), crate::pitch_units::Decimal(s.high - s.low))?;
            }
            return Ok(());
        }
        writeln!(
            out,
            "VERIFY MODE={} TESTED={} TOTAL={} MISSING={} COMPLETE={} MAX_SPAN_C={:.2}",
            if scan.points_mode { "POINTS" } else { "SCAN" },
            scan.tested,
            scan.total,
            scan.missing,
            scan.complete, crate::pitch_units::Decimal(scan.max_spread))?;
        if scan.tested > 0 {
            let (pitch, error) = scan.checked_worst();
            write!(out, "VERIFY WORST_C={:+.2} AT=", crate::pitch_units::Decimal(error))?;
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
                write!(out, "VERIFY GRID_WORST_C={:+.2} AT=", crate::pitch_units::Decimal(scan.worst_error))?;
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
                                writeln!(out, "VERIFY DAC_ROUNDING_C={:+.3}", crate::pitch_units::Decimal(cents))?;
                            }
                        }
                    }
                }
            }
            for (index, error) in scan.first_errors.iter().enumerate() {
                if let Some(error) = error {
                    writeln!(out, "VERIFY P{}_C={:+.2}", index, crate::pitch_units::Decimal(*error))?;
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
                        " MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}", crate::pitch_units::Decimal(mean), crate::pitch_units::Decimal(span), crate::pitch_units::Decimal(repeat))?;
                }
            }
            if let Some(residual) = check.residual() {
                writeln!(out, "LOCAL ENDPOINT_ADJUSTED_C={:+.2}", crate::pitch_units::Decimal(residual))?;
            }
            if let Some(r) = check.residuals() {
                writeln!(out, "LOCAL PASSES_C={:+.2},{:+.2},{:+.2}", crate::pitch_units::Decimal(r[0]), crate::pitch_units::Decimal(r[1]), crate::pitch_units::Decimal(r[2]))?;
            }
            if check.tested == 9 {
                writeln!(out, "LOCAL ADVICE={}", check.advice())?;
            }
        }
    }
    if let Some(error) = cal.error_cents {
        writeln!(out, "VERIFY CURRENT_C={:+.2}", crate::pitch_units::Decimal(error))?;
    }
    if let Some(s) = cal.deviation {
        writeln!(
            out,
            "VERIFY MEAN_C={:+.2} SPAN_C={:.2} SAMPLES={} AVERAGED={}", crate::pitch_units::Decimal(s.mean), crate::pitch_units::Decimal(s.spread), s.count, s.averaged
        )?;
    }
    if let Some(error) = cal.zero_error_cents {
        writeln!(out, "CAL ZERO_CHECK_C={:+.2}", crate::pitch_units::Decimal(error))?;
    }
    Ok(())
}
