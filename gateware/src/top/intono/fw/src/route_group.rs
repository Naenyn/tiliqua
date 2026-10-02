//! Four route groups: one input per group, exclusive physical output membership.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Layout { pub inputs: [u8;4], pub outputs: [u8;4] }
impl Layout {
    pub const fn new() -> Self { Self {inputs:[0,1,2,3],outputs:[1,2,4,8]} }
    pub fn valid(&self) -> bool {
        let mut used=0;
        for n in 0..4 {
            let mask=self.outputs[n];
            if self.inputs[n]>3 || mask&!15!=0 || used&mask!=0 {return false;}
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
    pub fn assign(&mut self, route:u8, output:u8, enabled:bool) -> bool {
        if route>3 || output>3 {return false;}
        let bit=1<<output;
        for mask in &mut self.outputs {*mask&=!bit;}
        if enabled {self.outputs[route as usize]|=bit;}
        true
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn fanout_transfer_and_empty_routes_have_exclusive_membership() {
        let mut g=Layout::new();assert!(g.assign(0,1,true));
        assert_eq!(g.outputs,[3,0,4,8]);assert_eq!(g.owner(1),Some(0));
        assert_eq!(g.first(1),None);assert!(g.valid());
        assert!(g.assign(0,0,false));assert_eq!(g.first(0),Some(1));
        assert!(g.assign(2,1,true));assert_eq!(g.outputs,[0,0,6,8]);
        assert!(g.valid());assert!(!g.assign(4,0,true));
        g.outputs[0]=2;assert!(!g.valid());
    }
}
