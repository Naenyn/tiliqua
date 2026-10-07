//! Production NSDF acquisition and pitch scheduling, with opt-in score export.
//! The continuous scheduler is required even when serial telemetry is disabled.
#[cfg(not(tuner_nsdf_continuous))]
use core::fmt::Write;
#[cfg(not(tuner_nsdf_continuous))]
use heapless::String;
#[cfg(not(tuner_nsdf_continuous))]
use tiliqua_pac as pac;

#[cfg(not(tuner_nsdf_continuous))]
const FAST: bool = !matches!(env!("TILIQUA_INTONO_NSDF_TRACE").as_bytes(), b"full");
#[cfg(not(tuner_nsdf_continuous))]
const FAST_LOW: bool = matches!(env!("TILIQUA_INTONO_NSDF_TRACE").as_bytes(), b"fast-low");
#[cfg(not(tuner_nsdf_continuous))]
const ALL: bool = matches!(env!("TILIQUA_INTONO_NSDF_TRACE").as_bytes(), b"fast-all");
#[cfg(tuner_nsdf_continuous)]
#[path = "nsdf_schedule.rs"]
mod schedule;
#[cfg(tuner_nsdf_continuous)]
pub use schedule::Scheduler as Trace;
#[cfg(tuner_nsdf_continuous)]
pub use schedule::Sequence;

#[cfg(not(tuner_nsdf_continuous))]
pub struct Trace {
    pending: String<192>,
    offset: usize,
    state: u8,
    channel: u8,
    low: bool,
    index: u16,
    due: u64,
    started: u64,
}

#[cfg(not(tuner_nsdf_continuous))]
impl Trace {
    pub fn new() -> Self {
        Self {
            pending: String::new(),
            offset: 0,
            state: 0,
            channel: 0,
            low: FAST_LOW,
            index: 0,
            due: 2000,
            started: 0,
        }
    }
    pub fn fast(&self) -> bool {
        FAST
    }
    pub fn ui_period_ms(&self, idle_tuner: bool, normal: u64) -> u64 {
        if FAST && !ALL && !cfg!(tuner_nsdf_continuous) && idle_tuner {
            100
        } else {
            normal
        }
    }
    pub fn tick(&mut self, uart: &pac::UART0, now: u64) {
        // Only compiled with the matching opt-in gateware register block.
        let nsdf = unsafe { &*pac::NSDF_PERIPH::ptr() };
        // Bounded, non-blocking UART service. No waiting and no frame-sized RAM.
        for _ in 0..32 {
            if self.offset == self.pending.len() || !uart.tx_ready().read().txe().bit() {
                break;
            }
            uart.tx_data()
                .write(|w| unsafe { w.data().bits(self.pending.as_bytes()[self.offset].into()) });
            self.offset += 1;
        }
        if self.offset != self.pending.len() {
            return;
        }
        self.pending.clear();
        self.offset = 0;
        match self.state {
            0 => {
                if now < self.due {
                    return;
                }
                if nsdf.identity().read().value().bits() != 0x4e534407 {
                    self.pending
                        .push_str("NSDF ERROR incompatible gateware\n")
                        .ok();
                    self.due = now.saturating_add(5000);
                    return;
                }
                let fill = nsdf.fill().read().value().bits();
                if (if self.low {
                    (fill >> 16) & 2047
                } else {
                    fill & 2047
                }) < 674
                {
                    self.due = now.saturating_add(100);
                    return;
                }
                nsdf.control().write(|w| unsafe {
                    w.value()
                        .bits(1 | ((self.low as u32) << 2) | ((self.channel as u32) << 3))
                });
                self.started = now;
                self.state = 1;
            }
            1 => {
                let status = nsdf.status().read().value().bits();
                if status & 2 == 0 && now.saturating_sub(self.started) < 1000 {
                    return;
                }
                let last = 621;
                if status & 0x1c != 0 || status & 2 == 0 || status >> 16 != last + 1 {
                    nsdf.control().write(|w| unsafe { w.value().bits(2) });
                    write!(
                        self.pending,
                        "NSDF ERROR ch={} low={} status={:08x}\n",
                        self.channel, self.low, status
                    )
                    .ok();
                    self.state = 3;
                    return;
                }
                let source_sum = nsdf.source_sum().read().value().bits() as i32;
                let source_squares = (nsdf.source_squares_low().read().value().bits() as u64)
                    | ((nsdf.source_squares_high().read().value().bits() as u64) << 32);
                write!(self.pending,"NSDF SOURCE ch={} low={} seq={} end={} n={} sum={} squares={} status={} frame_end={}\n",
                    self.channel,self.low,nsdf.sequence().read().value().bits(),
                    nsdf.source_sequence().read().value().bits(),nsdf.source_samples().read().value().bits(),
                    source_sum,source_squares,nsdf.source_status().read().value().bits(),
                    nsdf.frame_native_end().read().value().bits()).ok();
                self.state = 6;
            }
            6 => {
                let status = nsdf.status().read().value().bits();
                let energy = (nsdf.energy_low().read().value().bits() as u64)
                    | ((nsdf.energy_high().read().value().bits() as u64) << 32);
                let started = crate::playback_cycles();
                let mut reads = 0_u16;
                let result = crate::nsdf_select::select_frame(
                    |index| {
                        nsdf.address()
                            .write(|w| unsafe { w.value().bits(index as u16) });
                        let _ = nsdf.data().read(); // Settle the synchronous score RAM.
                        reads += 1;
                        nsdf.data().read().value().bits() as i32
                    },
                    self.low,
                    energy,
                    status & (1 << 8) != 0,
                    status & (1 << 9) != 0,
                );
                let cycles = crate::playback_cycles().wrapping_sub(started);
                let guard_started = crate::playback_cycles();
                let guard = crate::nsdf_guard::passes(
                    crate::nsdf_guard::Source {
                        end: nsdf.source_sequence().read().value().bits(),
                        samples: nsdf.source_samples().read().value().bits(),
                        sum: nsdf.source_sum().read().value().bits() as i32,
                        squares: (nsdf.source_squares_low().read().value().bits() as u64)
                            | ((nsdf.source_squares_high().read().value().bits() as u64) << 32),
                        status: nsdf.source_status().read().value().bits(),
                    },
                    self.channel,
                    self.low,
                    nsdf.sequence().read().value().bits(),
                    nsdf.frame_native_end().read().value().bits(),
                    energy,
                    status & (1 << 8) != 0,
                    status & (1 << 9) != 0,
                );
                let guard_cycles = crate::playback_cycles().wrapping_sub(guard_started);
                let (hz, raw, clarity, qualified) = result.map_or((0, 0, 0, false), |r| {
                    (
                        (r.hz * 1000.0) as u32,
                        (r.unrefined_hz * 1000.0) as u32,
                        (r.clarity * 1000000.0) as u32,
                        r.qualified,
                    )
                });
                write!(self.pending,"NSDF CPU ch={} low={} seq={} mhz={} raw={} ppm={} ok={} cycles={} reads={} guard={} gc={} policy=4\n",
                    self.channel,self.low,nsdf.sequence().read().value().bits(),hz,raw,clarity,qualified,cycles,reads,guard,guard_cycles).ok();
                self.state = if FAST { 7 } else { 5 };
            }
            7 => {
                // Summary only: no score sweep and no promise of model parity
                // without a full export. Native frame endpoints measure actual
                // cadence even when UI work delays this foreground service.
                let status = nsdf.status().read().value().bits();
                let energy = (nsdf.energy_low().read().value().bits() as u64)
                    | ((nsdf.energy_high().read().value().bits() as u64) << 32);
                write!(self.pending,"NSDF FAST ch={} low={} seq={} energy={} scaled={} clipped={} start_ms={} end_ms={}\n",
                    self.channel,self.low,nsdf.sequence().read().value().bits(),energy,
                    (status>>8)&1,(status>>9)&1,self.started,now).ok();
                self.state = 3;
            }
            5 => {
                // Separate diagnostic baseline for one full score-register
                // sweep. Not part of selector timing or production work.
                // Interrupts stay enabled; elapsed times include ISR work.
                let count = 622;
                let started = crate::playback_cycles();
                let mut checksum = 0_u32;
                for index in 0..count {
                    nsdf.address().write(|w| unsafe { w.value().bits(index) });
                    let _ = nsdf.data().read();
                    checksum = checksum.wrapping_add(nsdf.data().read().value().bits());
                }
                let cycles = crate::playback_cycles().wrapping_sub(started);
                write!(
                    self.pending,
                    "NSDF IO ch={} low={} seq={} cycles={} reads={} sum={:08x}\n",
                    self.channel,
                    self.low,
                    nsdf.sequence().read().value().bits(),
                    cycles,
                    count,
                    checksum
                )
                .ok();
                self.state = 4;
            }
            4 => {
                let status = nsdf.status().read().value().bits();
                let last = 621;
                let energy = (nsdf.energy_low().read().value().bits() as u64)
                    | ((nsdf.energy_high().read().value().bits() as u64) << 32);
                write!(self.pending,"NSDF BEGIN ch={} low={} fs={} n={} last={} seq={} energy={} scaled={} clipped={}\n",
                    self.channel,self.low,if self.low {6000} else {192000},674,last,
                    nsdf.sequence().read().value().bits(),energy,(status>>8)&1,(status>>9)&1).ok();
                self.index = 0;
                self.state = 2;
            }
            2 => {
                let count = 622;
                if self.index == count {
                    self.pending.push_str("NSDF END\n").ok();
                    self.state = 8;
                } else {
                    nsdf.address()
                        .write(|w| unsafe { w.value().bits(self.index) });
                    let _ = nsdf.data().read(); // Settle synchronous score RAM.
                    write!(self.pending, "{:08x}\n", nsdf.data().read().value().bits()).ok();
                    self.index += 1;
                }
            }
            8 => {
                write!(
                    self.pending,
                    "NSDF WAVE ch={} low={} seq={} n={}\n",
                    self.channel,
                    self.low,
                    nsdf.sequence().read().value().bits(),
                    674
                )
                .ok();
                self.index = 0;
                self.state = 9;
            }
            9 => {
                let count = 674;
                if self.index == count {
                    self.pending.push_str("NSDF WAVE END\n").ok();
                    self.state = 3;
                } else {
                    nsdf.address()
                        .write(|w| unsafe { w.value().bits(1024 | self.index) });
                    let _ = nsdf.data().read();
                    write!(self.pending, "{:08x}\n", nsdf.data().read().value().bits()).ok();
                    self.index += 1;
                }
            }
            _ => {
                if FAST {
                    if ALL {
                        if self.low {
                            self.channel = (self.channel + 1) & 3;
                        }
                        self.low = !self.low;
                    }
                    // Bound request rate to <=20 Hz; do not queue missed work.
                    self.due = now.max(self.started.saturating_add(50));
                } else {
                    if self.low {
                        self.channel = (self.channel + 1) & 3;
                    }
                    self.low = !self.low;
                    self.due = now.saturating_add(250);
                }
                self.state = 0;
            }
        }
    }
}
