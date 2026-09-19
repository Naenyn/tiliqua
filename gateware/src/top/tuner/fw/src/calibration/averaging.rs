//! Low-frequency acquisition, not display smoothing or a confidence guarantee.
//! Sixteen non-overlapping windows; retain raw span and test block agreement.
pub const LOW_PITCH:i32=4_800_000; // C3, about 130.8 Hz at A4=440.
pub const WINDOWS:usize=16;
pub struct Average {
    values:[i32;WINDOWS],next:usize,count:usize,last_end:Option<u64>,
    raw_low:i32,raw_high:i32,
    seen:u16,overlap:u16,span_resets:u16,gap_resets:u16,
}
#[derive(Clone,Copy,Debug)]
pub struct Snapshot {
    pub count:usize,pub seen:u16,pub overlap:u16,pub span_resets:u16,pub gap_resets:u16,
    pub raw_span:u32,pub quarter_delta:u32,pub half_delta:u32,pub values:[i32;WINDOWS],
}
#[derive(Clone,Copy,Debug)]
pub struct Estimate {pub mean:i32,pub spread:u32}
impl Average {
    pub fn new()->Self {Self{values:[0;WINDOWS],next:0,count:0,last_end:None,raw_low:i32::MAX,raw_high:i32::MIN,
        seen:0,overlap:0,span_resets:0,gap_resets:0}}
    fn reset_windows(&mut self) {self.next=0;self.count=0;self.last_end=None;self.raw_low=i32::MAX;self.raw_high=i32::MIN;}
    pub fn clear(&mut self) {self.reset_windows();self.seen=0;self.overlap=0;self.span_resets=0;self.gap_resets=0;}
    pub fn snapshot(&self)->Snapshot {
        let mut values=[0;WINDOWS];let mut sums=[0i64;4];
        for i in 0..self.count {
            values[i]=self.values[(if self.count==WINDOWS {self.next+i}else{i})%WINDOWS];
            sums[i/(WINDOWS/4)]+=values[i] as i64;
        }
        Snapshot {count:self.count,seen:self.seen,overlap:self.overlap,span_resets:self.span_resets,gap_resets:self.gap_resets,
            raw_span:if self.count==0 {0}else{(self.raw_high as i64-self.raw_low as i64) as u32},
            quarter_delta:if self.count==WINDOWS {((sums.iter().max().unwrap()-sums.iter().min().unwrap())/(WINDOWS/4) as i64) as u32}else{0},
            half_delta:if self.count==WINDOWS {((sums[0]+sums[1]-sums[2]-sums[3]).abs()/(WINDOWS/2) as i64) as u32}else{0},values}
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
        self.values[self.next]=value;self.next=(self.next+1)%WINDOWS;
        self.count=(self.count+1).min(WINDOWS);
        if self.count<WINDOWS {return None;}
        let mut sums=[0i64;4];
        for i in 0..WINDOWS {
            let v=self.values[(self.next+i)%WINDOWS];
            sums[i/(WINDOWS/4)]+=v as i64;
        }
        let spread=self.raw_high as i64-self.raw_low as i64;
        // Never turn a grossly unstable signal into an apparently precise mean.
        // Quarter-block means must agree within 2c; half means within 1c.
        if spread>8000 || sums.iter().max().unwrap()-sums.iter().min().unwrap()>2000*(WINDOWS/4) as i64
            || (sums[0]+sums[1]-sums[2]-sums[3]).abs()>1000*(WINDOWS/2) as i64 {return None;}
        Some(Estimate{mean:(sums.iter().sum::<i64>()/WINDOWS as i64) as i32,spread:spread as u32})
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn failure_snapshot_replay_uses_longer_blocks_without_relaxing_limits() {
        // Actual final eight retained pitches at -2.33325V on September 19.
        // Repeating them is a synthetic stationary continuation, not additional
        // hardware evidence. Exercise every phase of that continuation.
        let captured=[1848380,1851799,1852017,1848599,1846414,1848744,1851653,1852235];
        let pairs=captured.chunks_exact(2).map(|s|(s[0]+s[1])/2).collect::<Vec<_>>();
        assert!(pairs.iter().max().unwrap()-pairs.iter().min().unwrap()>4000);
        for phase in 0..8 {
            let mut a=Average::new();let mut result=None;let mut accepted_at=0;
            for n in 0..25 {
                result=a.observe(captured[(n+phase)%8],n as u64*180,n as u64*180+110);
                if n+1<WINDOWS {assert!(result.is_none());}
                if result.is_some() {accepted_at=n;break;}
            }
            assert!(result.is_some(),"phase {phase}");
            assert!(350+accepted_at*180+110<5000);
            let snapshot=a.snapshot();
            assert_eq!(snapshot.values[0],captured[(accepted_at+1-WINDOWS+phase)%8]);
            assert_eq!(snapshot.count,WINDOWS);assert_eq!(snapshot.half_delta,0);
            assert!(snapshot.quarter_delta<=2000);assert!(snapshot.raw_span<=8000);
        }
        assert!(350+(WINDOWS-1)*180+110<5000);
    }
    #[test] fn captured_generate3_readings_have_repeatable_mean_despite_raw_span() {
        // Readings from the 2026-09-18 serial capture, OUT1=-2.16675V,
        // IN1 fundamental. Synthetic replay repeats four logged values to
        // supply 16 windows, at 180ms spacing (not the telemetry print rate).
        let hz=[26.715,26.670,26.674,26.693,26.685,26.642,26.690,26.713,
            26.667,26.689,26.648,26.690,26.715,26.670,26.674,26.693];
        let mut a=Average::new();let mut result=None;let mut first_accepted=None;
        for (n,hz) in hz.into_iter().enumerate() {
            result=a.observe(crate::pitch_math::millicents(hz,440.0),n as u64*180,n as u64*180+110);
            if result.is_some() && first_accepted.is_none() {first_accepted=Some(n*180+110);}
        }
        let result=result.unwrap();assert!((4700..4800).contains(&result.spread));
        // Include the existing 350ms settling time within the 5s deadline.
        assert!(first_accepted.unwrap()+350<5000);
    }
    #[test] fn bounded_jitter_averages_but_drift_and_excess_span_do_not() {
        for scenario in 0..4 {
            let mut a=Average::new();let mut result=None;
            for n in 0..16 {
                let error=match scenario {0=>if n%2==0 {-2400}else{2400},
                    1=>n*400,2=>if n%2==0 {-5000}else{5000},
                    _=>if n<8 {-2000}else{2000}};
                result=a.observe(3_000_000+error,n as u64*160,n as u64*160+110);
            }
            if scenario==0 {let r=result.unwrap();assert_eq!(r.mean,3_000_000);assert_eq!(r.spread,4800);}
            else {assert!(result.is_none());}
        }
        assert!(core::mem::size_of::<Average>()<=128);
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
