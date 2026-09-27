//! Bounded, non-blocking serial status reporting.
//!
//! Raw waveform export used to share the retired crossing detector's period
//! verifier memory. NSDF diagnostics now come from the NSDF peripheral itself,
//! so this module deliberately contains no detector or fallback capture path.
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;

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

fn write_snapshot<const N: usize>(line: &mut String<N>, packed: u32, counts_per_v: i32) {
    if let Some(uv) = snapshot_microvolts(packed, counts_per_v) {
        write!(line, " {}", uv).ok();
    } else {
        line.push_str(" X").ok();
    }
}

#[derive(Default)]
pub struct Trace {
    // Final automatic reports combine acquisition warnings, verification
    // evidence, local repeatability, quality grading and recovery history.
    // 1536 bytes was sufficient before graded policies/local checks, but a
    // complete FORGIVING report can legitimately exceed it. This extra 512 B
    // is diagnostic storage only; it does not duplicate calibration profiles
    // or detector windows.
    report: String<2048>,
    offset: usize,
    due_at: u64,
    calibration_line: String<128>,
    unstable_seen: bool,
}

impl Trace {
    pub fn with_calibration(report: Option<(i32, i32, u8)>, hardware_bits: u8) -> Self {
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

    pub fn status_due(&self, now: u64, _calibration_active: bool) -> bool {
        self.offset != 0 || now >= self.due_at
    }

    pub fn cancel(&mut self, _tuner: &pac::TUNER_PERIPH) {}

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
            self.report.push_str(self.calibration_line.as_str()).ok();
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
            write_snapshot(&mut self.report, tuner.quant_cv0().read().value().bits(), counts_per_v);
            write_snapshot(&mut self.report, tuner.quant_cv1().read().value().bits(), counts_per_v);
            write_snapshot(&mut self.report, tuner.quant_cv2().read().value().bits(), counts_per_v);
            write_snapshot(&mut self.report, tuner.quant_cv3().read().value().bits(), counts_per_v);
            self.report.push('\n').ok();
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
                if let Some(auto) = cal.automatic.as_ref() {
                    writeln!(
                        self.report,
                        "AUTO PHASE={} POLICY={} PASSES={}/8",
                        auto.label(),
                        auto.policy_label(),
                        auto.passes
                    )
                    .ok();
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
