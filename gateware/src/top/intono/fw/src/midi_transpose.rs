//! Latched per-route MIDI offsets. No allocation or output ownership changes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Config { pub channel: u8, pub base: u8, pub hold: bool }
impl Config {
    pub const fn new() -> Self { Self { channel: 0, base: 60, hold: true } }
    pub fn valid(self) -> bool { self.channel <= 16 && self.base < 128 }
    /// A release resets only the note that supplied the current offset.
    pub fn released(self,word:u32,last:Option<u8>)->bool {
        let status=word as u8;let note=(word>>8) as u8;let velocity=(word>>16) as u8;
        !self.hold && self.channel!=0 && (status&15)+1==self.channel && last==Some(note)
            && note<128 && velocity<128 && (status&0xf0==0x80 || (status&0xf0==0x90 && velocity==0))
    }
    pub fn note_on(self, word: u32) -> Option<u8> {
        let status=word as u8; let note=(word>>8) as u8; let velocity=(word>>16) as u8;
        if !self.valid() || self.channel==0 || status&0xf0!=0x90
            || (status&15)+1!=self.channel || note>=128 || velocity==0 || velocity>=128 { return None; }
        Some(note)
    }
    pub fn offset(self, word: u32) -> Option<i8> {
        self.note_on(word).map(|note|(note as i16-self.base as i16) as i8)
    }

}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn channel_zero_and_release_are_explicit() {
        let c=Config {channel:2,base:60,hold:true};
        assert_eq!(c.offset(0x404891),Some(12));
        assert_eq!(c.offset(0x404890),None);
        assert_eq!(c.offset(0x004891),None);
        assert_eq!(c.offset(0x404881),None);
        assert_eq!(Config::new().offset(0x404890),None);
        assert_eq!(c.offset(0x804891),None);
    }
    #[test] fn optional_release_matches_last_note_only() {
        let c=Config {channel:1,base:60,hold:false};
        assert!(c.released(0x403c80,Some(60)));assert!(c.released(0x003c90,Some(60)));
        assert!(!c.released(0x403c81,Some(60)));assert!(!c.released(0x403c80,Some(61)));
        assert!(!Config {hold:true,..c}.released(0x403c80,Some(60)));
    }
    #[test] fn full_note_range_is_signed_and_bounded() {
        assert_eq!(Config {channel:16,base:127,hold:true}.offset(0x40009f),Some(-127));
        assert_eq!(Config {channel:1,base:0,hold:true}.offset(0x407f90),Some(127));
        assert_eq!(Config {channel:17,base:60,hold:true}.offset(0x403c90),None);
    }
}

/// One-shot base-note learning, shared between interrupt reception and UI.
#[derive(Clone, Copy, Default)]
pub struct Learn { pub route: Option<u8>, pub learned: Option<(u8,u8)> }
impl Learn {
    pub const fn new()->Self {Self {route:None,learned:None}}
    pub fn toggle(&mut self,route:u8) {self.route=if self.route==Some(route){None}else{Some(route)};self.learned=None;}
    pub fn receive(&mut self,route:u8,config:Config,word:u32)->Option<u8> {
        if self.route!=Some(route) {return None;}
        let note=config.note_on(word)?;
        self.route=None;self.learned=Some((route,note));Some(note)
    }
}
#[cfg(test)] mod learn_tests {
    use super::*;
    #[test] fn learns_exact_note_once_on_selected_route_and_channel() {
        let mut l=Learn::new();l.toggle(2);let c=Config{channel:2,..Config::new()};
        assert_eq!(l.receive(1,c,0x404191),None);
        assert_eq!(l.receive(2,c,0x404190),None);
        assert_eq!(l.receive(2,c,0x004191),None);
        assert_eq!(l.receive(2,c,0x404191),Some(65));
        assert_eq!(l.learned,Some((2,65)));assert_eq!(l.route,None);
        assert_eq!(l.receive(2,c,0x404291),None);
    }
    #[test] fn repeat_action_cancels_learning() {
        let mut l=Learn::new();l.toggle(0);l.toggle(0);
        assert_eq!(l.receive(0,Config{channel:1,..Config::new()},0x404090),None);
    }
}
