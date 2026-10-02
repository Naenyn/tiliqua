//! Bounded, non-blocking serial status reporting.
//!
//! Raw waveform export used to share the retired crossing detector's period
//! verifier memory. NSDF diagnostics now come from the NSDF peripheral itself,
//! so this module deliberately contains no detector or fallback capture path.
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;

#[cfg(intono_verbose_diagnostics)]
fn snapshot_microvolts(packed: u32, counts_per_v: i32) -> Option<i32> {
    if packed >> 31 == 0 || counts_per_v <= 0 {
        return None;
    }
    let counts = packed as u16 as i16 as i32;
    if counts.abs() >= 32760 {
        return None;
    }
    if counts_per_v == 4000 {
        Some(counts * 250)
    } else {
        i32::try_from(counts as i64 * 1_000_000 / counts_per_v as i64).ok()
    }
}

#[cfg(intono_verbose_diagnostics)]
fn write_snapshot<const N: usize>(line: &mut String<N>, packed: u32, counts_per_v: i32) {
    if let Some(uv) = snapshot_microvolts(packed, counts_per_v) {
        write!(line, " {}", uv).ok();
    } else {
        line.push_str(" X").ok();
    }
}

#[derive(Default)]
pub struct Trace {
    // Detailed reports retain their original capacity. Normal builds keep
    // only pass timings and health/status, including all 24 check timings.
    #[cfg(intono_verbose_diagnostics)]
    report: String<2048>,
    #[cfg(not(intono_verbose_diagnostics))]
    report: String<1536>,
    offset: usize,
    due_at: u64,
    #[cfg(intono_verbose_diagnostics)]
    calibration_line: String<128>,
    #[cfg(intono_verbose_diagnostics)]
    boot_line: String<192>,
    unstable_seen: bool,
    video_gaps: u16,
    background_errors: u8,
    #[cfg(intono_verbose_diagnostics)]
    frame_state: u32,
    #[cfg(intono_verbose_diagnostics)]
    published_ms: u64,
    #[cfg(intono_verbose_diagnostics)]
    preparing: bool,
    #[cfg(intono_verbose_diagnostics)]
    background_ready: bool,
}

impl Trace {
    pub fn with_calibration(report: Option<(i32, i32, u8)>, hardware_bits: u8) -> Self {
        #[cfg(intono_verbose_diagnostics)]
        {
            let mut trace = Self::default();
            if let Some((gain, zero, bits)) = report {
                write!(
                trace.calibration_line,
                "\nINTONO diagnostic link confirmed; ready for CAL.\nCAL SOURCE EEPROM OUT1 A={} B={} FBITS={} HWBITS={}\n",
                gain, zero, bits, hardware_bits
            )
            .ok();
            } else {
                write!(
                trace.calibration_line,
                "\nINTONO diagnostic link confirmed; ready for CAL.\nCAL SOURCE DEFAULT - EEPROM UNAVAILABLE HWBITS={}\n",
                hardware_bits
            )
            .ok();
            }
            trace
        }
        #[cfg(not(intono_verbose_diagnostics))]
        {
            let _ = (report, hardware_bits);
            Self::default()
        }
    }

    /// Cumulative firmware-startup timings, drained by the existing bounded UART path.
    pub fn with_boot_timings(&mut self, times: &[u32; 8]) {
        #[cfg(not(intono_verbose_diagnostics))]
        let _ = times;
        #[cfg(intono_verbose_diagnostics)]
        writeln!(self.boot_line,
            "BOOT ELAPSED_MS VIDEO={} ARC={} CAL={} CIRCLE={} LINEAR={} KEYBOARD={} EEPROM={} READY={}",
            times[0],times[1],times[2],times[3],times[4],times[5],times[6],times[7]).ok();
    }

    pub fn video_health(&mut self, gaps: u8, background_errors: u8) {
        self.video_gaps = gaps as u16;
        self.background_errors = background_errors;
    }

    pub fn display_state(&mut self, frame: u32, published: u64, preparing: bool, ready: bool) {
        #[cfg(not(intono_verbose_diagnostics))]
        let _ = (frame, published, preparing, ready);
        #[cfg(intono_verbose_diagnostics)]
        {
            self.frame_state = frame;
            self.published_ms = published;
            self.preparing = preparing;
            self.background_ready = ready;
        }
    }

    pub fn status_due(&self, now: u64, _calibration_active: bool) -> bool {
        self.offset != 0 || now >= self.due_at
    }

    pub fn note_unstable(&mut self) {
        self.unstable_seen = true;
    }

    pub fn tick(
        &mut self,
        tuner: &pac::TUNER_PERIPH,
        uart: &pac::UART0,
        now: u64,
        cal: &crate::calibration_live::Live,
        feedback: crate::runtime::ChannelMeasurement,
        counts_per_v: i32,
    ) {
        if self.offset == 0 {
            if now < self.due_at {
                return;
            }
            self.report.clear();
            #[cfg(not(intono_verbose_diagnostics))]
            {
                let _ = (tuner, feedback, counts_per_v);
                // Timing first: optional health/status must never displace it.
                crate::serial_report::timing(&mut self.report, cal).ok();
                writeln!(
                    self.report,
                    "CAL STATUS {} ACTIVE={} IN={} OUT={} MV={} POINT={}/{}",
                    cal.status,
                    cal.active(),
                    cal.input,
                    cal.output,
                    cal.millivolts,
                    cal.point,
                    cal.point_count
                )
                .ok();
                writeln!(
                    self.report,
                    "VIDEO BUFFER_GAPS={} BACKGROUND_ERRORS={}\nSTACK UNUSED_BYTES={}",
                    self.video_gaps,
                    self.background_errors,
                    crate::stack_monitor::free_bytes()
                )
                .ok();
            }
            #[cfg(intono_verbose_diagnostics)]
            {
                self.report.push_str(self.calibration_line.as_str()).ok();
                self.report.push_str(self.boot_line.as_str()).ok();
                writeln!(
                    self.report,
                    "VIDEO BUFFER_GAPS={} BACKGROUND_ERRORS={}",
                    self.video_gaps, self.background_errors
                )
                .ok();
                writeln!(
                    self.report,
                    "STACK UNUSED_BYTES={}",
                    crate::stack_monitor::free_bytes()
                )
                .ok();
                write!(
                self.report,
                "CAL STATUS {} ACTIVE={} IN={} OUT={} MV={} POINT={} COUNT={}\nNSDF UNSTABLE_SEEN={}\nCV SNAP UV",
                cal.status,
                cal.active(),
                cal.input,
                cal.output,
                cal.millivolts,
                cal.point,
                cal.point_count,
                self.unstable_seen,
            )
            .ok();
                write_snapshot(
                    &mut self.report,
                    tuner.quant_cv0().read().value().bits(),
                    counts_per_v,
                );
                write_snapshot(
                    &mut self.report,
                    tuner.quant_cv1().read().value().bits(),
                    counts_per_v,
                );
                write_snapshot(
                    &mut self.report,
                    tuner.quant_cv2().read().value().bits(),
                    counts_per_v,
                );
                write_snapshot(
                    &mut self.report,
                    tuner.quant_cv3().read().value().bits(),
                    counts_per_v,
                );
                self.report.push('\n').ok();
                writeln!(self.report, "SCAN IO CMD={:08x} ACK={:08x} NOW={} VIDEO FRAME={:08x} AGE={} PREP={} READY={}",
                cal.output_command(), tuner.cal_status().read().value().bits(), now,
                self.frame_state, now.saturating_sub(self.published_ms),
                self.preparing, self.background_ready).ok();
                if !cal.active() {
                    writeln!(self.report,
                    "TUNER MONITOR IN={} HZ={:.3} VALID={} QUALIFIED={} VPP={:.3} SEQ={} WINDOW_AGE_MS={} END_AGE_MS={}",
                    cal.input, feedback.frequency_hz, feedback.valid, feedback.qualified,
                    feedback.vpp, feedback.sequence, feedback.window_age_ms,
                    feedback.end_age_ms).ok();
                }
                if let Some(f) = cal.tracking_failure {
                    write!(
                        self.report,
                        "CAL REJECT UV={} MC={}\n",
                        f.rejected.microvolts, f.rejected.millicents
                    )
                    .ok();
                    if let Some(p) = f.neighbour {
                        write!(
                            self.report,
                            "CAL PREVIOUS UV={} MC={}\n",
                            p.microvolts, p.millicents
                        )
                        .ok();
                    }
                }
                let result = if crate::playback_visible() {
                    crate::write_playback_status(&mut self.report, feedback)
                } else {
                    crate::serial_report::verification(&mut self.report, cal)
                };
                if result.is_err() {
                    self.report.clear();
                    writeln!(self.report, "\nSERIAL REPORT TRUNCATED").ok();
                    // Emit these before optional diagnostics. Never erase the
                    // exact pass timings just because the detailed report grew.
                    crate::serial_report::timing(&mut self.report, cal).ok();
                    writeln!(
                        self.report,
                        "CAL STATUS {} ACTIVE={} POINT={}/{} MV={}",
                        cal.status,
                        cal.active(),
                        cal.point,
                        cal.point_count,
                        cal.millivolts
                    )
                    .ok();
                    if !cal.active() {
                        writeln!(self.report,
                        "TUNER MONITOR IN={} HZ={:.3} VALID={} QUALIFIED={} VPP={:.3} SEQ={} WINDOW_AGE_MS={} END_AGE_MS={}",
                        cal.input, feedback.frequency_hz, feedback.valid, feedback.qualified,
                        feedback.vpp, feedback.sequence, feedback.window_age_ms,
                        feedback.end_age_ms).ok();
                    }
                    if let Some(auto) = cal.automatic.as_ref() {
                        writeln!(
                            self.report,
                            "AUTO PHASE={} POLICY={} PASSES={}/{}",
                            auto.label(),
                            auto.policy_label(),
                            auto.passes,
                            crate::oscillator_calibration::automatic::MAX_PASSES
                        )
                        .ok();
                        if let Some(reason) = auto.review_reason {
                            writeln!(self.report, "AUTO REVIEW_REASON={}", reason).ok();
                        }
                        if let Some(scan) = auto.best.as_ref() {
                            let quality = scan.quality();
                            writeln!(
                            self.report,
                            "AUTO SUMMARY GRADE={} WORST_C={:.3} STABILITY_C={:.3} VERIFIED={}/{}",
                            quality.grade.label(),
                            quality.worst_cents(),
                            quality.stability_cents(),
                            scan.tested,
                            scan.total
                        )
                            .ok();
                            let (pitch, error) = scan.checked_worst();
                            writeln!(
                                self.report,
                                "AUTO WORST MC={} ERROR_C={:+.2} GRID_C={:+.2} SPAN_C={:.2}",
                                pitch, error, scan.worst_error, scan.max_spread
                            )
                            .ok();
                            if let Some(check) = scan.local.as_ref() {
                                for (index, label) in ["LOW", "HIGH", "TARGET"].iter().enumerate() {
                                    if let Some((mean, span, repeat)) = check.aggregate(index) {
                                        writeln!(self.report,
                                        "AUTO LOCAL {} UV={} MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                                        label, check.targets[index].microvolts,
                                        mean, span, repeat).ok();
                                    }
                                }
                                writeln!(self.report, "AUTO LOCAL ADVICE={}", check.advice()).ok();
                            }
                        } else if !auto.active() {
                            if let Some(scan) = cal.scan.as_ref() {
                                let (pitch, error) = scan.checked_worst();
                                writeln!(
                                    self.report,
                                    "AUTO CANDIDATE_WORST MC={} ERROR_C={:+.2} SPAN_C={:.2}",
                                    pitch, error, scan.max_spread
                                )
                                .ok();
                                if let Some(check) = scan.local.as_ref() {
                                    writeln!(
                                        self.report,
                                        "AUTO CANDIDATE_LOCAL TESTED={}/9 ADVICE={}",
                                        check.tested,
                                        check.advice()
                                    )
                                    .ok();
                                    for (index, label) in
                                        ["LOW", "HIGH", "TARGET"].iter().enumerate()
                                    {
                                        if let Some((mean, span, repeat)) = check.aggregate(index) {
                                            writeln!(self.report,
                                            "AUTO CANDIDATE_LOCAL {} UV={} MEAN_C={:+.2} SPAN_C={:.2} REPEAT_C={:.2}",
                                            label, check.targets[index].microvolts,
                                            mean, span, repeat).ok();
                                        }
                                    }
                                    if let Some(delta) = scan.grid_local_disagreement() {
                                        writeln!(
                                            self.report,
                                            "AUTO CANDIDATE_GRID_LOCAL_DELTA_C={:.2}",
                                            delta
                                        )
                                        .ok();
                                    }
                                    for (visit, result) in check.results.iter().enumerate() {
                                        if let Some(result) = result {
                                            let target = crate::oscillator_calibration::verification_scan::LocalCheck::ORDER[visit];
                                            writeln!(self.report,
                                            "AUTO CANDIDATE_LOCAL VISIT={} TARGET={} UV={} MEAN_C={:+.2} SPAN_C={:.2}",
                                            visit + 1, ["LOW", "HIGH", "MID"][target],
                                            check.targets[target].microvolts,
                                            result.mean, result.spread).ok();
                                        }
                                    }
                                }
                            }
                        }
                        if let Some((pitch, old, new, repeat)) = auto.last_refine {
                            writeln!(
                                self.report,
                                "AUTO LAST_REFINE MC={} OLD_C={:+.2} NEW_C={:+.2} REPEAT_C={:.2}",
                                pitch, old, new, repeat
                            )
                            .ok();
                        }
                        if let Some((old, new, kept)) = auto.last_recheck {
                            writeln!(
                                self.report,
                                "AUTO LAST_RECHECK OLD_C={:+.2} NEW_C={:+.2} KEPT={}",
                                old, new, kept
                            )
                            .ok();
                        }
                        if let Some(uv) = auto.recheck_missing_uv {
                            writeln!(self.report, "AUTO RECHECK_FIRST_MISSING_UV={}", uv).ok();
                        }
                        if let Some(a) = cal.recovered_verification.as_ref() {
                            writeln!(self.report,
                            "AUTO RECOVERED_AVG COUNT={} RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",
                            a.count, a.raw_span, a.quarter_delta, a.half_delta).ok();
                            write!(self.report, "AUTO RECOVERED_ERRORS_MC=").ok();
                            for (i, error) in a.values[..a.count].iter().enumerate() {
                                write!(self.report, "{}{}", if i == 0 { "" } else { "," }, error)
                                    .ok();
                            }
                            self.report.push('\n').ok();
                        }
                    }
                    if let Some(a) = cal.failure_verification.as_ref() {
                        writeln!(self.report,
                        "VERIFY FAILED_TARGET_MC={} COUNT={} RAW_SPAN_MC={} QUARTER_DELTA_MC={} HALF_DELTA_MC={}",
                        cal.target_millicents, a.count, a.raw_span, a.quarter_delta,
                        a.half_delta).ok();
                        write!(self.report, "VERIFY FAILED_ERRORS_MC=").ok();
                        for (i, error) in a.values[..a.count].iter().enumerate() {
                            write!(self.report, "{}{}", if i == 0 { "" } else { "," }, error).ok();
                        }
                        self.report.push('\n').ok();
                    }
                }
            }
        }
        if uart.tx_ready().read().txe().bit() {
            uart.tx_data()
                .write(|w| unsafe { w.data().bits(self.report.as_bytes()[self.offset].into()) });
            self.offset += 1;
            if self.offset == self.report.len() {
                self.offset = 0;
                self.due_at = now.saturating_add(5000);
            }
        }
    }
}
