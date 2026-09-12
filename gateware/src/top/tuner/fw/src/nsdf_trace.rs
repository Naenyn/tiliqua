//! Experimental score export only; never changes production pitch or outputs.
use core::fmt::Write;
use heapless::String;
use tiliqua_pac as pac;

pub struct Trace {
    pending: String<192>, offset: usize, state: u8, channel: u8,
    low: bool, index: u16, due: u64, started: u64,
}

impl Trace {
    pub fn new() -> Self {
        Self { pending: String::new(), offset: 0, state: 0, channel: 0,
            low: false, index: 0, due: 2000, started: 0 }
    }
    pub fn tick(&mut self, uart: &pac::UART0, now: u64) {
        // Only compiled with the matching opt-in gateware register block.
        let nsdf = unsafe { &*pac::NSDF_PERIPH::ptr() };
        // Bounded, non-blocking UART service. No waiting and no frame-sized RAM.
        for _ in 0..32 {
            if self.offset == self.pending.len() || !uart.tx_ready().read().txe().bit() { break; }
            uart.tx_data().write(|w| unsafe { w.data().bits(self.pending.as_bytes()[self.offset].into()) });
            self.offset += 1;
        }
        if self.offset != self.pending.len() { return; }
        self.pending.clear(); self.offset = 0;
        match self.state {
            0 => {
                if now < self.due { return; }
                if nsdf.identity().read().value().bits() != 0x4e534401 {
                    self.pending.push_str("NSDF ERROR incompatible gateware\n").ok();
                    self.due = now.saturating_add(5000); return;
                }
                let fill = nsdf.fill().read().value().bits();
                if (if self.low { (fill >> 16) & 2047 } else { fill & 2047 }) < (if self.low { 604 } else { 674 }) {
                    self.due = now.saturating_add(100); return;
                }
                nsdf.control().write(|w| unsafe { w.value().bits(1 | ((self.low as u32) << 2) | ((self.channel as u32) << 3)) });
                self.started = now; self.state = 1;
            }
            1 => {
                let status = nsdf.status().read().value().bits();
                if status & 2 == 0 && now.saturating_sub(self.started) < 1000 { return; }
                let last = if self.low { 301 } else { 321 };
                if status & 0x1c != 0 || status & 2 == 0 || status >> 16 != last + 1 {
                    nsdf.control().write(|w| unsafe { w.value().bits(2) });
                    write!(self.pending,"NSDF ERROR ch={} low={} status={:08x}\n",self.channel,self.low,status).ok();
                    self.state = 3; return;
                }
                let energy = (nsdf.energy_low().read().value().bits() as u64)
                    | ((nsdf.energy_high().read().value().bits() as u64) << 32);
                write!(self.pending,"NSDF BEGIN ch={} low={} fs={} n={} last={} seq={} energy={} scaled={} clipped={}\n",
                    self.channel,self.low,if self.low {6000} else {192000},if self.low {604} else {674},last,
                    nsdf.sequence().read().value().bits(),energy,(status>>8)&1,(status>>9)&1).ok();
                self.index=0;self.state=2;
            }
            2 => {
                let count = if self.low { 302 } else { 322 };
                if self.index == count {
                    self.pending.push_str("NSDF END\n").ok(); self.state=3;
                } else {
                    nsdf.address().write(|w| unsafe { w.value().bits(self.index) });
                    let _ = nsdf.data().read(); // Settle synchronous score RAM.
                    write!(self.pending,"{:08x}\n",nsdf.data().read().value().bits()).ok();
                    self.index+=1;
                }
            }
            _ => {
                if self.low { self.channel=(self.channel+1)&3; }
                self.low=!self.low;self.state=0;self.due=now.saturating_add(250);
            }
        }
    }
}
