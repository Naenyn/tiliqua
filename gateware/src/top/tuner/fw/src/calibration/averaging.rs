//! Low-frequency acquisition, not display smoothing or a confidence guarantee.
//! Eight non-overlapping windows; retain raw span and test block agreement.
pub const LOW_PITCH:i32=4_800_000; // C3, about 130.8 Hz at A4=440.
pub struct Average {
    values:[i32;8],next:usize,count:usize,last_end:Option<u64>,
    raw_low:i32,raw_high:i32,
    seen:u16,overlap:u16,span_resets:u16,gap_resets:u16,
}
#[derive(Clone,Copy,Debug)]
pub struct Snapshot {
    pub count:usize,pub seen:u16,pub overlap:u16,pub span_resets:u16,pub gap_resets:u16,
    pub raw_span:u32,pub quarter_delta:u32,pub half_delta:u32,pub values:[i32;8],
}
#[derive(Clone,Copy,Debug)]
pub struct Estimate {pub mean:i32,pub spread:u32}
impl Average {
    pub fn new()->Self {Self{values:[0;8],next:0,count:0,last_end:None,raw_low:i32::MAX,raw_high:i32::MIN,
        seen:0,overlap:0,span_resets:0,gap_resets:0}}
    fn reset_windows(&mut self) {self.next=0;self.count=0;self.last_end=None;self.raw_low=i32::MAX;self.raw_high=i32::MIN;}
    pub fn clear(&mut self) {self.reset_windows();self.seen=0;self.overlap=0;self.span_resets=0;self.gap_resets=0;}
    pub fn snapshot(&self)->Snapshot {
        let mut values=[0;8];let mut sums=[0i64;4];
        for i in 0..self.count {
            values[i]=self.values[(if self.count==8 {self.next+i}else{i})%8];
            sums[i/2]+=values[i] as i64;
        }
        Snapshot {count:self.count,seen:self.seen,overlap:self.overlap,span_resets:self.span_resets,gap_resets:self.gap_resets,
            raw_span:if self.count==0 {0}else{(self.raw_high as i64-self.raw_low as i64) as u32},
            quarter_delta:if self.count==8 {((sums.iter().max().unwrap()-sums.iter().min().unwrap())/2) as u32}else{0},
            half_delta:if self.count==8 {((sums[0]+sums[1]-sums[2]-sums[3]).abs()/4) as u32}else{0},values}
    }
    pub fn observe(&mut self,value:i32,start:u64,end:u64)->Option<Estimate> {
        if start>end {self.clear();return None;}
        if let Some(last)=self.last_end {
            if end<=last {return None;}
            if start.saturating_sub(last)>500 {self.gap_resets=self.gap_resets.saturating_add(1);self.reset_windows();}
        }
        self.seen=self.seen.saturating_add(1);
        // Include fresh overlapping frames in the instability guard too:
        // decimating alternate frames must not conceal alternating errors.
        self.raw_low=self.raw_low.min(value);self.raw_high=self.raw_high.max(value);
        if self.raw_high as i64-self.raw_low as i64>8000 {
            self.span_resets=self.span_resets.saturating_add(1);
            self.reset_windows();self.raw_low=value;self.raw_high=value;
        }
        if self.last_end.is_some_and(|last|start<last) {self.overlap=self.overlap.saturating_add(1);return None;}
        self.last_end=Some(end);
        self.values[self.next]=value;self.next=(self.next+1)%8;
        self.count=(self.count+1).min(8);
        if self.count<8 {return None;}
        let mut sums=[0i64;4];
        for i in 0..8 {
            let v=self.values[(self.next+i)%8];
            sums[i/2]+=v as i64;
        }
        let spread=self.raw_high as i64-self.raw_low as i64;
        // Never turn a grossly unstable signal into an apparently precise mean.
        // Quarter-block means must agree within 2c; half means within 1c.
        if spread>8000 || sums.iter().max().unwrap()-sums.iter().min().unwrap()>4000
            || (sums[0]+sums[1]-sums[2]-sums[3]).abs()>4000 {return None;}
        Some(Estimate{mean:(sums.iter().sum::<i64>()/8) as i32,spread:spread as u32})
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn captured_generate3_readings_have_repeatable_mean_despite_raw_span() {
        // Readings from the 2026-09-18 serial capture, OUT1=-2.16675V,
        // IN1 fundamental. Repeat the first four to exercise rolling storage.
        let hz=[26.715,26.670,26.674,26.693,26.685,26.642,26.690,26.713,
            26.667,26.689,26.648,26.690,26.715,26.670,26.674,26.693];
        let mut a=Average::new();let mut result=None;let mut first_accepted=None;
        for (n,hz) in hz.into_iter().enumerate() {
            result=a.observe(crate::pitch_math::millicents(hz,440.0),n as u64*400,n as u64*400+110);
            if result.is_some() && first_accepted.is_none() {first_accepted=Some(n*400+110);}
        }
        let result=result.unwrap();assert!((4700..4800).contains(&result.spread));
        // Include the existing 350ms settling time within the 5s deadline.
        assert!(first_accepted.unwrap()+350<5000);
    }
    #[test] fn bounded_jitter_averages_but_drift_and_excess_span_do_not() {
        for scenario in 0..4 {
            let mut a=Average::new();let mut result=None;
            for n in 0..8 {
                let error=match scenario {0=>if n%2==0 {-2400}else{2400},
                    1=>n*400,2=>if n%2==0 {-5000}else{5000},
                    _=>if n<4 {-2000}else{2000}};
                result=a.observe(3_000_000+error,n as u64*160,n as u64*160+110);
            }
            if scenario==0 {let r=result.unwrap();assert_eq!(r.mean,3_000_000);assert_eq!(r.spread,4800);}
            else {assert!(result.is_none());}
        }
        assert!(core::mem::size_of::<Average>()<=104);
    }
    #[test] fn repeated_overlapping_or_gapped_windows_cannot_fill_average() {
        let mut a=Average::new();
        for _ in 0..40 {assert!(a.observe(1,0,110).is_none());}
        assert_eq!(a.count,1);
        for n in 1..16 {assert!(a.observe(1,n*5,110+n*5).is_none());}
        assert_eq!(a.count,1);
        assert!(a.observe(1,1000,1110).is_none());assert_eq!(a.count,1);
        a.clear();assert_eq!(a.count,0);
    }
    #[test] fn overlapping_alternating_outliers_cannot_alias_to_a_stable_mean() {
        let mut a=Average::new();
        for n in 0..100 {
            assert!(a.observe(if n%2==0 {10000}else{-10000},n*80,n*80+110).is_none());
        }
    }
}
