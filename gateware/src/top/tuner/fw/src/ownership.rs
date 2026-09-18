//! Small atomic resource reservations; UI pages are not owners.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Owner { Tuner(u8), Calibration, Play, Quant(u8) }
impl Owner {
    fn index(self)->Option<usize> {match self {
        Self::Tuner(n) if n<4=>Some(n as usize),Self::Calibration=>Some(4),Self::Play=>Some(5),
        Self::Quant(n) if n<4=>Some(6+n as usize),_=>None,
    }}
}
#[derive(Clone, Copy)]
pub struct Reservations { inputs:[u8;10],outputs:[u8;10] }
impl Reservations {
    pub const fn new()->Self {Self {inputs:[0;10],outputs:[0;10]}}
    pub fn claim(&mut self,owner:Owner,inputs:u8,outputs:u8)->bool {
        let Some(index)=owner.index() else {return false;};
        if (inputs|outputs)&!15!=0 || inputs|outputs==0 {return false;}
        // An existing operation cannot silently change route.
        if self.inputs[index]|self.outputs[index]!=0 {
            return self.inputs[index]==inputs && self.outputs[index]==outputs;
        }
        for n in 0..10 {
            let shared_quant=index>=6 && n>=6;
            if self.outputs[n]&outputs!=0 || (!shared_quant && self.inputs[n]&inputs!=0) {return false;}
        }
        self.inputs[index]=inputs;self.outputs[index]=outputs;true
    }
    pub fn release(&mut self,owner:Owner) {if let Some(n)=owner.index() {self.inputs[n]=0;self.outputs[n]=0;}}
    pub fn held(&self,owner:Owner)->bool {owner.index().is_some_and(|n|self.inputs[n]|self.outputs[n]!=0)}
    pub fn tuner_available(&self,input:u8)->bool {
        input<4 && (4..10).all(|n|self.inputs[n]&(1<<input)==0)
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn three_modes_and_conflict_atomicity() {
        let mut r=Reservations::new();
        assert!(r.claim(Owner::Tuner(0),1,0));
        assert!(r.claim(Owner::Calibration,2,2));
        assert!(r.claim(Owner::Quant(2),4,4));
        assert!(!r.claim(Owner::Quant(3),2,8));
        assert!(!r.held(Owner::Quant(3)));
        assert!(r.claim(Owner::Quant(3),4,8));
        r.release(Owner::Quant(2));
        assert!(!r.claim(Owner::Play,4,4)); // Shared input still reserved.
        r.release(Owner::Quant(3));assert!(r.claim(Owner::Play,4,4));
        assert!(r.held(Owner::Calibration));assert!(r.held(Owner::Tuner(0)));
    }
    #[test] fn routes_are_immutable_and_directions_independent() {
        let mut r=Reservations::new();assert!(r.claim(Owner::Tuner(0),1,0));
        assert!(!r.claim(Owner::Tuner(0),2,0));
        assert!(r.claim(Owner::Calibration,2,1));
        assert!(!r.claim(Owner::Play,4,1));
        assert!(!r.tuner_available(1));assert!(r.tuner_available(0));
        r.release(Owner::Calibration);assert!(r.tuner_available(1));
    }
    #[test] fn invalid_requests_never_claim() {
        let mut r=Reservations::new();
        assert!(!r.claim(Owner::Quant(4),1,1));assert!(!r.claim(Owner::Play,16,1));
        assert!(!r.claim(Owner::Play,0,0));assert!(!r.held(Owner::Play));
    }
}
