//! Explicit, output-only tuning reference using the guarded calibration port.
//! The adapter renews commands in foreground; hardware supplies the watchdog.
use crate::ownership::{Owner, Reservations};
const ENABLE: u32 = 1 << 18;
const ACTIVE: u32 = 1 << 8;
const FAULT: u32 = 1 << 9;
#[derive(Clone, Copy)]
pub struct Reference {
    pub output: u8,
    pub millivolts: i16,
    pub phase: u8,
    pub free: u8,
    token: u8,
    deadline: u64,
    command: u32,
    pub status: &'static str,
}
impl Reference {
    pub const fn new() -> Self {
        Self {
            output: 0,
            millivolts: 0,
            phase: 0,
            free: 15,
            token: 0,
            deadline: 0,
            command: 0,
            status: "OFF",
        }
    }
    pub fn enabled(&self) -> bool {
        matches!(self.phase, 1 | 2)
    }
    pub fn command(&self) -> Option<u32> {
        if self.phase == 0 {
            None
        } else {
            Some(self.command)
        }
    }
    fn stop(&mut self, status: &'static str) {
        self.phase = 3;
        self.command = 0;
        self.status = status;
    }
    pub fn tick(
        &mut self,
        now: u64,
        status: u32,
        allowed: bool,
        toggle: bool,
        output: u8,
        millivolts: i16,
        claims: &mut Reservations,
    ) {
        // Never release a jack while the DAC-side owner still reports active.
        if self.phase == 3 {
            if status & (ACTIVE | FAULT) == 0 {
                self.phase = 0;
                claims.release(Owner::Reference);
            }
            return;
        }
        if self.enabled() && (!allowed || toggle) {
            self.stop("OFF");
            return;
        }
        if self.phase == 0 {
            if !toggle {
                return;
            }
            if !allowed
                || output >= 4
                || self.free & (1 << output) == 0
                || !claims.claim(Owner::Reference, 0, 1 << output)
            {
                self.status = "OUTPUT UNAVAILABLE";
                return;
            }
            self.output = output;
            self.millivolts = i16::MIN;
        } else if status & FAULT != 0 {
            self.stop("OUTPUT FAULT");
            return;
        }
        let millivolts = millivolts.clamp(-5000, 8000);
        if self.millivolts != millivolts {
            self.millivolts = millivolts;
            self.token = self.token.wrapping_add(1);
            self.command = (millivolts as i32 * 4) as i16 as u16 as u32
                | (self.output as u32) << 16
                | ENABLE
                | (self.token as u32) << 21
                | 1 << 29;
            self.phase = 1;
            self.deadline = now + 100;
            self.status = "STARTING";
        }
        if self.phase == 1 {
            if status & ACTIVE != 0 && status as u8 == self.token {
                self.phase = 2;
                self.status = "ON";
            } else if now >= self.deadline {
                self.stop("OUTPUT NO ACK");
            }
        } else if status & ACTIVE == 0 {
            self.stop("OUTPUT STOPPED");
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_enable_ack_adjust_disable_and_release() {
        let mut r = Reservations::new();
        let mut v = Reference::new();
        v.tick(0, 0, true, false, 2, 1000, &mut r);
        assert!(v.command().is_none());
        v.tick(1, 0, true, true, 2, 1000, &mut r);
        assert!(r.held(Owner::Reference));
        let command = v.command().unwrap();
        assert_eq!(command as u16, 4000);
        assert_eq!((command >> 16) & 3, 2);
        v.tick(2, ACTIVE | 1, true, false, 2, 1000, &mut r);
        assert_eq!(v.status, "ON");
        v.tick(3, ACTIVE | 1, true, false, 0, -5000, &mut r);
        assert_eq!(v.output, 2);
        assert_eq!(v.command().unwrap() as u16 as i16, -20000);
        v.tick(4, ACTIVE | 2, true, true, 2, -5000, &mut r);
        assert_eq!(v.command(), Some(0));
        assert!(r.held(Owner::Reference));
        v.tick(5, ACTIVE, true, false, 2, 0, &mut r);
        assert!(r.held(Owner::Reference));
        v.tick(6, 0, true, false, 2, 0, &mut r);
        assert!(!r.held(Owner::Reference));
        assert!(v.command().is_none());
    }
    #[test]
    fn configured_outputs_are_rejected_without_claiming_inputs() {
        let mut claims = Reservations::new();
        let mut v = Reference::new();
        v.free = 8;
        v.tick(0, 0, true, true, 0, 0, &mut claims);
        assert!(!v.enabled());
        assert!(!claims.held(Owner::Reference));
        v.tick(1, 0, true, true, 3, 0, &mut claims);
        assert!(v.enabled());
        for input in 0..4 {
            assert!(claims.tuner_available(input));
        }
        assert!(claims.claim(Owner::Quant(0), 1, 1));
    }
    #[test]
    fn reservations_timeouts_faults_and_page_exit_fail_closed() {
        for fault in [FAULT, 0] {
            let mut r = Reservations::new();
            assert!(r.claim(Owner::Quant(0), 1, 1));
            let mut v = Reference::new();
            v.tick(0, 0, true, true, 0, 0, &mut r);
            assert!(!v.enabled());
            v.tick(0, 0, true, true, 1, 8000, &mut r);
            assert_eq!(v.command().unwrap() as u16, 32000);
            v.tick(101, fault, true, false, 1, 8000, &mut r);
            assert_eq!(v.command(), Some(0));
            assert!(r.held(Owner::Reference));
            v.tick(102, 0, false, false, 1, 0, &mut r);
            assert!(!r.held(Owner::Reference));
            v.tick(103, 0, true, false, 1, 0, &mut r);
            assert!(!v.enabled());
            v.tick(104, 0, true, true, 1, 0, &mut r);
            v.tick(105, ACTIVE | 2, false, false, 1, 0, &mut r);
            assert_eq!(v.command(), Some(0));
        }
    }
}
