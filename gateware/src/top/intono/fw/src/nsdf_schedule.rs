//! Continuous acquisition for tuner display and diagnostics. No DAC writes.
//! Latest-value storage is bounded; a blocked UART cannot hold the score engine.
#[cfg(tuner_nsdf_telemetry)]
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;
#[cfg(tuner_nsdf_wave_diag)]
type Pending = String<448>;
#[cfg(all(not(tuner_nsdf_wave_diag), tuner_nsdf_telemetry))]
type Pending = String<512>;
#[cfg(not(tuner_nsdf_telemetry))]
type Pending = String<0>;
#[path = "nsdf_publish.rs"]
mod publish;
#[path = "nsdf_resolve.rs"]
mod resolve;
#[path = "nsdf_sequence.rs"]
mod sequence;
#[path = "nsdf_sampling.rs"]
mod sampling;
pub use sequence::Sequence;

#[derive(Clone, Copy)]
struct Latest {
    count: u32,
    #[cfg(tuner_nsdf_telemetry)]
    seq: u32,
    mhz: u32,
    #[cfg(tuner_nsdf_telemetry)]
    first_mhz: u32,
    #[cfg(tuner_nsdf_telemetry)]
    cycles: u32,
    #[cfg(tuner_nsdf_telemetry)]
    work: u32,
    dt: u32,
    done: u64,
    raw: bool,
    guard: bool,
    valid: bool,
}
impl Latest {
    const EMPTY: Self = Self {
        count: 0,
        #[cfg(tuner_nsdf_telemetry)]
        seq: 0,
        mhz: 0,
        #[cfg(tuner_nsdf_telemetry)]
        first_mhz: 0,
        #[cfg(tuner_nsdf_telemetry)]
        cycles: 0,
        #[cfg(tuner_nsdf_telemetry)]
        work: 0,
        dt: 0,
        done: 0,
        raw: false,
        guard: false,
        valid: false,
    };
}
pub struct Scheduler {
    latest: [Latest; 8],
    pending: Pending,
    offset: usize,
    slot: u8,
    sampling: sampling::Sampling,
    #[cfg(tuner_nsdf_telemetry)]
    report: u8,
    active: bool,
    due: u64,
    started: u64,
    #[cfg(tuner_nsdf_telemetry)]
    report_due: u64,
    #[cfg(tuner_nsdf_telemetry)]
    faults: u32,
    #[cfg(tuner_nsdf_telemetry)]
    baseline: [(u32, bool, u32, u64); 4],
    #[cfg(tuner_nsdf_wave_diag)]
    wave_mhz: u32,
    #[cfg(tuner_nsdf_wave_diag)]
    wave_crossings: u16,
    #[cfg(tuner_nsdf_wave_diag)]
    wave_seq: u32,
}
// Also checked by the embedded compiler with the real heapless buffer layout.
const _: () = assert!(core::mem::size_of::<Scheduler>() <= 1024);
impl Scheduler {
    /// Independent rising-zero-crossing estimate from the immutable native
    /// frame. Diagnostic only: never participates in published pitch or CAL.
    #[cfg(tuner_nsdf_wave_diag)]
    fn wave_period_mhz() -> (u32, u16) {
        let nsdf = unsafe { &*pac::NSDF_PERIPH::ptr() };
        let mut previous = 0_i32;
        let mut first = 0_u32;
        let mut last = 0_u32;
        let mut crossings = 0_u16;
        for index in 0..674_u32 {
            nsdf.address()
                .write(|w| unsafe { w.value().bits((1024 | index) as u16) });
            let _ = nsdf.data().read(); // Settle the synchronous sample RAM.
            let current = nsdf.data().read().value().bits() as i32;
            if index != 0 && previous <= 0 && current > 0 {
                let denominator = (current - previous) as u32;
                let fraction = ((-previous as u32) << 16) / denominator;
                let position = ((index - 1) << 16) + fraction;
                if crossings == 0 {
                    first = position;
                }
                last = position;
                crossings += 1;
            }
            previous = current;
        }
        if crossings < 4 || last <= first {
            return (0, crossings);
        }
        let mhz = (192000_u64 * 1000 * (crossings - 1) as u64 * 65536
            / (last - first) as u64) as u32;
        (mhz, crossings)
    }
    pub fn fast(&self) -> bool {
        true
    }
    pub fn ui_period_ms(&self, _idle_tuner: bool, normal: u64) -> u64 {
        normal
    }
    pub fn new() -> Self {
        Self {
            latest: [Latest::EMPTY; 8],
            pending: String::new(),
            offset: 0,
            slot: 0,
            sampling: sampling::Sampling::new(),
            #[cfg(tuner_nsdf_telemetry)]
        report: 0,
            active: false,
            due: 2000,
            started: 0,
            #[cfg(tuner_nsdf_telemetry)]
        report_due: 2000,
            #[cfg(tuner_nsdf_telemetry)]
        faults: 0,
            #[cfg(tuner_nsdf_telemetry)]
        baseline: [(0, false, u32::MAX, 0); 4],
            #[cfg(tuner_nsdf_wave_diag)]
            wave_mhz: 0,
            #[cfg(tuner_nsdf_wave_diag)]
            wave_crossings: 0,
            #[cfg(tuner_nsdf_wave_diag)]
            wave_seq: 0,
        }
    }
    pub fn observe_baseline(
        &mut self,
        input: u8,
        hz: f32,
        qualified: bool,
        end_age: u32,
        now: u64,
    ) {
        #[cfg(tuner_nsdf_telemetry)]
        if let Some(slot) = self.baseline.get_mut(input as usize) {
            *slot = ((hz * 1000.0) as u32, qualified, end_age, now);
        }
    }
    fn selected(&self, input: u8, now: u64, settled: bool) -> publish::Pitch {
        if input >= 4 {
            return publish::Pitch::NONE;
        }
        let frame = |r: Latest| publish::Frame {
            mhz: r.mhz,
            count: r.count,
            completed: r.done,
            request_ms: r.dt,
            qualified: r.valid && r.raw && r.guard,
        };
        let n = frame(self.latest[input as usize * 2]);
        let l = frame(self.latest[input as usize * 2 + 1]);
        if settled {
            publish::publish(n, l, now)
        } else {
            publish::display(n, l, now)
        }
    }
    /// Display-only pitch. Re-evaluate freshness on every render; never fall
    /// back to an old result or the baseline detector when unqualified.
    pub fn display_hz(&self, input: u8, now: u64) -> Option<f32> {
        let pitch = self.selected(input, now, false);
        if matches!(pitch.source, 1 | 2) {
            Some(pitch.mhz as f32 / 1000.0)
        } else {
            None
        }
    }
    /// Frequency, qualification, consumer sequence, full-window and endpoint
    /// ages. CAL's existing post-output settling gate uses these conservative
    /// ages; repeated UI reads are not additional acquired measurements.
    pub fn measurement(
        &self,
        input: u8,
        now: u64,
        identity: &mut Sequence,
    ) -> (f32, bool, u16, u32, u32) {
        self.measurement_with(input, now, identity, false)
    }
    /// Settled CAL/CHECK observations prefer the longer low-rate bank in its
    /// overlap, retaining cross-bank disagreement and full-window age guards.
    /// Do not apply this asynchronous-bank veto to the live tuner display.
    pub fn calibration_measurement(
        &self,
        input: u8,
        now: u64,
        identity: &mut Sequence,
    ) -> (f32, bool, u16, u32, u32) {
        self.measurement_with(input, now, identity, true)
    }
    fn measurement_with(
        &self,
        input: u8,
        now: u64,
        identity: &mut Sequence,
        settled: bool,
    ) -> (f32, bool, u16, u32, u32) {
        let p = if settled {
            if input >= 4 {
                publish::Pitch::NONE
            } else {
                let frame = |r: Latest| publish::Frame {
                    mhz: r.mhz,
                    count: r.count,
                    completed: r.done,
                    request_ms: r.dt,
                    qualified: r.valid && r.raw && r.guard,
                };
                publish::calibration(
                    frame(self.latest[input as usize * 2]),
                    frame(self.latest[input as usize * 2 + 1]),
                    now,
                )
            }
        } else {
            self.selected(input, now, false)
        };
        if input < 4 {
            if let Some(sequence) = identity.observe(p.source, p.generation) {
                return (
                    p.mhz as f32 / 1000.0,
                    true,
                    sequence,
                    p.window_age_ms,
                    p.end_age_ms,
                );
            }
        }
        (0.0, false, 0, u32::MAX, u32::MAX)
    }
    fn finish(&mut self, now: u64) {
        self.active = false;
        #[cfg(tuner_nsdf_pair_diag)]
        {
            // Diagnostic only: acquire the two buffered copies back-to-back.
            // The opt-in copy-comparison diagnostic keeps its special plan.
            self.slot = if self.slot == 0 { 4 } else { 0 };
        }
        #[cfg(not(tuner_nsdf_pair_diag))]
        {
            self.slot = self.sampling.next();
        }
        // At most 100 acquisitions/s TOTAL. Late service never queues catch-up.
        self.due = now.max(self.started.saturating_add(10));
    }
    /// The live operation supplies its captured input, independent of menu
    /// selection. Finish an in-flight bank under its original channel before
    /// changing the next request; no frame may be relabeled as another input.
    pub fn set_operation_input(&mut self, input: Option<u8>, tuner_visible: bool) {
        #[cfg(not(tuner_nsdf_pair_diag))]
        if self.sampling.configure(input, tuner_visible) && !self.active {
            self.slot = self.sampling.next();
        }
    }
    pub fn tick(&mut self, uart: &pac::UART0, now: u64) {
        self.tick_reporting(uart, now, true);
    }
    pub fn serial_idle(&self) -> bool {
        self.offset == self.pending.len()
    }
    /// Pause telemetry generation, not acquisition, during a status report.
    /// Always drain the old batch before handing UART ownership to its writer.
    pub fn tick_reporting(&mut self, uart: &pac::UART0, now: u64, reports: bool) {
        self.tick_serial(uart,now,reports,true);
    }
    pub fn tick_serial(&mut self, uart: &pac::UART0, now:u64, reports:bool, serial:bool) {
        let nsdf = unsafe { &*pac::NSDF_PERIPH::ptr() };
        // UART service never gates acquisition, even when disconnected/stalled.
        for _ in 0..32 {
            if !cfg!(tuner_nsdf_telemetry) || !serial || self.offset == self.pending.len() || !uart.tx_ready().read().txe().bit() {
                break;
            }
            uart.tx_data()
                .write(|w| unsafe { w.data().bits(self.pending.as_bytes()[self.offset].into()) });
            self.offset += 1;
        }
        let low = self.slot & 1 != 0;
        let channel = self.slot >> 1;
        if self.active {
            let status = nsdf.status().read().value().bits();
            let complete = status & 2 != 0;
            if status & 0x1c != 0
                || (!complete && now.saturating_sub(self.started) >= 250)
                || (complete && status >> 16 != 622)
            {
                nsdf.control().write(|w| unsafe { w.value().bits(2) });
                self.latest[self.slot as usize].valid = false;
                #[cfg(tuner_nsdf_telemetry)]
                { self.faults = self.faults.saturating_add(1); }
                self.finish(now);
            } else if complete {
                #[cfg(tuner_nsdf_telemetry)]
                let started = crate::playback_cycles();
                let energy = (nsdf.energy_low().read().value().bits() as u64)
                    | ((nsdf.energy_high().read().value().bits() as u64) << 32);
                let seq = nsdf.sequence().read().value().bits();
                let result = crate::nsdf_select::select_frame(
                    |index| {
                        nsdf.address()
                            .write(|w| unsafe { w.value().bits(index as u16) });
                        let _ = nsdf.data().read();
                        nsdf.data().read().value().bits() as i32
                    },
                    low,
                    energy,
                    status & (1 << 8) != 0,
                    status & (1 << 9) != 0,
                );
                let guard = crate::nsdf_guard::passes(
                    crate::nsdf_guard::Source {
                        end: nsdf.source_sequence().read().value().bits(),
                        samples: nsdf.source_samples().read().value().bits(),
                        sum: nsdf.source_sum().read().value().bits() as i32,
                        squares: (nsdf.source_squares_low().read().value().bits() as u64)
                            | ((nsdf.source_squares_high().read().value().bits() as u64) << 32),
                        status: nsdf.source_status().read().value().bits(),
                    },
                    channel,
                    low,
                    seq,
                    nsdf.frame_native_end().read().value().bits(),
                    energy,
                    status & (1 << 8) != 0,
                    status & (1 << 9) != 0,
                );
                #[cfg(tuner_nsdf_telemetry)]
                let cycles = crate::playback_cycles().wrapping_sub(started) as u32;
                let (mhz, first_mhz, raw) = result.map_or((0, 0, false), |r| {
                    (
                        (r.hz * 1000.0) as u32,
                        (r.unrefined_hz * 1000.0) as u32,
                        r.qualified,
                    )
                });
                #[cfg(tuner_nsdf_wave_diag)]
                let (wave_mhz, wave_crossings) = if !low && (channel == 0
                    || (cfg!(tuner_nsdf_pair_diag) && channel == 2)) {
                    Self::wave_period_mhz()
                } else {
                    (0, 0)
                };
                #[cfg(tuner_nsdf_wave_diag)]
                if channel == 0 && !low {
                    self.wave_mhz = wave_mhz;
                    self.wave_crossings = wave_crossings;
                    self.wave_seq = seq;
                }
                let old = self.latest[self.slot as usize];
                self.latest[self.slot as usize] = Latest {
                    count: old.count.saturating_add(1),
                    #[cfg(tuner_nsdf_telemetry)]
                    seq,
                    mhz,
                    #[cfg(tuner_nsdf_telemetry)]
                    first_mhz,
                    #[cfg(tuner_nsdf_telemetry)]
                    cycles,
                    #[cfg(tuner_nsdf_telemetry)]
                    work: old.work.wrapping_add(cycles),
                    dt: now.saturating_sub(self.started).min(u32::MAX as u64) as u32,
                    done: now,
                    raw,
                    guard,
                    valid: true,
                };
                #[cfg(tuner_nsdf_pair_diag)]
                if self.slot == 4 && self.serial_idle() {
                    self.pending.clear();
                    self.offset = 0;
                    let first = self.latest[0];
                    write!(self.pending,
                        "NSDF PAIR dt={} n0={} n2={} w0={} w2={} s0={} s2={} q0={} q2={}\n",
                        now.saturating_sub(first.done),first.mhz,mhz,
                        self.wave_mhz,wave_mhz,self.wave_seq,seq,
                        first.valid && first.raw && first.guard,raw && guard).ok();
                }
                self.finish(now);
            }
        } else if now >= self.due {
            if nsdf.identity().read().value().bits() != 0x4e534407 {
                #[cfg(tuner_nsdf_telemetry)]
                { self.faults = self.faults.saturating_add(1); }
                self.latest = [Latest::EMPTY; 8];
                self.due = now.saturating_add(5000);
            } else {
                let fill = nsdf.fill().read().value().bits();
                let ready = (if low {
                    (fill >> 16) & 2047
                } else {
                    fill & 2047
                }) >= 674;
                if ready {
                    nsdf.control().write(|w| unsafe {
                        w.value()
                            .bits(1 | ((low as u32) << 2) | ((channel as u32) << 3))
                    });
                    self.started = now;
                    self.active = true;
                } else {
                    // A bank that cannot fill must not starve the other seven.
                    self.latest[self.slot as usize].valid = false;
                    self.started = now;
                    self.finish(now);
                    self.due = now.saturating_add(10);
                }
            }
        }
        #[cfg(tuner_nsdf_telemetry)]
        if reports && !cfg!(tuner_nsdf_pair_diag) && self.serial_idle() && now >= self.report_due {
            self.pending.clear();
            self.offset = 0;
            let r = self.latest[self.report as usize];
            let age = now.saturating_sub(r.done).min(u32::MAX as u64) as u32;
            let ok = r.valid && age <= 500 && r.raw && r.guard;
            // One immutable line in flight; after a stall report current latest
            // results, never replay an unbounded backlog. age is at formatting.
            write!(self.pending,"NSDF RUN ch={} low={} count={} seq={} mhz={} first={} raw={} guard={} ok={} age={} dt={} cycles={} work={} faults={} ms={}\n",
                self.report>>1,self.report&1!=0,r.count,r.seq,r.mhz,r.first_mhz,r.raw,r.guard,ok,age,r.dt,r.cycles,r.work,self.faults,now as u32).ok();
            #[cfg(tuner_nsdf_wave_diag)]
            if self.report == 0 {
                write!(self.pending,"NSDF WAVE ch=0 seq={} mhz={} crossings={} nsdf_mhz={}\n",
                    self.wave_seq,self.wave_mhz,self.wave_crossings,r.mhz).ok();
            }
            if self.report & 1 != 0 {
                let n = self.latest[(self.report - 1) as usize];
                let na = now.saturating_sub(n.done).min(u32::MAX as u64) as u32;
                let nq = n.valid && n.count > 0 && n.raw && n.guard;
                let lq = r.valid && r.count > 0 && r.raw && r.guard;
                let selected = resolve::resolve(
                    resolve::Candidate {
                        mhz: n.mhz,
                        age: na,
                        qualified: nq,
                    },
                    resolve::Candidate {
                        mhz: r.mhz,
                        age,
                        qualified: lq,
                    },
                );
                write!(
                    self.pending,
                    "NSDF PICK ch={} ms={} n={} na={} nq={} l={} la={} lq={} mhz={} src={}\n",
                    self.report >> 1,
                    now as u32,
                    n.mhz,
                    na,
                    nq,
                    r.mhz,
                    age,
                    lq,
                    selected.mhz,
                    selected.source
                )
                .ok();
                let p = self.selected(self.report >> 1, now, false);
                let (base, bq, end_age, observed) = self.baseline[(self.report >> 1) as usize];
                let bage = now
                    .saturating_sub(observed)
                    .saturating_add(end_age as u64)
                    .min(u32::MAX as u64) as u32;
                write!(self.pending,"NSDF COMP ch={} ms={} mhz={} src={} gen={} age={} win={} base={} bq={} bage={}\n",
                    self.report>>1,now as u32,p.mhz,p.source,p.generation,p.end_age_ms,p.window_age_ms,
                    base,bq && bage<=250,bage).ok();
            }
            self.report = (self.report + 1) & 7;
            self.report_due = now.saturating_add(50);
        }
    }
}
