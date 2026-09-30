//! Temporary, opt-in CV-step diagnostic for the paired-wave firmware build.
//! Commands arrive over the debug UART only while the tuner is idle. This is
//! deliberately not a calibration profile or a production output mode.
use tiliqua_pac as pac;

const ENABLE: u32 = 1 << 18;
const LEASE_MS: u64 = 30_000;

#[derive(Default)]
pub struct Probe {
    command: u32,
    token: u8,
    expires: u64,
    pending_ack: Option<u8>,
}

impl Probe {
    fn counts(byte: u8) -> Option<u16> {
        // Exact DAC counts at 4 counts/mV. The three close targets reproduce
        // the grid/local ACRONYM region without requiring a full CAL sweep.
        // Binary commands 0x80..=0xa8 map every physical DAC count between
        // +2.45000 and +2.46000 V. They are diagnostic-only, outside the
        // printable serial command space, and permit a bidirectional check
        // for a steep continuous response versus an unplayable pitch jump.
        if (0x80..=0xa8).contains(&byte) {
            return Some(9_800 + u16::from(byte - 0x80));
        }
        // A second exact-count window brackets the unstable nominal +2 V
        // endpoint seen with ACRONYM at its lower coarse tuning. 0xd4 is
        // 8000 counts (nominal +2.00000 V); the full window corresponds to
        // +1.98925 .. +2.01075 V at 4 counts/mV, not an independently
        // measured jack voltage. Keep these binary
        // commands disjoint from the older +2.45 V diagnostic window.
        if (0xa9..=0xff).contains(&byte) {
            return Some(7_957 + u16::from(byte - 0xa9));
        }
        Some(match byte {
            b'd' => 8_000,  // +2.00000 V
            b'a' => 9_667,  // +2.41675 V
            b'b' => 9_730,  // +2.43250 V
            b'p' => 9_760,  // +2.44000 V
            b'q' => 9_800,  // +2.45000 V
            b'r' => 9_840,  // +2.46000 V
            b's' => 9_880,  // +2.47000 V
            b't' => 9_920,  // +2.48000 V
            b'u' => 9_960,  // +2.49000 V
            b'c' => 10_000, // +2.50000 V
            b'e' => 12_000, // +3.00000 V
            _ => return None,
        })
    }

    fn stop(&mut self, tuner: &pac::TUNER_PERIPH) {
        self.pending_ack = None;
        if self.command != 0 {
            self.command = 0;
            self.expires = 0;
            tuner.cal_command().write(|w| unsafe { w.value().bits(0) });
        }
    }

    pub fn tick(&mut self, tuner: &pac::TUNER_PERIPH, uart: &pac::UART0, now: u64, allowed: bool) {
        // Consume at most a few bytes per foreground turn. Unsupported input
        // is inert, and no command can arm an output outside the idle tuner.
        for _ in 0..8 {
            if !uart.rx_avail().read().rxe().bit() {
                break;
            }
            let byte = uart.rx_data().read().data().bits();
            if byte == b'x' {
                self.stop(tuner);
            } else if allowed {
                if let Some(counts) = Self::counts(byte) {
                    self.token = self.token.wrapping_add(1);
                    self.command = counts as u32 | ENABLE | ((self.token as u32) << 21);
                    self.expires = now.saturating_add(LEASE_MS);
                    // A one-byte, nonblocking serial ACK after the DAC-side
                    // token is observed. High-bit bytes cannot be confused
                    // with the ASCII diagnostic stream. The host waits for
                    // this before attributing a pitch reading to a command.
                    self.pending_ack = Some(byte | 0x80);
                }
            }
        }
        if !allowed || (self.command != 0 && now >= self.expires)
            || tuner.cal_status().read().value().bits() & (1 << 9) != 0
        {
            self.stop(tuner);
        } else if self.command != 0 {
            // Renew the exact command before the hardware heartbeat expires.
            tuner
                .cal_command()
                .write(|w| unsafe { w.value().bits(self.command) });
        }
        if let Some(ack) = self.pending_ack {
            let status = tuner.cal_status().read().value().bits();
            if status & 0xff == self.token as u32
                && status & (1 << 8) != 0
                && uart.tx_ready().read().txe().bit()
            {
                uart.tx_data().write(|w| unsafe { w.data().bits(ack) });
                self.pending_ack = None;
            }
        }
    }
}
