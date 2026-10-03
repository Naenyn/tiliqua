//! Four route groups: one input per group, exclusive physical output membership.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Layout { pub inputs: [u8;4], pub outputs: [u8;4] }
impl Layout {
    pub const fn new() -> Self { Self {inputs:[0,1,2,3],outputs:[0;4]} }
    /// First pair of saved routes assigning the same jack.
    pub fn conflict(&self)->Option<(bool,u8,u8,u8)> {
        for a in 0..4 {for c in a+1..4 {
            if self.outputs[a]==0 || self.outputs[c]==0 {continue;}
            if self.inputs[a]==self.inputs[c] {return Some((false,self.inputs[a],a as u8,c as u8));}
            let overlap=self.outputs[a]&self.outputs[c];
            if overlap!=0 {return Some((true,overlap.trailing_zeros() as u8,a as u8,c as u8));}
        }} None
    }
    pub fn valid(&self) -> bool {
        let mut used=0;let mut sources=0;
        for n in 0..4 {
            let mask=self.outputs[n];
            if self.inputs[n]>3 || mask&!15!=0 || used&mask!=0 {return false;}
            if mask!=0 {let source=1<<self.inputs[n];if sources&source!=0 {return false;}sources|=source;}
            used|=mask;
        }
        true
    }
    pub fn owner(&self, output:u8) -> Option<u8> {
        if output>3 {return None;}
        (0..4).find(|route|self.outputs[*route as usize]&(1<<output)!=0)
    }
    pub fn first(&self,route:u8) -> Option<u8> {
        if route>3 {return None;}
        (0..4).find(|output|self.outputs[route as usize]&(1<<output)!=0)
    }
    /// Configured routes reserve their source and destinations even when stopped.
    /// Empty routes have no source reservation. Runtime claims additionally
    /// exclude jacks borrowed by calibration, without changing this layout.
    pub fn available(&self, route:u8, output:bool, claims:&crate::ownership::Reservations)->u8 {
        if route>3 {return 0;}
        let mut free=claims.free_mask(crate::ownership::Owner::Quant(route),output);
        for n in 0..4 {
            if n==route as usize || self.outputs[n]==0 {continue;}
            free &= !if output {self.outputs[n]}else{1<<self.inputs[n]};
        }
        free
    }
    pub fn assign(&mut self, route:u8, output:u8, enabled:bool) -> bool {
        if route>3 || output>3 {return false;}
        let bit=1<<output;
        if enabled {
            if self.owner(output).is_some_and(|owner|owner!=route) {return false;}
            if (0..4).any(|n|n!=route as usize && self.outputs[n]!=0 && self.inputs[n]==self.inputs[route as usize]) {return false;}
            self.outputs[route as usize]|=bit;
        } else {self.outputs[route as usize]&=!bit;}
        true
    }

}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn assignments_never_transfer_another_routes_output() {
        let mut g=Layout {inputs:[0,1,2,3],outputs:[1,2,4,8]};assert!(!g.assign(0,1,true));
        assert_eq!(g.outputs,[1,2,4,8]);assert!(g.assign(1,1,false));
        assert!(g.assign(0,1,true));assert_eq!(g.outputs,[3,0,4,8]);
        assert!(g.valid());assert!(!g.assign(4,0,true));
        g.inputs[1]=0;assert!(!g.assign(1,2,true));
    }
    #[test] fn stopped_assignments_and_temporary_calibration_are_distinct() {
        use crate::ownership::{Reservations,Owner};
        let mut g=Layout {inputs:[0,1,2,3],outputs:[1,2,4,8]};let mut r=Reservations::new();
        assert_eq!(g.available(0,true,&r),1);assert_eq!(g.available(0,false,&r),1);
        assert_eq!(r.free_mask(Owner::Calibration,true),15);
        assert!(r.claim(Owner::Calibration,1,1));
        assert_eq!(g.available(0,true,&r),0);
        assert!(!r.claim(Owner::Quant(0),1,1));
        r.release(Owner::Calibration);assert_eq!(g.available(0,true,&r),1);
        assert!(g.assign(1,1,false));assert_eq!(g.available(0,true,&r),3);
        assert_eq!(g.available(0,false,&r),3);
    }
}
