//! Apply only a completed verification of the current channel and nearby pitch.
//! Zero means unverified, not a guessed subharmonic. The crossing estimate is
//! retained outside the verifier's limited range; this is not calibration confidence.
#[derive(Default)]
pub struct Verification {
    capture_mode: u8,
    channel: u8,
    lag: u32,
    factor: u8,
    last_raw_hz:f32,
    last_applied_factor:u8,
    diagnostic: Diagnostic,
}

#[derive(Clone,Copy,Default)]
pub struct Diagnostic {
    pub lag_q8:u32,
    pub divisor:u8,
    pub error:u32,
    pub span:u32,
}

impl Verification {
    pub fn diagnostic(&self)->Diagnostic {self.diagnostic}
    pub fn record_diagnostic(&mut self,lag_q8:u32,divisor:u8,error:u32,span:u32) {
        self.diagnostic=Diagnostic {lag_q8,divisor,error,span};
    }
    pub fn record_reading(&mut self,raw_hz:f32,factor:u8) {
        self.last_raw_hz=raw_hz;self.last_applied_factor=factor;
    }
    pub fn reading(&self)->(f32,u8) {(self.last_raw_hz,self.last_applied_factor)}
    pub fn capture_mode(&self)->u8 {self.capture_mode}
    pub fn set_capture_mode(&mut self,mode:u8) {
        if self.capture_mode!=mode {self.clear();self.capture_mode=mode;}
    }
    pub fn complete(&mut self, channel: u8, lag: u32, factor: u8) {
        self.channel = channel;
        self.lag = lag;
        self.factor = if (1..=4).contains(&factor) { factor } else { 0 };
    }

    pub fn clear(&mut self) {
        self.factor = 0;
    }

    pub fn factor(&self, channel: u8, lag: u32) -> u8 {
        // About 6.8 cents of tolerance. A changed note must be checked again;
        // do not retain a previous octave correction across a pitch jump.
        if self.factor != 0 && self.channel == channel && lag != 0
            && self.lag.abs_diff(lag) <= lag / 256 {
            self.factor
        } else {
            1
        }
    }

    pub fn matches(&self, channel: u8, lag: u32) -> bool {
        self.factor != 0 && self.channel == channel && lag != 0
            && self.lag.abs_diff(lag) <= lag / 256
    }
}

pub fn capture_divisor(sample_rate:u32,mode:u8)->u32 {
    let base=(sample_rate/24000).max(1).next_power_of_two().min(8);
    [base,1,base*4,base*16][mode.min(3) as usize]
}

/// At most 50 UI frames per second; leave eight frames after filling history.
pub fn dwell_frames(sample_rate:u32,divisor:u32)->u8 {
    ((2048u64*divisor as u64*50).div_ceil(sample_rate.max(1) as u64)+8).min(255) as u8
}

/// Choose a history rate with generous overlap. Retain the current rate inside
/// the overlap so pitch jitter cannot repeatedly discard the capture history.
pub fn capture_mode(samples:u32,cycles:u16,sample_rate:u32,current:u8)->u8 {
    if cycles==0 || sample_rate==0 {return current.min(3);}
    let base=(sample_rate/24000).max(1).next_power_of_two().min(8);
    let divisors=[base,1,base*4,base*16];
    let period=samples as u64*256/cycles as u64;
    let lag=period/divisors[current.min(3) as usize] as u64;
    if (16*256..=1200*256).contains(&lag) {return current.min(3);}
    for mode in [3,2,0,1] {
        let lag=period/divisors[mode as usize] as u64;
        if (24*256..=1000*256).contains(&lag) {return mode;}
    }
    if lag<16*256 {1} else {3}
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn capture_rates_extend_range_with_overlap_and_invalidate_old_matches() {
        assert_eq!(capture_mode(8,1,48000,0),1); // 6 kHz needs full rate.
        assert_eq!(capture_mode(4800,1,48000,0),3); // 10 Hz needs longer history.
        assert_eq!(capture_mode(48,1,48000,0),0);
        for samples in 3100..3300 {assert_eq!(capture_mode(samples,1,48000,2),2);}
        let mut v=Verification::default();v.complete(0,100,2);
        v.set_capture_mode(1);assert!(!v.matches(0,100));
        assert_eq!(capture_divisor(192000,3),128);
        assert_eq!(dwell_frames(192000,128),77);
        assert_eq!(dwell_frames(192000,1),9);
    }
    #[test]
    fn correction_is_scoped_to_channel_and_candidate() {
        let mut v = Verification::default();
        assert_eq!(v.factor(0, 10000), 1);
        v.complete(0, 10000, 2);
        assert_eq!(v.factor(0, 10030), 2);
        assert_eq!(v.factor(0, 10100), 1);
        assert_eq!(v.factor(1, 10000), 1);
        assert_eq!(v.factor(0, 5000), 1); // An actual note an octave higher.
        v.complete(0, 10000, 0);
        assert_eq!(v.factor(0, 10000), 1);
        v.complete(0, 10000, 2);
        v.clear();
        assert_eq!(v.factor(0, 10000), 1);
    }
    #[test]
    fn invalid_descriptors_cannot_correct_pitch() {
        let mut v = Verification::default();
        for factor in [0, 5, 255] {
            v.complete(0, 100, factor);
            assert_eq!(v.factor(0, 100), 1);
        }
        v.complete(0, 0, 2);
        assert_eq!(v.factor(0, 0), 1);
    }
}
