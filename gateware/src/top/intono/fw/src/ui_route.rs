//! User-facing route feedback; engine status and diagnostic logging stay intact.
pub fn route_status_message(status:&'static str,outputs:u8)->Option<&'static str> {
    if outputs!=0 && status=="ADD AN OUTPUT FIRST" {return None;}
    status_message(status)
}
pub fn status_message(status: &'static str) -> Option<&'static str> {
    Some(match status {
        "STOPPED" | "STOPPED BY USER" | "STOPPED - RUN TO START" => return None,
        "BIND CORRECTION ON ROUTE FIRST" => "APPLY PROFILE BEFORE START",
        "CHOOSE SCALE OR CORRECTION" => "ENABLE SCALE OR CHOOSE PROFILE",
        "STOP THIS OUTPUT BEFORE BINDING" => "STOP THIS OUTPUT BEFORE APPLY",
        "BOUND - NATURAL NOTE SET" => "PROFILE APPLIED - 0V NOTE SET",
        "BOUND - NO MEASURED 0V REFERENCE" => "APPLIED - NO MEASURED 0V NOTE",
        "CANNOT BIND PROFILE" => "CANNOT APPLY PROFILE",
        other => other,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn output_requirement_disappears_after_assignment_without_hiding_faults() {
        assert_eq!(route_status_message("ADD AN OUTPUT FIRST",0),Some("ADD AN OUTPUT FIRST"));
        assert_eq!(route_status_message("ADD AN OUTPUT FIRST",1),None);
        assert_eq!(route_status_message("EMPTY PROFILE SLOT",1),Some("EMPTY PROFILE SLOT"));
    }
    #[test]
    fn stopped_faults_and_action_errors_remain_visible() {
        for status in ["STOPPED - CV STALE", "STOPPED - OUTPUT FAULT",
            "STOPPED - OUTPUT NO ACK", "STOPPED - INVALID SCALE",
            "EMPTY PROFILE SLOT", "STOP OUTPUTS BEFORE FLASH READ"] {
            assert_eq!(status_message(status),Some(status));
        }
        assert_eq!(status_message("STOPPED BY USER"),None);
        assert!(status_message("BIND CORRECTION ON ROUTE FIRST").unwrap().contains("APPLY PROFILE"));
    }
}

/// Eight recent output-pitch samples, oldest at the left. Sampling stays in
/// foreground at 8 Hz; it never enters the playback interrupt or allocates.
#[derive(Clone,Copy)]
pub struct History { pub values:[[u8;8];4], pub counts:[u8;4], next_ms:u64 }
impl History {
    pub const fn new()->Self {Self {values:[[0;8];4],counts:[0;4],next_ms:0}}
    pub fn sample(&mut self,now:u64,pitches:[i32;4],active:u8) {
        if now<self.next_ms {return;}self.next_ms=now.saturating_add(125);
        for n in 0..4 {
            if active&(1<<n)==0 {self.counts[n]=0;self.values[n]=[0;8];continue;}
            self.values[n].copy_within(1..8,0);
            // Absolute MIDI pitch in millicents, bounded 0..127 notes. The
            // baseline remains visible for a held note, including low pitches.
            self.values[n][7]=(2+(pitches[n] as i64).clamp(0,12_700_000)*18/12_700_000) as u8;
            self.counts[n]=(self.counts[n]+1).min(8);
        }
    }
}
#[derive(Clone,Copy,PartialEq,Eq)]
#[repr(u8)]
pub enum ShapeKind {Outline,Rectangle,RoundedFill}
#[derive(Clone,Copy,PartialEq,Eq)]
pub struct Shape { pub x:u16,pub y:u16,pub w:u16,pub h:u16,pub color:u8,pub kind:ShapeKind }
impl Shape {
    pub const EMPTY:Self=Self{x:0,y:0,w:0,h:0,color:0,kind:ShapeKind::Outline};
    pub fn rect(self)->crate::ui_canvas::Rect {crate::ui_canvas::Rect{x:self.x as i32,y:self.y as i32,width:self.w,height:self.h}}
}
pub const MAX_SHAPES:usize=48;
/// Bounded transition work, without the read traffic of copying a full guide.
/// Timers remain interruptible; operation polling runs between chunks.
pub const CLEAR_WORDS_PER_TICK:usize=32768;
/// Wider scale and profile nodes; compact shift and physical-jack nodes.
/// Twelve-pixel gutters also align with the native text cell pitch.
pub const FLOW_NODES:[(u16,u16);4]=[(132,144),(288,84),(384,120),(516,72)];
#[derive(Clone,Copy)]
pub struct Drawing {pub shapes:[Shape;MAX_SHAPES],pub len:u8,pub editing:bool}
impl Drawing {
    pub const fn new()->Self{Self{shapes:[Shape::EMPTY;MAX_SHAPES],len:0,editing:false}}
    pub fn add(&mut self,x:u16,y:u16,w:u16,h:u16,color:u8,solid:bool){
        if self.len as usize>=MAX_SHAPES || w==0 || h==0 || x as u32+w as u32>720 || y as u32+h as u32>720 {return;}
        self.shapes[self.len as usize]=Shape{x,y,w,h,color,kind:if solid {ShapeKind::Rectangle}else{ShapeKind::Outline}};self.len+=1;
    }
    pub fn rounded_fill(&mut self,x:u16,y:u16,w:u16,h:u16){
        let old=self.len;self.add(x,y,w,h,0xF9,false);
        if self.len>old {self.shapes[old as usize].kind=ShapeKind::RoundedFill;}
    }
    pub fn changed(&self,old:&Self)->bool {self.len!=old.len || self.shapes[..self.len as usize]!=old.shapes[..old.len as usize]}
    pub fn outline(&mut self,x:u16,y:u16,w:u16,h:u16,selected:bool){self.add(x,y,w,h,if selected {0xF2}else{0x49},false);}
}
// Kept static, not in the already substantial foreground stack frame. Less
// than 1 KiB for both retained sparse lists; no second raster framebuffer.
pub struct Paint { pub banks:[Drawing;2],pub copied:[usize;2],pub resident:bool,pub imported:[u8;2] }
impl Paint {
    pub const fn new()->Self {Self {banks:[Drawing::new();2],copied:[0;2],resident:false,imported:[0;2]}}
    pub fn plot_cached(&self,bank:usize,output:u8)->bool {self.imported[bank]==output+1}
    pub fn invalidate_imported(&mut self) {self.imported=[0;2];}
}
#[cfg(test)]mod route_history_tests {
    use super::*;
    #[test]fn history_cadence_hold_reset_and_bounds(){
        let mut h=History::new();h.sample(0,[6_000_000,-100,i32::MAX,0],15);
        assert_eq!(h.counts,[1;4]);assert_eq!(h.values[1][7],2);assert_eq!(h.values[2][7],20);
        h.sample(124,[0;4],15);assert_eq!(h.counts,[1;4]);
        h.sample(125,[6_000_000;4],1);assert_eq!(h.counts,[2,0,0,0]);assert_eq!(h.values[0][6],h.values[0][7]);
        for now in (250..2000).step_by(125){h.sample(now,[0;4],1);}assert_eq!(h.counts[0],8);
    }
    #[test]fn retained_shapes_and_interval_cache_track_both_banks() {
        let mut p=Paint::new();let mut d=Drawing::new();d.outline(144,160,432,28,false);
        assert!(d.changed(&p.banks[0]));p.banks[0]=d;assert!(!d.changed(&p.banks[0]));
        assert!(d.changed(&p.banks[1]));d.shapes[0].color=0xD9;assert!(d.changed(&p.banks[0]));
        p.imported[0]=2;assert!(p.plot_cached(0,1));assert!(!p.plot_cached(1,1));assert!(!p.plot_cached(0,2));
        p.imported[1]=2;p.invalidate_imported();assert!(!p.plot_cached(0,1));assert!(!p.plot_cached(1,1));
    }
    #[test]fn paint_storage_is_small_and_geometry_never_spills(){
        assert!(core::mem::size_of::<Paint>()<=1024);
        let mut d=Drawing::new();for _ in 0..60{d.outline(144,160,432,28,false);}
        assert_eq!(d.len as usize,MAX_SHAPES);d.add(700,700,100,100,1,true);assert_eq!(d.len as usize,MAX_SHAPES);
    }
}

/// A configuration summary describes assignments, never the unsaved run state.
pub fn write_assignment(w:&mut impl core::fmt::Write,groups:crate::route_group::Layout,route:u8) {
    let r=route.min(3) as usize;
    if groups.outputs[r]==0 {write!(w,"Route {}: No outputs assigned",r+1).ok();return;}
    write!(w,"Route {}: IN{} -> ",r+1,groups.inputs[r]).ok();
    let mut first=true;
    for out in 0..4 {if groups.outputs[r]&(1<<out)!=0 {if !first {write!(w,", ").ok();}write!(w,"OUT{}",out).ok();first=false;}}
}
#[cfg(test)] mod assignment_tests {
    use super::*;
    #[test] fn lists_all_destinations_with_one_based_route_names() {
        let g=crate::route_group::Layout{inputs:[0,1,2,3],outputs:[15,0,0,0]};let mut s=std::string::String::new();
        write_assignment(&mut s,g,0);assert_eq!(s,"Route 1: IN0 -> OUT0, OUT1, OUT2, OUT3");assert!(s.len()<=40);
        s.clear();write_assignment(&mut s,g,1);assert_eq!(s,"Route 2: No outputs assigned");
    }
}
