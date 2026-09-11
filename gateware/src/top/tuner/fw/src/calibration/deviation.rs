//! Readout-only, bounded rolling statistics. Never feeds the DAC/profile.
#[derive(Clone,Copy,Debug)]
pub struct Summary {pub mean:f32,pub spread:f32,pub count:usize}
pub struct Deviation {
    values:[f32;16], times:[u64;16], next:usize, count:usize, sequence:Option<u16>,
}
impl Deviation {
    pub fn new()->Self {Self{values:[0.0;16],times:[0;16],next:0,count:0,sequence:None}}
    pub fn clear(&mut self) {self.next=0;self.count=0;self.sequence=None;}
    pub fn observe(&mut self,error:Option<f32>,sequence:u16,now:u64) {
        let Some(error)=error.filter(|v|v.is_finite()) else {self.clear();return;};
        if self.sequence==Some(sequence) {return;}
        self.sequence=Some(sequence);
        self.values[self.next]=error;self.times[self.next]=now;
        self.next=(self.next+1)%16;self.count=(self.count+1).min(16);
    }
    pub fn summary(&self,now:u64)->Option<Summary> {
        self.summary_with_max_age(now,500)
    }
    pub fn summary_with_max_age(&self,now:u64,max_age_ms:u64)->Option<Summary> {
        let mut n=0;let mut sum=0.0;let mut lo=f32::INFINITY;let mut hi=f32::NEG_INFINITY;
        for i in 0..self.count {
            if now<self.times[i] || now-self.times[i]>max_age_ms {continue;}
            let value=self.values[i];sum+=value;lo=lo.min(value);hi=hi.max(value);n+=1;
        }
        if n<8 {None} else {Some(Summary{mean:sum/n as f32,spread:hi-lo,count:n})}
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn repeated_sequence_cannot_fill_or_keep_statistics_alive() {
        let mut d=Deviation::new();
        for now in 0..100 {d.observe(Some(1.0),0,now);}
        assert!(d.summary(100).is_none());
        for n in 1..8 {d.observe(Some(1.0),n,n as u64*20+100);}
        assert_eq!(d.summary(240).unwrap().count,8);
        assert!(d.summary(1000).is_none());
    }
    #[test] fn rolling_mean_and_spread_expose_variation_then_reset() {
        let mut d=Deviation::new();
        for n in 0..16 {d.observe(Some(if n%2==0 {-1.0} else {1.0}),n,n as u64*20);}
        let s=d.summary(300).unwrap();assert_eq!(s.mean,0.0);assert_eq!(s.spread,2.0);
        for n in 16..32 {d.observe(Some(3.0),n,n as u64*20);}
        let s=d.summary(620).unwrap();assert_eq!(s.mean,3.0);assert_eq!(s.spread,0.0);assert_eq!(s.count,16);
        d.observe(None,32,640);assert!(d.summary(640).is_none());
        d.observe(Some(f32::NAN),33,660);assert!(d.summary(660).is_none());
    }
}
