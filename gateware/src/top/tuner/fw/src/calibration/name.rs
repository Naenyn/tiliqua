//! Encoder-friendly ASCII name draft, separate from the active profile.
pub struct Editor {bytes:[u8;24],position:u8}
impl Editor {
    pub fn new()->Self {let mut s=Self{bytes:[b' ';24],position:0};s.set("Oscillator");s}
    pub fn set(&mut self,name:&str) {self.bytes.fill(b' ');let n=name.len().min(24);self.bytes[..n].copy_from_slice(&name.as_bytes()[..n]);self.position=0;}
    pub fn name(&self)->&str {core::str::from_utf8(&self.bytes).unwrap_or("").trim_end()}
    pub fn character(&self)->u8 {self.bytes[self.position as usize]}
    /// A cursor move selects the existing character; it must not overwrite it
    /// with the old cursor's character from the same menu snapshot.
    pub fn update(&mut self,position:u8,character:u8)->Option<u8> {
        let position=position.saturating_sub(1).min(23);
        if position!=self.position {self.position=position;return Some(self.character());}
        self.bytes[position as usize]=character.clamp(32,126);None
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn cursor_movement_preserves_characters_and_spaces_can_trim_names() {
        let mut e=Editor::new();assert_eq!(e.update(2,b'O'),Some(b's'));assert_eq!(e.name(),"Oscillator");
        e.update(2,b'X');assert_eq!(e.name(),"OXcillator");
        e.set("VCO 1");assert_eq!(e.character(),b'V');
        assert_eq!(e.update(5,b'V'),Some(b'1'));e.update(5,b' ');assert_eq!(e.name(),"VCO");
    }
}
