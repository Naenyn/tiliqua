//! Map bank-local generations to a consumer sequence without counting a
//! reselected old frame as a fresh calibration observation.
#[derive(Clone,Copy,Default)]
pub struct Sequence {seen:[u32;2],last_source:u8,sequence:u16}
const _:()=assert!(core::mem::size_of::<[Sequence;4]>()<=48);
impl Sequence {
    pub fn observe(&mut self,source:u8,generation:u32)->Option<u16> {
        if !(1..=2).contains(&source) || generation==0 {return None;}
        if self.last_source==source && self.seen[(source-1) as usize]==generation {
            return Some(self.sequence);
        }
        let seen=&mut self.seen[(source-1) as usize];
        // Scheduler generations saturate, they do not wrap. A bank switching
        // back to an already consumed frame must wait for a new acquisition.
        if generation<=*seen {return None;}
        *seen=generation;self.last_source=source;
        self.sequence=self.sequence.wrapping_add(1);
        Some(self.sequence)
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn identity_and_reselection() {
        let mut s=Sequence::default();
        assert_eq!(s.observe(0,0),None);
        assert_eq!(s.observe(1,1),Some(1));
        assert_eq!(s.observe(1,1),Some(1));
        assert_eq!(s.observe(2,1),Some(2));
        assert_eq!(s.observe(1,1),None);
        assert_eq!(s.observe(1,2),Some(3));
        assert_eq!(s.observe(2,1),None);
        assert_eq!(s.observe(2,2),Some(4));
        assert_eq!(s.observe(3,3),None);
    }
    #[test] fn consumer_wrap_and_independent_channels() {
        let mut s=Sequence::default();let mut other=Sequence::default();
        for n in 1..=65537 {assert_eq!(s.observe(1,n),Some(n as u16));}
        assert_eq!(other.observe(1,1),Some(1));
        assert_eq!(s.observe(1,1),None);
    }
}
