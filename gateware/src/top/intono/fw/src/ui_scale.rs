//! Display the same reachable degrees as the quantizer, without merging octaves.
use crate::scale;
#[cfg(test)] use crate::scale::Pattern;
#[cfg(test)]
#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub struct Preview { pub masks: [u16;2], pub two_octaves: bool, pub quartertones: bool, pub count: u8 }
/// Both applied cycles remain independent; quarter tones use the exact grids.
#[cfg(test)]
impl Preview {
    pub fn keyboards(&self) -> Option<[u16;2]> {
        if self.quartertones {None}else{Some(self.masks)}
    }
}
#[cfg(test)]
pub fn preview(id: u8, root: u8, transpose: i8, masks: [u16;2]) -> Preview {
    let pattern=Pattern::compile(masks).ok();
    let scale=if id==6 {pattern.as_ref().and_then(|p|p.scale())} else {scale::preset(id)};
    let mut result=Preview {masks:[0;2],two_octaves:false,quartertones:id==5,count:0};
    let Some(scale)=scale else {return result};
    result.two_octaves=id==6 && masks[0]!=0 && masks[1]!=0;
    let offset=(root as i32+transpose as i32)*100_000;
    for note in 0..24 {
        let pitch=note as i32*100_000;
        if scale.quantize(pitch,offset,None)==Ok(pitch) {
            result.masks[note/12]|=1<<(note%12);
        }
    }
    result.count=if result.quartertones {24} else if result.two_octaves {
        (result.masks[0].count_ones()+result.masks[1].count_ones()) as u8
    } else {result.masks[0].count_ones() as u8};
    result
}
/// Bake the hidden preset root into a custom pattern. Keep transpose separate,
/// so a click edits the note shown on screen rather than a different degree.
#[cfg(test)]
pub fn toggle_key(id:u8,root:u8,transpose:i8,masks:[u16;2],key:u8) -> Option<[u16;2]> {
    if id==5 {return None;} // quarter-tone degrees cannot fit twelve piano keys
    let mut edited=preview(id,root,0,masks).masks;
    let degree=(key as i32-transpose as i32).rem_euclid(24) as usize;
    edited[degree/12]^=1<<(degree%12);
    Some(edited)
}
/// Recompute only when editor settings change.
pub struct Cache {
    #[cfg(test)] key:Option<(u8,u8,i8,[u16;2])>,
    #[cfg(test)] value:Preview,
    span_key:Option<(u8,[u16;8],u8)>,span_value:([u16;8],bool,u8),
}
impl Cache {
    pub const fn new()->Self {Self {
        #[cfg(test)] key:None,
        #[cfg(test)] value:Preview {masks:[0;2],two_octaves:false,quartertones:false,count:0},
        span_key:None,span_value:([0;8],false,0),
    }}
    pub fn get_span(&mut self,id:u8,masks:[u16;8],octaves:u8)->([u16;8],bool,u8) {
        let key=(id,masks,octaves);
        if self.span_key!=Some(key) {self.span_value=preview_span(id,masks,octaves);self.span_key=Some(key);}
        self.span_value
    }
    #[cfg(test)]
    pub fn get(&mut self,id:u8,root:u8,transpose:i8,masks:[u16;2])->Preview {
        let key=(id,root,transpose,masks);
        if self.key!=Some(key) {self.value=preview(id,root,transpose,masks);self.key=Some(key);}
        self.value
    }
}
pub fn preview_span(id:u8,masks:[u16;8],octaves:u8)->([u16;8],bool,u8) {
    if id==6 {return (masks,false,masks[..octaves as usize].iter().map(|m|m.count_ones() as u8).sum());}
    let (mask,count)=scale::preset_keys(id).unwrap_or((0,0));
    ([mask;8],id==5,count*octaves)
}
pub fn toggle_span(id:u8,masks:[u16;8],octaves:u8,key:u8)->Option<[u16;8]> {
    if id==5 || key>=octaves*12 {return None;}
    let mut edited=if id==6 {masks}else{preview_span(id,masks,octaves).0};
    edited[key as usize/12]^=1<<(key%12);Some(edited)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn direct_key_edit_matches_visible_pitch_with_root_and_transpose() {
        for root in 0..12 {for shift in -12..=12 {for key in 0..24 {
            let before=preview(1,root,shift,[0;2]).masks;
            let edited=toggle_key(1,root,shift,[0;2],key).unwrap();
            let after=preview(6,0,shift,edited).masks;
            let mut expected=before;expected[key as usize/12]^=1<<(key%12);
            assert_eq!(after,expected);
        }}}
        assert!(toggle_key(5,0,0,[0;2],0).is_none());
    }
    #[test]
    fn stacked_keyboards_keep_applied_cycles_separate() {
        let p=preview(6,1,0,[1<<11,1]);
        assert_eq!(p.keyboards(),Some([0,3])); // Empty A must not merge into B.
        let repeating=preview(6,0,0,[0,1<<7]);
        assert_eq!(repeating.keyboards(),Some([1<<7;2]));
        assert_eq!(preview(5,0,0,[0;2]).keyboards(),None);
    }
    #[test]
    fn key_and_transpose_follow_the_real_quantizer_degrees() {
        assert_eq!(preview(1,2,0,[0;2]).masks[0],0xad6); // D major, including F# and C#
        for id in 0..7 { for root in 0..12 { for shift in -12..=12 {
            let masks=[0x891,0x124];
            let pattern=Pattern::compile(masks).unwrap();
            let scale=if id==6 {pattern.scale().unwrap()} else {scale::preset(id).unwrap()};
            let p=preview(id,root,shift,masks);
            for note in 0..24 {
                let unshifted=(note as i32-shift as i32)*100_000;
                assert_eq!(p.masks[note/12]&(1<<(note%12))!=0,
                    scale.quantize(unshifted,root as i32*100_000,None)==Ok(unshifted));
            }
        }}}
    }
    #[test]
    fn displayed_preview_updates_when_key_transpose_or_pattern_changes() {
        let mut cache=Cache::new();
        assert_eq!(cache.get(1,2,0,[0;2]).masks[0],0xad6);
        assert_eq!(cache.get(1,0,2,[0;2]).masks[0],0xad6);
        assert_ne!(cache.get(1,0,0,[0;2]).masks[0],0xad6);
        assert_eq!(cache.get(6,0,0,[1,0]).count,1);
        assert_eq!(cache.get(6,0,0,[1,2]).count,2);
        assert!(cache.get(6,0,0,[1,2]).two_octaves);
    }
    #[test]
    fn custom_octaves_remain_distinct_and_follow_period_normalization() {
        let p=preview(6,1,0,[1<<11,1]);
        assert!(p.two_octaves);assert_eq!(p.masks,[0,3]);assert_eq!(p.count,2);
        let p=preview(6,0,0,[0,1<<7]);
        assert!(!p.two_octaves);assert_eq!(p.masks,[1<<7;2]);assert_eq!(p.count,1);
        assert_eq!(preview(6,0,0,[0;2]).count,0);
        assert_eq!(preview(5,0,0,[0;2]).count,24);
        assert!(preview(5,0,0,[0;2]).quartertones);
    }
}
